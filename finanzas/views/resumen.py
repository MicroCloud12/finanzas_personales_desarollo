"""
Pantalla "Resumen": la hoja de resumen del Excel, pero calculada desde el libro mayor.

1. Estado de resultados del mes contra el mes anterior, con variación $ y % y
   la bandera "Revisar" (método de análisis de variaciones: se marca cuando el
   cambio es de al menos $umbral Y al menos umbral_pct %, o cuando antes era 0).
2. Dinero que pasó entre tus cuentas (ahorro, pagos de deuda, otras cuentas):
   no es gasto.
3. Cuadre por cuenta: saldo inicial + entradas - salidas = saldo final.
4. Conciliación: saldo según tu estado de cuenta vs. saldo según el libro.
5. Notas en lenguaje claro: qué cambió y qué conviene revisar.
"""
import calendar
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from ..models import Cuenta, SaldoEstadoCuenta, registro_transacciones

CERO = Decimal('0.00')
MESES_ES = ['', 'Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio', 'Julio', 'Agosto',
            'Septiembre', 'Octubre', 'Noviembre', 'Diciembre']
CATEGORIAS_SIN_CLASIFICAR = {'otro', 'sin clasificar', 'sin categoría', 'sin categoria', 'gastos varios', ''}


def _mes_anterior(year, month):
    return (year - 1, 12) if month == 1 else (year, month - 1)


def _fin_de_mes(year, month):
    return date(year, month, calendar.monthrange(year, month)[1])


def _pct(actual, anterior):
    if not anterior:
        return None
    return (actual - anterior) / abs(anterior) * 100


def _fila(nombre, actual, anterior, umbral, umbral_pct, es_gasto=True, es_total=False):
    """Una fila del comparativo con variación y bandera 'Revisar'."""
    actual = actual or CERO
    anterior = anterior or CERO
    dif = actual - anterior
    pct = _pct(actual, anterior)
    revisar = abs(dif) >= umbral and (anterior == 0 or abs(pct) >= umbral_pct)
    # Para gastos subir es desfavorable; para ingresos subir es favorable.
    favorable = (dif < 0) if es_gasto else (dif > 0)
    return {
        'nombre': nombre, 'actual': actual, 'anterior': anterior, 'dif': dif, 'pct': pct,
        'revisar': revisar, 'favorable': favorable if dif != 0 else None, 'es_total': es_total,
    }


def _por_categoria(filas):
    return {f['categoria']: f['total'] for f in filas}


