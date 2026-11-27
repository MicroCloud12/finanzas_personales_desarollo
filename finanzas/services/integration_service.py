# finanzas/services/integration_service.py
import os
import requests
import jwt
from io import BytesIO
import logging
from jwt import PyJWKClient
import mercadopago
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.oauth2.credentials import Credentials
from django.conf import settings
from allauth.socialaccount.models import SocialApp, SocialToken, SocialAccount
from django.contrib.sessions.models import Session
from ..models import User

logger = logging.getLogger(__name__)

class GoogleDriveService:
    """Service to interact with Google Drive API."""
    def __init__(self, user: User):
        try:
            app = SocialApp.objects.get(provider='google')
            google_token = SocialToken.objects.get(account__user=user, account__provider='google')
            if not google_token.token_secret:
                # Sin refresh token no hay permiso de Drive: entró con Google pero no conectó Drive.
                raise ConnectionError("Google Drive no está conectado (falta el permiso de lectura).")
            # token=None: el access token guardado es el del último login (solo identidad); con el
            # refresh token, que sí tiene el permiso de Drive, google-auth pide uno nuevo al usarlo.
            creds = Credentials(
                token=None,
                refresh_token=google_token.token_secret,
                token_uri='https://oauth2.googleapis.com/token',
                client_id=app.client_id,
                client_secret=app.secret,
                scopes=[settings.GOOGLE_DRIVE_SCOPE],
            )
            self.service = build('drive', 'v3', credentials=creds)
        except (SocialToken.DoesNotExist, SocialApp.DoesNotExist) as e:
            raise ConnectionError("Google account link or Social App config missing.") from e

    def _get_folder_id(self, folder_name: str) -> str | None:
        try:
            query = f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
            response = self.service.files().list(q=query, spaces='drive', fields='files(id)').execute()
            return response.get('files', [])[0]['id'] if response.get('files') else None
        except HttpError as error:
            logger.error(f"Google Drive folder search error for '{folder_name}': {error}")
            return None

    def list_files_in_folder(self, folder_name: str, mimetypes: list[str]) -> list[dict]:
        folder_id = self._get_folder_id(folder_name)
        if not folder_id: return []
        
        mime_query = " or ".join([f"mimeType='{m}'" for m in mimetypes])
        query = f"'{folder_id}' in parents and ({mime_query}) and trashed=false"
        
        try:
            results = self.service.files().list(q=query, fields="files(id, name, mimeType)").execute()
            return results.get('files', [])
        except HttpError as error:
            logger.error(f"Google Drive list files error: {error}")
            return []

    def get_file_content(self, file_id: str) -> BytesIO:
        request = self.service.files().get_media(fileId=file_id)
        return BytesIO(request.execute())

