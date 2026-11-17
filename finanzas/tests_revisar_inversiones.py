"""
Pruebas de la pantalla Revisar Inversiones: aprobar / rechazar todas.

Correr:  python manage.py test finanzas.tests_revisar_inversiones
"""
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.contrib.messages import get_messages
from django.test import TestCase
from django.urls import reverse

from .models import PendingInvestment, inversiones


class RevisarTodasInversionesTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('mau', password='x')
        self.otro = User.objects.create_user('otro', password='x')
        self.buena = PendingInvestment.objects.create(propietario=self.user, datos_json={
            "nombre_activo": "Vanguard S&P 500", "emisora_ticker": "VOO", "fecha_compra": "2026-11-10",
            "cantidad_titulos": "3", "precio_por_titulo": "9500.17", "valor_actual_mercado": "28800.00"})
        self.mala = PendingInvestment.objects.create(propietario=self.user, datos_json={
            "nombre_activo": "Sin datos", "emisora_ticker": "XXX", "fecha_compra": "2026-11-11",
            "cantidad_titulos": "abc", "precio_por_titulo": "10"})
        self.ajena = PendingInvestment.objects.create(propietario=self.otro, datos_json={
            "nombre_activo": "De otro", "emisora_ticker": "OTR", "fecha_compra": "2026-11-11",
            "cantidad_titulos": "1", "precio_por_titulo": "10"})
        self.client.login(username='mau', password='x')

    def mensajes(self, r):
        return [m.message for m in get_messages(r.wsgi_request)]

    def test_botones_solo_cuando_hay_pendientes(self):
        r = self.client.get(reverse('revisar_inversiones'))
        self.assertContains(r, 'Aprobar Todas')
        self.assertContains(r, reverse('rechazar_todas_inversiones'))
        PendingInvestment.objects.filter(propietario=self.user).update(estado='rechazada')
        r = self.client.get(reverse('revisar_inversiones'))
        self.assertNotContains(r, 'Aprobar Todas')
        self.assertContains(r, 'Todo al día')

    @patch('finanzas.views.inversiones.update_user_portfolio_history')
    def test_aprobar_todas_crea_las_inversiones_y_deja_las_malas_pendientes(self, tarea):
        r = self.client.post(reverse('aprobar_todas_inversiones'))
        self.assertRedirects(r, reverse('revisar_inversiones'), fetch_redirect_response=False)
        inv = inversiones.objects.get(propietario=self.user)
        self.assertEqual((inv.emisora_ticker, inv.cantidad_titulos, inv.precio_compra_titulo), ('VOO', Decimal('3'), Decimal('9500.17')))
        self.buena.refresh_from_db(); self.mala.refresh_from_db(); self.ajena.refresh_from_db()
        self.assertEqual((self.buena.estado, self.mala.estado, self.ajena.estado), ('aprobada', 'pendiente', 'pendiente'))
        tarea.delay.assert_called_once_with(self.user.id)
        msgs = self.mensajes(r)
        self.assertIn('1 inversion aprobada', msgs[0])
        self.assertIn('Sin datos', msgs[1])

    @patch('finanzas.views.inversiones.update_user_portfolio_history')
    def test_rechazar_todas_solo_las_del_usuario(self, tarea):
        r = self.client.post(reverse('rechazar_todas_inversiones'))
        self.assertRedirects(r, reverse('revisar_inversiones'), fetch_redirect_response=False)
        self.assertEqual(PendingInvestment.objects.filter(propietario=self.user, estado='rechazada').count(), 2)
        self.ajena.refresh_from_db()
        self.assertEqual(self.ajena.estado, 'pendiente')
        self.assertEqual(inversiones.objects.count(), 0)
        tarea.delay.assert_not_called()
        self.assertIn('2 inversiones rechazadas', self.mensajes(r)[-1])

    def test_get_no_cambia_nada(self):
        self.client.get(reverse('aprobar_todas_inversiones'))
        self.client.get(reverse('rechazar_todas_inversiones'))
        self.assertEqual(PendingInvestment.objects.filter(estado='pendiente').count(), 3)
        self.assertEqual(inversiones.objects.count(), 0)