def _notas(ctx):
    """Notas automáticas (específicas y con cifras), al estilo de la hoja Resumen."""
    notas = []
    act = ctx['bal']
    mes, mes_ant = ctx['nombre_mes'], ctx['nombre_mes_prev']

    if act['ingresos'] > 0:
        pct_gastado = act['gastos'] / act['ingresos'] * 100
        if act['resultado'] >= 0:
            notas.append(f"En {mes} gastaste el {pct_gastado:.0f}% de lo que ingresó y te quedaron "
                         f"${act['resultado']:,.2f} libres (ingresos − gastos).")
        else:
            notas.append(f"En {mes} gastaste ${-act['resultado']:,.2f} más de lo que ingresó "
                         f"({pct_gastado:.0f}% de tus ingresos). Ese faltante salió de tus saldos o de deuda.")
    elif act['gastos'] > 0:
        notas.append(f"En {mes} no hay ingresos registrados y sí ${act['gastos']:,.2f} de gastos. "
                     "Si sí tuviste ingresos, regístralos para que el resultado tenga sentido.")

    gastos = [f for f in ctx['filas_gastos'] if not f['es_total']]
    if gastos:
        mayor = max(gastos, key=lambda f: f['actual'])
        if mayor['actual'] > 0:
            notas.append(f"La categoría más grande de {mes} fue {mayor['nombre']} con ${mayor['actual']:,.2f}"
                         + (f" ({mayor['actual'] / act['gastos'] * 100:.0f}% del gasto)." if act['gastos'] else "."))
        cambios = sorted((f for f in gastos if f['revisar']), key=lambda f: abs(f['dif']), reverse=True)
        for f in cambios[:3]:
            direccion = 'subió' if f['dif'] > 0 else 'bajó'
            pct_txt = f" ({abs(f['pct']):.0f}%)" if f['pct'] is not None else " (antes no había)"
            notas.append(f"{f['nombre']} {direccion} ${abs(f['dif']):,.2f}{pct_txt} respecto a {mes_ant}.")

    sin_clasificar = sum(f['actual'] for f in gastos if f['nombre'].strip().lower() in CATEGORIAS_SIN_CLASIFICAR)
    if sin_clasificar > 0:
        notas.append(f"Tienes ${sin_clasificar:,.2f} en categorías genéricas ('Otro', 'Gastos varios'). "
                     "Clasifícalos para que el resumen te diga algo útil.")

    if act['abonos_capital'] > 0:
        notas.append(f"Abonaste ${act['abonos_capital']:,.2f} a capital de tus deudas"
                     + (f" y pagaste ${act['intereses']:,.2f} de intereses" if act['intereses'] else "")
                     + f". Tu deuda total al cierre es ${ctx['balance']['pasivos']:,.2f}.")
    if act['ahorro_neto'] > 0:
        notas.append(f"Apartaste ${act['ahorro_neto']:,.2f} en cuentas de ahorro (no es gasto: sigue siendo tuyo).")
    elif act['ahorro_neto'] < 0:
        notas.append(f"Sacaste ${-act['ahorro_neto']:,.2f} de tus cuentas de ahorro este mes.")

    conc = ctx['conciliacion']
    con_dato = [c for c in conc if c['saldo_banco'] is not None]
    if con_dato:
        cuadran = [c for c in con_dato if c['cuadra']]
        no_cuadran = [c for c in con_dato if not c['cuadra']]
        if no_cuadran:
            notas.append(f"Conciliación: {len(cuadran)} de {len(con_dato)} cuentas cuadran con el banco.")
            for c in no_cuadran:
                d = c['diferencia']
                signo = '+' if d > 0 else '-'
                if c['cuenta'].es_pasivo:
                    causa = ('según el banco debes más: te falta registrar una compra o cargo' if d > 0
                             else 'según el banco debes menos: te falta registrar un pago, o registraste una compra de más')
                else:
                    causa = ('el banco tiene más que tu registro: te falta registrar una entrada, o registraste una salida de más' if d > 0
                             else 'el banco tiene menos que tu registro: te falta registrar un gasto o salida')
                notas.append(f"{c['cuenta'].nombre}: diferencia {signo}${abs(d):,.2f} ({causa}).")
        else:
            notas.append(f"Conciliación: las {len(con_dato)} cuentas con saldo capturado cuadran con el banco ✓")
    else:
        notas.append("Captura el saldo de tus estados de cuenta al cierre del mes (sección Conciliación) "
                     "para comprobar que no se te escapó ningún movimiento.")
    return notas


