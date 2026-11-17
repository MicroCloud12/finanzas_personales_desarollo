"""
Importación de movimientos desde un CSV al libro mayor. Acepta dos formatos y los detecta por el encabezado:

1. El propio:  Fecha (dd/mm/aaaa), Descripcion, Categoria, Monto, Tipo (gasto|ingreso|transferencia),
               Cuenta de origen, Cuenta de destino  [+ Usuario, Nota: se ignoran al subir por la página]
2. El export de Santander (MOVIMIENTOS_CUENTA_xxxx.csv): FECHA, HORA, SUCURSAL, CONCEPTO, RETIRO, DEPÓSITO, ...
   Un RETIRO es un gasto y un DEPÓSITO un ingreso, salvo lo que REGLAS diga (nómina, traspasos, préstamo).
   El comercio se reconoce por una palabra del CONCEPTO; lo que no se reconoce queda como "Gastos varios".

Lo usan el botón "Subir CSV" de Transacciones y los scripts importar_csv.py / convertir_santander.py.
Este módulo no importa Django al cargarse para que convertir_santander.py corra sin la base de datos.
"""
import csv
import io
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

TIPOS = {"gasto": "GASTO", "ingreso": "INGRESO", "transferencia": "TRANSFERENCIA"}
VACIOS = {"", "N/A", "SIN CUENTA", "OTRA CUENTA"}
CUENTA_SANTANDER = "Santander"

# (patrón en el CONCEPTO, descripción, categoría, tipo, cuenta de origen, cuenta de destino)
# tipo None = lo decide la columna (RETIRO -> gasto, DEPÓSITO -> ingreso). Agrega aquí tus comercios.
REGLAS = [
    (r"NOMINA|SUELDO",            "NÓMINA",             "Nomina",        "ingreso",       None,             CUENTA_SANTANDER),
    (r"MAURICIO NU|NU MEXICO",    "TRANSFERENCIA A NU", "Transferencia", "transferencia", CUENTA_SANTANDER, "NU (Debito)"),
    (r"^RENTA",                   "APARTADO RENTA",     "Transferencia", "transferencia", CUENTA_SANTANDER, "NU (Debito)"),
    (r"DIGITT",                   "PAGO DIGITT",        "Deudas",        "transferencia", CUENTA_SANTANDER, "Digitt"),
    (r"BANAMEX",                  "PAGO BANAMEX",       "Deudas",        "transferencia", CUENTA_SANTANDER, "Banamex"),
    (r"PAGOAMEX|\bAMEX\b",        "PAGO AMEX",          "Deudas",        "transferencia", CUENTA_SANTANDER, "AMEX"),
    (r"KLAR",                     "TRANSFERENCIA KLAR", "Transferencia", "transferencia", "Klar",           CUENTA_SANTANDER),
    (r"DISP ATM|CAJERO",          "RETIRO DE CAJERO",   "Transferencia", "transferencia", CUENTA_SANTANDER, "Efectivo"),
    (r"UBER",                     "UBER",               "Transporte",    None, None, None),
    (r"DIDI",                     "DIDI",               "Transporte",    None, None, None),
    (r"SUPER RIDES",              "DIDI",               "Transporte",    None, None, None),  # así cobra DiDi
    (r"PARQUIMETRO|METROTAP|AUTOB", None,               "Transporte",    None, None, None),
    (r"GASOLINA|GASOL|PEMEX",     "GASOLINA",           "Combustible",   None, None, None),
    (r"RAPPI",                    "RAPPI",              "Comida",        None, None, None),
    (r"OXXO",                     "OXXO",               "Tiendas de conveniencia", None, None, None),
    (r"WAL ?MART|^SUPER$|SORIANA|CHEDRAUI|COSTCO", None, "Supermercado", None, None, None),
    (r"STARBUCKS",                "STARBUCKS",          "Comida",        None, None, None),
    (r"COM RAP",                  "COMIDA RÁPIDA",      "Comida",        None, None, None),
    (r"REST|MCDONALD|VIPS|TACOS|KAITEN|DESAYUNO|HELADO|COMIDA|CAFE|FRUTOS", None, "Comida", None, None, None),
    (r"CINEMEX|CINEPOLIS",        "CINE",               "Entretenimiento", None, None, None),
    (r"HAY DAY|STEAM|PLAYSTATION|XBOX", None,          "Entretenimiento", None, None, None),
    (r"FARMACIA|F AHORRO|YZA|DR\. ?SIMI", "FARMACIA",   "Salud",         None, None, None),
    (r"GAMSGO|NETFLIX|SPOTIFY|ELEVENLABS|OPENAI|ANTHROPIC|GOOGLE ONE", None, "Suscripciones", None, None, None),
    (r"MUCHACHA|LIMPIEZA",        None,                 "Limpieza de la casa", None, None, None),
    (r"AMORCITO",                 None,                 "Pareja",        None, None, None),
    (r"AMAZON",                   "AMAZON",             "Gastos varios", None, None, None),
    (r"MERCADO ?PAGO|MERPAGO",    "MERCADO PAGO",       "Gastos varios", None, None, None),
]


