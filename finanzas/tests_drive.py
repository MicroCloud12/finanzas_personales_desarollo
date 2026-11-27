"""Google Drive se conecta aparte del login (permiso restringido para Google)."""
import html
from unittest.mock import patch, MagicMock
from urllib.parse import parse_qs, urlparse

from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.sites.models import Site
from django.test import TestCase, override_settings
from django.urls import reverse

from allauth.socialaccount.models import SocialAccount, SocialApp, SocialToken

from .templatetags.drive_tags import tiene_drive


class DriveAparteTest(TestCase):
    def setUp(self):
        sitio = Site.objects.get_current()
        self.app = SocialApp.objects.create(provider='google', name='Google', client_id='cid', secret='sec')
        self.app.sites.add(sitio)
        self.user = User.objects.create_user('mau', email='mau@test.com', password='x')
        self.cuenta = SocialAccount.objects.create(user=self.user, provider='google', uid='123',
                                                   extra_data={'email': 'mau@test.com'})
        self.token = SocialToken.objects.create(account=self.cuenta, app=self.app, token='acc', token_secret='ref')
        self.client.force_login(self.user)

    def _query(self, url):
        return parse_qs(urlparse(url).query)

    def test_el_login_con_google_no_pide_drive(self):
        self.assertNotIn('drive', ' '.join(settings.SOCIALACCOUNT_PROVIDERS['google']['SCOPE']))
        self.client.logout()
        r = self.client.get(reverse('login'))
        self.assertContains(r, reverse('google_login'))
        self.assertNotContains(r, 'prompt=consent')          # ya no se fuerza el consentimiento en cada entrada
        self.assertNotContains(r, 'drive.readonly')

    def test_el_boton_de_drive_pide_el_permiso_aparte_y_regresa_a_la_pagina(self):
        r = self.client.get(reverse('procesamiento_automatico'))
        self.assertContains(r, 'Conectar con Google Drive')
        self.assertNotContains(r, 'start-processing-btn')     # sin Drive no hay botón de procesar
        enlace = html.unescape([l for l in r.content.decode().split('"') if l.startswith(reverse('google_login') + '?')][0])
        q = self._query(enlace)
        self.assertEqual(q['process'], ['connect'])
        self.assertEqual(q['scope'], [settings.GOOGLE_DRIVE_SCOPE])
        self.assertIn('prompt=consent', q['auth_params'][0])
        self.assertIn('access_type=offline', q['auth_params'][0])
        regreso = q['next'][0]
        self.assertTrue(regreso.startswith(reverse('drive_conectado')))
        self.assertIn(reverse('procesamiento_automatico'), self._query(regreso)['next'][0])

    @patch('finanzas.views.auth.requests.get')
    def test_al_regresar_de_google_se_comprueba_el_permiso(self, get):
        get.return_value = MagicMock(json=lambda: {'scope': f'openid email {settings.GOOGLE_DRIVE_SCOPE}'})
        destino = reverse('procesamiento_automatico')
        r = self.client.get(reverse('drive_conectado') + '?next=' + destino, follow=True)
        self.assertRedirects(r, destino)
        self.cuenta.refresh_from_db()
        self.assertTrue(self.cuenta.extra_data['drive_ok'])
        self.assertTrue(tiene_drive(self.user))
        self.assertContains(r, 'Google Drive conectado')
        self.assertContains(r, 'start-processing-btn')
        get.assert_called_once()
        self.assertEqual(get.call_args.kwargs['params'], {'access_token': 'acc'})

    @patch('finanzas.views.auth.requests.get')
    def test_si_el_usuario_desmarco_drive_no_queda_conectado(self, get):
        get.return_value = MagicMock(json=lambda: {'scope': 'openid email profile'})
        r = self.client.get(reverse('drive_conectado') + '?next=https://malo.com/', follow=True)
        self.assertRedirects(r, reverse('mi_perfil'))       # next externo se ignora
        self.cuenta.refresh_from_db()
        self.assertFalse(self.cuenta.extra_data['drive_ok'])
        self.assertFalse(tiene_drive(self.user))
        self.assertContains(r, 'No obtuvimos permiso')

    def test_la_marca_sobrevive_a_que_allauth_reescriba_extra_data(self):
        self.cuenta.extra_data = {'email': 'mau@test.com', 'drive_ok': True}
        self.cuenta.save()
        # Esto es lo que hace allauth en cada login: sustituye extra_data por lo que manda Google
        self.cuenta.extra_data = {'email': 'mau@test.com', 'name': 'Mau'}
        self.cuenta.save()
        self.cuenta.refresh_from_db()
        self.assertTrue(self.cuenta.extra_data['drive_ok'])
        self.assertEqual(self.cuenta.extra_data['name'], 'Mau')

    def test_perfil_muestra_drive_aparte(self):
        r = self.client.get(reverse('mi_perfil'))
        self.assertContains(r, 'Conectar Google Drive')
        self.cuenta.extra_data['drive_ok'] = True
        self.cuenta.save()
        r = self.client.get(reverse('mi_perfil'))
        self.assertNotContains(r, 'Conectar Google Drive')

    def test_sin_refresh_token_el_servicio_de_drive_avisa(self):
        from .services import GoogleDriveService
        self.token.token_secret = ''
        self.token.save()
        with self.assertRaises(ConnectionError):
            GoogleDriveService(self.user)
