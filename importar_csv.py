"""Importa movimientos_limpios.csv a registro_transacciones. Uso único.
Corre: virtual-enviroment/Scripts/python.exe importar_csv.py <ruta_csv>
ponytail: bulk_create salta save() a propósito (no toca saldos de Deuda en histórico)."""
import csv, os, sys, django
from datetime import datetime
from decimal import Decimal

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()
from finanzas.models import registro_transacciones

TIPOS = {"gasto": "GASTO", "ingreso": "INGRESO", "transferencia": "TRANSFERENCIA"}
ruta = sys.argv[1] if len(sys.argv) > 1 else r"C:\Users\Mauricio\Downloads\movimientos_limpios.csv"

objs = []
with open(ruta, encoding="utf-8-sig", newline="") as f:
    for i, r in enumerate(csv.DictReader(f), start=2):
        objs.append(registro_transacciones(
            propietario_id=int(r["propietario_id"]),
            fecha=datetime.strptime(r["Fecha"].strip(), "%d/%m/%Y").date(),
            descripcion=r["Descripcion"].strip()[:100],
            categoria=r["Categoria"].strip()[:100],
            monto=Decimal(r["Monto"].strip()),
            tipo=TIPOS[r["Tipo"].strip().lower()],
            cuenta_origen=r["Cuenta de origen"].strip()[:100],
            cuenta_destino=r["Cuenta de destino"].strip()[:100],
        ))

registro_transacciones.objects.bulk_create(objs, batch_size=500)
print(f"Insertados {len(objs)} movimientos.")
