"""Pruebas de cancelar suscripción y eliminar cuenta desde el perfil.

Mercado Pago y Google se simulan (mock): ninguna prueba sale a internet.
"""
import json
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

from allauth.socialaccount.models import SocialAccount, SocialToken
from django.apps import apps
from django.contrib.auth.models import User
from django.core import mail
from django.db.models import ForeignKey, OneToOneField
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import (Cuenta, Deuda, Factura, Presupuesto, Suscripcion, inversiones,
                     registro_transacciones)


def sdk_simulado(update_status=200, resultados_busqueda=None):
    """SDK de Mercado Pago falso: preapproval().update / .search responden lo que pidamos."""
    sdk = MagicMock()
    sdk.preapproval.return_value.update.return_value = {"status": update_status, "response": {}}
    sdk.preapproval.return_value.search.return_value = {
        "status": 200, "response": {"results": resultados_busqueda or []},
    }
    return sdk


def suscripcion_activa(user, dias=20, mp_id='pre_123'):
    ahora = timezone.now()
    return Suscripcion.objects.create(
        usuario=user, estado='activa', fecha_inicio=ahora - timedelta(days=31 - dias),
        fecha_fin=ahora + timedelta(days=dias), id_suscripcion_mercadopago=mp_id,
    )


@patch('finanzas.services.integration_service.mercadopago.SDK')
class CancelarSuscripcionTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('ana', email='ana@test.com', password='x')
        self.client.force_login(self.user)
        self.url = reverse('cancelar_suscripcion')

    def test_cancelar_deja_de_cobrar_pero_conserva_acceso(self, SDK):
        SDK.return_value = sdk = sdk_simulado()
        sus = suscripcion_activa(self.user)

        resp = self.client.post(self.url, follow=True)

        sdk.preapproval.return_value.update.assert_called_once_with('pre_123', {"status": "cancelled"})
        sus.refresh_from_db()
        self.assertEqual(sus.estado, 'cancelada')
        self.assertIsNotNone(sus.fecha_cancelacion)
        self.assertTrue(sus.is_active(), "conserva Premium hasta fecha_fin")
        self.assertFalse(sus.puede_cancelarse, "no se puede cancelar dos veces")
        self.assertRedirects(resp, reverse('mi_perfil'))
        self.assertContains(resp, 'Reactivar Suscripción')
        self.assertNotContains(resp, 'Cancelar Suscripción')
        self.assertContains(resp, 'no habrá más cobros')

    def test_cancelada_pierde_acceso_al_vencer(self, SDK):
        sus = suscripcion_activa(self.user)
        sus.estado = 'cancelada'
        sus.fecha_fin = timezone.now() - timedelta(days=1)
        sus.save()
        self.assertFalse(sus.is_active())
        # El perfil vuelve a ofrecer "Mejorar Plan"
        self.assertContains(self.client.get(reverse('mi_perfil')), 'Mejorar Plan')

    def test_pausada_no_da_acceso(self, SDK):
        sus = suscripcion_activa(self.user)
        sus.estado = 'pausada'
        sus.save()
        self.assertFalse(sus.is_active())

    def test_si_mercadopago_falla_no_se_cancela_localmente(self, SDK):
        SDK.return_value = sdk_simulado(update_status=500)
        sus = suscripcion_activa(self.user)

        resp = self.client.post(self.url, follow=True)

        sus.refresh_from_db()
        self.assertEqual(sus.estado, 'activa')
        self.assertIsNone(sus.fecha_cancelacion)
        self.assertContains(resp, 'No pudimos cancelar tu suscripción')

    def test_sin_id_busca_el_preapproval_por_email(self, SDK):
        SDK.return_value = sdk = sdk_simulado(resultados_busqueda=[{"id": "pre_999"}])
        sus = suscripcion_activa(self.user, mp_id=None)

        self.client.post(self.url)

        sdk.preapproval.return_value.search.assert_called_once_with({"payer_email": "ana@test.com", "status": "authorized"})
        sdk.preapproval.return_value.update.assert_called_once_with('pre_999', {"status": "cancelled"})
        sus.refresh_from_db()
        self.assertEqual(sus.estado, 'cancelada')
        self.assertEqual(sus.id_suscripcion_mercadopago, 'pre_999')

    def test_sin_suscripcion_activa_no_llama_a_mercadopago(self, SDK):
        SDK.return_value = sdk = sdk_simulado()
        Suscripcion.objects.create(usuario=self.user, estado='pendiente')

        resp = self.client.post(self.url, follow=True)

        sdk.preapproval.return_value.update.assert_not_called()
        self.assertContains(resp, 'No tienes una suscripción activa')

    def test_next_vuelve_a_gestionar_suscripcion(self, SDK):
        SDK.return_value = sdk_simulado()
        suscripcion_activa(self.user)
        resp = self.client.post(self.url, {'next': 'gestionar_suscripcion'})
        self.assertRedirects(resp, reverse('gestionar_suscripcion'), fetch_redirect_response=False)

    def test_solo_post(self, SDK):
        self.assertEqual(self.client.get(self.url).status_code, 405)

    def test_pagina_suscripcion_muestra_boton_cancelar(self, SDK):
        suscripcion_activa(self.user)
        resp = self.client.get(reverse('gestionar_suscripcion'))
        self.assertContains(resp, 'Cancelar suscripción')
        self.assertContains(resp, reverse('cancelar_suscripcion'))

    def test_webhook_cancelled_y_paused(self, SDK):
        sus = suscripcion_activa(self.user)
        SDK.return_value = sdk = sdk_simulado()

        def webhook(status):
            sdk.preapproval.return_value.get.return_value = {
                "status": 200, "response": {"payer_email": "ana@test.com", "status": status},
            }
            payload = {"type": "subscription_preapproval", "data": {"id": "pre_123"}}
            r = self.client.post(reverse('mercadopago_webhook'), json.dumps(payload), content_type='application/json')
            self.assertEqual(r.status_code, 200)
            sus.refresh_from_db()

        webhook('cancelled')
        self.assertEqual(sus.estado, 'cancelada')
        self.assertIsNotNone(sus.fecha_cancelacion)
        self.assertTrue(sus.is_active(), "cancelada desde Mercado Pago también conserva el periodo pagado")

        webhook('paused')
        self.assertEqual(sus.estado, 'pausada')
        self.assertFalse(sus.is_active())

        webhook('authorized')  # se volvió a suscribir
        self.assertEqual(sus.estado, 'activa')
        self.assertIsNone(sus.fecha_cancelacion)
        self.assertTrue(sus.is_active())


