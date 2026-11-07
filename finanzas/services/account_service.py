# finanzas/services/account_service.py
"""Acciones sobre la cuenta del usuario: cancelar la suscripción y eliminar la cuenta."""
import logging

import requests
from allauth.socialaccount.models import SocialToken
from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction

from ..models import Suscripcion
from .integration_service import MercadoPagoService

logger = logging.getLogger(__name__)

GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"


class AccountService:
    # Palabra que el usuario debe teclear para confirmar que quiere borrar su cuenta
    PALABRA_CONFIRMACION = "ELIMINAR"

    @staticmethod
    def cancelar_suscripcion(user) -> tuple[Suscripcion | None, bool]:
        """Deja de cobrar en Mercado Pago y marca la suscripción como cancelada.

        El usuario conserva el acceso Premium hasta ``fecha_fin`` (ya pagó ese periodo).
        Devuelve ``(suscripcion, cancelada)``: ``cancelada`` es False si no había nada
        que cancelar. Si Mercado Pago falla, propaga la excepción y NO cambia nada local.
        """
        suscripcion = Suscripcion.objects.filter(usuario=user).first()
        if not suscripcion or not suscripcion.puede_cancelarse:
            return suscripcion, False

        MercadoPagoService().cancelar_suscripcion(suscripcion)
        suscripcion.cancelar()
        return suscripcion, True

    @staticmethod
    def revocar_google(user) -> None:
        """Revoca el permiso OAuth que el usuario dio a la app (Drive/Gmail).

        Es "best effort": si Google no responde, la cuenta se elimina de todos modos
        (el token se borra junto con la cuenta social y el usuario puede quitar el
        permiso desde su cuenta de Google).
        """
        tokens = SocialToken.objects.filter(account__user=user, account__provider='google')
        for social_token in tokens:
            # Revocar el refresh token invalida también los access tokens derivados
            for token in (social_token.token_secret, social_token.token):
                if not token:
                    continue
                try:
                    respuesta = requests.post(GOOGLE_REVOKE_URL, params={'token': token}, timeout=5)
                    if respuesta.status_code == 200:
                        logger.info(f"Permiso de Google revocado para {user.username}.")
                        break
                    logger.warning(f"Google respondió {respuesta.status_code} al revocar token de {user.username}.")
                except requests.RequestException as e:
                    logger.warning(f"No se pudo revocar el token de Google de {user.username}: {e}")

    @classmethod
    def eliminar_cuenta(cls, user) -> None:
        """Elimina al usuario y TODA su información.

        Orden:
        1. Cancelar el cobro recurrente en Mercado Pago. Si falla, se aborta: no
           queremos borrar la cuenta y seguir cobrando.
        2. Revocar el permiso de Google (best effort).
        3. Borrar el usuario. Por ``on_delete=CASCADE`` se van con él: cuentas y sus
           saldos, transacciones, tickets pendientes, inversiones, deudas y
           amortizaciones, facturas, presupuestos e historial de recibos, historial
           del portafolio, la suscripción y las cuentas sociales/tokens de allauth.
        """
        suscripcion = Suscripcion.objects.filter(usuario=user).first()
        if suscripcion and suscripcion.estado == 'activa':
            MercadoPagoService().cancelar_suscripcion(suscripcion)

        cls.revocar_google(user)

        username, email = user.username, user.email
        with transaction.atomic():
            user.delete()
        logger.info(f"Cuenta de {username} eliminada con toda su información.")

        if email:
            send_mail(
                "Tu cuenta fue eliminada",
                f"Hola {username},\n\nTu cuenta y toda la información asociada fueron eliminadas "
                "de forma definitiva, y cualquier suscripción activa quedó cancelada.\n\n"
                "Si no fuiste tú, responde a este correo.",
                getattr(settings, 'DEFAULT_FROM_EMAIL', None),
                [email],
                fail_silently=True,
            )
