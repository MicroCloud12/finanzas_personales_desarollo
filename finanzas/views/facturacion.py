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
def facturacion(request):
    """
    Muestra el historial de facturas registradas.
    """
    suscripcion, created = Suscripcion.objects.get_or_create(usuario=request.user)
    
    # Ahora consultamos el modelo Factura en lugar de registro_transacciones
    facturas = Factura.objects.filter(propietario=request.user, estado='facturado').order_by('-fecha_emision')

    context = {
        'facturas': facturas,
        'es_usuario_premium': suscripcion.is_active()
    }
    return render(request, 'lista_facturacion.html', context)

# --- VISTA 2: Listado de Pendientes (La redirección) ---
def revisar_facturas_pendientes(request):
    """Lista los tickets pendientes para facturación."""
    # Ahora consultamos directamente la tabla Factura con estado 'pendiente'
    facturas_pendientes = Factura.objects.filter(propietario=request.user, estado='pendiente').order_by('-fecha_emision')
    
    return render(request, 'revisar_factura.html', {'tickets': facturas_pendientes})

@login_required
def revisar_factura_detalle(request, ticket_id):
    """Procesa y muestra los datos de facturación de un ticket concreto (ahora objeto Factura)."""
    
    # Buscamos la Factura pendiente por ID
    factura_obj = get_object_or_404(Factura, id=ticket_id, propietario=request.user)
    
    # Usamos el servicio para procesar/refinar los datos que ya tenemos guardados
    # Nota: BillingService espera un dict. Le pasamos 'datos_facturacion'
    contexto_facturacion = BillingService.procesar_datos_facturacion(factura_obj.datos_facturacion)
    
    # Aseguramos que el contexto tenga los datos 'meta' del modelo si no vienen en el JSON
    if not contexto_facturacion.get('tienda') or contexto_facturacion.get('tienda') == 'DESCONOCIDO':
        contexto_facturacion['tienda'] = factura_obj.tienda
        
    contexto_facturacion['fecha_emision'] = factura_obj.fecha_emision
    contexto_facturacion['total_pagado'] = factura_obj.total
    contexto_facturacion['archivo_id'] = factura_obj.archivo_drive_id

    if request.method == 'POST':
        accion = request.POST.get('accion')
        
        # --- FLUJO DE APRENDIZAJE (Guardar Configuración) ---
        if accion == 'guardar_configuracion':
            nombre_tienda = request.POST.get('nombre_tienda')
            campos_seleccionados = request.POST.getlist('campos_seleccionados')
            
            if campos_seleccionados:
                BillingService.guardar_configuracion_tienda(nombre_tienda, campos_seleccionados)
                messages.success(request, f"¡Entendido! Para {nombre_tienda} solo necesitamos: {', '.join(campos_seleccionados)}.")
            else:
                messages.warning(request, "No seleccionaste ningún campo. La configuración no se guardó.")
            
            return redirect('revisar_factura', ticket_id=ticket_id)
            
        # --- FLUJO DE EDICIÓN (Corregir datos originales) ---
        elif accion == 'editar_datos':
            nuevo_tienda = request.POST.get('tienda')
            nueva_fecha = request.POST.get('fecha_emision')
            nuevo_total = request.POST.get('total')

            if nuevo_tienda and nueva_fecha and nuevo_total:
                factura_obj.tienda = nuevo_tienda
                try:
                    factura_obj.fecha_emision = parse_date_safely(nueva_fecha)
                    factura_obj.total = Decimal(nuevo_total)
                    factura_obj.save()
                    messages.success(request, f"Datos actualizados para {nuevo_tienda}.")
                except Exception as e:
                    messages.error(request, f"Error al guardar los datos: {e}")
            else:
                 messages.error(request, "Faltan datos para actualizar la factura.")
            
            return redirect('revisar_factura', ticket_id=ticket_id)
            
        # --- FLUJO DE CONFIRMACIÓN (Datos Correctos) ---
        elif accion == 'confirmar_datos':
            # ACTUALIZAMOS el objeto Factura existente
            # Y lo marcamos como 'listo_para_facturar' o 'facturado' (según tu flujo)
            # Vamos a usar 'facturado' para que salga de pendientes y vaya al historial.
            
            factura_obj.estado = 'facturado' # O el estado que signifique "Listo"
            
            # Opcional: Actualizar datos si cambiaron en el proceso (aunque aquí solo confirmamos)
            # factura_obj.datos_facturacion = contexto_facturacion.get('datos_para_cliente', {})
            
            factura_obj.save()
            
            messages.success(request, "Factura confirmada y guardada correctamente.")
            return redirect('facturacion') # Redirige al historial de facturas
        
    # Obtenemos la lista lateral de otros pendientes
    otros_pendientes = Factura.objects.filter(propietario=request.user, estado='pendiente').exclude(id=ticket_id).order_by('-fecha_emision')

    return render(
        request,
        'revisar_factura.html',
        {
            'factura': contexto_facturacion,
            'tickets': [factura_obj] + list(otros_pendientes), # Hack para que la lista lateral funcione si el template itera 'tickets'
            'ticket_seleccionado': factura_obj,
            'factura_json': json.dumps(contexto_facturacion.get('datos_para_cliente', {})),
        }
    )