def _fecha(texto, formatos):
    for formato in formatos:
        try:
            return datetime.strptime(texto.strip(), formato).date()
        except ValueError:
            pass
    raise ValueError(f"fecha no reconocida: {texto!r}")


def _hora(texto):
    try:
        return datetime.strptime((texto or "").strip(), "%H:%M:%S").time()
    except ValueError:
        return datetime.min.time()


def _monto(texto):
    texto = (texto or "").strip().replace(",", "").replace("$", "")
    try:
        return abs(Decimal(texto)) if texto else Decimal("0")
    except InvalidOperation:
        raise ValueError(f"monto no válido: {texto!r}")


def _saldo(texto):
    """Columna SALDO del banco (con signo); None si no viene."""
    texto = (texto or "").strip().replace(",", "").replace("$", "")
    try:
        return Decimal(texto) if texto else None
    except InvalidOperation:
        raise ValueError(f"saldo no válido: {texto!r}")


def _fila(fecha, descripcion, categoria, monto, tipo, origen, destino, nota="", usuario="", banco=None,
          saldo=None, entra=None):
    """`banco` es el texto con el que el archivo nombra al comercio; sirve para aprender alias.
    `saldo` y `entra` (¿el dinero entró a la cuenta del banco?) solo vienen en el estado de cuenta
    del banco y sirven para conciliar."""
    return {"fecha": fecha, "descripcion": descripcion.strip()[:100], "categoria": categoria.strip()[:100],
            "monto": monto, "tipo": tipo, "origen": origen.strip(), "destino": destino.strip(),
            "nota": nota, "usuario": usuario.strip(), "banco": (banco if banco is not None else descripcion).strip()[:100],
            "saldo": saldo, "entra": entra}


def _desde_santander(lector):
    filas = []
    for r in lector:
        concepto = (r.get("CONCEPTO") or "").strip()
        if not concepto:
            continue  # Santander rellena el archivo con renglones vacíos
        retiro, deposito = _monto(r.get("RETIRO")), _monto(r.get("DEPÓSITO") or r.get("DEPOSITO"))
        tipo = "GASTO" if retiro else "INGRESO"
        origen, destino = (CUENTA_SANTANDER, "") if retiro else ("", CUENTA_SANTANDER)
        comercio = descripcion = re.split(r"\s{2,}", concepto)[0]  # 'SUPER RIDES      CIUDAD DE MEX   7696182' -> 'SUPER RIDES'
        if retiro:
            categoria, nota = "Gastos varios", "Revisar: comercio no reconocido"
        else:
            categoria, nota = "Otro", "Revisar: depósito sin concepto claro (¿nómina, traspaso de otra cuenta tuya, devolución?)"
        for patron, desc, cat, tipo_regla, ori, dest in REGLAS:
            if re.search(patron, concepto, re.I):
                descripcion, categoria, nota = desc or descripcion, cat, ""
                if tipo_regla:
                    tipo, origen, destino = TIPOS[tipo_regla], ori or "", dest or ""
                break
        # Santander exporta m/d/aaaa (11/6/2026 = 6 de noviembre); si no cuadra, d/m/aaaa.
        fila = _fila(_fecha(r["FECHA"], ("%m/%d/%Y", "%d/%m/%Y")), descripcion, categoria,
                     retiro or deposito, tipo, origen, destino, nota, banco=comercio,
                     saldo=_saldo(r.get("SALDO")), entra=not retiro)
        filas.append((fila["fecha"], _hora(r.get("HORA")), fila))
    return [f for _, _, f in sorted(filas, key=lambda x: (x[0], x[1]))]


