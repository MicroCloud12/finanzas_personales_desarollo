import json
import logging
from decimal import Decimal
from datetime import datetime, timedelta

from django.utils import timezone
from django.urls import reverse
from django.contrib import messages
from django.contrib.auth import login
from django.http import HttpResponse, JsonResponse
from django.core.mail import send_mail
from django.conf import settings
from django.db.models import Sum, Q, Count
from django.contrib.auth.models import User
from django.utils.dateformat import DateFormat
from django.db.models.functions import TruncMonth
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_GET
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404

from celery.result import AsyncResult, GroupResult

from ..utils import parse_date_safely
from ..services.finance_service import InvestmentService
from ..tasks import (
    process_drive_tickets,
    process_drive_investments,
    process_drive_amortizations,
    process_drive_for_invoices,
    process_drive_utility_bills,
)
from ..forms import (
    TransaccionesForm, FormularioRegistroPersonalizado, InversionForm, 
    DeudaForm, PagoAmortizacionForm, CuentaForm
)
from ..services import (
    TransactionService, MercadoPagoService, StockPriceService, 
    InvestmentService, RISCService, BillingService
)
from ..models import (
    registro_transacciones, Suscripcion, TransaccionPendiente, 
    inversiones, GananciaMensual, PendingInvestment, Deuda, 
    PagoAmortizacion, AmortizacionPendiente, Factura, PortfolioHistory,
    GoogleCredentials, TiendaFacturacion, Cuenta, Presupuesto, 
    HistorialReciboServicio
)

logger = logging.getLogger(__name__)