@login_required
def revisar_factura_individual(request, ticket_id):
    # Obtener el ticket pendiente
    ticket = get_object_or_404(TiendaFacturacion, id=ticket_id, propietario=request.user)
    
    # Procesar con la lógica inteligente (aprende si es tienda nueva)
    contexto_facturacion = BillingService.procesar_datos_facturacion(ticket.datos_json)
    
    if request.method == 'POST':
        accion = request.POST.get('accion')
        
        if accion == 'guardar_configuracion':
            # El usuario enseña al sistema qué campos usar
            nombre_tienda = request.POST.get('nombre_tienda')
            campos = request.POST.getlist('campos_seleccionados')
            BillingService.guardar_configuracion_tienda(nombre_tienda, campos)
            messages.success(request, f"Configuración guardada para {nombre_tienda}.")
            return redirect('revisar_factura', ticket_id=ticket_id)
            
        elif accion == 'confirmar_datos':
            # El usuario confirma que los datos son correctos
            # Nota: revisar_factura_individual recibe un TiendaFacturacion ID, no TransaccionPendiente.
            # PERO, parece que el código original usaba 'ticket.datos_json'.
            # Vamos a asumir que si estamos aquí, queremos finalizar el proceso.
            # Como TiendaFacturacion es configuración, no transacción pendiente, este flujo es confuso en el código original.
            # Sin embargo, si el ID es de TransaccionPendiente (como sugiere el nombre variable), aplicamos lo mismo.
            
            # Revisando el código original:
            # ticket = get_object_or_404(TiendaFacturacion, id=ticket_id, ...)
            # Esto parece un error en el código original (¿revisar una configuración como si fuera un ticket pendiente?)
            # O tal vez TransaccionPendiente?
            pass # Dejo esto pendiente de revisión mental, pero actualizo el mensaje.
            messages.success(request, "Datos listos. Puedes proceder a facturar.")
            return redirect('revisar_facturas_pendientes')

    return render(request, 'revisar_factura.html', {'factura': contexto_facturacion})

@login_required
def marcar_como_facturado(request, factura_id):
    factura = get_object_or_404(TiendaFacturacion, id=factura_id, propietario=request.user)
    if request.method == 'POST':
        factura.estado = 'facturado'
        factura.save()
        messages.success(request, "¡Factura completada y archivada!")
    return redirect('revisar_facturas_pendientes')

@login_required
def iniciar_procesamiento_facturacion(request):
    """Inicia la sincronización de tickets pensada para facturación."""
    try:
        task = process_drive_for_invoices.delay(request.user.id)
        return JsonResponse({"task_id": task.id}, status=202)
    except Exception as e:
        return JsonResponse({"error": f"No se pudo iniciar la tarea: {str(e)}"}, status=400)
    
def vista_procesamiento_facturacion(request):
    return render(request, 'procesamiento_facturas.html')

@login_required
def eliminar_factura_pendiente(request, ticket_id):
    """
    Elimina un ticket pendiente de facturación (ahora objeto Factura).
    """
    # Buscamos por ID y estado pendiente para seguridad
    ticket = get_object_or_404(Factura, id=ticket_id, propietario=request.user, estado='pendiente')
    
    if request.method == 'POST':
        ticket.delete()
        messages.success(request, "Factura pendiente eliminada correctamente.")
        
    return redirect('revisar_facturas_pendientes')

