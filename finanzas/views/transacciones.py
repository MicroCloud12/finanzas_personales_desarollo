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
from config.celery import app as celery_app

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
def aprobar_todos_tickets(request):
    """
    Aprueba TODOS los tickets pendientes que estaban en la página, cada uno
    con su propia configuración seleccionada.
    """
    if request.method == 'POST':
        # Primero, obtenemos una lista de todos los IDs de tickets pendientes del usuario.
        tickets_pendientes = TransaccionPendiente.objects.filter(propietario=request.user, estado='pendiente')
        tickets_aprobados_count = 0

        # Iteramos sobre cada ticket pendiente
        for ticket in tickets_pendientes:
            # Para cada ticket, construimos los nombres de sus campos de formulario
            cuenta_key = f'cuenta_origen_{ticket.id}'
            categoria_key = f'categoria_{ticket.id}'
            tipo_key = f'tipo_{ticket.id}'
            cuenta_destino_key = f'cuenta_destino_{ticket.id}'

            # Extraemos los datos de ESE ticket en particular del POST
            cuenta = request.POST.get(cuenta_key)
            categoria = request.POST.get(categoria_key)
            tipo = request.POST.get(tipo_key, 'GASTO')
            cuenta_destino = request.POST.get(cuenta_destino_key)

            # Si se proporcionaron los datos necesarios, procesamos el ticket
            if cuenta and categoria and tipo and cuenta_destino:
                TransactionService.approve_pending_transaction(
                    ticket_id=ticket.id,
                    user=request.user,
                    cuenta=cuenta,
                    categoria=categoria,
                    tipo_transaccion=tipo,
                    cuenta_destino=cuenta_destino
                )
                tickets_aprobados_count += 1
        
        if tickets_aprobados_count > 0:
            messages.success(request, f"{tickets_aprobados_count} tickets han sido aprobados correctamente.")
        else:
            messages.warning(request, "No se seleccionaron tickets para aprobar o faltaron datos.")

    return redirect('revisar_tickets')

@login_required
def rechazar_todos_tickets(request):
    if request.method == 'POST':
        TransaccionPendiente.objects.filter(propietario=request.user, estado='pendiente').update(estado='rechazada')
    return redirect('revisar_tickets')

@login_required
def aprobar_ticket(request, ticket_id):
    """
    Aprueba un SOLO ticket. Esta vista ahora es más inteligente y sabe
    buscar los datos específicos de este ticket dentro del gran formulario.
    """
    if request.method == 'POST':
        # Construimos los nombres únicos de los campos para este ticket específico
        cuenta_key = f'cuenta_origen_{ticket_id}'
        categoria_key = f'categoria_{ticket_id}'
        tipo_key = f'tipo_{ticket_id}'
        cuenta_destino_key = f'cuenta_destino_{ticket_id}'

        # Extraemos los valores del POST usando esos nombres únicos
        cuenta_seleccionada = request.POST.get(cuenta_key)
        categoria_seleccionada = request.POST.get(categoria_key)
        tipo_seleccionado = request.POST.get(tipo_key, 'GASTO') # 'GASTO' como valor por defecto
        cuenta_destino_seleccionada = request.POST.get(cuenta_destino_key)

        # Usamos el servicio para manejar la aprobación del ticket individual
        TransactionService.approve_pending_transaction(
            ticket_id=ticket_id,
            user=request.user,
            cuenta=cuenta_seleccionada,
            categoria=categoria_seleccionada,
            tipo_transaccion=tipo_seleccionado,
            cuenta_destino=cuenta_destino_seleccionada
        )
        messages.success(request, "Ticket aprobado correctamente.")
        
    return redirect('revisar_tickets')

@login_required
def crear_transacciones(request):
    if request.method == 'POST':
        form = TransaccionesForm(request.POST, user=request.user)
        if form.is_valid():
            nueva_transaccion = form.save(commit=False)
            nueva_transaccion.propietario = request.user
            nueva_transaccion.save()
            return redirect('lista_transacciones')
        else:
            logger.error(f"Error de validación en TransaccionesForm: {form.errors.as_json()}")
    else: 
        form = TransaccionesForm(user=request.user)
    context = {'form': form}
    return render(request, 'transacciones.html', context)

@login_required
def lista_transacciones(request):
    suscripcion, created = Suscripcion.objects.get_or_create(usuario=request.user)
    es_usuario_premium = suscripcion.is_active()
    current_year = datetime.now().year
    current_month = datetime.now().month
    year = int(request.GET.get('year', current_year))
    month = int(request.GET.get('month', current_month))
    transacciones_del_mes = registro_transacciones.objects.filter(
        propietario=request.user,
        fecha__year=year,
        fecha__month=month
    ).order_by('-fecha')
    
    context = {
        'transacciones': transacciones_del_mes,
        'es_usuario_premium': es_usuario_premium, # <-- Añadir la variable al contexto
        'selected_year': year,
        'selected_month': month,
        'years': range(current_year, current_year - 5, -1),
        'months': range(1, 13),
    }
    return render(request, 'lista_transacciones.html', context)

@login_required
def editar_transaccion(request, transaccion_id):
    transaccion = get_object_or_404(registro_transacciones, id=transaccion_id, propietario=request.user)
    
    if request.method == 'POST':
        # --- CAMBIO 1: Pasamos el 'user' aquí ---
        form = TransaccionesForm(request.POST, instance=transaccion, user=request.user)
        if form.is_valid():
            form.save()
            return redirect('lista_transacciones')
    else:
        # --- CAMBIO 2: Y también lo pasamos aquí ---
        form = TransaccionesForm(instance=transaccion, user=request.user)
    
    return render(request, 'editar_transaccion.html', {'form': form})

