"""
Estados financieros del año, calculados desde el libro mayor.

- Estado de resultados: es un FLUJO (lo que pasó durante un periodo), así que va una
  columna por mes, más total del año, promedio de los meses cerrados, bandera "Revisar"
  contra ese promedio y presupuesto vs real por categoría.
- Balance general: es una FOTO (lo que tienes y debes a una fecha), así que va a una
  fecha comparada con el cierre del mes anterior y el cierre del año anterior; abajo,
  el patrimonio al cierre de cada mes y la comprobación
  capital al cierre del año anterior + resultado acumulado del año = capital hoy.
"""
from datetime import date
from decimal import Decimal, InvalidOperation

from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from ..models import Cuenta, Presupuesto, registro_transacciones
from .resumen import CERO, MESES_ES, _fin_de_mes, _mes_anterior, _por_categoria

MESES_CORTOS = ['', 'Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun', 'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic']

GRUPOS_BALANCE = [
    # (título, tipos de cuenta que incluye)
    ('Efectivo y cuentas de débito', ('EFECTIVO', 'DEBITO')),
    ('Ahorro', ('AHORRO',)),
    ('Inversiones', ('INVERSION',)),
    ('Tarjetas de crédito', ('CREDITO',)),
    ('Préstamos', ('PRESTAMO',)),
]


# ----------------------------------------------------------------------------- estado de resultados

def _fila_anual(nombre, valores, meses, cerrados, umbral, umbral_pct, es_gasto=True, es_total=False, presupuesto=None):
    """Una fila con una celda por mes. 'Revisar' compara cada mes cerrado contra el promedio de los cerrados."""
    vals = [valores.get(m) or CERO for m in meses]
    base = [valores.get(m) or CERO for m in cerrados]
    promedio = sum(base, CERO) / len(base)
    # Una categoría esporádica (un viaje, una compra grande) no marca los meses en que no hubo nada.
    esporadica = sum(1 for v in base if v) * 2 < len(base)
    celdas = []
    for m, v in zip(meses, vals):
        dif = v - promedio
        revisar = (m in cerrados and not (esporadica and v == 0) and abs(dif) >= umbral
                   and (promedio == 0 or abs(dif) / abs(promedio) * 100 >= umbral_pct))
        favorable = ((dif < 0) if es_gasto else (dif > 0)) if dif != 0 else None
        celdas.append({'mes': m, 'valor': v, 'dif': dif, 'revisar': revisar, 'favorable': favorable,
                       'presupuesto': presupuesto.get(m) if presupuesto else None})
    total = sum(vals, CERO)
    pres_total = sum((presupuesto.get(m) or CERO for m in meses), CERO) if presupuesto else None
    return {
        'nombre': nombre, 'celdas': celdas, 'total': total, 'promedio': promedio, 'es_total': es_total,
        'presupuesto': pres_total,
        'dif_presupuesto': (total - pres_total) if pres_total is not None else None,
    }


def _presupuestos_por_mes(user, year, meses):
    """{categoría en minúsculas: (nombre, {mes: monto})}. El presupuesto de un mes concreto manda sobre el recurrente."""
    por_cat = {}
    for p in Presupuesto.objects.filter(propietario=user).order_by('es_recurrente'):  # específicos primero
        clave = p.categoria.strip().lower()
        nombre, por_mes = por_cat.setdefault(clave, (p.categoria.strip(), {}))
        if p.es_recurrente:
            for m in meses:
                por_mes.setdefault(m, p.monto_presupuestado)
        elif p.anio == year and p.mes in meses:
            por_mes[p.mes] = p.monto_presupuestado
    return por_cat


def _filas_por_categoria(por_mes, meses, cerrados, umbral, umbral_pct, es_gasto, presupuestos=None):
    """por_mes = {mes: {categoría: total}} -> filas por categoría, ordenadas por total del año."""
    nombres = {}
    for m in meses:
        for c in por_mes[m]:
            nombres.setdefault(c.strip().lower(), c)
    for clave, (nombre, _) in (presupuestos or {}).items():
        nombres.setdefault(clave, nombre)  # categoría presupuestada aunque no haya gasto
    filas = []
    for clave, nombre in nombres.items():
        valores = {m: sum((t for c, t in por_mes[m].items() if c.strip().lower() == clave), CERO) for m in meses}
        pres = presupuestos[clave][1] if presupuestos and clave in presupuestos else None
        filas.append(_fila_anual(nombre, valores, meses, cerrados, umbral, umbral_pct, es_gasto=es_gasto, presupuesto=pres))
    return sorted(filas, key=lambda f: -f['total'])