@login_required
def vista_resumen(request):
    hoy = datetime.now()
    try:
        year = int(request.GET.get('year', hoy.year))
        month = int(request.GET.get('month', hoy.month))
        umbral = Decimal(request.GET.get('umbral', '500'))
        umbral_pct = Decimal(request.GET.get('pct', '20'))
    except (ValueError, InvalidOperation):
        return redirect('resumen')
    if not 1 <= month <= 12:
        return redirect('resumen')

    prev_year, prev_month = _mes_anterior(year, month)
    fin_mes = _fin_de_mes(year, month)
    fin_mes_prev = _fin_de_mes(prev_year, prev_month)
    inicio_mes = date(year, month, 1)
    user = request.user
    tx = registro_transacciones.objects

    # ----- POST: guardar saldos de estados de cuenta / fijar saldo inicial -----
    if request.method == 'POST':
        cuentas = {c.id: c for c in Cuenta.objects.filter(propietario=user)}
        guardados = 0
        for key, valor in request.POST.items():
            if not key.startswith('saldo_banco_'):
                continue
            try:
                cuenta = cuentas[int(key.rsplit('_', 1)[1])]
            except (KeyError, ValueError):
                continue
            valor = (valor or '').strip().replace(',', '').replace('$', '')
            if valor == '':
                SaldoEstadoCuenta.objects.filter(cuenta=cuenta, anio=year, mes=month).delete()
                continue
            try:
                saldo = Decimal(valor)
            except InvalidOperation:
                messages.error(request, f"Saldo inválido para {cuenta.nombre}: {valor!r}")
                continue
            # Capturado a mano en esta pantalla = saldo al cierre del mes (fecha None)
            SaldoEstadoCuenta.objects.update_or_create(
                cuenta=cuenta, anio=year, mes=month, defaults={'saldo_banco': saldo, 'fecha': None, 'nota': ''})
            guardados += 1
            # "Fijar saldo inicial": ajusta la cuenta para que el libro cuadre con el banco a esta fecha
            if request.POST.get(f'fijar_inicial_{cuenta.id}'):
                dif = cuenta.ajustar_saldo_inicial_para(saldo, hasta=fin_mes)
                messages.info(request, f"{cuenta.nombre}: saldo inicial ajustado en ${dif:+,.2f} para cuadrar con el banco.")
        if guardados:
            messages.success(request, f"Saldos de {MESES_ES[month]} guardados ({guardados}).")
        return redirect(f"{request.path}?year={year}&month={month}&umbral={umbral}&pct={umbral_pct}")

    # ----- 1. Estado de resultados comparativo -----
    bal = tx.balance_dashboard(user, year, month)
    bal_prev = tx.balance_dashboard(user, prev_year, prev_month)
    g_act = _por_categoria(tx.gastos_por_categoria(user, year, month))
    g_ant = _por_categoria(tx.gastos_por_categoria(user, prev_year, prev_month))
    i_act = _por_categoria(tx.ingresos_por_categoria(user, year, month))
    i_ant = _por_categoria(tx.ingresos_por_categoria(user, prev_year, prev_month))

    filas_ingresos = [_fila(c, i_act.get(c), i_ant.get(c), umbral, umbral_pct, es_gasto=False)
                      for c in sorted(set(i_act) | set(i_ant), key=lambda c: -(i_act.get(c, CERO)))]
    filas_ingresos.append(_fila('Total ingresos', bal['ingresos'], bal_prev['ingresos'], umbral, umbral_pct, es_gasto=False, es_total=True))
    filas_gastos = [_fila(c, g_act.get(c), g_ant.get(c), umbral, umbral_pct)
                    for c in sorted(set(g_act) | set(g_ant), key=lambda c: -(g_act.get(c, CERO)))]
    filas_gastos.append(_fila('Total gastos', bal['gastos'], bal_prev['gastos'], umbral, umbral_pct, es_total=True))
    fila_resultado = _fila('Resultado del mes (ingresos − gastos)', bal['resultado'], bal_prev['resultado'], umbral, umbral_pct, es_gasto=False, es_total=True)
    pct_gastado = (bal['gastos'] / bal['ingresos'] * 100) if bal['ingresos'] else None
    pct_gastado_prev = (bal_prev['gastos'] / bal_prev['ingresos'] * 100) if bal_prev['ingresos'] else None

    # ----- 2. Movimientos entre cuentas propias (no es gasto) -----
    cuentas = list(Cuenta.objects.filter(propietario=user).order_by('tipo', 'nombre'))
    netos_act = tx.movimientos_entre_cuentas(user, year, month)
    netos_ant = tx.movimientos_entre_cuentas(user, prev_year, prev_month)
    entre_cuentas = []
    for c in cuentas:
        a, p = netos_act.get(c.id, CERO), netos_ant.get(c.id, CERO)
        if a == 0 and p == 0:
            continue
        if c.es_pasivo:
            que_es = 'Pago de deuda: baja lo que debes. El gasto se registró al comprar (tarjeta) o es el interés (préstamo).'
        elif c.tipo == 'AHORRO':
            que_es = 'Ahorro: sigue siendo tuyo, no es gasto.'
        elif c.tipo == 'INVERSION':
            que_es = 'Inversión: cambia de forma, no es gasto.'
        else:
            que_es = 'Dinero movido entre tus cuentas (positivo = recibió, negativo = envió).'
        entre_cuentas.append({'cuenta': c, 'actual': a, 'anterior': p, 'dif': a - p, 'que_es': que_es})

    # ----- 3. Cuadre por cuenta -----
    saldos_ini = Cuenta.objects.saldos(user, hasta=fin_mes_prev)
    saldos_fin = Cuenta.objects.saldos(user, hasta=fin_mes)
    flujos = Cuenta.objects.entradas_salidas(user, desde=inicio_mes, hasta=fin_mes)
    cuadre = []
    for c in cuentas:
        f = flujos.get(c.id, {'entradas': CERO, 'salidas': CERO})
        cuadre.append({
            'cuenta': c, 'inicial': saldos_ini.get(c.id, CERO), 'entradas': f['entradas'],
            'salidas': f['salidas'], 'final': saldos_fin.get(c.id, CERO),
        })

    # ----- 4. Conciliación contra estados de cuenta -----
    saldos_banco = {s.cuenta_id: s for s in SaldoEstadoCuenta.objects.filter(cuenta__propietario=user, anio=year, mes=month)}
    conciliados_antes = set(SaldoEstadoCuenta.objects.filter(
        cuenta__propietario=user).filter(anio__lt=year).values_list('cuenta_id', flat=True)) | set(
        SaldoEstadoCuenta.objects.filter(cuenta__propietario=user, anio=year, mes__lt=month).values_list('cuenta_id', flat=True))
    conciliacion = []
    for c in cuentas:
        sb = saldos_banco.get(c.id)
        saldo_banco = sb.saldo_banco if sb else None
        # Si el saldo del banco es de una fecha concreta (captura a mitad de mes),
        # comparamos contra el libro a ESA fecha, no al cierre del mes.
        fecha_saldo = sb.fecha if (sb and sb.fecha and sb.fecha < fin_mes) else None
        registro = c.saldo(hasta=fecha_saldo) if fecha_saldo else saldos_fin.get(c.id, CERO)
        diferencia = (saldo_banco - registro) if saldo_banco is not None else None
        conciliacion.append({
            'cuenta': c, 'registro': registro, 'saldo_banco': saldo_banco, 'diferencia': diferencia,
            'fecha_saldo': fecha_saldo,
            'cuadra': diferencia is not None and abs(diferencia) < Decimal('0.005'),
            'puede_fijar_inicial': c.id not in conciliados_antes,
        })

    balance = Cuenta.objects.resumen_balance(user, hasta=fin_mes)
    balance_prev = Cuenta.objects.resumen_balance(user, hasta=fin_mes_prev)

    ctx = {
        'selected_year': year, 'selected_month': month,
        'nombre_mes': f"{MESES_ES[month]} {year}", 'nombre_mes_prev': f"{MESES_ES[prev_month]} {prev_year}",
        'years': range(hoy.year, hoy.year - 5, -1), 'months': range(1, 13),
        'umbral': umbral, 'umbral_pct': umbral_pct,
        'bal': bal, 'bal_prev': bal_prev,
        'filas_ingresos': filas_ingresos, 'filas_gastos': filas_gastos, 'fila_resultado': fila_resultado,
        'pct_gastado': pct_gastado, 'pct_gastado_prev': pct_gastado_prev,
        'entre_cuentas': entre_cuentas,
        'cuadre': cuadre,
        'conciliacion': conciliacion,
        'balance': balance, 'balance_prev': balance_prev,
        'fin_mes': fin_mes,
    }
    ctx['notas'] = _notas(ctx)
    return render(request, 'resumen.html', ctx)