def _desde_propio(lector):
    filas = []
    for i, r in enumerate(lector, start=2):
        if not any((v or "").strip() for v in r.values()):
            continue
        try:
            tipo = TIPOS[(r.get("Tipo") or "").strip().lower()]
        except KeyError:
            raise ValueError(f"fila {i}: Tipo debe ser gasto, ingreso o transferencia (viene {r.get('Tipo')!r})")
        try:
            filas.append(_fila(_fecha(r.get("Fecha") or "", ("%d/%m/%Y", "%Y-%m-%d")), r.get("Descripcion") or "",
                               r.get("Categoria") or "", _monto(r.get("Monto")), tipo,
                               r.get("Cuenta de origen") or "", r.get("Cuenta de destino") or "",
                               r.get("Nota") or "", r.get("Usuario") or r.get("propietario_id") or ""))
        except ValueError as e:
            raise ValueError(f"fila {i}: {e}")
    return filas


def leer_csv(texto):
    """Texto del CSV -> (filas normalizadas, es_export_santander). Lanza ValueError con la fila que falla."""
    lineas = texto.lstrip("﻿").splitlines()
    # Santander a veces antepone "Detalle del ... de la cuenta ..." y "Número de registros": el encabezado
    # es la primera línea que empieza con FECHA.
    inicio = next((i for i, l in enumerate(lineas) if l.strip().upper().startswith("FECHA")), 0)
    texto = "\n".join(lineas[inicio:])
    primera = lineas[inicio] if lineas else ""
    delimitador = ";" if primera.count(";") > primera.count(",") else ","  # Excel en español guarda con ;
    lector = csv.DictReader(io.StringIO(texto), delimiter=delimitador)
    campos = {(c or "").strip().upper() for c in (lector.fieldnames or [])}
    if {"FECHA", "CONCEPTO"} <= campos:
        return _desde_santander(lector), True
    if {"FECHA", "MONTO", "TIPO"} <= campos:
        return _desde_propio(lector), False
    raise ValueError("no reconozco las columnas; espero el archivo de Santander o uno con "
                     "Fecha, Descripcion, Categoria, Monto, Tipo, Cuenta de origen, Cuenta de destino")


def decodificar(contenido: bytes) -> str:
    """Excel en Windows guarda el CSV en cp1252 salvo que elijas 'CSV UTF-8'."""
    try:
        return contenido.decode("utf-8-sig")
    except UnicodeDecodeError:
        return contenido.decode("cp1252")