@login_required
def vista_estado_resultados(request):
    hoy = date.today()
    try:
        year = int(request.GET.get('year', hoy.year))
        umbral = Decimal(request.GET.get('umbral', '500'))
        umbral_pct = Decimal(request.GET.get('pct', '20'))
    except (ValueError, InvalidOperation):
        return redirect('estado_resultados')
    user = request.user
    tx = registro_transacciones.objects

    meses = list(range(1, (hoy.month if year == hoy.year else 12) + 1))
    # El mes en curso está incompleto: no entra al promedio ni se marca "Revisar".
    cerrados = [m for m in meses if not (year == hoy.year and m == hoy.month)] or meses

    resultados = {m: tx.balance_dashboard(user, year, m) for m in meses}
    gastos = {m: _por_categoria(tx.gastos_por_categoria(user, year, m)) for m in meses}
    ingresos = {m: _por_categoria(tx.ingresos_por_categoria(user, year, m)) for m in meses}
    presupuestos = _presupuestos_por_mes(user, year, meses)

    def fila_total(nombre, clave, es_gasto, presupuesto=None):
        return _fila_anual(nombre, {m: resultados[m][clave] for m in meses}, meses, cerrados, umbral, umbral_pct,
                           es_gasto=es_gasto, es_total=True, presupuesto=presupuesto)

    filas_ingresos = _filas_por_categoria(ingresos, meses, cerrados, umbral, umbral_pct, es_gasto=False)
    filas_ingresos.append(fila_total('Total ingresos', 'ingresos', es_gasto=False))
    filas_gastos = _filas_por_categoria(gastos, meses, cerrados, umbral, umbral_pct, es_gasto=True, presupuestos=presupuestos)
    presupuesto_total = {m: sum((p[1].get(m) or CERO for p in presupuestos.values()), CERO) for m in meses} if presupuestos else None
    total_gastos = fila_total('Total gastos', 'gastos', es_gasto=True, presupuesto=presupuesto_total)
    if presupuestos:
        # La diferencia del total solo suma las categorías que tienen presupuesto (si no, las que no
        # presupuestaste aparecerían como "excedido").
        total_gastos['dif_presupuesto'] = sum((f['dif_presupuesto'] for f in filas_gastos if f['dif_presupuesto'] is not None), CERO)
    filas_gastos.append(total_gastos)
    fila_resultado = fila_total('Resultado (ingresos − gastos)', 'resultado', es_gasto=False)

    pct_gastado = [(resultados[m]['gastos'] / resultados[m]['ingresos'] * 100) if resultados[m]['ingresos'] else None for m in meses]
    total_ingresos, total_gastos = filas_ingresos[-1]['total'], filas_gastos[-1]['total']

    ctx = {
        'selected_year': year, 'years': range(hoy.year, hoy.year - 5, -1),
        'umbral': umbral, 'umbral_pct': umbral_pct,
        'meses': [{'num': m, 'nombre': MESES_CORTOS[m], 'cerrado': m in cerrados} for m in meses],
        'n_cerrados': len(cerrados), 'hay_presupuesto': bool(presupuestos),
        'filas_ingresos': filas_ingresos, 'filas_gastos': filas_gastos, 'fila_resultado': fila_resultado,
        'pct_gastado': pct_gastado,
        'total_ingresos': total_ingresos, 'total_gastos': total_gastos,
        'resultado_anual': fila_resultado['total'],
        'pct_gastado_anual': (total_gastos / total_ingresos * 100) if total_ingresos else None,
        'promedio_gasto': filas_gastos[-1]['promedio'],
    }
    return render(request, 'estado_resultados.html', ctx)


# ----------------------------------------------------------------------------- balance general

