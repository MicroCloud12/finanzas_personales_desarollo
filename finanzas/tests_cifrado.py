"""
Pruebas de seguridad y cifrado Nivel 2:
  1. Inspección SQL cruda: ningún monto, saldo, descripción, tarjeta ni JSON aparece en claro en BD.
  2. Aislamiento por usuario: cada usuario tiene su propia DEK y alterar el uid invalida el HMAC.
  3. Rotación de llave maestra (`generar_llave_cifrado --rotar`) sin pérdida de datos.
  4. Migración de datos existentes en texto plano (`_cifrado_datos.cifrar_datos_existentes`).
  5. Privacidad en `/admin/`: ningún modelo financiero personal está expuesto.
"""
from datetime import date
from decimal import Decimal as D
from io import StringIO

from cryptography.fernet import Fernet, InvalidToken
from django.apps import apps
from django.contrib import admin
from django.contrib.auth.models import User
from django.core.management import call_command
from django.db import IntegrityError, connection
from django.test import TestCase, override_settings

from .crypto import ENC_PREFIX, clear_key_cache, decrypt_str
from .migrations import _cifrado_datos
from .models import (
    AliasComercio,
    AmortizacionPendiente,
    Cuenta,
    Deuda,
    Factura,
    HistorialReciboServicio,
    LlaveUsuario,
    PagoAmortizacion,
    PendingInvestment,
    PortfolioHistory,
    Presupuesto,
    SaldoEstadoCuenta,
    Suscripcion,
    TiendaFacturacion,
    TransaccionPendiente,
    UsoIA,
    inversiones,
    registro_transacciones,
)


def _raw_row(tabla: str, pk: int, columnas: list[str]) -> tuple:
    cols = ", ".join(columnas)
    with connection.cursor() as cur:
        cur.execute(f"SELECT {cols} FROM {tabla} WHERE id = %s", [pk])
        return cur.fetchone()


