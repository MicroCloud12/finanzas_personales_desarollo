import json
import logging
from datetime import datetime

from django.contrib import messages
from django.db.models import Q
from django.http import JsonResponse
from django.urls import reverse
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404

from celery.result import AsyncResult, GroupResult
from config.celery import app as celery_app

from ..utils import parse_date_safely
from ..importacion import (a_sesion, aplicar_alias, aprender_alias, coincidencias, completar_desde_historial,
                           de_sesion, decodificar, importar, leer_csv)
from ..categorias import Sugeridor, categorias_para, clasificar_ticket, monto_de_ticket
from ..tasks import (
    process_drive_tickets, olvidar_lote,
)
from ..forms import (
    TransaccionesForm
)
from ..services import (
    TransactionService
)
from ..models import (
    registro_transacciones, Suscripcion, TransaccionPendiente, 
    PendingInvestment, AmortizacionPendiente, Factura, Cuenta
)
from .. import planes

logger = logging.getLogger(__name__)

def _aprobar(request, ticket_id):
    """Aprueba un ticket con los campos de SU fila del formulario (sufijo _<id>)."""
    campo = lambda nombre, default=None: request.POST.get(f'{nombre}_{ticket_id}', default)
    return TransactionService.approve_pending_transaction(
        ticket_id=ticket_id,
        user=request.user,
        cuenta=campo('cuenta_origen'),
        categoria=campo('categoria'),
        tipo_transaccion=campo('tipo', 'GASTO'),
        cuenta_destino=campo('cuenta_destino'),
        monto=campo('monto', '').strip(),
    )

@login_required
def aprobar_todos_tickets(request):
    """Aprueba todos los tickets pendientes, cada uno con lo elegido en su fila."""
    if request.method == 'POST':
        aprobados = omitidos = 0
        for ticket in TransaccionPendiente.objects.filter(propietario=request.user, estado='pendiente'):
            monto = request.POST.get(f'monto_{ticket.id}', '').strip()
            if clasificar_ticket(ticket.datos_json) != 'MOVIMIENTO' and not monto:
                omitidos += 1   # sin monto no hay nada que registrar
            elif _aprobar(request, ticket.id) is not None:
                aprobados += 1
            else:
                omitidos += 1

        if aprobados:
            messages.success(request, f"{aprobados} tickets han sido aprobados correctamente.")
        elif not omitidos:
            messages.warning(request, "No se seleccionaron tickets para aprobar o faltaron datos.")
        if omitidos:
            messages.info(request, f"{omitidos} ticket(s) sin monto se dejaron pendientes: escribe el monto en la fila o recházalos.")

    return redirect('revisar_tickets')

@login_required
def rechazar_todos_tickets(request):
    if request.method == 'POST':
        TransaccionPendiente.objects.filter(propietario=request.user, estado='pendiente').update(estado='rechazada')
    return redirect('revisar_tickets')

@login_required
def aprobar_ticket(request, ticket_id):
    """Aprueba un SOLO ticket tomando sus campos del formulario grande."""
    if request.method == 'POST':
        if _aprobar(request, ticket_id) is None:
            messages.warning(request, "Ese ticket no tiene monto: escríbelo en la fila para poder registrarlo.")
        else:
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
    context = {'form': form, 'categorias': categorias_para(request.user)}
    return render(request, 'transacciones.html', context)

@login_required
def lista_transacciones(request):
    es_usuario_premium = planes.puede_procesar(request.user)   # le quedan documentos con IA este mes
    current_year = datetime.now().year
    current_month = datetime.now().month
    year = int(request.GET.get('year', current_year))
    month = int(request.GET.get('month', current_month))
    transacciones_del_mes = registro_transacciones.objects.filter(
        propietario=request.user,
        fecha__year=year,
        fecha__month=month
    ).select_related('origen', 'destino').order_by('-fecha', '-id')

    # Filtro por cuenta/tarjeta: un movimiento "es" de la cuenta si sale de ella o entra a ella.
    cuentas = Cuenta.objects.filter(propietario=request.user).order_by('-es_principal', 'tipo', 'nombre')
    cuenta_id = request.GET.get('cuenta', '')
    cuenta_sel = cuentas.filter(id=int(cuenta_id)).first() if cuenta_id.isdigit() else None
    if cuenta_sel is not None:
        transacciones_del_mes = transacciones_del_mes.filter(Q(origen=cuenta_sel) | Q(destino=cuenta_sel))

    context = {
        'transacciones': transacciones_del_mes,
        'es_usuario_premium': es_usuario_premium, # <-- Añadir la variable al contexto
        'selected_year': year,
        'selected_month': month,
        'years': range(current_year, current_year - 5, -1),
        'months': range(1, 13),
        'cuentas': cuentas,
        'cuenta_sel': cuenta_sel,
    }
    return render(request, 'lista_transacciones.html', context)