@login_required
def eliminar_transaccion(request, transaccion_id):
    transaccion = get_object_or_404(registro_transacciones, id=transaccion_id, propietario=request.user)
    if request.method == 'POST':
        transaccion.delete()
        return redirect('lista_transacciones')
    return render(request, 'confirmar_eliminar_transaccion.html', {'transaccion': transaccion})

@login_required
def revisar_tickets(request):
    tickets_pendientes = TransaccionPendiente.objects.filter(propietario=request.user, estado='pendiente')
    # --- NUEVO: Obtenemos las cuentas y deudas del usuario ---
    cuentas_usuario = Cuenta.objects.filter(propietario=request.user)
    deudas_usuario = Deuda.objects.filter(propietario=request.user)
    
    # Formateamos la fecha de manera segura para mostrarla en el template
    for ticket in tickets_pendientes:
        fecha_cruda = ticket.datos_json.get("fecha") or ticket.datos_json.get("fecha_emision")
        fecha_obj = parse_date_safely(fecha_cruda)
        ticket.fecha_formateada = fecha_obj.strftime("%d/%m/%Y")
    
    return render(request, 'revisar_tickets.html', {
        'tickets': tickets_pendientes,
        'cuentas_usuario': cuentas_usuario,
        'deudas_usuario': deudas_usuario
    })

@login_required
def rechazar_ticket(request, ticket_id):
    ticket = TransaccionPendiente.objects.get(id=ticket_id, propietario=request.user)
    ticket.estado = 'rechazada'
    ticket.save()
    return redirect('revisar_tickets')

'''
Vista para procesar automáticamente los tickets de Drive.
'''
@login_required
def iniciar_procesamiento_drive(request):
    """
    Inicia el proceso de descubrimiento y procesamiento paralelo de tickets.
    """
    try:
        # La lógica de token ahora está dentro del servicio, pero la vista
        # debe asegurarse de que la tarea se inicie.
        task = process_drive_tickets.delay(request.user.id)
        return JsonResponse({"task_id": task.id}, status=202)
    except Exception as e:
        # Captura errores generales durante el inicio de la tarea
        return JsonResponse({"error": f"No se pudo iniciar la tarea: {str(e)}"}, status=400)

'''
vista para los Dashboards y gráficas de transacciones 
y ganancias mensuales, e inversiones.
'''
@login_required
def vista_procesamiento_automatico(request):
    return render(request, 'procesamiento_automatico.html')

@login_required
def get_initial_task_result(request, task_id):
    """
    Consulta el resultado de la tarea "lanzadora". Su único trabajo es
    esperar a que esta tarea termine para devolver el ID del grupo.
    """
    try:
        task_result = AsyncResult(task_id)
        if task_result.ready():
            return JsonResponse({"status": "SUCCESS", "result": task_result.result})
        else:
            return JsonResponse({"status": "PENDING"})
    except Exception as e:
        logger.error(f"Error en get_initial_task_result: {e}")
        return JsonResponse({"status": "FAILURE", "info": str(e)}, status=500)

@login_required
def get_group_status(request, group_id):
    """
    Consulta el estado de un GroupResult para reportar el progreso.
    """
    try:
        group_result = GroupResult.restore(group_id)
        if not group_result:
             return JsonResponse({"status": "PENDING"})

        if group_result.ready():
            return JsonResponse({"status": "COMPLETED"})
        else:
            total = len(group_result)
            completed = group_result.completed_count()
            return JsonResponse({
                "status": "PROGRESS",
                "total": total,
                "completed": completed,
                "progress": int((completed / total) * 100) if total > 0 else 0
            })
    except Exception as e:
        logger.error(f"Error en get_group_status: {e}")
        return JsonResponse({"status": "FAILURE", "info": str(e)}, status=500)

@require_POST
@login_required
def cancelar_procesamiento(request):
    """
    Controlador para revocar la tarea principal y el grupo de tareas hijo
    del autoescaneo para detener el consumo de recursos.
    """
    try:
        data = json.loads(request.body)
        task_id = data.get('task_id')
        group_id = data.get('group_id')
        cancel_type = data.get('cancel_type', 'tickets')

        if not task_id:
            return JsonResponse({'status': 'error', 'message': 'Falta task_id'}, status=400)

        # Revocar la tarea principal (por si aún no empieza a hacer dispatch del grupo)
        celery_app.control.revoke(task_id, terminate=True)
        logger.info(f"Tarea principal revocada: {task_id}")

        # Si ya se generó el group_id, revocamos todas las subtareas pendientes
        if group_id:
            group_result = GroupResult.restore(group_id)
            if group_result:
                group_result.revoke()
                logger.info(f"Grupo de tareas revocado: {group_id}")

        # Rechazar los registros que pudieron haberse creado parcialmente antes de cancelar
        if cancel_type == 'tickets':
            TransaccionPendiente.objects.filter(propietario=request.user, estado='pendiente').update(estado='rechazada')
        elif cancel_type == 'inversiones':
            PendingInvestment.objects.filter(propietario=request.user, estado='pendiente').update(estado='rechazada')
        elif cancel_type == 'deudas':
            AmortizacionPendiente.objects.filter(deuda__propietario=request.user, estado='pendiente').update(estado='rechazada')
        elif cancel_type == 'facturas':
            Factura.objects.filter(usuario=request.user, estado='pendiente').update(estado='rechazada')

        return JsonResponse({'status': 'success', 'message': 'Procesamiento cancelado exitosamente.'})
    except Exception as e:
        logger.error(f"Error al cancelar procesamiento: {e}")
        return JsonResponse({'status': 'error', 'message': 'Ocurrió un error inesperado al cancelar'}, status=500)
     
'''
Mercado Pago y suscripciones
'''
