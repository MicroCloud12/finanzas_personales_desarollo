"""Importa movimientos_limpios.csv a registro_transacciones (libro mayor). Uso único.
Corre: virtual-enviroment/Scripts/python.exe importar_csv.py <ruta_csv>

Las columnas "Cuenta de origen" / "Cuenta de destino" se ligan por nombre a las
cuentas del catálogo (`Cuenta`) del propietario. Un ingreso usa la cuenta de
origen del CSV como cuenta a la que ENTRA el dinero (formato histórico).
Nombres que no existan en el catálogo quedan sin ligar y se reportan al final;
después puedes ligarlos con `manage.py conciliar_saldos --ligar "Nombre=Cuenta"`.
"""
import csv, os, sys, django
from datetime import datetime
from decimal import Decimal

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()
from finanzas.models import registro_transacciones, Cuenta

TIPOS = {"gasto": "GASTO", "ingreso": "INGRESO", "transferencia": "TRANSFERENCIA"}
VACIOS = {"", "N/A", "SIN CUENTA", "OTRA CUENTA"}
ruta = sys.argv[1] if len(sys.argv) > 1 else r"C:\Users\Mauricio\Downloads\movimientos_limpios.csv"

cuentas = {(c.propietario_id, c.nombre.strip().upper()): c for c in Cuenta.objects.all()}
sin_cuenta = {}

def buscar(propietario_id, nombre):
    nombre = (nombre or "").strip()
    if nombre.upper() in VACIOS:
        return None
    cuenta = cuentas.get((propietario_id, nombre.upper()))
    if cuenta is None:
        sin_cuenta[nombre] = sin_cuenta.get(nombre, 0) + 1
    return cuenta

objs = []
with open(ruta, encoding="utf-8-sig", newline="") as f:
    for i, r in enumerate(csv.DictReader(f), start=2):
        propietario_id = int(r["propietario_id"])
        tipo = TIPOS[r["Tipo"].strip().lower()]
        origen = buscar(propietario_id, r["Cuenta de origen"])
        destino = buscar(propietario_id, r["Cuenta de destino"])
        if tipo == "INGRESO":
            origen, destino = None, (destino or origen)
        elif tipo == "GASTO":
            destino = None
        objs.append(registro_transacciones(
            propietario_id=propietario_id,
            fecha=datetime.strptime(r["Fecha"].strip(), "%d/%m/%Y").date(),
            descripcion=r["Descripcion"].strip()[:100],
            categoria=r["Categoria"].strip()[:100],
            monto=Decimal(r["Monto"].strip()),
            tipo=tipo,
            origen=origen,
            destino=destino,
            cuenta_origen=r["Cuenta de origen"].strip()[:100],
            cuenta_destino=r["Cuenta de destino"].strip()[:100],
        ))

registro_transacciones.objects.bulk_create(objs, batch_size=500)
print(f"Insertados {len(objs)} movimientos.")
for nombre, n in sorted(sin_cuenta.items(), key=lambda x: -x[1]):
    print(f"  Sin cuenta en el catálogo: {nombre!r} ({n} movimientos)")