@login_required
def vista_dashboard(request):
    # --- ONBOARDING OBLIGATORIO ---
    # Si el usuario no tiene ninguna cuenta registrada, lo forzamos a crear una
    if not Cuenta.objects.filter(propietario=request.user).exists():
        messages.info(request, "¡Bienvenido! Para poder analizar tus tickets y automatizar tus gastos, primero necesitamos que registres al menos una cuenta o tarjeta.")
        return redirect('gestionar_cuentas')
    # ------------------------------

    # Definimos fechas al inicio para usarlas en todo el dashboard
    current_year = datetime.now().year
    current_month = datetime.now().month
    year = int(request.GET.get('year', current_year))
    month = int(request.GET.get('month', current_month))

    suscripcion, created = Suscripcion.objects.get_or_create(usuario=request.user)
    
    # --- LÓGICA PARA LA GRÁFICA DE AHORRO (SAVINGS GROWTH) ---
    # Calculamos el ahorro acumulado mes a mes para el año seleccionado
    savings_qs = registro_transacciones.objects.filter(
        propietario=request.user,
        fecha__year=year
    ).filter(
        # 1. Todo lo que esté categorizado explícitamente como Ahorro (menos Gastos)
        (Q(categoria__iexact='Ahorro') & ~Q(tipo__in=['GASTO', 'PAGO_MENSUALIDAD', 'PAGO_CAPITAL'])) |
        # 2. Transferencias directas a la Cuenta Ahorro
        Q(tipo__iexact='TRANSFERENCIA', cuenta_destino__iexact='Cuenta Ahorro') | 
        # 3. Ingresos que entraron directo a Cuenta Ahorro 
        Q(tipo__iexact='INGRESO', cuenta_origen__iexact='Cuenta Ahorro')
    ).annotate(mes=TruncMonth('fecha')).values('mes').annotate(total=Sum('monto')).order_by('mes')

    savings_labels = []
    savings_data = []
    ahorro_acumulado = Decimal('0.0')
    
    # Mapa de ahorro por mes
    ahorro_por_mes = {s['mes'].strftime('%Y-%m'): s['total'] for s in savings_qs}
    
    # Generamos los meses para todo el año
    meses_es = ['', 'Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio', 'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre']
    for m in range(1, 13):
        try:
            mes_fecha = datetime(year, m, 1)
        except ValueError:
             # Caso borde
            continue
            
        mes_key = mes_fecha.strftime('%Y-%m')
        
        monto_mes = ahorro_por_mes.get(mes_key, Decimal('0.0'))
        ahorro_acumulado += monto_mes
        
        savings_labels.append(meses_es[mes_fecha.month]) # Nombre del mes
        savings_data.append(str(ahorro_acumulado))
        
    chart_labels = savings_labels
    chart_data = savings_data
    # ----------------------------------------------
    
    # Verificamos si la suscripción está activa con nuestro método del modelo.
    es_usuario_premium = suscripcion.is_active()

    # --- LA MAGIA DE LA OPTIMIZACIÓN (VIA MANAGER) ---
    bal = registro_transacciones.objects.balance_dashboard(request.user, year, month)
    
    # Hacemos UNA SOLA CONSULTA para las inversiones
    agregados_inversion = inversiones.objects.filter(propietario=request.user).aggregate(
        total_inicial=Sum('costo_total_adquisicion'),
        total_actual=Sum('valor_actual_mercado')
    )
    # --- FIN DE LA OPTIMIZACIÓN ---

    # Asignamos valores desde el diccionario 'bal'
    ingresos = bal['ingresos_efectivo']
    gastos = bal['gastos_efectivo']
    ahorro_total = bal['ahorro_total']
    transferencias = bal['transferencias_efectivo']
    gastos_ahorro = bal['gastos_ahorro']
    ingresos_ahorro = bal['ingresos_ahorro']

    inversion_inicial_usd = agregados_inversion.get('total_inicial') or Decimal('0.00')
    inversion_actual = agregados_inversion.get('total_actual') or Decimal('0.00')

    balance = ingresos - gastos - gastos_ahorro
    disponible_banco = ingresos - gastos - transferencias - ahorro_total
    
    ahorro = ahorro_acumulado
    
    # --- Cálculo de Transacciones de Ahorro del Mes ---
    ahorros_tx_count = registro_transacciones.objects.filter(
        propietario=request.user,
        fecha__year=year,
        fecha__month=month
    ).filter(
        (Q(categoria__iexact='Ahorro') & ~Q(tipo__in=['GASTO', 'PAGO_MENSUALIDAD', 'PAGO_CAPITAL'])) |
        Q(tipo__iexact='TRANSFERENCIA', cuenta_destino__iexact='Cuenta Ahorro') | 
        Q(tipo__iexact='INGRESO', cuenta_origen__iexact='Cuenta Ahorro')
    ).count()

    # --- Cálculo de Deuda Total ---
    todas_deudas = Deuda.objects.filter(propietario=request.user)
    deuda_total = Decimal('0.00')
    
    num_tarjetas = todas_deudas.filter(tipo_deuda='TARJETA_CREDITO').count()
    num_prestamos = todas_deudas.filter(tipo_deuda='PRESTAMO').count()
    
    for d in todas_deudas:
        if d.tipo_deuda == 'TARJETA_CREDITO':
            # Para TC: Deuda Real = Límite (monto_total) - Disponible (saldo_pendiente)
            deuda_real = d.monto_total - d.saldo_pendiente
            if deuda_real > 0:
                deuda_total += deuda_real
        else:
            # Para Préstamos: Deuda Real = Saldo Pendiente
            deuda_total += d.saldo_pendiente
            
    # --- Pago total a deudas este mes ---
    pagos_prestamos = registro_transacciones.objects.filter(
        propietario=request.user,
        fecha__year=year,
        fecha__month=month,
        tipo__in=['PAGO_MENSUALIDAD', 'PAGO_CAPITAL']
    ).aggregate(total=Sum('monto'))['total'] or Decimal('0.00')
    
    nombres_tarjetas = todas_deudas.filter(tipo_deuda='TARJETA_CREDITO').values_list('nombre', flat=True)
    pagos_tc = registro_transacciones.objects.filter(
        propietario=request.user,
        fecha__year=year,
        fecha__month=month,
        tipo='TRANSFERENCIA',
        cuenta_destino__in=nombres_tarjetas
    ).aggregate(total=Sum('monto'))['total'] or Decimal('0.00')
    
    total_pagado_deudas = pagos_prestamos + pagos_tc
    # --- Listado de Tarjetas para el Widget ---
    las_cuentas = Cuenta.objects.filter(propietario=request.user, tipo='DEBITO').order_by('-es_principal', 'id')
    tarjetas_list = []
    for c in las_cuentas:
        term = c.terminacion.strip() if c.terminacion else ""
        if len(term) > 4:
            term = term[-4:]
        elif len(term) < 4 and len(term) > 0:
            term = term.zfill(4)
        else:
            term = term or "****"
            
        tarjetas_list.append({
            'id': c.id,
            'nombre': c.nombre,
            'terminacion': term,
            'tipo': c.tipo
        })
        
    tarjetas_data_json = json.dumps(tarjetas_list)

    context = {
        'ingresos': ingresos,
        'gastos': gastos,
        'balance': balance,
        'transferencias': transferencias,
        'disponible_banco': disponible_banco,
        'ahorro': ahorro,
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
        'tarjetas_data_json': tarjetas_data_json,
        'tarjetas_list': tarjetas_list,
        'investment_chart_labels': chart_labels,
        'investment_chart_data': chart_data,
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
    gastos_por_categoria = registro_transacciones.objects.filter(
        propietario=request.user,
        tipo__in=['GASTO', 'PAGO_MENSUALIDAD', 'PAGO_CAPITAL'],
        fecha__year=year,
        fecha__month=month
    ).values('categoria').annotate(total=Sum('monto')).order_by('-total')
    data = {
        'labels': [item['categoria'] for item in gastos_por_categoria],
        'data': [item['total'] for item in gastos_por_categoria],
    }
    return JsonResponse(data)

@login_required
@require_GET
def datos_presupuesto(request):
    print(f"DEBUG: api_datos_presupuesto hit by {request.user}")
    presupuestos = Presupuesto.objects.filter(propietario=request.user).order_by('-monto_presupuestado')
    
    labels = []
    data_presupuestado = []
    data_real = []
    
    for p in presupuestos:
        labels.append(p.categoria)
        data_presupuestado.append(float(p.monto_presupuestado))
        data_real.append(float(p.monto_real))
        
    return JsonResponse({
        'labels': labels,
        'presupuestado': data_presupuestado,
        'real': data_real
    })

@login_required
@require_GET
def datos_flujo_dinero(request):
    try:
        year = int(request.GET.get('year', datetime.now().year))
        month = int(request.GET.get('month', datetime.now().month))
    except ValueError:
        return JsonResponse({'error': 'Formato de fecha inválido'}, status=400)
    transacciones_del_mes = registro_transacciones.objects.filter(
        propietario=request.user,
        fecha__year=year,
        fecha__month=month
    )
    ingresos = transacciones_del_mes.filter(tipo='INGRESO').exclude(categoria='Ahorro').aggregate(total=Sum('monto'))['total'] or Decimal('0.00')
    gastos = transacciones_del_mes.filter(tipo__in=['GASTO', 'PAGO_MENSUALIDAD', 'PAGO_CAPITAL']).exclude(categoria='Ahorro').aggregate(total=Sum('monto'))['total'] or Decimal('0.00')
    data = {
        'labels': ['Ingresos del Mes', 'Gastos del Mes'],
        'data': [ingresos, gastos],
    }
    return JsonResponse(data)

@login_required
@require_GET
def datos_ganancias_mensuales(request):
    """Retorna las ganancias mensuales acumuladas de las inversiones del usuario.
    profits = InvestmentService.calculate_monthly_profit(request.user)
    labels = list(profits.keys())
    data = [profits[month] for month in labels]
    return JsonResponse({'labels': labels, 'data': data})
    """
    ganancias = GananciaMensual.objects.filter(
        propietario=request.user
    ).order_by('mes')
    labels = [g.mes for g in ganancias]
    data = [g.total for g in ganancias]
    return JsonResponse({'labels': labels, 'data': data})

@login_required
@require_GET
def datos_inversiones(request):
    
    qs = (
        inversiones.objects
        .filter(propietario=request.user)
        .annotate(month=TruncMonth('fecha_compra'))
        .values('month')
        .annotate(total=Sum('ganancia_perdida_no_realizada'))
        .order_by('month')
    )
    labels = [DateFormat(item['month']).format('Y-m') for item in qs]
    values = [item['total'] for item in qs]
    return JsonResponse({'labels': labels, 'data': values})

'''
Deudas y amortizaciones
'''
@login_required
@require_GET
def api_ingresos_tarjeta(request):
    try:
        cuenta_nombre = request.GET.get('cuenta_nombre', '')
        year = request.GET.get('year', '')
        month = request.GET.get('month', '')
        
        if not cuenta_nombre or not year or not month:
            return JsonResponse({'status': 'error', 'message': 'Parámetros incompletos'}, status=400)
            
        try:
            year = int(year)
            month = int(month)
        except ValueError:
            return JsonResponse({'status': 'error', 'message': 'El formato de fecha es inválido'}, status=400)
        
        # Calcular el mes anterior para la comparación
        if month == 1:
            prev_month = 12
            prev_year = year - 1
        else:
            prev_month = month - 1
            prev_year = year
            
        # --- NUEVA LÓGICA: Procesador de flujos con Transferencias ---
        def procesar_flujo(es_entrada, y, m):
            if es_entrada:
                # Entradas: Ingresos normales OR Transferencias que llegaron a esta tarjeta
                qs = registro_transacciones.objects.filter(
                    propietario=request.user, fecha__year=y, fecha__month=m
                ).filter(
                    Q(tipo='INGRESO', cuenta_origen=cuenta_nombre) | 
                    Q(tipo='TRANSFERENCIA', cuenta_destino=cuenta_nombre)
                )
            else:
                # Salidas: Gastos normales OR Transferencias que salieron de esta tarjeta
                qs = registro_transacciones.objects.filter(
                    propietario=request.user, fecha__year=y, fecha__month=m
                ).filter(
                    Q(tipo='GASTO', cuenta_origen=cuenta_nombre) | 
                    Q(tipo='TRANSFERENCIA', cuenta_origen=cuenta_nombre)
                )
            
            agregados = qs.aggregate(
                total=Sum('monto'),
                num_categorias=Count('categoria', distinct=True)
            )
            
            return {
                'total': agregados['total'] or Decimal('0.00'),
                'transactions': qs.count(),
                'categories': agregados['num_categorias'] or 0
            }

        # 1. Obtenemos datos del mes actual y anterior
        entradas_act = procesar_flujo(es_entrada=True, y=year, m=month)
        salidas_act = procesar_flujo(es_entrada=False, y=year, m=month)
        
        entradas_prev = procesar_flujo(es_entrada=True, y=prev_year, m=prev_month)
        salidas_prev = procesar_flujo(es_entrada=False, y=prev_year, m=prev_month)

        # 2. Función auxiliar para calcular métricas de la tarjeta
        def calcular_metricas(act, prev):
            dif = act['total'] - prev['total']
            if prev['total'] > 0:
                pct = (dif / prev['total']) * Decimal('100.0')
            else:
                pct = Decimal('100.0') if act['total'] > 0 else Decimal('0.0')
                
            return {
                'total': f"{act['total']:,.2f}",
                'transactions': act['transactions'],
                'categories': act['categories'],
                'diferencia_monto': f"{abs(dif):,.2f}",
                'porcentaje': round(float(abs(pct)), 1),
                'es_positivo': bool(dif >= 0),
            }

        ingresos_data = calcular_metricas(entradas_act, entradas_prev)
        gastos_data = calcular_metricas(salidas_act, salidas_prev)
        
        # 3. Calcular Balance Total de esta Tarjeta específica
        balance_act = float(entradas_act['total']) - float(salidas_act['total'])
        balance_prev = float(entradas_prev['total']) - float(salidas_prev['total'])
        
        dif_balance = balance_act - balance_prev
        if balance_prev > 0:
            pct_balance = (dif_balance / balance_prev) * 100.0
        else:
            pct_balance = 100.0 if balance_act > 0 else 0.0

        balance_data = {
            'total': f"{balance_act:,.2f}",
            'transactions': entradas_act['transactions'] + salidas_act['transactions'],
            'categories': entradas_act['categories'] + salidas_act['categories'],
            'diferencia_monto': f"{abs(dif_balance):,.2f}",
            'porcentaje': round(float(abs(pct_balance)), 1),
            'es_positivo': bool(dif_balance >= 0),
        }

        return JsonResponse({
            'status': 'success',
            'ingresos': ingresos_data,
            'gastos': gastos_data,
            'balance': balance_data
        })
        
    except Exception as e:
        logger.error(f"Error en api_ingresos_tarjeta: {e}")
        return JsonResponse({'status': 'error', 'message': 'Ha ocurrido un error inesperado al procesar los ingresos.'}, status=500)

