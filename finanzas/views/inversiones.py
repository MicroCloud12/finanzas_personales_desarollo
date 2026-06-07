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
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404

from celery.result import AsyncResult, GroupResult

from ..utils import parse_date_safely
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
def vista_portafolio(request):
    """
    Vista dedicada para el Portafolio de Inversiones.
    """
    suscripcion, created = Suscripcion.objects.get_or_create(usuario=request.user)
    es_usuario_premium = suscripcion.is_active()

    # --- LÓGICA DE ACTIVOS ---
    mis_inversiones = inversiones.objects.filter(propietario=request.user).order_by('-valor_actual_mercado')
    
    # Totales Generales
    agregados = mis_inversiones.aggregate(
        total_invertido=Sum('costo_total_adquisicion'),
        valor_actual=Sum('valor_actual_mercado')
    )
    
    total_invertido = agregados['total_invertido'] or Decimal('0.00')
    valor_total = agregados['valor_actual'] or Decimal('0.00')
    ganancia_total = valor_total - total_invertido
    
    # Porcentaje de ganancia total
    porcentaje_ganancia = 0
    if total_invertido > 0:
        porcentaje_ganancia = ((valor_total - total_invertido) / total_invertido) * 100

    # --- DATOS PARA GRÁFICAS ---
    # --- DATOS PARA GRÁFICAS ---
    # 1. Historia del Portafolio (Line/Area Chart - Diario)
    # Consultamos el historial diario ya calculado
    historial_diario = PortfolioHistory.objects.filter(usuario=request.user).order_by('fecha')
    
    chart_labels = []
    chart_data = []
    
    # Si no hay historial diario (primer uso), intentamos usar lo mensual como fallback temporal
    # o simplemente mostramos vacío hasta que corran el comando.
    if historial_diario.exists():
        for dia in historial_diario:
            chart_labels.append(dia.fecha.strftime('%Y-%m-%d'))
            chart_data.append(str(dia.valor_total))
    else:
        # Fallback: Usamos la lógica mensual anterior si no han corrido el script aún
        historial_ganancias = GananciaMensual.objects.filter(propietario=request.user).order_by('mes')
        # ... (Lógica de fallback omitida para limpieza, asumimos que correrán el script)
        pass

    # 2. Distribución (Doughnut)
    # Agrupar por tipo (Cripto vs Acciones) o por Activo
    distribucion_labels = []
    distribucion_data = []
    for inv in mis_inversiones[:5]: # Top 5 activos
        distribucion_labels.append(inv.nombre_activo)
        distribucion_data.append(float(inv.valor_actual_mercado))

    context = {
        'inversiones': mis_inversiones,
        'valor_total': valor_total,
        'total_invertido': total_invertido,
        'ganancia_total': ganancia_total,
        'porcentaje_ganancia': porcentaje_ganancia,
        'chart_labels': json.dumps(chart_labels),
        'chart_data': json.dumps(chart_data),
        'dist_labels': json.dumps(distribucion_labels),
        'dist_data': json.dumps(distribucion_data),
        'es_usuario_premium': es_usuario_premium,
    }
    return render(request, 'portafolio.html', context)

@login_required
def iniciar_procesamiento_inversiones(request):
    """Inicia el procesamiento automático de inversiones."""
    try:
        task = process_drive_investments.delay(request.user.id)
        return JsonResponse({"task_id": task.id}, status=202)
    except Exception as e:
        return JsonResponse({"error": f"No se pudo iniciar la tarea: {str(e)}"}, status=400)

@login_required
def vista_procesamiento_inversiones(request):
    return render(request, 'procesamiento_inversiones.html')

@login_required
def revisar_inversiones(request):
    """
    Muestra todas las inversiones pendientes para que el usuario las revise.
    """
    pending_investments = PendingInvestment.objects.filter(propietario=request.user, estado='pendiente')
    
    # Formateamos la fecha de manera segura para mostrarla en el template
    for investment in pending_investments:
        fecha_cruda = investment.datos_json.get("fecha_compra") or investment.datos_json.get("fecha")
        fecha_obj = parse_date_safely(fecha_cruda)
        investment.fecha_formateada = fecha_obj.strftime("%d/%m/%Y")
        
    context = {'pending_investments': pending_investments}
    return render(request, 'revisar_inversiones.html', context)

@login_required
def aprobar_inversion(request, inversion_id):
    """
    Aprueba una inversión pendiente, la convierte en una inversión real y la elimina de la lista de pendientes.
    """
    pending = get_object_or_404(PendingInvestment, id=inversion_id, propietario=request.user)
    
    if request.method == 'POST':
        datos = pending.datos_json
        
        # --- CORRECCIÓN AQUÍ ---
        # Leemos los datos correctos que calculamos en la tarea asíncrona.
        
        # 1. Obtenemos el precio actual que guardamos. Si no existe, usamos el de compra como respaldo.
        precio_actual = datos.get("valor_actual_mercado", datos.get("precio_por_titulo", "0.0"))

        # 2. Obtenemos el tipo de cambio usando la clave correcta ('tipo_cambio').
        tipo_cambio = datos.get("tipo_cambio")

        # 3. Creamos la inversión final usando los datos correctos del JSON.
        inversiones.objects.create(
            propietario=request.user,
            fecha_compra=parse_date_safely(datos.get("fecha_compra")),
            emisora_ticker=datos.get("emisora_ticker"),
            nombre_activo=datos.get("nombre_activo"),
            cantidad_titulos=Decimal(datos.get("cantidad_titulos", "0.0")),
            precio_compra_titulo=Decimal(datos.get("precio_por_titulo", "0.0")),
            
            # Usamos el precio actual del mercado que calculamos en la tarea
            precio_actual_titulo=Decimal(precio_actual) / Decimal(datos.get("cantidad_titulos", "1.0")),

            # Usamos la clave correcta para el tipo de cambio
            tipo_cambio_compra=Decimal(tipo_cambio) if tipo_cambio is not None else None,
        )
        
        # El modelo `inversiones` calculará automáticamente:
        # - costo_total_adquisicion
        # - valor_actual_mercado
        # - ganancia_perdida_no_realizada
        # ...en su método .save(), que es llamado por .create()

        pending.estado = 'aprobada'
        pending.save()
        
        messages.success(request, f"Inversión en {datos.get('nombre_activo')} aprobada correctamente.")
        return redirect('revisar_inversiones')

    return redirect('revisar_inversiones')

