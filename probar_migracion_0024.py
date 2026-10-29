"""
Prueba de la migración 0024_libro_mayor de punta a punta sobre SQLite:
1. Construye las tablas en el estado de la migración 0023 (modelos históricos).
2. Inserta datos "viejos" (nombres de cuenta en texto, saldo_pendiente mutable).
3. Aplica 0024 con el ejecutor real de Django.
4. Verifica los saldos derivados.
"""
import os
import sys
from datetime import date
from decimal import Decimal as D

os.environ['DJANGO_SETTINGS_MODULE'] = 'test_settings'
import django
from django.conf import settings

DB = '/tmp/prueba_0024.sqlite3'
if os.path.exists(DB):
    os.remove(DB)
settings.DATABASES['default']['NAME'] = DB
settings.MIGRATION_MODULES = {}
django.setup()

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.recorder import MigrationRecorder

executor = MigrationExecutor(connection)
loader = executor.loader

# 1. Tablas de las apps base (auth, contenttypes, etc.) con migraciones normales
otras = [k for k in loader.graph.leaf_nodes() if k[0] != 'finanzas']
executor.migrate(otras)

# Estado histórico de finanzas en 0023
estado = loader.project_state(('finanzas', '0023_presupuesto_monto_real'))
apps_viejas = estado.apps
with connection.schema_editor() as editor:
    for model in apps_viejas.get_app_config('finanzas').get_models():
        editor.create_model(model)
# Registramos 0001..0023 como aplicadas para que el ejecutor solo corra 0024
recorder = MigrationRecorder(connection)
for key in loader.graph.forwards_plan(('finanzas', '0023_presupuesto_monto_real')):
    if key[0] == 'finanzas':
        recorder.record_applied(*key)

# 2. Datos viejos
User = apps_viejas.get_model('auth', 'User')
Cuenta = apps_viejas.get_model('finanzas', 'Cuenta')
Deuda = apps_viejas.get_model('finanzas', 'Deuda')
Tx = apps_viejas.get_model('finanzas', 'registro_transacciones')
PagoAmort = apps_viejas.get_model('finanzas', 'PagoAmortizacion')

u = User.objects.create(username='mau')
Cuenta.objects.create(propietario=u, nombre='BBVA', tipo='DEBITO')
Cuenta.objects.create(propietario=u, nombre='Tarjeta Nu', tipo='CREDITO')
tc = Deuda.objects.create(propietario=u, nombre='Tarjeta Nu', tipo_deuda='TARJETA_CREDITO',
                          monto_total=D('10000'), tasa_interes=D('50'), plazo_meses=1, saldo_pendiente=D('9000'))
pr = Deuda.objects.create(propietario=u, nombre='Crédito Coche', tipo_deuda='PRESTAMO',
                          monto_total=D('50000'), tasa_interes=D('12'), plazo_meses=12, saldo_pendiente=D('46000'))

def legacy(tipo, monto, origen, destino, deuda=None, tipo_pago='MENSUALIDAD'):
    return Tx.objects.create(propietario=u, fecha=date(2026, 9, 1), descripcion=tipo, categoria='x',
                             monto=D(str(monto)), tipo=tipo, cuenta_origen=origen, cuenta_destino=destino,
                             deuda_asociada=deuda, tipo_pago=tipo_pago)

legacy('INGRESO', 8000, 'BBVA', 'Sin Cuenta')
legacy('GASTO', 700, 'BBVA', 'Sin Cuenta')
legacy('GASTO', 1500, 'Tarjeta Nu', 'N/A')
legacy('TRANSFERENCIA', 500, 'BBVA', 'Tarjeta Nu')
pago = legacy('PAGO_MENSUALIDAD', 5000, 'BBVA', 'Crédito Coche', deuda=pr)
cuota = PagoAmort.objects.create(deuda=pr, numero_cuota=1, fecha_vencimiento=date(2026, 9, 15), capital=D('4000'),
                                 interes=D('862.07'), iva=D('137.93'), saldo_insoluto=D('46000'), pago_total=D('5000'),
                                 pagado=True, transaccion_pago=pago)
legacy('GASTO', 100, 'Efectivo Quincena', 'N/A')
legacy('GASTO', 250, 'Tarjeta Nu', 'N/A', deuda=tc, tipo_pago='TARJETA_CREDITO')

# 3. Aplicar 0024
executor = MigrationExecutor(connection)
executor.migrate([('finanzas', '0024_libro_mayor')])

# 4. Verificar con los modelos reales
from finanzas.models import Cuenta as C, Deuda as Dd, registro_transacciones as T
tc = Dd.objects.get(nombre='Tarjeta Nu'); pr = Dd.objects.get(nombre='Crédito Coche')
bbva = C.objects.get(nombre='BBVA')
print('Tarjeta Nu: debe', tc.saldo_pendiente, '| disponible', tc.disponible, '| saldo_inicial', tc.cuenta.saldo_inicial, '| legado', tc.saldo_legado)
print('Crédito Coche: debe', pr.saldo_pendiente, '| saldo_inicial', pr.cuenta.saldo_inicial, '| legado', pr.saldo_legado)
print('BBVA: saldo', bbva.saldo())
p = T.objects.get(tipo='PAGO_MENSUALIDAD')
print('Pago mensualidad: interés', p.monto_interes, 'capital', p.monto_capital, 'destino', p.destino, 'deuda', p.deuda_asociada)
print('Columnas tx:', [f.name for f in T._meta.get_fields() if f.concrete])

assert tc.saldo_pendiente == D('1000') - D('0') + D('250') - D('250'), tc.saldo_pendiente  # 10000-9000 = 1000 (el libro ya explica 1500+250-500=1250 => inicial -250)
assert pr.saldo_pendiente == D('46000'), pr.saldo_pendiente
assert p.monto_interes == D('1000.000'), p.monto_interes
assert bbva.saldo() == D('8000') - D('700') - D('500') - D('5000')
assert 'tipo_pago' not in [f.name for f in T._meta.get_fields()]
print('\nOK: migración 0024 aplicada y conciliada correctamente.')
