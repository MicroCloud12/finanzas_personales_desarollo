"""Convierte el CSV que exporta Santander (MOVIMIENTOS_CUENTA_xxxx.csv) al formato de importar_csv.py.

Corre:  python convertir_santander.py MOVIMIENTOS_CUENTA_2790.csv [salida.csv]
        python importar_csv.py <salida.csv>

Reglas: un RETIRO es un gasto y un DEPÓSITO un ingreso, salvo lo que REGLAS diga distinto
(nómina, traspasos a tus otras cuentas, pago del préstamo). El comercio se reconoce por una
palabra del CONCEPTO; lo que no reconozca sale como "Gastos varios" con una nota "Revisar"
para que lo corrijas en Excel antes de importar. Agrega tus comercios a REGLAS.
"""
import csv
import re
import sys
from datetime import datetime

USUARIO = "mauricio"
CUENTA = "Santander"

# (patrón en el CONCEPTO, descripción, categoría, tipo, cuenta de origen, cuenta de destino)
# tipo None = lo decide la columna (RETIRO -> gasto, DEPÓSITO -> ingreso).
REGLAS = [
    (r"NOMINA|SUELDO",            "NÓMINA",       "Nomina",                 "ingreso",       None,       CUENTA),
    (r"MAURICIO NU|NU MEXICO",    "TRANSFERENCIA A NU", "Transferencia",    "transferencia", CUENTA,     "NU (Debito)"),
    (r"DIGITT",                   "PAGO DIGITT",  "Deudas",                 "transferencia", CUENTA,     "Digitt"),
    (r"KLAR",                     "TRANSFERENCIA KLAR", "Transferencia",    "transferencia", "Klar",     CUENTA),
    (r"UBER",                     "UBER",         "Transporte",             None, None, None),
    (r"DIDI",                     "DIDI",         "Transporte",             None, None, None),
    (r"SUPER RIDES",              "SUPER RIDES",  "Transporte",             None, None, None),
    (r"RAPPI",                    "RAPPI",        "Comida",                 None, None, None),
    (r"OXXO",                     "OXXO",         "Tiendas de conveniencia", None, None, None),
    (r"STARBUCKS",                "STARBUCKS",    "Comida",                 None, None, None),
    (r"COM RAP",                  "COMIDA RÁPIDA", "Comida",                None, None, None),
    (r"CINEMEX|CINEPOLIS",        "CINE",         "Entretenimiento",        None, None, None),
    (r"FARMACIA",                 "FARMACIA",     "Salud",                  None, None, None),
    (r"GAMSGO|NETFLIX|SPOTIFY",   None,           "Suscripciones",          None, None, None),
    (r"MERCADO PAGO|MERCADOPAGO", "MERCADO PAGO", "Gastos varios",          None, None, None),
]


def fecha_iso(texto):
    """Santander exporta m/d/aaaa (11/6/2026 = 6 de noviembre); si no cuadra, prueba d/m/aaaa."""
    for formato in ("%m/%d/%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(texto.strip(), formato).date()
        except ValueError:
            pass
    sys.exit(f"Fecha no reconocida: {texto!r}")


def hora(texto):
    try:
        return datetime.strptime((texto or "").strip(), "%H:%M:%S").time()
    except ValueError:
        return datetime.min.time()


def monto(texto):
    texto = (texto or "").strip().replace(",", "").replace("$", "")
    return abs(float(texto)) if texto else 0.0


def nombre_comercio(concepto):
    """'SUPER RIDES      CIUDAD DE MEX   7696182' -> 'SUPER RIDES'."""
    return re.split(r"\s{2,}", concepto.strip())[0].strip()


def convertir(ruta):
    filas = []
    with open(ruta, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            concepto = (r.get("CONCEPTO") or "").strip()
            if not concepto:
                continue
            retiro, deposito = monto(r.get("RETIRO")), monto(r.get("DEPÓSITO") or r.get("DEPOSITO"))
            tipo = "gasto" if retiro else "ingreso"
            origen, destino = (CUENTA, "") if retiro else ("", CUENTA)
            descripcion, categoria, nota = nombre_comercio(concepto), "Gastos varios", "Revisar: comercio no reconocido"
            for patron, desc, cat, tipo_regla, ori, dest in REGLAS:
                if re.search(patron, concepto, re.I):
                    descripcion, categoria, nota = desc or descripcion, cat, ""
                    if tipo_regla:
                        tipo, origen, destino = tipo_regla, ori or "", dest or ""
                    break
            filas.append({
                "Usuario": USUARIO, "Fecha": fecha_iso(r["FECHA"]), "Descripcion": descripcion,
                "Categoria": categoria, "Monto": f"{retiro or deposito:.2f}", "Tipo": tipo,
                "Cuenta de origen": origen, "Cuenta de destino": destino, "Nota": nota,
                "_hora": hora(r.get("HORA")),
            })
    filas.sort(key=lambda x: (x["Fecha"], x["_hora"]))
    for x in filas:
        del x["_hora"]
    return filas


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("Uso: python convertir_santander.py MOVIMIENTOS_CUENTA_2790.csv [salida.csv]")
    filas = convertir(sys.argv[1])
    if not filas:
        sys.exit("El archivo no tiene movimientos.")
    primera, ultima = filas[0]["Fecha"], filas[-1]["Fecha"]
    salida = sys.argv[2] if len(sys.argv) > 2 else f"movimientos_santander_{primera:%d%b}_al_{ultima:%d%b%Y}.csv".lower()
    with open(salida, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(filas[0]))
        w.writeheader()
        for fila in filas:
            w.writerow({**fila, "Fecha": fila["Fecha"].strftime("%d/%m/%Y")})
    revisar = [x for x in filas if x["Nota"]]
    print(f"{len(filas)} movimientos del {primera:%d/%m} al {ultima:%d/%m} -> {salida}")
    for x in revisar:
        print(f"  Revisar: {x['Fecha']:%d/%m} {x['Descripcion']} ${x['Monto']}")
    print(f"Ahora: python importar_csv.py {salida}")