class CifradoEnSqlCrudoTest(TestCase):

    def setUp(self):
        self.ana = User.objects.create_user("ana_sec", password="x")
        self.beto = User.objects.create_user("beto_sec", password="x")

    def test_todas_las_tablas_financieras_quedan_cifradas_en_sql(self):
        cuenta = Cuenta.objects.create(
            propietario=self.ana, nombre="Banamex Oro", terminacion="4821",
            tipo="DEBITO", saldo_inicial=D("25430.75"),
        )
        saldo_ec = SaldoEstadoCuenta.objects.create(
            cuenta=cuenta, anio=2026, mes=11, saldo_banco=D("25000.50"), nota="Corte noviembre",
        )
        mov = registro_transacciones.objects.create(
            propietario=self.ana, fecha=date(2026, 11, 10), descripcion="FARMACIA SAN PABLO",
            categoria="Salud", monto=D("430.250"), tipo="GASTO", origen=cuenta,
            cuenta_origen="Banamex Oro", datos_extra={"folio": "FSP-9981"},
        )
        pend_tx = TransaccionPendiente.objects.create(
            propietario=self.ana, datos_json={"establecimiento": "COSTCO", "total": 1899.90},
        )
        inv = inversiones.objects.create(
            propietario=self.ana, emisora_ticker="NVDA", nombre_activo="NVIDIA Corp",
            cantidad_titulos=D("2.5"), fecha_compra=date(2026, 10, 1),
            precio_compra_titulo=D("120.00"), precio_actual_titulo=D("140.00"),
            tipo_cambio_compra=D("19.85"),
        )
        pend_inv = PendingInvestment.objects.create(
            propietario=self.ana, datos_json={"nombre_activo": "Apple", "precio_por_titulo": "220"},
        )
        deuda = Deuda.objects.create(
            propietario=self.ana, nombre="Crédito Automotriz", tipo_deuda="PRESTAMO",
            monto_total=D("180000.00"), tasa_interes=D("13.50"), plazo_meses=24,
        )
        cuota = PagoAmortizacion.objects.create(
            deuda=deuda, numero_cuota=1, fecha_vencimiento=date(2026, 12, 1),
            capital=D("6500.00"), interes=D("2025.00"), iva=D("324.00"), saldo_insoluto=D("173500.00"),
        )
        amort_pend = AmortizacionPendiente.objects.create(
            propietario=self.ana, deuda=deuda, datos_json=[{"capital": 6500}], nombre_archivo="tabla_bbva.pdf",
        )
        fac = Factura.objects.create(
            propietario=self.ana, tienda="WALMART", fecha_emision=date(2026, 11, 12),
            total=D("980.40"), datos_facturacion={"rfc": "XAXX010101000", "ticket": "777123"},
            archivo_drive_id="drive_file_abc123",
        )
        hist_port = PortfolioHistory.objects.create(
            usuario=self.ana, fecha=date(2026, 11, 12), valor_total=D("350.00"),
            capital_invertido=D("300.00"), ganancia_no_realizada=D("50.00"),
        )
        pres = Presupuesto.objects.create(
            propietario=self.ana, categoria="Electricidad CFE",
            monto_presupuestado=D("1250.00"), monto_real=D("1190.00"),
        )
        recibo = HistorialReciboServicio.objects.create(
            propietario=self.ana, presupuesto=pres, fecha_emision=date(2026, 11, 1),
            monto_total=D("1190.00"), datos_json={"consumo": "310 kWh"}, archivo_drive_id="cfe_nov_2026",
        )
        alias = AliasComercio.objects.create(
            propietario=self.ana, texto_banco="DLO*UBER", descripcion="Uber", categoria="Transporte",
        )

        verificaciones = [
            ("finanzas_cuenta", cuenta.id, ["nombre", "terminacion", "saldo_inicial"], ["Banamex", "4821", "25430"]),
            ("finanzas_saldoestadocuenta", saldo_ec.id, ["saldo_banco", "nota"], ["25000", "Corte"]),
            ("finanzas_registro_transacciones", mov.id, ["descripcion", "categoria", "monto", "monto_interes", "cuenta_origen", "datos_extra"], ["FARMACIA", "Salud", "430.25", "FSP-9981"]),
            ("finanzas_transaccionpendiente", pend_tx.id, ["datos_json"], ["COSTCO", "1899"]),
            ("finanzas_inversiones", inv.id, ["emisora_ticker", "nombre_activo", "cantidad_titulos", "precio_compra_titulo", "valor_actual_mercado"], ["NVDA", "NVIDIA", "120", "350"]),
            ("finanzas_pendinginvestment", pend_inv.id, ["datos_json"], ["Apple", "220"]),
            ("finanzas_deuda", deuda.id, ["nombre", "monto_total", "tasa_interes"], ["Automotriz", "180000", "13.50"]),
            ("finanzas_pagoamortizacion", cuota.id, ["capital", "interes", "iva", "saldo_insoluto", "pago_total"], ["6500", "2025", "8849"]),
            ("finanzas_amortizacionpendiente", amort_pend.id, ["datos_json", "nombre_archivo"], ["6500", "tabla_bbva"]),
            ("finanzas_factura", fac.id, ["tienda", "total", "datos_facturacion", "archivo_drive_id"], ["WALMART", "980.40", "XAXX010101000", "drive_file_abc123"]),
            ("finanzas_portfoliohistory", hist_port.id, ["valor_total", "capital_invertido", "ganancia_no_realizada"], ["350", "300", "50"]),
            ("finanzas_presupuesto", pres.id, ["categoria", "monto_presupuestado", "monto_real"], ["Electricidad", "1250", "1190"]),
            ("finanzas_historialreciboservicio", recibo.id, ["monto_total", "datos_json", "archivo_drive_id"], ["1190", "310 kWh", "cfe_nov_2026"]),
            ("finanzas_aliascomercio", alias.id, ["texto_banco", "descripcion", "categoria"], ["UBER", "Transporte"]),
        ]

        prefijo_ana = f"{ENC_PREFIX}{self.ana.id}:"
        for tabla, pk, cols, prohibidos in verificaciones:
            crudo = _raw_row(tabla, pk, cols)
            for col_name, valor_sql in zip(cols, crudo):
                self.assertIsInstance(valor_sql, str, f"{tabla}.{col_name} debe ser texto cifrado")
                self.assertTrue(
                    valor_sql.startswith(prefijo_ana),
                    f"{tabla}.{col_name} no está cifrado con la llave de Ana: {valor_sql!r}",
                )
                for texto_plano in prohibidos:
                    self.assertNotIn(texto_plano, valor_sql, f"Se filtró {texto_plano!r} en {tabla}.{col_name}")

        # Y al leer desde Django ORM, todos los tipos y valores regresan exactos
        mov.refresh_from_db()
        self.assertEqual((mov.descripcion, mov.monto, mov.datos_extra), ("FARMACIA SAN PABLO", D("430.250"), {"folio": "FSP-9981"}))
        cuota.refresh_from_db()
        self.assertEqual(cuota.pago_total, D("8849.00"))

    def test_aislamiento_entre_usuarios_e_integridad_hmac(self):
        c_ana = Cuenta.objects.create(propietario=self.ana, nombre="Santander", tipo="DEBITO", saldo_inicial=D("5000"))
        c_beto = Cuenta.objects.create(propietario=self.beto, nombre="Santander", tipo="DEBITO", saldo_inicial=D("5000"))

        raw_ana = _raw_row("finanzas_cuenta", c_ana.id, ["nombre", "nombre_hash", "saldo_inicial"])
        raw_beto = _raw_row("finanzas_cuenta", c_beto.id, ["nombre", "nombre_hash", "saldo_inicial"])

        # Mismo nombre y mismo saldo, pero tanto el ciphertext como el blind index son distintos
        self.assertNotEqual(raw_ana[0], raw_beto[0])
        self.assertNotEqual(raw_ana[1], raw_beto[1])
        self.assertNotEqual(raw_ana[2], raw_beto[2])

        # Si alguien intenta leer un token de Ana fingiendo ser el uid de Beto, HMAC falla
        token_solo = raw_ana[0].split(":", 3)[3]
        adulterado = f"{ENC_PREFIX}{self.beto.id}:{token_solo}"
        with self.assertRaises(InvalidToken):
            decrypt_str(adulterado)

    def test_unicidad_por_indice_ciego(self):
        from django.db import transaction
        Cuenta.objects.create(propietario=self.ana, nombre="BBVA", tipo="DEBITO")
        # Mismo usuario, mismo nombre en minúsculas -> rechazado por unique_together(propietario, nombre_hash)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Cuenta.objects.create(propietario=self.ana, nombre="  bbva ", tipo="AHORRO")
        # Otro usuario sí puede tener "BBVA"
        Cuenta.objects.create(propietario=self.beto, nombre="BBVA", tipo="DEBITO")