def _convertible(fila, igual, nombres):
    """La fila es una transferencia X -> Y (Y es cuenta tuya) y lo que ya tienes es un gasto, o una
    transferencia a otro lado, que sale de X: en vez de guardar la fila se puede convertir el registrado
    en transferencia a Y. Pasa cuando el banco de X no dijo a dónde iba el dinero (SPEI con concepto libre)."""
    if igual is None or fila['tipo'] != 'TRANSFERENCIA' or igual['tipo'] not in ('GASTO', 'TRANSFERENCIA'):
        return False
    destino = fila['destino'].strip().upper()
    return (destino in nombres and igual['cuenta'].strip().upper() == fila['origen'].strip().upper()
            and igual['destino'].strip().upper() != destino)


def _convertir_en_transferencias(usuario, filas, ids, indices):
    """Convierte los movimientos ya registrados (ids[i]) en transferencias al destino de la fila i.
    Devuelve {nombre de cuenta destino: cuántos}."""
    cuentas = {c.nombre.strip().upper(): c for c in Cuenta.objects.filter(propietario=usuario)}
    convertidos = {}
    for i in indices:
        if i >= len(filas) or not ids[i]:
            continue
        destino = cuentas.get(filas[i]['destino'].strip().upper())
        t = registro_transacciones.objects.filter(propietario=usuario, id=ids[i]).first()
        if destino is None or t is None:
            continue
        t.tipo, t.destino, t.categoria, t.cuenta_destino = 'TRANSFERENCIA', destino, 'Transferencia', destino.nombre
        t.save()
        convertidos[destino.nombre] = convertidos.get(destino.nombre, 0) + 1
    return convertidos


@require_POST
@login_required
def subir_csv(request):
    """Botón "Subir CSV": lee el archivo (export de Santander o formato propio), busca qué movimientos
    ya están registrados y muestra la lista para revisar antes de guardar nada."""
    archivo = request.FILES.get('archivo')
    if not archivo:
        messages.error(request, "Elige un archivo .csv.")
        return redirect('lista_transacciones')
    try:
        filas, es_santander = leer_csv(decodificar(archivo.read()))
    except (ValueError, UnicodeDecodeError) as e:
        messages.error(request, f"No pude leer {archivo.name}: {e}. No se guardó nada.")
        return redirect('lista_transacciones')
    if not filas:
        messages.warning(request, f"{archivo.name} no trae movimientos.")
        return redirect('lista_transacciones')

    # Primero lo que tú ya corregiste otras veces (alias); luego, para lo que el archivo no reconoció,
    # tu historial de movimientos con esa misma descripción.
    completar_desde_historial(request.user, aplicar_alias(request.user, filas))

    iguales = coincidencias(request.user, filas)
    nombres = {c.nombre.strip().upper() for c in Cuenta.objects.filter(propietario=request.user)}
    renglones = [{'i': i, 'fila': f, 'igual': c, 'marcar': c is None, 'ajustable': _convertible(f, c, nombres)}
                 for i, (f, c) in enumerate(zip(filas, iguales))]
    request.session['csv_pendiente'] = {'nombre': archivo.name, 'filas': a_sesion(filas),
                                        'iguales': [c['id'] if c else None for c in iguales]}
    return render(request, 'subir_csv_revisar.html', {
        'nombre': archivo.name, 'es_santander': es_santander, 'renglones': renglones,
        'categorias': categorias_para(request.user),
        'nuevos': sum(1 for r in renglones if r['igual'] is None),
        'repetidos': sum(1 for r in renglones if r['igual'] is not None),
        'por_revisar': sum(1 for f in filas if f['nota']),
    })