def coincidencias(usuario, filas, dias=3):
    """Para cada fila, el movimiento YA registrado que parece ser el mismo, o None.

    Un ticket escaneado o capturado a mano no trae el mismo texto que el banco ("Uber" vs
    "DLO*UBER RIDE") y a veces ni la misma fecha (el cargo se refleja uno o dos días después),
    así que se compara por monto exacto, misma dirección (sale/entra) y fecha a ±`dias`.
    Cada movimiento registrado solo puede explicar una fila del archivo.
    Devuelve dicts {'id', 'descripcion', 'monto', 'fecha', 'cuenta', 'exacta'}.
    """
    from datetime import timedelta
    from .models import registro_transacciones
    if not filas:
        return []
    fechas = [f["fecha"] for f in filas]
    existentes = list(registro_transacciones.objects.filter(
        propietario=usuario, fecha__range=(min(fechas) - timedelta(dias), max(fechas) + timedelta(dias)),
    ).select_related("origen", "destino").order_by("fecha", "id"))
    usados = set()
    resultado = []
    for f in filas:
        sale = f["tipo"] != "INGRESO"
        candidatos = [t for t in existentes if t.id not in usados and t.monto == f["monto"]
                      and (t.tipo != "INGRESO") == sale and abs((t.fecha - f["fecha"]).days) <= dias]
        if not candidatos:
            resultado.append(None)
            continue
        mejor = min(candidatos, key=lambda t: (abs((t.fecha - f["fecha"]).days),
                                               t.descripcion.strip().lower() != f["descripcion"].strip().lower()))
        usados.add(mejor.id)
        cuenta = mejor.destino if mejor.tipo == "INGRESO" else mejor.origen
        resultado.append({
            "id": mejor.id, "descripcion": mejor.descripcion, "monto": mejor.monto, "fecha": mejor.fecha,
            "cuenta": cuenta.nombre if cuenta else "sin cuenta",
            "exacta": mejor.fecha == f["fecha"] and mejor.descripcion.strip().lower() == f["descripcion"].strip().lower(),
        })
    return resultado


def aplicar_alias(usuario, filas):
    """Lo que el usuario ya corrigió antes manda sobre las REGLAS: 'SUPER RIDES' -> 'DIDI', Transporte."""
    from .models import AliasComercio
    alias = {a.texto_banco.upper(): a for a in AliasComercio.objects.filter(propietario=usuario)}
    for f in filas:
        a = alias.get(f["banco"].upper())
        if a is not None:
            f["descripcion"], f["nota"] = a.descripcion, ""
            if a.categoria:
                f["categoria"] = a.categoria
    return filas


def aprender_alias(usuario, fila, descripcion, categoria):
    """Guarda la corrección del usuario para la próxima vez; devuelve True si hubo algo que aprender."""
    from .models import AliasComercio
    descripcion, categoria = descripcion.strip()[:100], categoria.strip()[:100]
    if not descripcion or (descripcion == fila["descripcion"] and categoria == fila["categoria"]):
        return False
    AliasComercio.objects.update_or_create(
        propietario=usuario, texto_banco=fila["banco"],
        defaults={"descripcion": descripcion, "categoria": categoria})
    return True


def completar_desde_historial(usuario, filas):
    """Para lo que el archivo no reconoció (traen nota), usa tu historial de movimientos con esa
    misma descripción: categoría y, si antes fue una transferencia, también tipo y destino."""
    from .categorias import Sugeridor
    sugeridor = Sugeridor(usuario)
    for f in filas:
        previo = sugeridor.historial(f["descripcion"]) if f["nota"] else None
        if previo is not None:
            f["categoria"], f["nota"] = previo.categoria, ""
            if previo.tipo in ("TRANSFERENCIA", "PAGO_MENSUALIDAD", "PAGO_CAPITAL") and previo.destino_id and f["tipo"] == "GASTO":
                f["tipo"], f["destino"] = "TRANSFERENCIA", previo.destino.nombre
    return filas


def a_sesion(filas):
    """Filas -> algo que cabe en la sesión (JSON): fechas ISO y montos como texto."""
    return [{**f, "fecha": f["fecha"].isoformat(), "monto": str(f["monto"]),
             "saldo": None if f.get("saldo") is None else str(f["saldo"])} for f in filas]