def modelos_ligados_a_usuario():
    """Todos los modelos de la app con FK/OneToOne a User (lo que debe borrarse con la cuenta)."""
    for modelo in apps.get_app_config('finanzas').get_models():
        for campo in modelo._meta.get_fields():
            if isinstance(campo, (ForeignKey, OneToOneField)) and campo.related_model is User:
                yield modelo, campo.name


@patch('finanzas.services.account_service.requests.post')
@patch('finanzas.services.integration_service.mercadopago.SDK')
class EliminarCuentaTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('ana', email='ana@test.com', password='x')
        self.otro = User.objects.create_user('beto', email='beto@test.com', password='x')
        for u in (self.user, self.otro):
            self._poblar(u)
        self.client.force_login(self.user)
        self.url = reverse('eliminar_cuenta_usuario')

    def _poblar(self, user):
        cuenta = Cuenta.objects.create(propietario=user, nombre='BBVA', tipo='DEBITO')
        registro_transacciones.objects.create(propietario=user, fecha=date.today(), descripcion='x',
                                              categoria='Comida', monto=10, tipo='GASTO', origen=cuenta)
        inversiones.objects.create(propietario=user, nombre_activo='BTC', cantidad_titulos=1,
                                   fecha_compra=date.today(), precio_compra_titulo=1, precio_actual_titulo=1)
        Deuda.objects.create(propietario=user, nombre='Coche', monto_total=1000, tasa_interes=10, plazo_meses=12)
        Presupuesto.objects.create(propietario=user, categoria='Agua')
        Factura.objects.create(propietario=user, tienda='OXXO', total=10, estado='pendiente')
        suscripcion_activa(user, mp_id=f'pre_{user.username}')
        social = SocialAccount.objects.create(user=user, provider='google', uid=f'g_{user.username}', extra_data={})
        SocialToken.objects.create(account=social, token='access_tok', token_secret=f'refresh_{user.username}')

    def _filas_de(self, user_id):
        return sum(m.objects.filter(**{campo: user_id}).count() for m, campo in modelos_ligados_a_usuario())

    def test_elimina_todo_lo_del_usuario_y_nada_del_resto(self, SDK, post_google):
        SDK.return_value = sdk = sdk_simulado()
        post_google.return_value = MagicMock(status_code=200)
        user_id, otro_id = self.user.id, self.otro.id
        filas_otro = self._filas_de(otro_id)
        self.assertGreater(self._filas_de(user_id), 0)

        resp = self.client.post(self.url, {'confirmacion': 'ELIMINAR'})

        self.assertRedirects(resp, reverse('home'), fetch_redirect_response=False)
        self.assertFalse(User.objects.filter(id=user_id).exists())
        self.assertEqual(self._filas_de(user_id), 0, "quedaron filas ligadas al usuario borrado")
        self.assertFalse(SocialAccount.objects.filter(user_id=user_id).exists())
        self.assertFalse(SocialToken.objects.filter(token_secret='refresh_ana').exists())
        # Se canceló el cobro y se revocó Google ANTES de borrar
        sdk.preapproval.return_value.update.assert_called_once_with('pre_ana', {"status": "cancelled"})
        post_google.assert_called_once()
        self.assertEqual(post_google.call_args.kwargs['params'], {'token': 'refresh_ana'})
        # El otro usuario sigue intacto
        self.assertTrue(User.objects.filter(id=otro_id).exists())
        self.assertEqual(self._filas_de(otro_id), filas_otro)
        # Sesión cerrada y correo de despedida
        self.assertNotIn('_auth_user_id', self.client.session)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['ana@test.com'])
        # La página de inicio muestra el aviso
        self.assertContains(self.client.get(reverse('home')), 'fueron eliminadas')

    def test_confirmacion_incorrecta_no_borra(self, SDK, post_google):
        SDK.return_value = sdk = sdk_simulado()
        for mala in ('', 'eliminar cuenta', 'BORRAR'):
            resp = self.client.post(self.url, {'confirmacion': mala}, follow=True)
            self.assertRedirects(resp, reverse('mi_perfil'))
            self.assertContains(resp, 'escribe ELIMINAR')
        self.assertTrue(User.objects.filter(id=self.user.id).exists())
        sdk.preapproval.return_value.update.assert_not_called()
        post_google.assert_not_called()

    def test_confirmacion_en_minusculas_se_acepta(self, SDK, post_google):
        SDK.return_value = sdk_simulado()
        self.client.post(self.url, {'confirmacion': ' eliminar '})
        self.assertFalse(User.objects.filter(id=self.user.id).exists())

    def test_si_mercadopago_falla_no_se_borra_la_cuenta(self, SDK, post_google):
        SDK.return_value = sdk_simulado(update_status=500)
        resp = self.client.post(self.url, {'confirmacion': 'ELIMINAR'}, follow=True)
        self.assertTrue(User.objects.filter(id=self.user.id).exists())
        self.assertGreater(self._filas_de(self.user.id), 0)
        post_google.assert_not_called()
        self.assertContains(resp, 'tu cuenta NO se eliminó')
        self.assertIn('_auth_user_id', self.client.session)

    def test_si_google_falla_la_cuenta_se_borra_igual(self, SDK, post_google):
        SDK.return_value = sdk_simulado()
        import requests
        post_google.side_effect = requests.ConnectionError('sin red')
        self.client.post(self.url, {'confirmacion': 'ELIMINAR'})
        self.assertFalse(User.objects.filter(id=self.user.id).exists())

    def test_sin_suscripcion_activa_no_llama_a_mercadopago(self, SDK, post_google):
        SDK.return_value = sdk = sdk_simulado()
        Suscripcion.objects.filter(usuario=self.user).update(estado='cancelada')
        self.client.post(self.url, {'confirmacion': 'ELIMINAR'})
        self.assertFalse(User.objects.filter(id=self.user.id).exists())
        sdk.preapproval.return_value.update.assert_not_called()

    def test_solo_post_y_solo_logueado(self, SDK, post_google):
        self.assertEqual(self.client.get(self.url).status_code, 405)
        self.client.logout()
        resp = self.client.post(self.url, {'confirmacion': 'ELIMINAR'})
        self.assertEqual(resp.status_code, 302)
        self.assertIn('login', resp.url)
        self.assertTrue(User.objects.filter(id=self.user.id).exists())

    def test_perfil_muestra_modal(self, SDK, post_google):
        resp = self.client.get(reverse('mi_perfil'))
        self.assertContains(resp, 'id="modal-eliminar"')
        self.assertContains(resp, reverse('eliminar_cuenta_usuario'))
        self.assertContains(resp, 'name="confirmacion"')
