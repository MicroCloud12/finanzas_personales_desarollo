"""
Predicción de recibos de servicio (luz, agua, gas, internet...) a partir de su historial.

Sin Django a propósito: solo fechas y números, para poder probarlo con Python a secas.
El historial entra como una lista de `Recibo` (emisión, vencimiento, monto) del más viejo al más nuevo;
sale como `Pago`s (fecha, monto, exacto) o como la `Prediccion` de un mes completo.
"""
import calendar
from dataclasses import dataclass, field
from datetime import date, timedelta
from statistics import median

DIAS_PARA_PAGAR = 12   # si el recibo no trae fecha límite: lo típico entre que se emite y vence (CFE: ~12 días)
MESES = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio',
         'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre']


@dataclass
class Recibo:
    emision: date | None
    vence: date | None
    monto: float


@dataclass
class Pago:
    fecha: date
    monto: float
    exacto: bool          # True: recibo en mano (monto real). False: estimado.


@dataclass
class Prediccion:
    """Lo que toca pagar de un concepto en un mes dado."""
    monto: float = 0.0                 # suma de los pagos del mes
    fecha: date | None = None          # primer pago del mes (o el siguiente pago, cuando no toca en ese mes)
    exacto: bool = False               # True si el monto sale de un recibo en mano
    fuente: str = 'sin_datos'          # fijo | unico | recibos | movimientos | capturado | no_toca | sin_datos
    nota: str = ''                     # texto corto para la tabla
    pagos: list = field(default_factory=list)


# ---------- calendario ----------

def mes_siguiente(hoy):
    return (hoy.year + 1, 1) if hoy.month == 12 else (hoy.year, hoy.month + 1)


def rango_mes(anio, mes):
    return date(anio, mes, 1), date(anio, mes, calendar.monthrange(anio, mes)[1])


def nombre_mes(mes):
    return MESES[mes - 1]


def fecha_corta(f):
    """'21 ene' (sin depender del locale del servidor)."""
    return f'{f.day} {nombre_mes(f.month)[:3]}'


def dia_del_mes(anio, mes, dia):
    """Ese día del mes; si el mes es más corto, su último día."""
    ultimo = calendar.monthrange(anio, mes)[1]
    return date(anio, mes, min(dia or ultimo, ultimo))


# ---------- cadencia y montos ----------

def cadencia_dias(fechas, categoria):
    """Días típicos entre recibos: mediana de los últimos gaps; default por categoría con <2 fechas."""
    gaps = [(fechas[i] - fechas[i - 1]).days for i in range(1, len(fechas))]
    gaps = [g for g in gaps if g > 0]   # dos recibos del mismo día (duplicado, reproceso) no son un ciclo
    if gaps:
        return int(round(median(gaps[-6:])))
    return 61 if categoria in ('agua', 'luz') else 30  # ponytail: agua/luz suelen ser bimestrales; el resto mensual


def proxima_fecha(base, paso, hoy):
    """Primera fecha de facturación estrictamente posterior a hoy, anclada al último recibo."""
    f = base + timedelta(days=paso)
    while f <= hoy:
        f += timedelta(days=paso)
    return f


def estimar_monto(montos):
    """Extrapola un periodo con regresión lineal sobre los últimos 6 recibos; acota ±25% sobre la media."""
    ys = montos[-6:]
    n = len(ys)
    if n <= 1:
        return round(ys[0], 2) if ys else 0.0
    mx = (n - 1) / 2
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in range(n))
    sxy = sum((x - mx) * (y - my) for x, y in enumerate(ys))
    slope = sxy / sxx if sxx else 0.0
    pred = my + slope * (n - mx)  # siguiente punto (x = n)
    return round(min(max(pred, my * 0.75), my * 1.25), 2)


