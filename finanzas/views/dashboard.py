import logging
from decimal import Decimal
import calendar
from datetime import datetime, date

from django.contrib import messages
from django.http import JsonResponse
from django.db.models import Sum, Q, Count
from django.views.decorators.http import require_GET
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect


from ..models import registro_transacciones, Suscripcion, Cuenta, Presupuesto
from ..templatetags.dinero import dinero

logger = logging.getLogger(__name__)


def _metrica(act, prev, transactions, categories):
    """Cifra del mes contra el mes anterior, en el formato que pinta dashboard_cards.js."""
    dif = act - prev
    if prev > 0:
        pct = (dif / prev) * Decimal('100.0')
    else:
        pct = Decimal('100.0') if act > 0 else Decimal('0.0')
    return {
        'total': f"{act:,.2f}",
        'transactions': transactions,
        'categories': categories,
        'diferencia_monto': f"{abs(dif):,.2f}",
        'porcentaje': round(float(abs(pct)), 1),
        'es_positivo': bool(dif >= 0),
    }


def _conteo(qs):
    agg = qs.aggregate(n=Count('id'), cats=Count('categoria', distinct=True))
    return agg['n'], agg['cats']

@login_required
def vista_dashboard(request):
    # --- ONBOARDING OBLIGATORIO ---
    # Si el usuario no tiene ninguna cuenta registrada, lo forzamos a crear una
    if not Cuenta.objects.filter(propietario=request.user).exists():
        messages.info(request, "¡Bienvenido! Para poder analizar tus tickets y automatizar tus gastos, primero necesitamos que registres al menos una cuenta o tarjeta.")
        return redirect('gestionar_cuentas')
    # ------------------------------

    current_year = datetime.now().year
    current_month = datetime.now().month
    year = int(request.GET.get('year', current_year))
    month = int(request.GET.get('month', current_month))
    fin_de_mes = date(year, month, calendar.monthrange(year, month)[1])

    suscripcion, created = Suscripcion.objects.get_or_create(usuario=request.user)
    es_usuario_premium = suscripcion.is_active()

    # ===== 1. ESTADO DE RESULTADOS DEL MES (flujos) =====
    # ingresos = lo que entró a cuentas de activo
    # gastos   = gastos de consumo (con débito, efectivo O tarjeta) + intereses de deuda
    bal = registro_transacciones.objects.balance_dashboard(request.user, year, month)
    prev_year, prev_month = (year - 1, 12) if month == 1 else (year, month - 1)
    bal_prev = registro_transacciones.objects.balance_dashboard(request.user, prev_year, prev_month)
    ingresos = bal['ingresos']
    gastos = bal['gastos']
    balance = bal['resultado']                 # resultado neto del mes
    transferencias = bal['transferencias']
    total_pagado_deudas = bal['pagos_deuda']   # pagos a tarjetas + préstamos del mes

    # ===== 2. BALANCE GENERAL (saldos derivados del libro al cierre del mes) =====
    resumen = Cuenta.objects.resumen_balance(request.user, hasta=fin_de_mes)
    disponible_banco = resumen['liquido']      # efectivo + débito
    ahorro = resumen['ahorro']                 # saldo de cuentas de ahorro
    deuda_total = resumen['pasivos']           # tarjetas + préstamos
    patrimonio = resumen['patrimonio']

    cuentas_pasivo = [c for c in resumen['cuentas'] if c.es_pasivo]
    num_tarjetas = sum(1 for c in cuentas_pasivo if c.tipo == 'CREDITO')
    num_prestamos = sum(1 for c in cuentas_pasivo if c.tipo == 'PRESTAMO')

    # ===== 3. GRÁFICA DE AHORRO ACUMULADO (año seleccionado) =====
    # Base: saldo de las cuentas de ahorro al cierre del año anterior; luego
    # se acumula el flujo neto mensual hacia esas cuentas.
    base_ahorro = Cuenta.objects.resumen_balance(request.user, hasta=date(year - 1, 12, 31))['ahorro']
    ahorro_por_mes = registro_transacciones.objects.ahorro_por_mes(request.user, year)
    meses_es = ['', 'Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio', 'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre']
    savings_labels, savings_data = [], []
    ahorro_acumulado = base_ahorro
    for m in range(1, 13):
        ahorro_acumulado += ahorro_por_mes.get(f"{year}-{m:02d}", Decimal('0.0'))
        savings_labels.append(meses_es[m])
        savings_data.append(str(ahorro_acumulado))

    ahorros_tx_count = registro_transacciones.objects.del_mes(request.user, year, month).filter(
        Q(destino__tipo='AHORRO') | Q(origen__tipo='AHORRO')).count()

    # ===== 4. WIDGET DE TARJETAS (cuentas líquidas con su saldo) =====
    tarjetas_list = []
    for c in resumen['cuentas']:
        if c.tipo not in Cuenta.TIPOS_LIQUIDOS:
            continue
        term = c.terminacion.strip() if c.terminacion else ""
        if len(term) > 4:
            term = term[-4:]
        elif 0 < len(term) < 4:
            term = term.zfill(4)
        else:
            term = term or "****"
        tarjetas_list.append({
            'id': c.id,
            'nombre': c.nombre,
            'terminacion': term,
            'tipo': c.tipo,
            'saldo': dinero(c.saldo_calculado),
        })

    # Tarjetas de arriba: cifras GLOBALES del mes (no de la cuenta elegida en "Mis tarjetas")
    del_mes = registro_transacciones.objects.del_mes(request.user, year, month)
    n_ing, cat_ing = _conteo(del_mes.filter(tipo='INGRESO').exclude(destino__tipo__in=Cuenta.TIPOS_PASIVO))
    n_gas, cat_gas = _conteo(del_mes.filter(tipo='GASTO'))
    metricas = {
        'ingresos': _metrica(bal['ingresos'], bal_prev['ingresos'], n_ing, cat_ing),
        'gastos': _metrica(bal['gastos'], bal_prev['gastos'], n_gas, cat_gas),
        'balance': _metrica(bal['resultado'], bal_prev['resultado'], n_ing + n_gas, cat_ing + cat_gas),
    }

    context = {
        'ingresos': ingresos,
        'gastos': gastos,
        'gastos_consumo': bal['gastos_consumo'],
        'gastos_tarjeta': bal['gastos_tarjeta'],
        'intereses': bal['intereses'],
        'balance': balance,
        'transferencias': transferencias,
        'disponible_banco': disponible_banco,
        'patrimonio': patrimonio,
        'activos_total': resumen['activos'],
        'ahorro': ahorro,
        'ahorro_mes': bal['ahorro_neto'],
        'ahorros_tx_count': ahorros_tx_count,
        'selected_year': year,
        'selected_month': month,
        'years': range(current_year, current_year - 5, -1),
        'months': range(1, 13),
        'es_usuario_premium': es_usuario_premium,
        'deuda_total': deuda_total,
        'num_tarjetas': num_tarjetas,
        'num_prestamos': num_prestamos,
        'total_pagado_deudas': total_pagado_deudas,
        'abonos_capital': bal['abonos_capital'],
        'metricas': metricas,
        'tarjetas_list': tarjetas_list,
        'investment_chart_labels': savings_labels,
        'investment_chart_data': savings_data,
    }
    return render(request, 'dashboard.html', context)

