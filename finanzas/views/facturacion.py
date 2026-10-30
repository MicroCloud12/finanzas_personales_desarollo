import json
import logging
from decimal import Decimal

from django.contrib import messages
from django.http import JsonResponse
from django.urls import reverse
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404


from ..utils import parse_date_safely
from ..tasks import (
    process_drive_for_invoices,
)
from ..services import (
    BillingService
)
from ..models import (
    Suscripcion, Factura, TiendaFacturacion
)

logger = logging.getLogger(__name__)

@login_required
def facturacion(request):
    """
    Muestra el historial de facturas registradas.
    """
    suscripcion, created = Suscripcion.objects.get_or_create(usuario=request.user)
    facturas = Factura.objects.filter(propietario=request.user, estado='facturado').order_by('-fecha_emision')

    context = {
        'facturas': facturas,
        'es_usuario_premium': suscripcion.is_active()
    }
    return render(request, 'lista_facturacion.html', context)

@login_required
def revisar_facturas_pendientes(request):
    """Lista los tickets pendientes para facturación."""
    facturas_pendientes = Factura.objects.filter(propietario=request.user, estado='pendiente').order_by('-fecha_emision')
    return render(request, 'revisar_factura.html', {'tickets': facturas_pendientes})

@login_required
def revisar_factura_detalle(request, ticket_id):
    """Muestra los datos de facturación de un ticket concreto y permite corregir tienda/fecha/total."""
    factura_obj = get_object_or_404(Factura, id=ticket_id, propietario=request.user)

    if request.method == 'POST' and request.POST.get('accion') == 'editar_datos':
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

    # Guardar configuración y confirmar se hacen por JSON (ver procesamiento.js).
    contexto_facturacion = BillingService.procesar_datos_facturacion(factura_obj.datos_facturacion)
    if not contexto_facturacion.get('tienda') or contexto_facturacion.get('tienda') == 'DESCONOCIDO':
        contexto_facturacion['tienda'] = factura_obj.tienda
    contexto_facturacion['fecha_emision'] = factura_obj.fecha_emision
    contexto_facturacion['total_pagado'] = factura_obj.total
    contexto_facturacion['archivo_id'] = factura_obj.archivo_drive_id

    otros_pendientes = Factura.objects.filter(propietario=request.user, estado='pendiente').exclude(id=ticket_id).order_by('-fecha_emision')

    return render(
        request,
        'revisar_factura.html',
        {
            'factura': contexto_facturacion,
            'tickets': [factura_obj] + list(otros_pendientes),
            'ticket_seleccionado': factura_obj,
            'factura_json': json.dumps(contexto_facturacion.get('datos_para_cliente', {})),
        }
    )

@login_required
def iniciar_procesamiento_facturacion(request):
    """Inicia la sincronización de tickets pensada para facturación."""
    try:
        task = process_drive_for_invoices.delay(request.user.id)
        return JsonResponse({"task_id": task.id}, status=202)
    except Exception as e:
        return JsonResponse({"error": f"No se pudo iniciar la tarea: {str(e)}"}, status=400)

@login_required
def vista_procesamiento_facturacion(request):
    return render(request, 'procesamiento.html', {
        'titulo': 'Sincronización de Facturas',
        'subtitulo': 'Extrae datos fiscales (CFDI) de tus tickets',
        'icono': 'M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z',
        'paso2': 'Procesar',
        'descripcion': 'Buscaremos tickets en tu carpeta para extraer folios y datos fiscales.',
        'start_url': reverse('procesar_drive_facturacion'),
        'redirect_url': reverse('revisar_facturas_pendientes'),
    })

@login_required
def eliminar_factura_pendiente(request, ticket_id):
    """Elimina un ticket pendiente de facturación."""
    ticket = get_object_or_404(Factura, id=ticket_id, propietario=request.user, estado='pendiente')
    if request.method == 'POST':
        ticket.delete()
        messages.success(request, "Factura pendiente eliminada correctamente.")
    return redirect('revisar_facturas_pendientes')

@login_required
def eliminar_todas_facturas_pendientes(request):
    """Elimina todos los tickets pendientes de facturación de un jalón."""
    if request.method == 'POST':
        count, _ = Factura.objects.filter(propietario=request.user, estado='pendiente').delete()
        if count:
            messages.success(request, f"Se han eliminado {count} facturas pendientes correctamente.")
        else:
            messages.info(request, "No hay facturas pendientes para eliminar.")
    return redirect('revisar_facturas_pendientes')

@login_required
def marcar_ticket_facturado(request, ticket_id):
    """Marca un ticket pendiente como 'facturado' (mueve de pendientes al historial)."""
    factura_obj = get_object_or_404(Factura, id=ticket_id, propietario=request.user)
    if request.method == 'POST':
        factura_obj.estado = 'facturado'
        factura_obj.save()
        messages.success(request, "Factura archivada en el historial.")
    return redirect('revisar_facturas_pendientes')

@require_POST
@login_required
def actualizar_json_factura(request, ticket_id):
    """Actualiza el JSON de datos extraídos de un ticket pendiente (cuando el usuario edita un campo)."""
    factura_obj = get_object_or_404(Factura, id=ticket_id, propietario=request.user, estado='pendiente')
    try:
        nuevo_json = json.loads(request.body).get('datos_facturacion')
    except (json.JSONDecodeError, AttributeError):
        return JsonResponse({'status': 'error', 'message': 'JSON inválido'}, status=400)
    if nuevo_json is None:
        return JsonResponse({'status': 'error', 'message': 'Falta datos_facturacion'}, status=400)
    factura_obj.datos_facturacion = nuevo_json
    factura_obj.save()
    return JsonResponse({'status': 'success'})

