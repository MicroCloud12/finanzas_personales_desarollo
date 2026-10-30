import logging
from decimal import Decimal

from django.contrib import messages
from django.http import JsonResponse
from django.urls import reverse
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.shortcuts import render, redirect, get_object_or_404


from ..utils import parse_date_safely
from ..services.finance_service import DebtService
from ..tasks import (
    process_drive_amortizations,
)
from ..forms import (
    DeudaForm, PagoAmortizacionForm
)
from ..models import (
    Suscripcion, Deuda, PagoAmortizacion, 
    AmortizacionPendiente, Cuenta
)

logger = logging.getLogger(__name__)

@login_required
def lista_deudas(request):
    """
    Muestra una lista de todas las deudas (préstamos y tarjetas) del usuario.
    """
    suscripcion, created = Suscripcion.objects.get_or_create(usuario=request.user)
    es_usuario_premium = suscripcion.is_active()
    deudas = list(Deuda.objects.filter(propietario=request.user).select_related('cuenta').order_by('fecha_adquisicion'))
    # Un solo cálculo de saldos del libro mayor para todas las deudas
    saldos = Cuenta.objects.saldos(request.user)
    for d in deudas:
        if d.cuenta_id:
            d.cuenta.saldo_calculado = saldos.get(d.cuenta_id, Decimal('0.00'))
    context = {'deudas': deudas,
               'es_usuario_premium': es_usuario_premium
              }
    return render(request, 'lista_deudas.html', context)

@login_required
def crear_deuda(request):
    """
    Maneja la creación de una nueva deuda. Al guardarse se crea su cuenta de
    pasivo en el libro mayor (el saldo se deriva de los movimientos).
    """
    if request.method == 'POST':
        form = DeudaForm(request.POST)
        if form.is_valid():
            form.instance.propietario = request.user
            deuda = form.save()

            # Si es un préstamo con tasa y plazo, generamos su tabla de amortización
            if deuda.tipo_deuda == 'PRESTAMO' and deuda.plazo_meses > 1 and not deuda.amortizacion.exists():
                DebtService.generar_tabla_amortizacion(deuda)

            messages.success(request, f"Deuda '{deuda.nombre}' creada con éxito.")
            return redirect('lista_deudas')
    else:
        form = DeudaForm()

    return render(request, 'form_simple.html', {
        'form': form, 'titulo': 'Añadir Nueva Deuda', 'boton': 'Guardar Deuda', 'cancel_url': reverse('lista_deudas')})

@login_required
def detalle_deuda(request, deuda_id):
    deuda = get_object_or_404(Deuda, id=deuda_id, propietario=request.user)

    if request.method == 'POST':
        form = PagoAmortizacionForm(request.POST)
        if form.is_valid():
            pago = form.save(commit=False)
            pago.deuda = deuda
            # Nueva cuota = la siguiente a la última; su saldo parte del saldo anterior (o del monto total).
            ultima_cuota = deuda.amortizacion.order_by('-numero_cuota').first()
            pago.numero_cuota = (ultima_cuota.numero_cuota if ultima_cuota else 0) + 1
            saldo_previo = ultima_cuota.saldo_insoluto if ultima_cuota else deuda.monto_total
            pago.saldo_insoluto = saldo_previo - pago.capital
            pago.save()
            messages.success(request, "Cuota añadida correctamente.")
            return redirect('detalle_deuda', deuda_id=deuda.id)
    else:
        form = PagoAmortizacionForm()

    context = {
        'deuda': deuda,
        'amortizacion': deuda.amortizacion.order_by('numero_cuota'),
        'form': form 
    }
    return render(request, 'detalle_deuda.html', context)

@login_required
def editar_deuda(request, deuda_id):
    deuda = get_object_or_404(Deuda, id=deuda_id, propietario=request.user)

    if request.method == 'POST':
        form = DeudaForm(request.POST, instance=deuda)
        if form.is_valid():
            form.instance.requiere_configuracion_adicional = False
            # form.save() liga la cuenta de pasivo y, si se capturó "¿cuánto debes hoy?",
            # concilia el saldo inicial para que el libro coincida con ese valor.
            deuda = form.save()
            messages.success(request, f"La deuda '{deuda.nombre}' ha sido actualizada.")
            return redirect('lista_deudas')
    else:
        form = DeudaForm(instance=deuda)

    return render(request, 'form_simple.html', {
        'form': form, 'titulo': 'Editar Deuda', 'boton': 'Guardar Deuda', 'cancel_url': reverse('lista_deudas')})

@login_required
@require_POST
def eliminar_deuda(request, deuda_id):
    """Elimina la deuda, su cuenta de pasivo y su amortización (se confirma en la lista)."""
    deuda = get_object_or_404(Deuda, id=deuda_id, propietario=request.user)
    deuda.delete()
    messages.success(request, f"La deuda '{deuda.nombre}' ha sido eliminada correctamente.")
    return redirect('lista_deudas')

@login_required
def vista_procesamiento_deudas(request, deuda_id):
    deuda = get_object_or_404(Deuda, id=deuda_id, propietario=request.user)
    return render(request, 'procesamiento.html', {
        'deuda': deuda,
        'titulo': 'Procesamiento de Amortizaciones',
        'icono': 'M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z',
        'descripcion': 'Buscaremos tablas de amortización en tu carpeta de Drive.',
        'start_url': reverse('procesar_drive_deudas', args=[deuda.id]),
        'redirect_url': reverse('revisar_amortizaciones', args=[deuda.id]),
    })

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