@login_required
@require_GET
def datos_gastos_categoria(request):
    try:
        year = int(request.GET.get('year', datetime.now().year))
        month = int(request.GET.get('month', datetime.now().month))
    except ValueError:
        return JsonResponse({'error': 'Formato de fecha inválido'}, status=400)

    es_ingreso = request.GET.get('tipo') == 'INGRESO'
    agrupar = 'descripcion' if request.GET.get('agrupar') == 'descripcion' else 'categoria'

    if agrupar == 'categoria':
        # Mismas cifras que la tarjeta "Gastos"/"Ingresos" del dashboard
        if es_ingreso:
            resumen = registro_transacciones.objects.ingresos_por_categoria(request.user, year, month)
        else:
            resumen = registro_transacciones.objects.gastos_por_categoria(request.user, year, month)
    else:
        qs = registro_transacciones.objects.del_mes(request.user, year, month)
        if es_ingreso:
            qs = qs.filter(tipo='INGRESO').exclude(destino__tipo__in=Cuenta.TIPOS_PASIVO)
        else:
            qs = qs.filter(tipo='GASTO')
        resumen = list(qs.values(agrupar).annotate(total=Sum('monto')).order_by('-total'))

    # Mostramos solo las 9 mayores; el resto se agrupa en "Otros" para que la dona sea legible
    LIMITE = 9
    labels = [item[agrupar] for item in resumen[:LIMITE]]
    montos = [item['total'] for item in resumen[:LIMITE]]
    otros = sum((item['total'] for item in resumen[LIMITE:]), Decimal('0'))
    if otros:
        labels.append('Otros')
        montos.append(otros)
    return JsonResponse({'labels': labels, 'data': montos})

@login_required
@require_GET
def datos_presupuesto(request):
    """Presupuesto vs. gasto real del mes, con el real tomado del libro (no capturado a mano)."""
    try:
        year = int(request.GET.get('year', datetime.now().year))
        month = int(request.GET.get('month', datetime.now().month))
    except ValueError:
        return JsonResponse({'error': 'Formato de fecha inválido'}, status=400)

    presupuestos = Presupuesto.objects.filter(propietario=request.user).filter(
        Q(es_recurrente=True) | Q(mes=month, anio=year)
    ).order_by('-monto_presupuestado')

    gastado = {f['categoria'].strip().lower(): f['total']
               for f in registro_transacciones.objects.gastos_por_categoria(request.user, year, month)}

    labels, data_presupuestado, data_real = [], [], []
    for p in presupuestos:
        labels.append(p.categoria)
        data_presupuestado.append(float(p.monto_presupuestado))
        real = gastado.get(p.categoria.strip().lower())
        # Si no hay movimientos en esa categoría usamos el monto capturado (recibos estimados por IA)
        data_real.append(float(real if real is not None else p.monto_real))

    return JsonResponse({
        'labels': labels,
        'presupuestado': data_presupuestado,
        'real': data_real
    })