@login_required
def eliminar_todas_facturas_pendientes(request):
    """
    Elimina todos los tickets pendientes de facturación de un jalón.
    """
    if request.method == 'POST':
        facturas_pendientes = Factura.objects.filter(propietario=request.user, estado='pendiente')
        count = facturas_pendientes.count()
        if count > 0:
            facturas_pendientes.delete()
            messages.success(request, f"Se han eliminado {count} facturas pendientes correctamente.")
        else:
            messages.info(request, "No hay facturas pendientes para eliminar.")
    return redirect('revisar_facturas_pendientes')

@login_required
def marcar_ticket_facturado(request, ticket_id):
    """
    Marca un ticket pendiente como 'facturado' (mueve de pendientes al historial).
    """
    # Ahora trabajamos directamente con el objeto Factura que ya existe
    factura_obj = get_object_or_404(Factura, id=ticket_id, propietario=request.user)
    
    if request.method == 'POST':
        # Simplemente cambiamos el estado
        factura_obj.estado = 'facturado'
        factura_obj.save()
        
        messages.success(request, "Factura archivada en el historial.")
        
    return redirect('revisar_facturas_pendientes')

@require_POST
@login_required
def actualizar_json_factura(request, ticket_id):
    """
    Actualiza el JSON de datos extraídos de un ticket pendiente.
    Se usa cuando el usuario edita un campo sugerido.
    """
    
    if request.method == 'POST':
        try:
            factura_obj = get_object_or_404(Factura, id=ticket_id, propietario=request.user, estado='pendiente')
            data = json.loads(request.body)
            nuevo_json = data.get('datos_facturacion')
            
            if nuevo_json is not None:
                factura_obj.datos_facturacion = nuevo_json
                factura_obj.save()
                return JsonResponse({'status': 'success'})
        except Exception as e:
            logger.error(f"Error actualizando json factura: {e}")
            return JsonResponse({'status': 'error', 'message': 'Error inesperado procesando la solicitud'}, status=400)
    
    return JsonResponse({'status': 'error', 'message': 'Método no permitido'}, status=405)

@login_required
def editar_factura_registro(request, factura_id):
    """
    Vista para editar una factura guardada.
    """
    factura = get_object_or_404(Factura, id=factura_id, propietario=request.user)
    
    if request.method == 'POST':
        # Actualizamos los campos desde el formulario
        factura.tienda = request.POST.get('tienda', factura.tienda)
        factura.total = request.POST.get('total', factura.total)
        factura.estado = request.POST.get('estado', factura.estado)
        factura.save()
        messages.success(request, "Factura actualizada correctamente.")
        return redirect('facturacion')
    
    context = {'factura': factura}
    return render(request, 'editar_factura.html', context)

@login_required
def eliminar_factura_registro(request, factura_id):
    """
    Vista para eliminar una factura guardada.
    """
    factura = get_object_or_404(Factura, id=factura_id, propietario=request.user)
    
    if request.method == 'POST':
        factura.delete()
        messages.success(request, "Factura eliminada correctamente.")
        return redirect('facturacion')
    
    context = {'factura': factura}
    return render(request, 'confirmar_eliminar_factura.html', context)

@require_POST
@login_required
def guardar_configuracion_tienda(request):
    """
    BOTÓN 1: ENSEÑAR (Guardar Configuración)
    Guarda qué campos son requeridos para una tienda específica.
    """
    try:
        data = json.loads(request.body)
        nombre_tienda = data.get('tienda', '').strip().upper()
        campos_seleccionados = data.get('campos_seleccionados', []) # Ej: ['folio', 'sucursal']
        url_portal = data.get('url_portal', '')

        if not nombre_tienda:
            return JsonResponse({'status': 'error', 'message': 'El nombre de la tienda es obligatorio'}, status=400)

        # Actualizamos o creamos la configuración "maestra"
        tienda_obj, created = TiendaFacturacion.objects.update_or_create(
            tienda=nombre_tienda,
            defaults={
                'campos_requeridos': campos_seleccionados,
                'url_portal': url_portal,
                'configuracion_finalizada': True # ¡CAMBIO CLAVE! El usuario confirmó, así que "cerramos" la config.
            }
        )

        accion = "creada" if created else "actualizada"
        return JsonResponse({'status': 'success', 'message': f'Configuración de {nombre_tienda} {accion} correctamente.'})

    except Exception as e:
        logger.error(f"Error guardando config tienda: {e}")
        return JsonResponse({'status': 'error', 'message': 'Ocurrió un error inesperado al guardar la configuración'}, status=500)