def estimar_para_fecha(recibos, fecha_objetivo):
    """Monto esperado de un recibo que vence en `fecha_objetivo`.

    Parte de la tendencia reciente (`estimar_monto`). Si hay un recibo de la misma época del año pasado
    y suficientes vecinos para compararlo, lo ajusta por estacionalidad: el promedio reciente multiplicado
    por (lo que pagaste esa época / lo que pagabas en promedio por entonces). Así la luz de verano no se
    estima con el promedio de todo el año. Devuelve (monto, factor_estacional o None).
    """
    montos = [r.monto for r in recibos]
    tendencia = estimar_monto(montos)
    con_fecha = [r for r in recibos if r.emision]
    if len(con_fecha) < 4:
        return tendencia, None
    hace_un_anio = fecha_objetivo - timedelta(days=365)
    mismo = min(con_fecha, key=lambda r: abs((r.emision - hace_un_anio).days))
    if abs((mismo.emision - hace_un_anio).days) > 25:
        return tendencia, None
    ventana = [r.monto for r in con_fecha
               if hace_un_anio - timedelta(days=200) <= r.emision <= hace_un_anio + timedelta(days=200)]
    if len(ventana) < 3 or sum(ventana) <= 0:
        return tendencia, None
    factor = min(max(mismo.monto / (sum(ventana) / len(ventana)), 0.5), 2.0)
    ultimos = montos[-6:]
    return round(sum(ultimos) / len(ultimos) * factor, 2), round(factor, 2)


# ---------- proyección ----------

def _ancla(recibos):
    """(fechas de emisión ordenadas, vencimiento del último recibo o None)."""
    fechas = sorted(r.emision for r in recibos if r.emision)
    ultimo = recibos[-1]
    vence = ultimo.vence or (ultimo.emision + timedelta(days=DIAS_PARA_PAGAR) if ultimo.emision else None)
    return fechas, vence


def proximo_pago(recibos, categoria, hoy):
    """(Pago, días entre recibos) del siguiente pago a partir de hoy, o (None, paso) si no se puede proyectar.
    Si el último recibo todavía no vence, ESE es el próximo pago (monto exacto); si ya venció, el siguiente
    ciclo: su vencimiento más la cadencia real, con el monto estimado."""
    if not recibos:
        return None, cadencia_dias([], categoria)
    fechas, vence = _ancla(recibos)
    paso = cadencia_dias(fechas, categoria)
    if vence is None:
        return None, paso
    if vence >= hoy:
        return Pago(vence, round(recibos[-1].monto, 2), True), paso
    fecha = proxima_fecha(vence, paso, hoy)
    return Pago(fecha, estimar_para_fecha(recibos, fecha)[0], False), paso


def pagos_en_mes(recibos, categoria, anio, mes, hoy):
    """Pagos de un concepto que caen en el mes (anio, mes) según sus recibos: el recibo en mano si vence ahí,
    y los ciclos siguientes proyectados con la cadencia. Normalmente es uno o ninguno (bimestrales)."""
    if not recibos:
        return []
    ini, fin = rango_mes(anio, mes)
    fechas, vence = _ancla(recibos)
    if vence is None:
        return []
    paso = max(cadencia_dias(fechas, categoria), 14)   # nada se cobra más seguido que cada dos semanas
    pagos = []
    if vence >= hoy and ini <= vence <= fin:
        pagos.append(Pago(vence, round(recibos[-1].monto, 2), True))
    f = proxima_fecha(vence, paso, hoy)
    while f <= fin:
        if f >= ini:
            pagos.append(Pago(f, estimar_para_fecha(recibos, f)[0], False))
        f += timedelta(days=paso)
    return pagos


def prediccion_variable(recibos, categoria, anio, mes, hoy, fuente='recibos'):
    """Prediccion del mes para un concepto de recibo variable, a partir de su historial."""
    pagos = pagos_en_mes(recibos, categoria, anio, mes, hoy)
    if pagos:
        etiqueta = 'según tus movimientos' if fuente == 'movimientos' else ('recibo en mano' if pagos[0].exacto else 'estimado')
        return Prediccion(round(sum(p.monto for p in pagos), 2), pagos[0].fecha, pagos[0].exacto, fuente, etiqueta, pagos)
    siguiente, paso = proximo_pago(recibos, categoria, hoy)
    if siguiente is None:
        return Prediccion(fuente='sin_datos', nota='los recibos no traen fecha')
    # el siguiente pago cae fuera del mes: buscamos el primero después del mes para decir cuándo toca
    fin = rango_mes(anio, mes)[1]
    fecha = siguiente.fecha if siguiente.fecha > fin else proxima_fecha(siguiente.fecha, max(paso, 14), fin)
    return Prediccion(0.0, fecha, False, 'no_toca', f'no toca · siguiente {fecha_corta(fecha)}', [])
