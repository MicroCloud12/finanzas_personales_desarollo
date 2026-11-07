"""Importa un CSV de movimientos a registro_transacciones (libro mayor).
Corre: python importar_csv.py <ruta_csv>   (la ruta es obligatoria)

Columnas: Usuario (tu username, p. ej. "mauricio"; también acepta el id numérico), Fecha (dd/mm/yyyy),
Descripcion, Categoria, Monto, Tipo (gasto|ingreso|transferencia), Cuenta de origen, Cuenta de destino.
Columnas extra (p. ej. Nota) se ignoran.
Un movimiento que ya exista (mismo usuario, fecha, monto, tipo y descripción) se omite,
así que el archivo se puede volver a correr sin duplicar nada.

Las columnas "Cuenta de origen" / "Cuenta de destino" se ligan por nombre a las
cuentas del catálogo (`Cuenta`) del propietario. Un ingreso usa la cuenta de
origen del CSV como cuenta a la que ENTRA el dinero (formato histórico).
Nombres que no existan en el catálogo quedan sin ligar y se reportan al final;
después puedes ligarlos con `manage.py conciliar_saldos --ligar "Nombre=Cuenta"`.
"""
import csv, os, sys, django
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # raíz del proyecto
from datetime import datetime
from decimal import Decimal

ruta = sys.argv[1] if len(sys.argv) > 1 else sys.exit("Uso: python importar_csv.py <ruta_del_csv>")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()
from django.contrib.auth.models import User
from finanzas.models import registro_transacciones, Cuenta

TIPOS = {"gasto": "GASTO", "ingreso": "INGRESO", "transferencia": "TRANSFERENCIA"}
VACIOS = {"", "N/A", "SIN CUENTA", "OTRA CUENTA"}

cuentas = {(c.propietario_id, c.nombre.strip().upper()): c for c in Cuenta.objects.all()}
usuarios = {u.username: u.id for u in User.objects.all()}
sin_cuenta = {}
vistos = {}
duplicados = 0

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
        usuario = (r.get("Usuario") or r.get("propietario_id") or "").strip()
        propietario_id = int(usuario) if usuario.isdigit() else usuarios.get(usuario)
        if propietario_id not in usuarios.values():
            sys.exit(f"Fila {i}: el usuario {usuario!r} no existe. En la columna Usuario escribe tu "
                     f"username: {', '.join(usuarios)}")
        tipo = TIPOS[r["Tipo"].strip().lower()]
        fecha = datetime.strptime(r["Fecha"].strip(), "%d/%m/%Y").date()
        monto = Decimal(r["Monto"].strip())
        descripcion = r["Descripcion"].strip()[:100]
        # Dos viajes iguales el mismo día son dos movimientos: solo se omite lo que ya esté en la base
        # tantas veces como venga en el archivo (así el archivo se puede volver a correr sin duplicar).
        clave = (propietario_id, fecha, monto, tipo, descripcion.lower())
        vistos[clave] = vistos.get(clave, 0) + 1
        if vistos[clave] <= registro_transacciones.objects.filter(propietario_id=propietario_id, fecha=fecha, monto=monto,
                                                                  tipo=tipo, descripcion__iexact=descripcion).count():
            duplicados += 1
            continue
        origen = buscar(propietario_id, r["Cuenta de origen"])
        destino = buscar(propietario_id, r["Cuenta de destino"])
        if tipo == "INGRESO":
            origen, destino = None, (destino or origen)
        elif tipo == "GASTO":
            destino = None
        objs.append(registro_transacciones(
            propietario_id=propietario_id,
            fecha=fecha,
            descripcion=descripcion,
            categoria=r["Categoria"].strip()[:100],
            monto=monto,
            tipo=tipo,
            origen=origen,
            destino=destino,
            cuenta_origen=r["Cuenta de origen"].strip()[:100],
            cuenta_destino=r["Cuenta de destino"].strip()[:100],
        ))

# Guardamos uno por uno para que apliquen las reglas del libro (p. ej. una transferencia
# a un préstamo se registra como pago de mensualidad y marca su cuota).
for obj in objs:
    obj.save()
print(f"Insertados {len(objs)} movimientos." + (f" Omitidos {duplicados} que ya existían." if duplicados else ""))
for nombre, n in sorted(sin_cuenta.items(), key=lambda x: -x[1]):
    print(f"  Sin cuenta en el catálogo: {nombre!r} ({n} movimientos)")
