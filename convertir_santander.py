"""Convierte el CSV que exporta Santander (MOVIMIENTOS_CUENTA_xxxx.csv) al formato propio, por si quieres
revisarlo en Excel antes de subirlo. Si no necesitas revisarlo, el botón "Subir CSV" (o importar_csv.py)
acepta el archivo de Santander directo.

Corre:  python convertir_santander.py MOVIMIENTOS_CUENTA_2790.csv [salida.csv]
Las reglas de comercios viven en finanzas/importacion.py (REGLAS).
"""
import csv
import sys

from finanzas.importacion import decodificar, leer_csv

USUARIO = "mauricio"

if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("Uso: python convertir_santander.py MOVIMIENTOS_CUENTA_2790.csv [salida.csv]")
    with open(sys.argv[1], "rb") as f:
        try:
            filas, _ = leer_csv(decodificar(f.read()))
        except ValueError as e:
            sys.exit(f"No pude leer el archivo: {e}")
    if not filas:
        sys.exit("El archivo no tiene movimientos.")
    primera, ultima = filas[0]["fecha"], filas[-1]["fecha"]
    salida = sys.argv[2] if len(sys.argv) > 2 else f"movimientos_santander_{primera:%d%b}_al_{ultima:%d%b%Y}.csv".lower()
    with open(salida, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Usuario", "Fecha", "Descripcion", "Categoria", "Monto", "Tipo", "Cuenta de origen", "Cuenta de destino", "Nota"])
        for x in filas:
            w.writerow([USUARIO, f"{x['fecha']:%d/%m/%Y}", x["descripcion"], x["categoria"], f"{x['monto']:.2f}",
                        x["tipo"].lower(), x["origen"], x["destino"], x["nota"]])
    print(f"{len(filas)} movimientos del {primera:%d/%m} al {ultima:%d/%m} -> {salida}")
    for x in filas:
        if x["nota"]:
            print(f"  Revisar: {x['fecha']:%d/%m} {x['descripcion']} ${x['monto']}")
    print(f"Ahora: python importar_csv.py {salida}")