def _grupos_balance(balances):
    """Filas del balance con una columna por corte (lista de resumen_balance), con subtotales por grupo."""
    por_corte = [{c.id: c.saldo_calculado for c in b['cuentas']} for b in balances]

    def con_variaciones(nombre, valores, **extra):
        return {'nombre': nombre, 'valores': valores, 'dif_mes': valores[-1] - valores[-2],
                'dif_anio': valores[-1] - valores[0], **extra}

    grupos = []
    for titulo, tipos in GRUPOS_BALANCE:
        filas = [con_variaciones(c.nombre, [s.get(c.id, CERO) for s in por_corte])
                 for c in balances[-1]['cuentas'] if c.tipo in tipos]
        if filas:
            subtotal = [sum((f['valores'][i] for f in filas), CERO) for i in range(len(balances))]
            grupos.append(con_variaciones(titulo, subtotal, filas=filas, es_pasivo=tipos[0] in Cuenta.TIPOS_PASIVO))
    return {
        'grupos_activos': [g for g in grupos if not g['es_pasivo']],
        'grupos_pasivos': [g for g in grupos if g['es_pasivo']],
        'total_activos': con_variaciones('Total activos', [b['activos'] for b in balances]),
        'total_pasivos': con_variaciones('Total pasivos', [b['pasivos'] for b in balances]),
        'patrimonio': con_variaciones('Patrimonio neto = activos − pasivos', [b['patrimonio'] for b in balances]),
    }


@login_required
def vista_balance_general(request):
    hoy = date.today()
    try:
        fecha = date.fromisoformat(request.GET.get('fecha') or hoy.isoformat())
    except ValueError:
        return redirect('balance_general')
    user = request.user
    tx = registro_transacciones.objects
    prev_year, prev_month = _mes_anterior(fecha.year, fecha.month)
    inicio_anio = date(fecha.year, 1, 1)
    cierre_anio_prev = date(fecha.year - 1, 12, 31)

    cortes = [(f'Cierre {fecha.year - 1}', cierre_anio_prev),
              (f'Cierre {MESES_ES[prev_month]} {prev_year}', _fin_de_mes(prev_year, prev_month)),
              (f'Al {fecha:%d/%m/%Y}', fecha)]
    balances = [Cuenta.objects.resumen_balance(user, hasta=f) for _, f in cortes]
    grupos = _grupos_balance(balances)

    # Comprobación del año: capital inicial + resultado acumulado = capital hoy
    acumulado = tx.resultado(tx.filter(propietario=user, fecha__range=(inicio_anio, fecha)))
    capital_ini, capital_hoy = balances[0]['patrimonio'], balances[-1]['patrimonio']
    sin_explicar = capital_hoy - (capital_ini + acumulado['resultado'])

    # Patrimonio al cierre de cada mes del año (el mes en curso, a la fecha pedida)
    serie = []
    anterior = capital_ini
    for m in range(1, fecha.month + 1):
        corte = min(_fin_de_mes(fecha.year, m), fecha)
        b = Cuenta.objects.resumen_balance(user, hasta=corte)
        # Resultado del mes hasta el corte (el mes en curso solo hasta la fecha pedida)
        r = tx.resultado(tx.filter(propietario=user, fecha__range=(date(fecha.year, m, 1), corte)))
        serie.append({'mes': m, 'nombre': MESES_CORTOS[m], 'fecha': corte, 'activos': b['activos'],
                      'pasivos': b['pasivos'], 'patrimonio': b['patrimonio'], 'dif': b['patrimonio'] - anterior,
                      'resultado': r['resultado'], 'sin_explicar': b['patrimonio'] - anterior - r['resultado']})
        anterior = b['patrimonio']

    ctx = {
        'fecha': fecha, 'cortes': [c[0] for c in cortes], 'anio': fecha.year,
        'grupos': grupos, 'acumulado': acumulado,
        'capital_ini': capital_ini, 'capital_hoy': capital_hoy, 'sin_explicar': sin_explicar,
        'cuadra': abs(sin_explicar) < Decimal('0.005'),
        'serie': serie,
        'grafica': {'labels': [f'Dic {fecha.year - 1}'] + [s['nombre'] for s in serie],
                    'patrimonio': [float(capital_ini)] + [float(s['patrimonio']) for s in serie],
                    'activos': [float(balances[0]['activos'])] + [float(s['activos']) for s in serie],
                    'pasivos': [float(balances[0]['pasivos'])] + [float(s['pasivos']) for s in serie]},
    }
    return render(request, 'balance_general.html', ctx)