def de_sesion(datos):
    from datetime import date
    return [{**f, "fecha": date.fromisoformat(f["fecha"]), "monto": Decimal(f["monto"]),
             "saldo": None if f.get("saldo") is None else Decimal(f["saldo"])} for f in datos]


def _efecto(t, cuenta):
    """(entra, monto) de un movimiento visto desde `cuenta`; None si no la toca."""
    if t.destino_id == cuenta.id and t.origen_id != cuenta.id:
        return True, t.monto - (t.monto_interes or 0)
    if t.origen_id == cuenta.id:
        return False, t.monto
    return None


def _neto(pares):
    return sum((m if entra else -m for entra, m in pares), Decimal("0"))


def conciliar(usuario, cuenta, filas, dias=3):
    """Cruza el estado de cuenta del banco (filas de su export, con SALDO) contra lo registrado en `cuenta`.

    Un movimiento del banco "coincide" con uno de la app si tienen el mismo monto, la misma dirección
    (entra/sale de la cuenta) y fecha a ±`dias`; cada movimiento de la app explica a lo más una fila.
    Devuelve un dict con los saldos del banco y de la app al inicio y al cierre del periodo del archivo,
    sus diferencias, y:
      solo_app    -> movimientos registrados en el periodo que el banco no tiene (duplicados, errores)
      solo_banco  -> índices de filas del banco que no están registradas (faltan)
      desfasados  -> (índice, movimiento) que coinciden pero el movimiento tiene fecha fuera del periodo
    Siempre se cumple: dif_fin = dif_inicio + neto(solo_app) - neto(solo_banco) - neto(desfasados) + resto,
    donde neto = entradas - salidas y `resto` debería ser 0. `ajuste_inicial` es lo que habría que sumar al
    saldo inicial de la cuenta para que la app arranque el periodo igual que el banco.
    """
    from datetime import timedelta
    from django.db.models import Q
    from .models import registro_transacciones
    if not filas:
        raise ValueError("el archivo no trae movimientos")
    if any(f.get("saldo") is None for f in filas):
        raise ValueError("el archivo no trae la columna SALDO; sube el estado de cuenta tal como lo exporta el banco")

    def entra_banco(f):
        return f["entra"] if f.get("entra") is not None else f["destino"].strip().upper() == cuenta.nombre.strip().upper()

    inicio, fin = min(f["fecha"] for f in filas), max(f["fecha"] for f in filas)
    primera, ultima = filas[0], filas[-1]           # vienen ordenadas por fecha y hora
    banco_inicio = primera["saldo"] - (primera["monto"] if entra_banco(primera) else -primera["monto"])
    banco_fin = ultima["saldo"]
    app_inicio = cuenta.saldo(hasta=inicio - timedelta(days=1))
    app_fin = cuenta.saldo(hasta=fin)

    movimientos = list(registro_transacciones.objects.filter(propietario=usuario)
                       .filter(Q(origen=cuenta) | Q(destino=cuenta))
                       .filter(fecha__range=(inicio - timedelta(dias), fin + timedelta(dias)))
                       .select_related("origen", "destino").order_by("fecha", "id"))
    for t in movimientos:
        t.entra, t.efecto = _efecto(t, cuenta)
        otra = t.origen if t.entra else t.destino
        t.otra_cuenta = otra.nombre if otra else (t.cuenta_origen if t.entra else t.cuenta_destino) or ""

    usados, desfasados, solo_banco = set(), [], []
    coinciden = 0
    for i, f in enumerate(filas):
        entra = entra_banco(f)
        candidatos = [t for t in movimientos if t.id not in usados and t.entra == entra
                      and t.efecto == f["monto"] and abs((t.fecha - f["fecha"]).days) <= dias]
        if not candidatos:
            solo_banco.append(i)
            continue
        mejor = min(candidatos, key=lambda t: (abs((t.fecha - f["fecha"]).days), not (inicio <= t.fecha <= fin)))
        usados.add(mejor.id)
        if inicio <= mejor.fecha <= fin:
            coinciden += 1
        else:
            desfasados.append((i, mejor))
    solo_app = [t for t in movimientos if t.id not in usados and inicio <= t.fecha <= fin]

    neto_solo_app = _neto((t.entra, t.efecto) for t in solo_app)
    neto_solo_banco = _neto((entra_banco(filas[i]), filas[i]["monto"]) for i in solo_banco)
    neto_desfasados = _neto((entra_banco(filas[i]), filas[i]["monto"]) for i, _ in desfasados)
    # Los desfasados con fecha anterior al periodo ya están en el saldo de la app al inicio: no son
    # un error de saldo inicial, así que el ajuste sugerido los deja fuera.
    neto_desfasados_antes = _neto((entra_banco(filas[i]), filas[i]["monto"]) for i, t in desfasados if t.fecha < inicio)
    dif_inicio, dif_fin = app_inicio - banco_inicio, app_fin - banco_fin
    return {
        "cuenta": cuenta, "inicio": inicio, "fin": fin, "dias": dias,
        "banco_inicio": banco_inicio, "banco_fin": banco_fin, "app_inicio": app_inicio, "app_fin": app_fin,
        "dif_inicio": dif_inicio, "dif_fin": dif_fin,
        "coinciden": coinciden, "solo_app": solo_app, "solo_banco": solo_banco, "desfasados": desfasados,
        "neto_solo_app": neto_solo_app, "neto_solo_banco": neto_solo_banco, "neto_desfasados": neto_desfasados,
        "ajuste_inicial": banco_inicio + neto_desfasados_antes - app_inicio,
        "resto": dif_fin - dif_inicio - neto_solo_app + neto_solo_banco + neto_desfasados,
    }