class RotacionLlaveMaestraTest(TestCase):

    def test_rotar_llave_maestra_conserva_acceso_a_datos(self):
        k_vieja = Fernet.generate_key().decode("ascii")
        k_nueva = Fernet.generate_key().decode("ascii")

        with override_settings(DATA_ENCRYPTION_KEY=k_vieja):
            clear_key_cache()
            u = User.objects.create_user("rota", password="x")
            c = Cuenta.objects.create(propietario=u, nombre="Nu", saldo_inicial=D("777.77"))

        # Paso 1: agregar llave nueva adelante (k_nueva,k_vieja) y correr --rotar
        with override_settings(DATA_ENCRYPTION_KEY=f"{k_nueva},{k_vieja}"):
            clear_key_cache()
            call_command("generar_llave_cifrado", "--rotar", stdout=StringIO())

        # Paso 2: retirar k_vieja por completo; todo sigue descifrándose con k_nueva
        with override_settings(DATA_ENCRYPTION_KEY=k_nueva):
            clear_key_cache()
            c.refresh_from_db()
            self.assertEqual(c.nombre, "Nu")
            self.assertEqual(c.saldo_inicial, D("777.77"))
            self.assertEqual(LlaveUsuario.objects.filter(usuario=u).count(), 1)


class MigracionTextoPlanoACifradoTest(TestCase):

    def test_cifra_filas_antiguas_en_texto_plano_y_calcula_hashes(self):
        u = User.objects.create_user("legacy_plain", password="x")
        c = Cuenta.objects.create(propietario=u, nombre="Temp", tipo="DEBITO", saldo_inicial=D("0"))
        t = registro_transacciones.objects.create(
            propietario=u, fecha=date(2026, 5, 1), descripcion="Temp", categoria="Temp",
            monto=D("1"), tipo="GASTO", origen=c,
        )

        # Simulamos cómo quedan las columnas justo después de convertirlas a TEXT antes de 0035
        with connection.cursor() as cur:
            cur.execute(
                "UPDATE finanzas_cuenta SET nombre = %s, saldo_inicial = %s, nombre_hash = '' WHERE id = %s",
                ["Santander Legacy", "1234.50", c.id],
            )
            cur.execute(
                "UPDATE finanzas_registro_transacciones SET descripcion = %s, categoria = %s, monto = %s WHERE id = %s",
                ["SUPERMERCADO", "Comida", "345.670", t.id],
            )

        _cifrado_datos.cifrar_datos_existentes(apps)

        raw_c = _raw_row("finanzas_cuenta", c.id, ["nombre", "saldo_inicial", "nombre_hash"])
        raw_t = _raw_row("finanzas_registro_transacciones", t.id, ["descripcion", "categoria", "monto"])
        self.assertTrue(raw_c[0].startswith(f"{ENC_PREFIX}{u.id}:"))
        self.assertTrue(raw_c[1].startswith(f"{ENC_PREFIX}{u.id}:"))
        self.assertEqual(len(raw_c[2]), 64)
        self.assertTrue(all(x.startswith(f"{ENC_PREFIX}{u.id}:") for x in raw_t))

        c.refresh_from_db()
        t.refresh_from_db()
        self.assertEqual((c.nombre, c.saldo_inicial), ("Santander Legacy", D("1234.50")))
        self.assertEqual((t.descripcion, t.categoria, t.monto), ("SUPERMERCADO", "Comida", D("345.670")))
        self.assertEqual(Cuenta.objects.por_nombre(u, "santander legacy"), c)


class AdminPrivacidadTest(TestCase):

    def test_admin_no_expone_modelos_financieros_privados(self):
        registrados = set(admin.site._registry.keys())
        privados = {
            Cuenta, SaldoEstadoCuenta, registro_transacciones, TransaccionPendiente,
            inversiones, PendingInvestment, Deuda, PagoAmortizacion, AmortizacionPendiente,
            Factura, PortfolioHistory, Presupuesto, HistorialReciboServicio, AliasComercio,
            LlaveUsuario,
        }
        self.assertTrue(registrados.isdisjoint(privados), f"Modelos privados expuestos en Admin: {registrados & privados}")
        self.assertTrue({Suscripcion, UsoIA, TiendaFacturacion}.issubset(registrados))