@require_POST
@login_required
def confirmar_csv(request):
    """Guarda solo los renglones que el usuario dejó marcados en la pantalla de revisión."""
    pendiente = request.session.pop('csv_pendiente', None)
    if not pendiente:
        messages.error(request, "No hay un archivo pendiente; vuelve a subirlo.")
        return redirect('lista_transacciones')
    filas = de_sesion(pendiente['filas'])
    elegidas = {int(i) for i in request.POST.getlist('fila') if i.isdigit()}
    # "Convertir el que ya tienes en transferencia a Y": se corrige el registrado y la fila no se guarda.
    ajustar = {int(i) for i in request.POST.getlist('ajustar') if i.isdigit()}
    convertidos = _convertir_en_transferencias(request.user, filas, pendiente.get('iguales') or [], sorted(ajustar))
    elegidas -= ajustar
    # Lo que corrigió en pantalla (descripción / categoría) se aplica y se aprende para la próxima vez.
    aprendidos = set()
    for i, f in enumerate(filas):
        desc = request.POST.get(f'desc_{i}', f['descripcion'])
        cat = request.POST.get(f'cat_{i}', f['categoria'])
        if i in elegidas and aprender_alias(request.user, f, desc, cat):
            aprendidos.add(f['banco'].upper())
        f['descripcion'], f['categoria'] = desc.strip()[:100] or f['descripcion'], cat.strip()[:100] or f['categoria']
    filas = [f for i, f in enumerate(filas) if i in elegidas]
    for nombre, n in convertidos.items():
        messages.success(request, f"{n} movimiento{'s' if n > 1 else ''} que ya tenías ahora "
                                  f"{'son transferencias' if n > 1 else 'es transferencia'} a {nombre}.")
    if not filas:
        if not convertidos:
            messages.warning(request, "No marcaste ningún movimiento; no se guardó nada.")
        return redirect('lista_transacciones')

    r = importar(request.user, filas)   # siempre al usuario conectado, diga lo que diga la columna Usuario
    texto = f"{pendiente['nombre']}: {r['insertados']} movimientos guardados"
    if r['omitidos']:
        texto += f", {r['omitidos']} ya estaban"
    if aprendidos:
        texto += f". Aprendí {len(aprendidos)} nombre{'s' if len(aprendidos) > 1 else ''} para la próxima vez"
    messages.success(request, texto + ".")
    for nombre, n in r['sin_cuenta'].items():
        messages.warning(request, f"La cuenta '{nombre}' ({n} movimientos) no existe en Mis Tarjetas: quedaron sin cuenta. "
                                  "Dala de alta y vuelve a subir el archivo, o edítalos uno por uno.")
    ultima = max(f['fecha'] for f in filas)
    return redirect(f"{reverse('lista_transacciones')}?year={ultima.year}&month={ultima.month}")


@login_required
def descargar_csv(request):
    """Botón "Descargar CSV": los movimientos que se ven en la lista (mes y cuenta elegidos; todos los meses
    con ?todo=1) en el formato propio que acepta "Subir CSV", más una columna Id al final que al subir se ignora."""
    import csv
    from django.http import HttpResponse
    from django.utils.text import slugify

    movimientos = (registro_transacciones.objects.filter(propietario=request.user)
                   .select_related('origen', 'destino').order_by('fecha', 'id'))
    nombre = 'movimientos'
    if request.GET.get('todo') != '1':
        year = int(request.GET.get('year', datetime.now().year))
        month = int(request.GET.get('month', datetime.now().month))
        movimientos = movimientos.filter(fecha__year=year, fecha__month=month)
        nombre += f'_{year}-{month:02d}'
    cuenta_id = request.GET.get('cuenta', '')
    cuenta = Cuenta.objects.filter(propietario=request.user, id=int(cuenta_id)).first() if cuenta_id.isdigit() else None
    if cuenta is not None:
        movimientos = movimientos.filter(Q(origen=cuenta) | Q(destino=cuenta))
        nombre += '_' + slugify(cuenta.nombre)

    respuesta = HttpResponse(content_type='text/csv; charset=utf-8')
    respuesta['Content-Disposition'] = f'attachment; filename="{nombre}.csv"'
    respuesta.write('﻿')  # BOM: así Excel abre bien los acentos
    escritor = csv.writer(respuesta, delimiter=';')
    escritor.writerow(['Usuario', 'Fecha', 'Descripcion', 'Categoria', 'Monto', 'Tipo',
                       'Cuenta de origen', 'Cuenta de destino', 'Nota', 'Id'])
    tipos = {'GASTO': 'gasto', 'INGRESO': 'ingreso'}
    for t in movimientos:
        nota = '' if t.tipo in ('GASTO', 'INGRESO', 'TRANSFERENCIA') else t.get_tipo_display()  # pago de mensualidad / a capital
        if t.monto_interes:
            nota += f' (interés {t.monto_interes:.2f})'
        escritor.writerow([request.user.username, t.fecha.strftime('%d/%m/%Y'), t.descripcion, t.categoria,
                           f'{t.monto:.2f}', tipos.get(t.tipo, 'transferencia'),
                           t.origen.nombre if t.origen else t.cuenta_origen,
                           t.destino.nombre if t.destino else t.cuenta_destino, nota, t.id])
    return respuesta

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
    
    return render(request, 'transacciones.html', {'form': form, 'categorias': categorias_para(request.user)})

