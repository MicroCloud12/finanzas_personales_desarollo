from datetime import date
from allauth.socialaccount.models import SocialApp
from django.contrib.sites.models import Site
from django.test import TestCase
from django.urls import reverse
from .models import (registro_transacciones, Cuenta, Deuda, inversiones, Presupuesto, Factura,
                     proximo_dia_del_mes)
from .views.presupuesto import cadencia_dias, estimar_monto, proxima_fecha
from django.contrib.auth.models import User


class PaginasRenderizanTest(TestCase):
    """Smoke test: cada página responde 200 (cubre las plantillas compartidas form_simple/procesamiento)."""

    def test_paginas_get(self):
        user = User.objects.create_user('smoke', password='x')
        self.client.force_login(user)
        # provider_login_url necesita la app de Google configurada (en producción ya existe)
        SocialApp.objects.create(provider='google', name='Google', client_id='x', secret='y').sites.add(Site.objects.get_current())
        cuenta = Cuenta.objects.create(propietario=user, nombre='BBVA', tipo='DEBITO')
        deuda = Deuda.objects.create(propietario=user, nombre='Coche', monto_total=1000, tasa_interes=10, plazo_meses=12)
        mov = registro_transacciones.objects.create(propietario=user, fecha=date.today(), descripcion='x',
                                                    categoria='Comida', monto=10, tipo='GASTO', origen=cuenta)
        inv = inversiones.objects.create(propietario=user, nombre_activo='BTC', cantidad_titulos=1,
                                         fecha_compra=date.today(), precio_compra_titulo=1, precio_actual_titulo=1)
        pres = Presupuesto.objects.create(propietario=user, categoria='Agua')
        fac = Factura.objects.create(propietario=user, tienda='OXXO', total=10, estado='pendiente')
        paginas = [
            ('dashboard', []), ('resumen', []), ('portafolio', []), ('lista_transacciones', []),
            ('crear_transacciones', []), ('editar_transaccion', [mov.id]), ('revisar_tickets', []),
            ('procesamiento_automatico', []), ('lista_inversiones', []), ('crear_inversion', []),
            ('editar_inversion', [inv.id]), ('procesamiento_inversiones', []), ('revisar_inversiones', []),
            ('gestionar_suscripcion', []), ('lista_deudas', []), ('crear_deuda', []),
            ('detalle_deuda', [deuda.id]), ('editar_deuda', [deuda.id]), ('procesamiento_deudas', [deuda.id]),
            ('revisar_amortizaciones', [deuda.id]), ('mi_perfil', []), ('facturacion', []),
            ('revisar_facturas_pendientes', []), ('procesamiento_facturacion', []), ('revisar_factura', [fac.id]),
            ('editar_factura_registro', [fac.id]), ('gestionar_cuentas', []), ('editar_cuenta', [cuenta.id]),
            ('presupuesto', []), ('revisar_historicos', []), ('crear_presupuesto', []),
            ('editar_presupuesto', [pres.id]), ('privacy_policy', []), ('terms_of_service', []),
            ('password_change', []), ('robots', []),
        ]
        for nombre, args in paginas:
            with self.subTest(nombre):
                self.assertEqual(self.client.get(reverse(nombre, args=args)).status_code, 200)
        # Borrar ya no tiene página de confirmación: solo POST (confirm() en la lista)
        self.assertEqual(self.client.get(reverse('eliminar_deuda', args=[deuda.id])).status_code, 405)

    def test_proximo_dia_del_mes(self):
        self.assertEqual(proximo_dia_del_mes(31, hoy=date(2026, 2, 10)), date(2026, 2, 28))  # mes corto
        self.assertEqual(proximo_dia_del_mes(5, hoy=date(2026, 12, 20)), date(2027, 1, 5))   # cruza de año
        self.assertEqual(proximo_dia_del_mes(20, hoy=date(2026, 3, 20)), date(2026, 3, 20))  # hoy cuenta
        self.assertIsNone(proximo_dia_del_mes(None))


class PrediccionReciboTest(TestCase):
    def test_cadencia_bimestral(self):
        # ~61 días entre recibos -> bimestral
        fechas = [date(2026, 1, 9), date(2026, 3, 11), date(2026, 5, 9)]
        self.assertEqual(cadencia_dias(fechas, 'agua'), 60)

    def test_cadencia_default_un_recibo(self):
        self.assertEqual(cadencia_dias([date(2026, 5, 9)], 'agua'), 61)
        self.assertEqual(cadencia_dias([], 'gas'), 30)

    def test_estimar_monto_tendencia(self):
        # serie creciente: la predicción debe quedar por encima de la media y dentro del tope +25%
        montos = [800.0, 860.0, 944.0]
        pred = estimar_monto(montos)
        self.assertGreater(pred, sum(montos) / 3)
        self.assertLessEqual(pred, (sum(montos) / 3) * 1.25)

    def test_estimar_monto_un_valor(self):
        self.assertEqual(estimar_monto([944.0]), 944.0)

    def test_proxima_fecha_proyecta_al_futuro(self):
        # último recibo viejo (2025): debe saltar ciclos hasta pasar 'hoy'
        f = proxima_fecha(date(2025, 6, 21), 61, date(2026, 6, 19))
        self.assertGreater(f, date(2026, 6, 19))
        # y debe caer dentro de un ciclo después de hoy
        self.assertLessEqual((f - date(2026, 6, 19)).days, 61)

class RegistroTransaccionesModelTest(TestCase):
    def test_str_representation(self):
        user = User.objects.create(username="tester")
        trans = registro_transacciones.objects.create(
            propietario=user,
            fecha=date.today(),
            descripcion="Compra",
            categoria="General",
            monto=10,
            tipo="INGRESO",
            cuenta_origen="A",
            cuenta_destino="B",
        )

        self.assertEqual(str(trans), f"{trans.id} - Compra")