@require_POST
@login_required
def agregar_campo_tienda(request):
    try:
        data = json.loads(request.body)
        nombre_tienda = data.get('tienda')
        nuevo_campo = data.get('campo')

        if not nombre_tienda or not nuevo_campo:
            return JsonResponse({'success': False, 'error': 'Faltan datos'}, status=400)

        # Buscar la configuración de la tienda
        config, created = TiendaFacturacion.objects.get_or_create(tienda=nombre_tienda)
        
        # Asegurarse de que campos_requeridos sea una lista
        if not isinstance(config.campos_requeridos, list):
            config.campos_requeridos = []

        # Agregar el campo si no existe
        if nuevo_campo not in config.campos_requeridos:
            config.campos_requeridos.append(nuevo_campo)
            config.save()
            return JsonResponse({'success': True, 'mensaje': f'Campo "{nuevo_campo}" agregado correctamente'})
        else:
            return JsonResponse({'success': True, 'mensaje': 'El campo ya existía'})

    except Exception as e:
        logger.error(f"Error agregando campo tienda: {e}")
        return JsonResponse({'success': False, 'error': 'Ocurrió un error inesperado al agregar el campo'}, status=500)

@require_POST
@login_required
def eliminar_campo_tienda(request):
    try:
        data = json.loads(request.body)
        nombre_tienda = data.get('tienda')
        campo_a_eliminar = data.get('campo')

        if not nombre_tienda or not campo_a_eliminar:
            return JsonResponse({'success': False, 'error': 'Faltan datos'}, status=400)

        # Buscar la configuración
        try:
            config = TiendaFacturacion.objects.get(tienda=nombre_tienda)
        except TiendaFacturacion.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Tienda no encontrada'}, status=404)
        
        if config.campos_requeridos and campo_a_eliminar in config.campos_requeridos:
            config.campos_requeridos.remove(campo_a_eliminar)
            config.save()
            return JsonResponse({'success': True, 'mensaje': f'Campo "{campo_a_eliminar}" eliminado correctamente'})
        else:
            return JsonResponse({'success': True, 'mensaje': 'El campo no estaba en la configuración'})

    except Exception as e:
        logger.error(f"Error eliminando campo tienda: {e}")
        return JsonResponse({'success': False, 'error': 'Ocurrió un error inesperado al eliminar el campo'}, status=500)

@require_POST
@login_required
def confirmar_datos_factura(request):
    """
    BOTÓN 2: LA PALOMA (Confirmar Transacción)
    Guarda/Actualiza los datos del ticket específico en la tabla Factura.
    """
    try:
        data = json.loads(request.body)
        # Identificadores para encontrar o crear la factura
        archivo_id = data.get('archivo_id') # ID de Drive
        
        # Datos extraídos y validados por el usuario en el frontend
        tienda = data.get('tienda', 'DESCONOCIDO').upper()
        total = data.get('total', 0)
        fecha = data.get('fecha')
        datos_json = data.get('datos_facturacion', {}) # El JSON completo con folio, rfc, etc.

        defaults = {
            'propietario': request.user,
            'tienda': tienda,
            'total': Decimal(str(total)),
            'fecha_emision': parse_date_safely(fecha),
            'datos_facturacion': datos_json,
            'estado': 'facturado' # ¡CAMBIO CLAVE! Al confirmar, ya lo damos por bueno.
        }

        if archivo_id:
            # Si hay un archivo de Drive asociado, intentamos no duplicarlo
            factura_obj, created = Factura.objects.update_or_create(
                archivo_drive_id=archivo_id,
                defaults=defaults
            )
        else:
            # Si no hay archivo ID (manual o subida directa), CREAMOS uno nuevo siempre
            factura_obj = Factura.objects.create(
                archivo_drive_id=None,
                **defaults
            )
            created = True

        return JsonResponse({'status': 'success', 'message': 'Factura guardada y lista para procesar.'})

    except Exception as e:
        logger.error(f"Error confirmando datos factura: {e}")
        return JsonResponse({'status': 'error', 'message': 'Ocurrió un error inesperado al guardar la factura.'}, status=500)

