"""Importa un CSV de movimientos al libro mayor desde la terminal (lo mismo que el botón "Subir CSV").
Corre: python importar_csv.py <ruta_csv>   (la ruta es obligatoria)

Acepta el archivo que exporta Santander o el formato propio (ver finanzas/importacion.py).
En el formato propio la columna Usuario dice a quién pertenece (username o id numérico);
en el de Santander, o si la columna viene vacía, se usa --usuario (o el único usuario que exista).
Un movimiento que ya exista se omite, así que el archivo se puede volver a correr sin duplicar nada.
Nombres de cuenta que no existan en el catálogo quedan sin ligar y se reportan al final;
después puedes ligarlos con `manage.py conciliar_saldos --ligar "Nombre=Cuenta"`.
"""
import os
import sys

import django

args = [a for a in sys.argv[1:] if not a.startswith("--")]
opciones = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--") and "=" in a)
if not args:
    sys.exit("Uso: python importar_csv.py <ruta_del_csv> [--usuario=mauricio]")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()
from django.contrib.auth.models import User
from finanzas.importacion import aplicar_alias, decodificar, importar, leer_csv

with open(args[0], "rb") as f:
    try:
        filas, es_santander = leer_csv(decodificar(f.read()))
    except ValueError as e:
        sys.exit(f"No pude leer el archivo: {e}")
if not filas:
    sys.exit("El archivo no trae movimientos.")

valores = {f["usuario"] for f in filas} - {""}
if len(valores) > 1:
    sys.exit(f"El archivo mezcla varios usuarios ({', '.join(sorted(valores))}); sube uno por usuario.")
nombre = opciones.get("usuario") or (valores.pop() if valores else "")
usuarios = {u.username: u for u in User.objects.all()}
if nombre.isdigit():
    usuario = User.objects.filter(id=int(nombre)).first()
elif nombre:
    usuario = usuarios.get(nombre)
else:
    usuario = next(iter(usuarios.values())) if len(usuarios) == 1 else None
if usuario is None:
    sys.exit(f"¿De quién son los movimientos? Usa --usuario=<username>. Usuarios: {', '.join(usuarios)}")

aplicar_alias(usuario, filas)   # los nombres que el usuario ya corrigió en la página
r = importar(usuario, filas)
print(f"Insertados {r['insertados']} movimientos para {usuario.username}."
      + (f" Omitidos {r['omitidos']} que ya existían." if r['omitidos'] else ""))
for f in filas:
    if f["nota"]:
        print(f"  Revisar: {f['fecha']:%d/%m} {f['descripcion']} ${f['monto']} ({f['nota']})")
for nombre, n in sorted(r["sin_cuenta"].items(), key=lambda x: -x[1]):
    print(f"  Sin cuenta en el catálogo: {nombre!r} ({n} movimientos)")