@login_required
def rechazar_inversion(request, inversion_id):
    """
    Rechaza (elimina) una inversión pendiente.
    """
    inversion = PendingInvestment.objects.get(id=inversion_id, propietario=request.user)
    inversion.estado = 'rechazada'
    inversion.save()
    return redirect('revisar_inversiones')

@login_required
def aprobar_todas_inversiones(request):
    if request.method == 'POST':
        pendientes = TransaccionPendiente.objects.filter(propietario=request.user, estado='pendiente')
        inversiones_pendientes = [p for p in pendientes if 'nombre_activo' in p.datos_json]
        investment_service = InvestmentService()
        aprobadas = 0
        for inv in inversiones_pendientes:
            investment_service.create_investment(request.user, inv.datos_json)
            inv.estado = 'aprobada'
            inv.save()
            aprobadas += 1
        if aprobadas > 0:
            messages.success(request, f"{aprobadas} inversiones han sido aprobadas correctamente.")
        else:
            messages.warning(request, "No se aprobaron inversiones.")
    return redirect('revisar_inversiones')

@login_required
def rechazar_todas_inversiones(request):
    if request.method == 'POST':
        pendientes = TransaccionPendiente.objects.filter(propietario=request.user, estado='pendiente')
        for inv in pendientes:
            if 'nombre_activo' in inv.datos_json:
                inv.estado = 'rechazada'
                inv.save()
    return redirect('revisar_inversiones')

@login_required
def lista_inversiones(request):
    """
    Muestra todas las inversiones del usuario logueado.
    """
    suscripcion, created = Suscripcion.objects.get_or_create(usuario=request.user)
    lista = inversiones.objects.filter(propietario=request.user).order_by('-fecha_compra')
    es_usuario_premium = suscripcion.is_active()
    context = {'inversiones': lista, 'es_usuario_premium': es_usuario_premium}
    return render(request, 'lista_inversiones.html', context)

@login_required
def editar_inversion(request, inversion_id):
    inversion = get_object_or_404(inversiones, id=inversion_id, propietario=request.user)
    if request.method == 'POST':
        form = InversionForm(request.POST, instance=inversion)
        if form.is_valid():
            form.save()
            return redirect('lista_inversiones')
    else:
        form = InversionForm(instance=inversion)
    return render(request, 'editar_inversion.html', {'form': form})

@login_required
def eliminar_inversion(request, inversion_id):
    inversion = get_object_or_404(inversiones, id=inversion_id, propietario=request.user)
    if request.method == 'POST':
        inversion.delete()
        next_url = request.POST.get('next', request.GET.get('next', 'lista_inversiones'))
        return redirect(next_url)
    return render(request, 'confirmar_eliminar_inversion.html', {'inversion': inversion})

@login_required
def crear_inversion(request):
    """
    Maneja la creación de una nueva inversión, obteniendo el precio actual de una API.
    """
    if request.method == 'POST':
        form = InversionForm(request.POST)
        if form.is_valid():
            nueva_inversion = form.save(commit=False)
            nueva_inversion.propietario = request.user
            # --- OPTIMIZACIÓN: EVITAR BLOQUEOS LARGOS ---
            # 1. Intentamos obtener precio de caché (instantáneo)
            # 2. Si no está en caché, usamos el precio de compra del usuario TEMPORALMENTE para no hacer esperar al navegador.
            # 3. Lanzamos una tarea async para actualizar el precio real después (Mejora futura: Celery task).
            
            ticker = form.cleaned_data.get('emisora_ticker').upper()
            try:
                # Modificamos get_current_price para que tenga un timeout corto internamente o confiamos en el cache
                precio_actual_float = price_service.get_current_price(ticker)
            except Exception as e:
                logger.warning(f"Timeout o error al obtener precio síncrono para {ticker}: {e}")
                precio_actual_float = None

            if precio_actual_float is not None:
                nueva_inversion.precio_actual_titulo = Decimal(str(precio_actual_float))
            else:
                # FALLBACK: Usamos el precio de compra si la API falla o tarda.
                # Esto asegura que el usuario siempre reciba una respuesta rápida.
                nueva_inversion.precio_actual_titulo = nueva_inversion.precio_compra_titulo
                # AQUÍ podríamos disparar una tarea: update_price.delay(nueva_inversion.id)
            
            nueva_inversion.save()
            messages.success(request, f"Inversión en {ticker} guardada con éxito.")
            return redirect('lista_inversiones')
    else:
        form = InversionForm()
    
    context = {'form': form}
    # Asegúrate de que el path a tu template es correcto
    return render(request, 'crear_inversion.html', context)

