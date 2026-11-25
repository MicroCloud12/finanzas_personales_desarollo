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
    """Días típicos entre recibos: mediana de los últimos gaps reales (>=10 días); default por categoría con <2 fechas."""
    gaps = [(fechas[i] - fechas[i - 1]).days for i in range(1, len(fechas))]
    gaps = [g for g in gaps if g >= 10]   # recibos del mismo ciclo (duplicado o corrección) no definen cadencia
    if gaps:
        return int(round(median(gaps[-6:])))
    return 61 if categoria in ('agua', 'luz') else 30


def _sumar_paso(f, paso):
    """Avanza un ciclo: un mes calendario si la cadencia es mensual (~26-35 días), o `paso` días."""
    if 26 <= paso <= 35:
        y, m = mes_siguiente(f)
        return dia_del_mes(y, m, f.day)
    return f + timedelta(days=max(paso, 1))


def proxima_fecha(base, paso, hoy):
    """Siguiente fecha de ciclo estrictamente posterior al último recibo (`base`) y a `hoy`."""
    f = _sumar_paso(base, paso)
    while f <= hoy:
        f = _sumar_paso(f, paso)
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


def _fecha_ref(r):
    """Fecha de referencia del recibo: emisión o, si falta, vencimiento menos DIAS_PARA_PAGAR."""
    return r.emision or (r.vence - timedelta(days=DIAS_PARA_PAGAR) if r.vence else None)


def estimar_estacional_servicio(recibos, categoria, fecha_objetivo):
    """Estimación local consciente de época del año (invierno/verano) y resistente a picos aislados.
    Se usa como respaldo cuando la API de IA no está disponible (ej. límite de cuota)."""
    monto_anual, factor_anual = estimar_para_fecha(recibos, fecha_objetivo)
    if factor_anual is not None:
        return monto_anual, f"Ajustado con tu consumo de la misma época del año pasado (factor {factor_anual}x)."

    ordenados = sorted(recibos, key=lambda r: _fecha_ref(r) or date.min)
    montos = [r.monto for r in ordenados if r.monto > 0]
    if not montos:
        return 0.0, ""
    ultimos = montos[-6:]
    ultimo = ultimos[-1]
    med = median(ultimos)
    mes = fecha_objetivo.month
    cat = (categoria or '').lower().strip()

    if mes in (12, 1, 2):       # Invierno
        epoca = "invierno"
        factor = 0.88 if 'agua' in cat else (0.90 if 'luz' in cat else (1.12 if 'gas' in cat else 1.0))
    elif mes in (5, 6, 7, 8):   # Verano / calor
        epoca = "verano"
        factor = 1.12 if 'agua' in cat else (1.20 if 'luz' in cat else (0.88 if 'gas' in cat else 1.0))
    else:
        epoca = "temporada templada"
        factor = 1.0

    # Si hubo cambio fuerte de estación (ej. luz bajó de verano $1,800 a otoño $426), anclar al nivel actual;
    # si el último recibo fue un pico aislado sobre una base estable (ej. agua $1,029 vs mediana $680), amortiguarlo.
    if 'luz' in cat and mes in (11, 12, 1, 2) and ultimo < med * 0.75:
        base = ultimo
    elif 'gas' in cat and mes in (11, 12, 1, 2) and ultimo > med * 1.15:
        base = ultimo
    elif len(ultimos) >= 2 and ultimo > med * 1.25:
        base = 0.65 * med + 0.35 * ultimo
    else:
        base = 0.5 * med + 0.5 * ultimo

    estimado = round(base * factor, 2)
    razon = f"Estimado considerando {epoca} y amortiguando picos atípicos sobre {len(montos)} recibo(s)."
    return estimado, razon


