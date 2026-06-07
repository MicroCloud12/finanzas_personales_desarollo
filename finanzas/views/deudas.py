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
from ..services.finance_service import DebtService
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
def lista_deudas(request):
    """
    Muestra una lista de todas las deudas (préstamos y tarjetas) del usuario.
    """
    suscripcion, created = Suscripcion.objects.get_or_create(usuario=request.user)
    es_usuario_premium = suscripcion.is_active()
    deudas = Deuda.objects.filter(propietario=request.user).order_by('fecha_adquisicion')
    context = {'deudas': deudas,
               'es_usuario_premium': es_usuario_premium
              }
    return render(request, 'lista_deudas.html', context)

@login_required
def crear_deuda(request):
    """
    Maneja la creación de una nueva deuda.
    """
    if request.method == 'POST':
        form = DeudaForm(request.POST)
        if form.is_valid():
            deuda = form.save(commit=False)
            deuda.propietario = request.user
            deuda.save() # Se guarda la deuda primero
            
            # --- 2. ¡AQUÍ OCURRE LA MAGIA! ---
            # Si la deuda es un préstamo, generamos su tabla de amortización
            #if deuda.tipo_deuda == 'PRESTAMO':
            #    DebtService.generar_tabla_amortizacion(deuda)
            
            messages.success(request, f"Deuda '{deuda.nombre}' creada con éxito.")
            return redirect('lista_deudas')
    else:
        form = DeudaForm()
    
    context = {'form': form}
    return render(request, 'crear_deuda.html', context)

# Placeholder para las vistas que construiremos a continuación.
# Esto evita que la aplicación se rompa por las URLs que ya creamos.

@login_required
def detalle_deuda(request, deuda_id):
    deuda = get_object_or_404(Deuda, id=deuda_id, propietario=request.user)
    # Obtenemos la amortización ordenada para facilitar el cálculo
    amortizacion = deuda.amortizacion.all().order_by('-numero_cuota') 

    if request.method == 'POST':
        form = PagoAmortizacionForm(request.POST)
        if form.is_valid():
            pago = form.save(commit=False)
            pago.deuda = deuda
            pago.numero_cuota = (amortizacion.first().numero_cuota if amortizacion.exists() else 0) + 1

            # --- LÓGICA DE CÁLCULO AÑADIDA AQUÍ ---
            ultima_cuota = amortizacion.first()
            if ultima_cuota:
                # Si ya hay cuotas, el nuevo saldo es el saldo anterior menos el capital de la nueva cuota
                pago.saldo_insoluto = ultima_cuota.saldo_insoluto - pago.capital
            else:
                # Si es la primera cuota, se calcula sobre el monto total de la deuda
                pago.saldo_insoluto = deuda.monto_total - pago.capital
            
            pago.save() # El modelo ahora solo calculará el pago_total y guardará.
            messages.success(request, "Cuota añadida correctamente.")
            return redirect('detalle_deuda', deuda_id=deuda.id)
    else:
        form = PagoAmortizacionForm()

    context = {
        'deuda': deuda,
        # La pasamos ordenada ascendentemente a la plantilla para la visualización
        'amortizacion': deuda.amortizacion.all().order_by('numero_cuota'), 
        'form': form 
    }
    return render(request, 'detalle_deuda.html', context)

@login_required
def editar_deuda(request, deuda_id):
    deuda = get_object_or_404(Deuda, id=deuda_id, propietario=request.user)
    
    if request.method == 'POST':
        monto_total_anterior = deuda.monto_total
        estaba_pendiente_configuracion = deuda.requiere_configuracion_adicional
        
        form = DeudaForm(request.POST, instance=deuda)
        if form.is_valid():
            deuda = form.save(commit=False)
            
            # --- CORRECCIÓN SALDO PENDIENTE ---
            # Ya sea la configuración inicial o un cambio de límite posterior,
            # sumamos la diferencia del límite al saldo pendiente actual.
            # Esto evita borrar gastos que se hayan hecho antes de configurar el límite.
            diferencia_monto = (deuda.monto_total or 0) - (monto_total_anterior or 0)
            if diferencia_monto != 0:
                deuda.saldo_pendiente = (deuda.saldo_pendiente or 0) + diferencia_monto

            deuda.requiere_configuracion_adicional = False # Ya se actualizó la configuración
            deuda.save()
            messages.success(request, f"La deuda '{deuda.nombre}' ha sido actualizada.")
            return redirect('lista_deudas')
    else:
        form = DeudaForm(instance=deuda)
        
    return render(request, 'editar_deuda.html', {'form': form, 'deuda': deuda})

