"""Pruebas del detalle de deuda: borrar la tabla de amortización para volver a cargarla."""
from datetime import date
from decimal import Decimal as D

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .models import Cuenta, Deuda, PagoAmortizacion, registro_transacciones


class BorrarAmortizacionTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('mau', password='x')
        self.deuda = Deuda.objects.create(propietario=self.user, nombre='Digitt', tipo_deuda='PRESTAMO',
                                          monto_total=D('20000'), tasa_interes=D('60'), plazo_meses=12)
        self.santander = Cuenta.objects.create(propietario=self.user, nombre='Santander', tipo='DEBITO', saldo_inicial=D('5000'))
        self.pago = registro_transacciones.objects.create(propietario=self.user, fecha=date(2026, 11, 13), descripcion='PAGO DIGITT',
                                                          categoria='Deudas', monto=D('1775.54'), tipo='TRANSFERENCIA',
                                                          origen=self.santander, destino=self.deuda.cuenta)
        for n in range(1, 4):
            PagoAmortizacion.objects.create(deuda=self.deuda, numero_cuota=n, fecha_vencimiento=date(2026, 8 + n, 13),
                                            capital=D('1200'), interes=D('500'), iva=D('80'), saldo_insoluto=D('20000') - 1200 * n,
                                            pagado=(n == 1), transaccion_pago=self.pago if n == 1 else None)
        self.client.login(username='mau', password='x')

    def test_boton_solo_con_cuotas_y_borra_sin_tocar_los_pagos(self):
        r = self.client.get(reverse('detalle_deuda', args=[self.deuda.id]))
        self.assertContains(r, 'Borrar tabla')
        self.assertEqual(self.client.get(reverse('eliminar_amortizacion', args=[self.deuda.id])).status_code, 405)
        r = self.client.post(reverse('eliminar_amortizacion', args=[self.deuda.id]), follow=True)
        self.assertRedirects(r, reverse('detalle_deuda', args=[self.deuda.id]))
        self.assertEqual(PagoAmortizacion.objects.filter(deuda=self.deuda).count(), 0)
        self.assertTrue(registro_transacciones.objects.filter(id=self.pago.id).exists())   # el pago sigue en el libro
        self.assertEqual(self.deuda.cuenta.saldo(), self.deuda.cuenta.saldo_inicial - D('1775.54'))   # y la deuda sigue abonada
        self.assertIn("Se borraron 3 cuotas", [str(m) for m in r.context['messages']][0])
        self.assertNotContains(r, 'Borrar tabla')                      # ya no hay cuotas

    def test_no_borra_la_tabla_de_otro(self):
        otro = User.objects.create_user('otro', password='x')
        ajena = Deuda.objects.create(propietario=otro, nombre='Ajena', tipo_deuda='PRESTAMO', monto_total=D('1'), tasa_interes=D('1'), plazo_meses=1)
        self.assertEqual(self.client.post(reverse('eliminar_amortizacion', args=[ajena.id])).status_code, 404)


class EliminarDeudaDesdeLaListaTest(BorrarAmortizacionTest):
    def test_el_boton_de_la_lista_manda_post_y_borra_la_deuda(self):
        # Antes era un <a href>, y como la vista solo acepta POST el botón terminaba en un 405.
        r = self.client.get(reverse('lista_deudas'))
        url = reverse('eliminar_deuda', args=[self.deuda.id])
        self.assertContains(r, f'<form method="POST" action="{url}"')
        self.assertNotContains(r, f'<a href="{url}"')
        cuenta_id = self.deuda.cuenta_id
        r = self.client.post(url, follow=True)
        self.assertRedirects(r, reverse('lista_deudas'))
        self.assertFalse(Deuda.objects.filter(id=self.deuda.id).exists())
        self.assertFalse(Cuenta.objects.filter(id=cuenta_id).exists())                   # se va su cuenta de pasivo
        self.assertEqual(PagoAmortizacion.objects.filter(deuda_id=self.deuda.id).count(), 0)
        self.assertTrue(registro_transacciones.objects.filter(id=self.pago.id).exists())  # el movimiento se conserva
        self.assertContains(r, 'ha sido eliminada correctamente')
        self.assertContains(r, 'no has registrado ninguna deuda')


class MarcarCuotaTest(BorrarAmortizacionTest):
    def test_resumen_y_toggle_de_cuotas(self):
        r = self.client.get(reverse('detalle_deuda', args=[self.deuda.id]))
        # 1 de 3 cuotas pagada: 1200 + 500 + 80 = 1780; faltan 2 x 1780 = 3560
        self.assertEqual(r.context['resumen']['n_pagadas'], 1)
        self.assertEqual(r.context['resumen']['total_pagado'], D('1780'))
        self.assertEqual(r.context['resumen']['capital_pagado'], D('1200'))
        self.assertEqual(r.context['resumen']['interes_pagado'], D('580'))
        self.assertEqual(r.context['resumen']['total_pendiente'], D('3560'))
        self.assertContains(r, 'Pagado según la tabla:')
        self.assertContains(r, '$1,780.00')

        cuota2 = PagoAmortizacion.objects.get(deuda=self.deuda, numero_cuota=2)
        url = reverse('marcar_cuota', args=[cuota2.id])
        self.assertEqual(self.client.get(url).status_code, 405)
        r = self.client.post(url, follow=True)
        self.assertRedirects(r, reverse('detalle_deuda', args=[self.deuda.id]))
        cuota2.refresh_from_db()
        self.assertTrue(cuota2.pagado)
        self.assertEqual(r.context['resumen']['n_pagadas'], 2)
        self.assertEqual(r.context['resumen']['total_pagado'], D('3560'))
        # Marcar como pendiente una cuota ligada a un pago la desliga, pero el pago sigue en el libro
        cuota1 = PagoAmortizacion.objects.get(deuda=self.deuda, numero_cuota=1)
        self.client.post(reverse('marcar_cuota', args=[cuota1.id]))
        cuota1.refresh_from_db()
        self.assertFalse(cuota1.pagado)
        self.assertIsNone(cuota1.transaccion_pago)
        self.assertTrue(registro_transacciones.objects.filter(id=self.pago.id).exists())
        # el saldo del libro no cambia por marcar cuotas
        self.assertEqual(self.deuda.cuenta.saldo(), self.deuda.cuenta.saldo_inicial - D('1775.54'))

    def test_no_marca_cuotas_de_otro(self):
        otro = User.objects.create_user('otro2', password='x')
        self.client.login(username='otro2', password='x')
        cuota = PagoAmortizacion.objects.get(deuda=self.deuda, numero_cuota=2)
        self.assertEqual(self.client.post(reverse('marcar_cuota', args=[cuota.id])).status_code, 404)
        cuota.refresh_from_db()
        self.assertFalse(cuota.pagado)