def importar(usuario, filas):
    """Guarda las filas como movimientos del usuario (las reglas del libro aplican al guardar).

    Un movimiento se omite solo si ya está en la base tantas veces como viene en el archivo: así el
    mismo archivo se puede subir dos veces sin duplicar, y dos viajes iguales el mismo día sí entran.
    Devuelve {'insertados', 'omitidos', 'sin_cuenta': {nombre: veces}}.
    """
    from django.db import transaction
    from .models import Cuenta, registro_transacciones

    cuentas = {c.nombre.strip().upper(): c for c in Cuenta.objects.filter(propietario=usuario)}
    sin_cuenta, vistos = {}, {}
    insertados = omitidos = 0

    def buscar(nombre):
        if nombre.upper() in VACIOS:
            return None
        cuenta = cuentas.get(nombre.upper())
        if cuenta is None:
            sin_cuenta[nombre] = sin_cuenta.get(nombre, 0) + 1
        return cuenta

    with transaction.atomic():
        for f in filas:
            clave = (f["fecha"], f["monto"], f["tipo"], f["descripcion"].lower())
            vistos[clave] = vistos.get(clave, 0) + 1
            existentes = registro_transacciones.objects.filter(
                propietario=usuario, fecha=f["fecha"], monto=f["monto"], tipo=f["tipo"],
                descripcion__iexact=f["descripcion"]).count()
            if vistos[clave] <= existentes:
                omitidos += 1
                continue
            origen, destino = buscar(f["origen"]), buscar(f["destino"])
            if f["tipo"] == "INGRESO":
                origen, destino = None, (destino or origen)  # formato histórico: el ingreso traía la cuenta en "origen"
            elif f["tipo"] == "GASTO":
                destino = None
            registro_transacciones(
                propietario=usuario, fecha=f["fecha"], descripcion=f["descripcion"], categoria=f["categoria"],
                monto=f["monto"], tipo=f["tipo"], origen=origen, destino=destino,
                cuenta_origen=f["origen"][:100], cuenta_destino=f["destino"][:100],
            ).save()
            insertados += 1
    return {"insertados": insertados, "omitidos": omitidos, "sin_cuenta": sin_cuenta}