@login_required
def eliminar_deuda(request, deuda_id):
    """
    Maneja la eliminación de una deuda y sus pagos de amortización asociados.
    """
    deuda = get_object_or_404(Deuda, id=deuda_id, propietario=request.user)
    
    # Si el usuario confirma la eliminación (envía el formulario)
    if request.method == 'POST':
        nombre_deuda = deuda.nombre
        deuda.delete()
        messages.success(request, f"La deuda '{nombre_deuda}' ha sido eliminada correctamente.")
        return redirect('lista_deudas')
    
    # Si es la primera vez que se carga la página, muestra la confirmación
    context = {'deuda': deuda}
    return render(request, 'confirmar_eliminar_deuda.html', context)

@login_required
def vista_procesamiento_deudas(request, deuda_id):
    deuda = get_object_or_404(Deuda, id=deuda_id, propietario=request.user)
    return render(request, 'procesamiento_deudas.html', {'deuda': deuda})

@login_required
def iniciar_procesamiento_deudas(request, deuda_id):
    """Inicia la tarea de Celery para procesar las tablas de amortización."""
    try:
        task = process_drive_amortizations.delay(request.user.id, deuda_id)
        return JsonResponse({"task_id": task.id}, status=202)
    except Exception as e:
        return JsonResponse({"error": f"No se pudo iniciar la tarea: {str(e)}"}, status=400)

@login_required
def revisar_amortizaciones(request, deuda_id):
    """Muestra las tablas de amortización pendientes para su revisión."""
    deuda = get_object_or_404(Deuda, id=deuda_id, propietario=request.user)
    pendientes = AmortizacionPendiente.objects.filter(deuda=deuda, estado='pendiente')
    context = {
        'deuda': deuda,
        'pendientes': pendientes
    }
    return render(request, 'revisar_amortizaciones.html', context)

@login_required
def aprobar_amortizacion(request, pendiente_id):
    """Crea los registros de PagoAmortizacion a partir de una tabla pendiente."""
    pendiente = get_object_or_404(AmortizacionPendiente, id=pendiente_id, propietario=request.user)
    deuda = pendiente.deuda

    if request.method == 'POST':
        cuotas_json = pendiente.datos_json
        
        # Borramos la tabla de amortización existente para evitar duplicados
        PagoAmortizacion.objects.filter(deuda=deuda).delete()

        for i, cuota_data in enumerate(cuotas_json, 1):
            PagoAmortizacion.objects.create(
                deuda=deuda,
                numero_cuota=i,
                fecha_vencimiento=parse_date_safely(cuota_data.get("fecha_vencimiento")),
                capital=Decimal(str(cuota_data.get("capital", 0.0))),
                interes=Decimal(str(cuota_data.get("interes", 0.0))),
                iva=Decimal(str(cuota_data.get("iva", 0.0))),
                saldo_insoluto=Decimal(str(cuota_data.get("saldo_insoluto", 0.0)))
            )
        
        pendiente.estado = 'aprobada'
        pendiente.save()
        messages.success(request, f"Tabla de amortización del archivo '{pendiente.nombre_archivo}' aprobada y aplicada.")
        return redirect('detalle_deuda', deuda_id=deuda.id)

    return redirect('revisar_amortizaciones', deuda_id=deuda.id)

@login_required
def rechazar_amortizacion(request, pendiente_id):
    """Marca una tabla de amortización pendiente como rechazada."""
    pendiente = get_object_or_404(AmortizacionPendiente, id=pendiente_id, propietario=request.user)
    deuda_id = pendiente.deuda.id

    if request.method == 'POST':
        pendiente.estado = 'rechazada'
        pendiente.save()
        messages.success(request, f"La tabla de amortización del archivo '{pendiente.nombre_archivo}' ha sido rechazada.")
        return redirect('revisar_amortizaciones', deuda_id=deuda_id)

    # Si se accede por GET, simplemente redirigir
    return redirect('revisar_amortizaciones', deuda_id=deuda_id)