@login_required
@require_POST
def eliminar_transaccion(request, transaccion_id):
    get_object_or_404(registro_transacciones, id=transaccion_id, propietario=request.user).delete()
    return redirect('lista_transacciones')

@login_required
def revisar_tickets(request):
    """
    Revisión de tickets "en un clic": cada fila llega pre-llenada con la mejor
    sugerencia (IA -> historial del usuario -> cuenta principal).
    """
    tickets_pendientes = TransaccionPendiente.objects.filter(propietario=request.user, estado='pendiente')
    sugeridor = Sugeridor(request.user)

    for ticket in tickets_pendientes:
        fecha_cruda = ticket.datos_json.get("fecha") or ticket.datos_json.get("fecha_emision")
        fecha_obj = parse_date_safely(fecha_cruda)
        ticket.fecha_formateada = fecha_obj.strftime("%d/%m/%Y")
        ticket.sug = sugeridor.sugerir(ticket.datos_json)
        ticket.clase = clasificar_ticket(ticket.datos_json)   # MOVIMIENTO o SIN_MONTO (monto editable)
        ticket.monto = monto_de_ticket(ticket.datos_json)

    return render(request, 'revisar_tickets.html', {
        'tickets': tickets_pendientes,
        'cuentas_usuario': sugeridor.cuentas,
        'categorias': categorias_para(request.user),
        'cuenta_principal': sugeridor.principal,
        'tiene_cuenta_ahorro': any(c.tipo == 'AHORRO' for c in sugeridor.cuentas),
    })

@login_required
def rechazar_ticket(request, ticket_id):
    TransaccionPendiente.objects.filter(id=ticket_id, propietario=request.user).update(estado='rechazada')
    return redirect('revisar_tickets')

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

@login_required
def vista_procesamiento_automatico(request):
    return render(request, 'procesamiento.html', {
        'titulo': 'Procesamiento Automático',
        'subtitulo': 'Sincroniza tus tickets desde Google Drive',
        'icono': 'M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15',
        'descripcion': 'Buscaremos nuevos archivos en tu carpeta designada.',
        'start_url': reverse('procesar_drive'),
        'redirect_url': reverse('revisar_tickets'),
        'back_url': reverse('lista_transacciones'),
        'back_text': 'Volver a Transacciones',
    })

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
            # Terminó, pero no todo fue éxito necesariamente: la pantalla avisa cuántos fallaron.
            fallidos = sum(1 for r in group_result.results if r.failed())
            return JsonResponse({"status": "COMPLETED", "total": len(group_result), "fallidos": fallidos})
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
            olvidar_lote(group_id)  # el siguiente clic lanza un lote nuevo en vez de pegarse a este

        # Rechazar los registros que pudieron haberse creado parcialmente antes de cancelar
        if cancel_type == 'tickets':
            TransaccionPendiente.objects.filter(propietario=request.user, estado='pendiente').update(estado='rechazada')
        elif cancel_type == 'inversiones':
            PendingInvestment.objects.filter(propietario=request.user, estado='pendiente').update(estado='rechazada')
        elif cancel_type == 'deudas':
            AmortizacionPendiente.objects.filter(deuda__propietario=request.user, estado='pendiente').update(estado='rechazada')
        elif cancel_type == 'facturas':
            Factura.objects.filter(propietario=request.user, estado='pendiente').update(estado='rechazada')

        return JsonResponse({'status': 'success', 'message': 'Procesamiento cancelado exitosamente.'})
    except Exception as e:
        logger.error(f"Error al cancelar procesamiento: {e}")
        return JsonResponse({'status': 'error', 'message': 'Ocurrió un error inesperado al cancelar'}, status=500)