def estimar_para_fecha(recibos, fecha_objetivo):
    """Monto esperado de un recibo proyectado en `fecha_objetivo`.

    Parte de la tendencia reciente (`estimar_monto`). Si hay un recibo de la misma época del año pasado
    y suficientes vecinos para compararlo, lo ajusta por estacionalidad: el promedio reciente multiplicado
    por (lo que pagaste esa época / lo que pagabas en promedio por entonces). Así la luz de verano no se
    estima con el promedio de todo el año. Devuelve (monto, factor_estacional o None).
    """
    ordenados = sorted(recibos, key=lambda r: _fecha_ref(r) or date.min)
    montos = [r.monto for r in ordenados]
    tendencia = estimar_monto(montos)
    con_fecha = [(r, _fecha_ref(r)) for r in ordenados if _fecha_ref(r)]
    if len(con_fecha) < 4:
        return tendencia, None
    hace_un_anio = fecha_objetivo - timedelta(days=365)
    mismo, f_mismo = min(con_fecha, key=lambda par: abs((par[1] - hace_un_anio).days))
    if abs((f_mismo - hace_un_anio).days) > 25:
        return tendencia, None
    ventana = [r.monto for r, f in con_fecha
               if hace_un_anio - timedelta(days=200) <= f <= hace_un_anio + timedelta(days=200)]
    if len(ventana) < 3 or sum(ventana) <= 0:
        return tendencia, None
    factor = min(max(mismo.monto / (sum(ventana) / len(ventana)), 0.5), 2.0)
    ultimos = montos[-6:]
    return round(sum(ultimos) / len(ultimos) * factor, 2), round(factor, 2)


# ---------- proyección ----------

def _ancla(recibos):
    """(fechas de referencia ordenadas, última fecha conocida o None)."""
    fechas = sorted(f for f in (_fecha_ref(r) for r in recibos) if f)
    return fechas, (fechas[-1] if fechas else None)


def proximo_pago(recibos, categoria, hoy):
    """(Pago pronosticado del próximo recibo, días entre recibos) a partir del historial.
    Siempre proyecta el siguiente ciclo después del último recibo recibido, sin importar cuántos días falten."""
    if not recibos:
        return None, cadencia_dias([], categoria)
    fechas, base = _ancla(recibos)
    paso = cadencia_dias(fechas, categoria)
    if base is None:
        return None, paso
    fecha = proxima_fecha(base, max(paso, 14), hoy)
    return Pago(fecha, estimar_para_fecha(recibos, fecha)[0], False), paso


def pagos_en_mes(recibos, categoria, anio, mes, hoy):
    """Pagos proyectados de un concepto que caen en el mes (anio, mes) según su cadencia."""
    if not recibos:
        return []
    ini, fin = rango_mes(anio, mes)
    fechas, base = _ancla(recibos)
    if base is None:
        return []
    paso = max(cadencia_dias(fechas, categoria), 14)
    pagos = []
    f = proxima_fecha(base, paso, hoy)
    while f <= fin:
        if f >= ini:
            pagos.append(Pago(f, estimar_para_fecha(recibos, f)[0], False))
        f = _sumar_paso(f, paso)
    return pagos


def prediccion_variable(recibos, categoria, anio, mes, hoy, fuente='recibos'):
    """Pronóstico para (anio, mes) a partir del historial; aunque falten más días y el siguiente recibo
    caiga después del mes, siempre devuelve el monto pronosticado del próximo recibo."""
    etiqueta = 'según tus movimientos' if fuente == 'movimientos' else 'estimado'
    pagos = pagos_en_mes(recibos, categoria, anio, mes, hoy)
    if pagos:
        return Prediccion(round(sum(p.monto for p in pagos), 2), pagos[0].fecha, False, fuente, etiqueta, pagos)
    siguiente, _ = proximo_pago(recibos, categoria, hoy)
    if siguiente is None:
        return Prediccion(fuente='sin_datos', nota='los recibos no traen fecha')
    return Prediccion(siguiente.monto, siguiente.fecha, False, fuente, etiqueta, [siguiente])
