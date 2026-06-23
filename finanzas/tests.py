from datetime import date
from django.test import TestCase
from .models import registro_transacciones
from .views.presupuesto import cadencia_dias, estimar_monto, proxima_fecha
from django.contrib.auth.models import User


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