@login_required
def editar_factura_registro(request, factura_id):
    """Vista para editar una factura guardada."""
    factura = get_object_or_404(Factura, id=factura_id, propietario=request.user)

    if request.method == 'POST':
        factura.tienda = request.POST.get('tienda', factura.tienda)
        factura.total = request.POST.get('total', factura.total)
        factura.estado = request.POST.get('estado', factura.estado)
        factura.save()
        messages.success(request, "Factura actualizada correctamente.")
        return redirect('facturacion')

    return render(request, 'editar_factura.html', {'factura': factura})

@login_required
@require_POST
def eliminar_factura_registro(request, factura_id):
    get_object_or_404(Factura, id=factura_id, propietario=request.user).delete()
    messages.success(request, "Factura eliminada correctamente.")
    return redirect('facturacion')

@require_POST
@login_required
def guardar_configuracion_tienda(request):
    """Guarda qué campos son requeridos para una tienda específica."""
    try:
        data = json.loads(request.body)
        nombre_tienda = data.get('tienda', '').strip().upper()
        if not nombre_tienda:
            return JsonResponse({'status': 'error', 'message': 'El nombre de la tienda es obligatorio'}, status=400)

        _, created = TiendaFacturacion.objects.update_or_create(
            tienda=nombre_tienda,
            defaults={
                'campos_requeridos': data.get('campos_seleccionados', []),
                'url_portal': data.get('url_portal', ''),
                'configuracion_finalizada': True,  # el usuario confirmó: se "cierra" la configuración
            }
        )
        accion = "creada" if created else "actualizada"
        return JsonResponse({'status': 'success', 'message': f'Configuración de {nombre_tienda} {accion} correctamente.'})
    except Exception as e:
        logger.error(f"Error guardando config tienda: {e}")
        return JsonResponse({'status': 'error', 'message': 'Ocurrió un error inesperado al guardar la configuración'}, status=500)

def _tienda_y_campo(request):
    data = json.loads(request.body)
    return data.get('tienda'), data.get('campo')

@require_POST
@login_required
def agregar_campo_tienda(request):
    try:
        nombre_tienda, nuevo_campo = _tienda_y_campo(request)
        if not nombre_tienda or not nuevo_campo:
            return JsonResponse({'success': False, 'error': 'Faltan datos'}, status=400)

        config, _ = TiendaFacturacion.objects.get_or_create(tienda=nombre_tienda)
        if not isinstance(config.campos_requeridos, list):
            config.campos_requeridos = []
        if nuevo_campo in config.campos_requeridos:
            return JsonResponse({'success': True, 'mensaje': 'El campo ya existía'})
        config.campos_requeridos.append(nuevo_campo)
        config.save()
        return JsonResponse({'success': True, 'mensaje': f'Campo "{nuevo_campo}" agregado correctamente'})
    except Exception as e:
        logger.error(f"Error agregando campo tienda: {e}")
        return JsonResponse({'success': False, 'error': 'Ocurrió un error inesperado al agregar el campo'}, status=500)

@require_POST
@login_required
def eliminar_campo_tienda(request):
    try:
        nombre_tienda, campo = _tienda_y_campo(request)
        if not nombre_tienda or not campo:
            return JsonResponse({'success': False, 'error': 'Faltan datos'}, status=400)

        config = TiendaFacturacion.objects.filter(tienda=nombre_tienda).first()
        if config is None:
            return JsonResponse({'success': False, 'error': 'Tienda no encontrada'}, status=404)
        if campo not in (config.campos_requeridos or []):
            return JsonResponse({'success': True, 'mensaje': 'El campo no estaba en la configuración'})
        config.campos_requeridos.remove(campo)
        config.save()
        return JsonResponse({'success': True, 'mensaje': f'Campo "{campo}" eliminado correctamente'})
    except Exception as e:
        logger.error(f"Error eliminando campo tienda: {e}")
        return JsonResponse({'success': False, 'error': 'Ocurrió un error inesperado al eliminar el campo'}, status=500)

@require_POST
@login_required
def confirmar_datos_factura(request):
    """Guarda/actualiza los datos confirmados de un ticket en la tabla Factura y la marca como facturada."""
    try:
        data = json.loads(request.body)
        archivo_id = data.get('archivo_id')  # ID de Drive
        defaults = {
            'tienda': data.get('tienda', 'DESCONOCIDO').upper(),
            'total': Decimal(str(data.get('total', 0))),
            'fecha_emision': parse_date_safely(data.get('fecha')),
            'datos_facturacion': data.get('datos_facturacion', {}),
            'estado': 'facturado',
        }
        if archivo_id:
            # Mismo archivo de Drive = misma factura (y solo dentro de las del usuario)
            Factura.objects.update_or_create(propietario=request.user, archivo_drive_id=archivo_id, defaults=defaults)
        else:
            Factura.objects.create(propietario=request.user, archivo_drive_id=None, **defaults)
        return JsonResponse({'status': 'success', 'message': 'Factura guardada y lista para procesar.'})
    except Exception as e:
        logger.error(f"Error confirmando datos factura: {e}")
        return JsonResponse({'status': 'error', 'message': 'Ocurrió un error inesperado al guardar la factura.'}, status=500)