class MercadoPagoService:
    """Service for Mercado Pago business logic.

    Hay un plan de suscripción (preapproval_plan) en Mercado Pago por cada combinación de
    plan y periodo; sus ids van en el .env: MERCADOPAGO_PLAN_PERSONAL_MENSUAL,
    MERCADOPAGO_PLAN_PERSONAL_ANUAL, MERCADOPAGO_PLAN_PRO_MENSUAL y MERCADOPAGO_PLAN_PRO_ANUAL
    (MERCADOPAGO_PLAN_ID, el viejo, se toma como Personal mensual si falta el nuevo).
    """
    CHECKOUT_URL = "https://www.mercadopago.com.mx/subscriptions/checkout"

    def __init__(self):
        self.sdk = mercadopago.SDK(os.getenv('MERCADOPAGO_ACCESS_TOKEN'))
        self.planes = {
            ('personal', 'mensual'): os.getenv('MERCADOPAGO_PLAN_PERSONAL_MENSUAL') or os.getenv('MERCADOPAGO_PLAN_ID'),
            ('personal', 'anual'): os.getenv('MERCADOPAGO_PLAN_PERSONAL_ANUAL'),
            ('pro', 'mensual'): os.getenv('MERCADOPAGO_PLAN_PRO_MENSUAL'),
            ('pro', 'anual'): os.getenv('MERCADOPAGO_PLAN_PRO_ANUAL'),
        }
        self.plan_id = self.planes[('personal', 'mensual')]
        if not self.sdk or not self.plan_id:
            logger.warning("Mercado Pago credentials/Plan ID missing in .env")

    def crear_link_suscripcion(self, user, back_url: str, plan: str = 'personal', periodo: str = 'mensual'):
        """Link al checkout de Mercado Pago del plan pedido; None si ese plan no está configurado."""
        preapproval_plan_id = self.planes.get((plan, periodo))
        if not preapproval_plan_id:
            return None
        # external_reference = id del usuario: si Mercado Pago lo conserva en el preapproval, el webhook
        # identifica al usuario sin depender de que su correo de Mercado Pago sea el mismo que el de la app
        return f"{self.CHECKOUT_URL}?preapproval_plan_id={preapproval_plan_id}&external_reference={user.pk}"

    def plan_por_preapproval(self, preapproval_plan_id: str | None):
        """(plan, periodo) que corresponde a un preapproval_plan_id de Mercado Pago; Personal mensual
        si no se reconoce (p. ej. una suscripción creada antes de tener planes separados)."""
        for clave, valor in self.planes.items():
            if valor and valor == preapproval_plan_id:
                return clave
        return ('personal', 'mensual')

    def cancelar_preapproval(self, preapproval_id: str) -> bool:
        """Cancela un preapproval concreto (p. ej. el plan anterior cuando el usuario cambia de plan)."""
        respuesta = self.sdk.preapproval().update(preapproval_id, {"status": "cancelled"})
        ok = respuesta.get("status") in (200, 201)
        if not ok:
            logger.error(f"Mercado Pago respondió {respuesta.get('status')} al cancelar {preapproval_id}")
        return ok

    def buscar_id_suscripcion(self, user) -> str | None:
        """Busca el preapproval vigente del usuario por su email (respaldo cuando el
        webhook no alcanzó a guardar ``id_suscripcion_mercadopago``)."""
        if not user.email:
            return None
        respuesta = self.sdk.preapproval().search({"payer_email": user.email, "status": "authorized"})
        if respuesta.get("status") != 200:
            raise RuntimeError(f"Mercado Pago respondió {respuesta.get('status')} al buscar la suscripción")
        resultados = respuesta.get("response", {}).get("results") or []
        return resultados[0].get("id") if resultados else None

    def cancelar_suscripcion(self, suscripcion) -> bool:
        """Cancela el cobro recurrente en Mercado Pago (``status: cancelled``).

        Devuelve True si Mercado Pago confirmó la cancelación y False si no hay ningún
        preapproval que cancelar (p. ej. activada a mano). Lanza RuntimeError si Mercado
        Pago responde con error, para que quien llama NO marque la cancelación localmente
        mientras el cobro sigue vivo.
        """
        preapproval_id = suscripcion.id_suscripcion_mercadopago or self.buscar_id_suscripcion(suscripcion.usuario)
        if not preapproval_id:
            logger.warning(f"Suscripción de {suscripcion.usuario.username} sin preapproval en Mercado Pago; nada que cancelar.")
            return False

        respuesta = self.sdk.preapproval().update(preapproval_id, {"status": "cancelled"})
        if respuesta.get("status") not in (200, 201):
            raise RuntimeError(f"Mercado Pago respondió {respuesta.get('status')}: {respuesta.get('response')}")

        if not suscripcion.id_suscripcion_mercadopago:
            suscripcion.id_suscripcion_mercadopago = preapproval_id
            suscripcion.save(update_fields=['id_suscripcion_mercadopago'])
        logger.info(f"Suscripción {preapproval_id} de {suscripcion.usuario.username} cancelada en Mercado Pago.")
        return True

class RISCService:
    """Service to handle Google RISC security events."""
    GOOGLE_RISC_CONFIG_URL = "https://accounts.google.com/.well-known/risc-configuration"
    _jwk_client = None

    def __init__(self):
        self.audience = os.getenv("GOOGLE_CLIENT_ID")
        if not self.audience:
            logger.warning("GOOGLE_CLIENT_ID missing in .env")

    def _get_jwk_client(self):
        if self._jwk_client is None:
            config = requests.get(self.GOOGLE_RISC_CONFIG_URL, timeout=5).json()
            self._jwk_client = PyJWKClient(config.get("jwks_uri"))
        return self._jwk_client

    def validate_token(self, token: str) -> dict:
        jwk_client = self._get_jwk_client()
        try:
            signing_key = jwk_client.get_signing_key_from_jwt(token)
            payload = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                audience=self.audience,
                issuer="https://accounts.google.com",
            )
            
            for event_type, event_data in payload.get('events', {}).items():
                if event_type == "https://schemas.openid.net/secevent/risc/event-type/verification":
                    logger.info(f"✅ RISC Verification Event. State: {event_data.get('state')}")
            return payload
        except jwt.exceptions.PyJWKClientError as e:
            raise ValueError(f"Signing key error: {e}")
        except jwt.PyJWTError as e:
            raise ValueError(f"Invalid Token: {e}")
    
    def process_security_event(self, payload: dict):
        for event_type, event_details in payload.get("events", {}).items():
            user_google_id = event_details.get("subject", {}).get("sub")
            if not user_google_id: continue

            try:
                user = SocialAccount.objects.get(provider='google', uid=user_google_id).user
                
                if event_type == "https://schemas.openid.net/secevent/risc/event-type/account-disabled":
                    user.is_active = False
                    user.save()
                    Session.objects.filter(session_key__in=user.session_set.values_list('session_key', flat=True)).delete()
                    logger.warning(f"User {user.username} deactivated (Google account disabled via RISC).")

                elif event_type == "https://schemas.openid.net/secevent/risc/event-type/sessions-revoked":
                    Session.objects.filter(session_key__in=user.session_set.values_list('session_key', flat=True)).delete()
                    logger.warning(f"User {user.username} sessions revoked via RISC.")
            except SocialAccount.DoesNotExist:
                logger.warning(f"RISC event for unknown Google ID {user_google_id}.")
