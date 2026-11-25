import calendar
import logging
import re
import unicodedata
from datetime import date, timedelta

from django.utils import timezone
from django.contrib import messages
from django.http import JsonResponse
from django.urls import reverse
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST

from ..forms import PresupuestoForm
from ..services import GoogleDriveService
from ..tasks import process_drive_utility_bills, carpeta_recibos
from ..models import Presupuesto, HistorialReciboServicio, registro_transacciones, proximo_dia_del_mes
from ..services.prediccion import (Recibo, Prediccion, cadencia_dias, proxima_fecha, estimar_monto,  # noqa: F401
                                   proximo_pago, prediccion_variable, mes_siguiente, nombre_mes, dia_del_mes,
                                   DIAS_PARA_PAGAR)

logger = logging.getLogger(__name__)
DIAS_QUINCENA = (13, 28)   # días en que cae la nómina; el plan de apartado va de una nómina a la siguiente
DIAS_POR_QUINCENA = 15


def _vence(recibo):
    """Fecha límite de pago del recibo: la que leyó la IA o, si no venía, emisión + DIAS_PARA_PAGAR."""
    texto = (recibo.datos_json or {}).get('fecha_limite_pago')
    try:
        if texto:
            return date.fromisoformat(str(texto)[:10])
    except ValueError:
        pass
    return recibo.fecha_emision + timedelta(days=DIAS_PARA_PAGAR) if recibo.fecha_emision else None


def recibos_de(presupuesto):
    """Historial de recibos procesados como `Recibo`s, del más viejo al más nuevo."""
    historial = presupuesto.historial_recibos.order_by('fecha_emision', 'id')
    return [Recibo(h.fecha_emision, _vence(h), float(h.monto_total)) for h in historial]


def _plano(texto):
    """minúsculas y sin acentos, para comparar nombres ('Teléfono' == 'telefono')."""
    return unicodedata.normalize('NFKD', texto or '').encode('ascii', 'ignore').decode().lower()


def recibos_del_libro(presupuesto, hoy):
    """Respaldo cuando no hay recibos procesados: los gastos de los últimos 13 meses cuya descripción o
    categoría mencionen el concepto como palabra completa ('gas' agarra 'GAS', no 'GASOLINA')."""
    nombre = _plano(presupuesto.categoria).strip()
    if not nombre:
        return []
    patron = re.compile(r'\b' + re.escape(nombre) + r'\b')
    movimientos = (registro_transacciones.objects
                   .filter(propietario=presupuesto.propietario, tipo='GASTO',
                           fecha__gte=hoy - timedelta(days=400), fecha__lte=hoy)
                   .order_by('fecha', 'id'))
    return [Recibo(m.fecha, m.fecha, float(m.monto)) for m in movimientos
            if patron.search(_plano(m.descripcion)) or patron.search(_plano(m.categoria))]


def proximo_recibo(historial, categoria, hoy):
    """(fecha, monto, días entre recibos, ya_facturado) del siguiente pago según los recibos (modelos
    HistorialReciboServicio, del más viejo al más nuevo). Ver `proximo_pago` en services/prediccion."""
    recibos = [Recibo(h.fecha_emision, _vence(h), float(h.monto_total)) for h in historial]
    pago, paso = proximo_pago(recibos, categoria, hoy)
    if pago is None:
        return None, estimar_monto([r.monto for r in recibos]), paso, False
    return pago.fecha, pago.monto, paso, pago.exacto


def prediccion_mes(presupuesto, hoy, anio, mes):
    """Lo que toca pagar de este concepto en el mes (anio, mes).

    Monto fijo: su monto el día de pago. Pago único: solo si es ese mes. Recibo variable: lo que digan sus
    recibos; sin recibos, lo que digan tus movimientos; sin nada de eso, la fecha/monto capturados a mano.
    """
    monto = float(presupuesto.monto_presupuestado or 0)
    if not presupuesto.es_recurrente and presupuesto.mes and presupuesto.anio:
        if (presupuesto.anio, presupuesto.mes) != (anio, mes):
            return Prediccion(0.0, None, False, 'no_toca', 'no toca')
        return Prediccion(monto, dia_del_mes(anio, mes, presupuesto.dia_pago), True, 'unico', 'pago único')
    if presupuesto.dia_pago:
        return Prediccion(monto, dia_del_mes(anio, mes, presupuesto.dia_pago), True, 'fijo', 'monto fijo')
    categoria = presupuesto.categoria.lower().strip()
    recibos = recibos_de(presupuesto)
    if recibos:
        return prediccion_variable(recibos, categoria, anio, mes, hoy)
    movimientos = recibos_del_libro(presupuesto, hoy)
    if movimientos:
        return prediccion_variable(movimientos, categoria, anio, mes, hoy, fuente='movimientos')
    fecha = presupuesto.fecha_proximo_recibo
    if fecha and (fecha.year, fecha.month) == (anio, mes):
        return Prediccion(monto, fecha, False, 'capturado', 'lo que capturaste')
    return Prediccion(0.0, None, False, 'sin_datos', 'sin datos: procesa recibos')


def proxima_quincena(hoy, dias=DIAS_QUINCENA):
    """Primer día de nómina estrictamente posterior a hoy."""
    return min(f for f in (proximo_dia_del_mes(d, hoy=hoy + timedelta(days=1)) for d in dias) if f)


def estimacion(presupuesto, hoy):
    """(próximo pago, monto, días entre pagos, ya_facturado) de un concepto.

    Monto fijo con día de pago: ese día cada mes. Recibo variable: lo que digan sus recibos (misma regla
    que el botón de predecir, sin guardar nada) o, si aún no hay recibos, lo último que se predijo/capturó.
    """
    monto = float(presupuesto.monto_presupuestado or 0)
    if not presupuesto.es_recurrente and presupuesto.mes and presupuesto.anio:   # un solo pago en ese mes
        ultimo = calendar.monthrange(presupuesto.anio, presupuesto.mes)[1]
        fecha = date(presupuesto.anio, presupuesto.mes, min(presupuesto.dia_pago or ultimo, ultimo))
        return (fecha if fecha >= hoy else None), monto, 30, False
    if presupuesto.dia_pago:
        return proximo_dia_del_mes(presupuesto.dia_pago, hoy=hoy), monto, 30, False
    categoria = presupuesto.categoria.lower().strip()
    historial = list(presupuesto.historial_recibos.order_by('fecha_emision', 'id'))
    if not historial:
        fecha = presupuesto.fecha_proximo_recibo
        return (fecha if fecha and fecha >= hoy else None), monto, cadencia_dias([], categoria), False
    return proximo_recibo(historial, categoria, hoy)


def plan_quincenal(presupuestos, hoy):
    """Cuánto apartar cada quincena para llegar a cada pago, y qué vence antes de la próxima nómina."""
    nomina = proxima_quincena(hoy)
    anio, mes = mes_siguiente(hoy)
    filas, total, antes, total_mes = [], 0.0, 0.0, 0.0
    for p in presupuestos:
        fecha, monto, paso, facturado = estimacion(p, hoy)
        proximo_mes = prediccion_mes(p, hoy, anio, mes)
        total_mes += proximo_mes.monto
        if p.es_recurrente:
            por_quincena = round(monto * DIAS_POR_QUINCENA / max(paso, 1), 2)
        else:  # un solo pago: lo que falte repartido en las quincenas que quedan
            quincenas = max(1, ((fecha - hoy).days // DIAS_POR_QUINCENA) + 1) if fecha else 1
            por_quincena = round(monto / quincenas, 2)
        vence_antes = bool(fecha and fecha < nomina)
        filas.append({'p': p, 'proximo': fecha, 'estimado': monto, 'cada_dias': paso, 'facturado': facturado,
                      'por_quincena': por_quincena, 'vence_antes': vence_antes, 'proximo_mes': proximo_mes})
        total += por_quincena
        if vence_antes:
            antes += monto
    return {'filas': filas, 'total_quincena': round(total, 2), 'proxima_nomina': nomina,
            'vence_antes': round(antes, 2), 'n_vencen': sum(1 for f in filas if f['vence_antes']),
            'mes_siguiente': nombre_mes(mes), 'total_proximo_mes': round(total_mes, 2),
            'n_sin_datos': sum(1 for f in filas if f['proximo_mes'].fuente == 'sin_datos')}


@login_required
def presupuesto_view(request):
    presupuestos = Presupuesto.objects.filter(propietario=request.user).order_by('-monto_presupuestado')
    plan = plan_quincenal(presupuestos, timezone.localdate())
    return render(request, 'presupuesto.html', {'presupuestos': presupuestos, 'hoy': timezone.localdate(), **plan})

@login_required
def crear_presupuesto(request):
    form = PresupuestoForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        presupuesto = form.save(commit=False)
        presupuesto.propietario = request.user
        presupuesto.save()
        messages.success(request, 'Concepto de presupuesto guardado exitosamente.')
        return redirect('presupuesto')
    return render(request, 'form_simple.html', {
        'form': form, 'titulo': 'Añadir Nuevo Concepto', 'boton': 'Guardar Concepto', 'cancel_url': reverse('presupuesto')})

@login_required
def editar_presupuesto(request, presupuesto_id):
    presupuesto = get_object_or_404(Presupuesto, id=presupuesto_id, propietario=request.user)
    form = PresupuestoForm(request.POST or None, instance=presupuesto)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Concepto de presupuesto actualizado exitosamente.')
        return redirect('presupuesto')
    return render(request, 'form_simple.html', {
        'form': form, 'titulo': 'Editar Concepto', 'boton': 'Guardar Cambios', 'cancel_url': reverse('presupuesto')})

@require_POST
@login_required
def eliminar_presupuesto(request, presupuesto_id):
    """Borra el concepto y su historial de recibos (se confirma en la lista)."""
    presupuesto = get_object_or_404(Presupuesto, id=presupuesto_id, propietario=request.user)
    presupuesto.delete()
    messages.success(request, f"El concepto '{presupuesto.categoria}' se eliminó.")
    return redirect('presupuesto')

def _es_ajax(request):
    return request.headers.get('x-requested-with') == 'XMLHttpRequest'

def _aviso(request, mensaje, status, nivel=messages.warning):
    """Error como JSON para fetch() o como mensaje + redirect para navegación normal."""
    if _es_ajax(request):
        return JsonResponse({'error': mensaje}, status=status)
    nivel(request, mensaje)
    return redirect('presupuesto')

@login_required
def buscar_recibos_presupuesto(request, presupuesto_id):
    presupuesto = get_object_or_404(Presupuesto, id=presupuesto_id, propietario=request.user)
    categoria_lower = presupuesto.categoria.lower().strip()
    if presupuesto.dia_pago:
        return _aviso(request, f'{presupuesto.categoria} es de monto fijo (tiene día de pago); los recibos son para los conceptos variables.', 400)

    try:
        archivos = carpeta_recibos(GoogleDriveService(request.user), categoria_lower)
    except ValueError as e:  # falta la carpeta 'Recibos' o la subcarpeta
        return _aviso(request, str(e), 404)
    except Exception as e:
        return _aviso(request, f"Error al acceder a Google Drive: {e}. Recuerda vincular tu cuenta.", 500, messages.error)

    if _es_ajax(request):
        return JsonResponse({'cantidad': len(archivos)})
    messages.success(request, f"Se encontró la carpeta '{categoria_lower}' en Drive con {len(archivos)} archivo(s). ¡Listo para el siguiente paso!")
    return redirect('presupuesto')

@login_required
def procesar_recibos_anteriores_presupuesto(request, presupuesto_id):
    if not _es_ajax(request):
        return JsonResponse({'error': 'Método no permitido'}, status=405)

    presupuesto = get_object_or_404(Presupuesto, id=presupuesto_id, propietario=request.user)
    categoria_lower = presupuesto.categoria.lower().strip()
    if presupuesto.dia_pago:
        return JsonResponse({'error': f'{presupuesto.categoria} es de monto fijo; los recibos son para los conceptos variables.'}, status=400)

    try:
        task = process_drive_utility_bills.delay(request.user.id, presupuesto.id, categoria_lower)
        return JsonResponse({
            'success': True,
            'task_id': task.id,
            'mensaje': 'Tus recibos se están procesando en segundo plano. Los resultados aparecerán pronto.'
        })
    except Exception as e:
        logger.exception("Error al encolar process_drive_utility_bills")
        return JsonResponse({'error': f'Ocurrió un error al encolar la tarea: {str(e)}'}, status=500)

@login_required
def predecir_recibo_presupuesto(request, presupuesto_id):
    """Botón "Predecir recibo del próximo mes": cuánto va a tocar pagar de este concepto el mes que entra.

    Usa los recibos procesados; si no hay, los movimientos que ya registraste con ese nombre. Guarda la
    predicción del siguiente pago en el concepto (monto y fecha) para que la tabla y el plan la usen.
    """
    if not _es_ajax(request):
        return JsonResponse({'error': 'Método no permitido'}, status=405)

    presupuesto = get_object_or_404(Presupuesto, id=presupuesto_id, propietario=request.user)
    categoria_lower = presupuesto.categoria.lower().strip()
    if presupuesto.dia_pago:
        return JsonResponse({'error': f'{presupuesto.categoria} es de monto fijo; no hay nada que predecir.'}, status=400)

    try:
        hoy = timezone.localdate()
        anio, mes = mes_siguiente(hoy)
        recibos, fuente = recibos_de(presupuesto), 'recibos'
        if not recibos:
            recibos, fuente = recibos_del_libro(presupuesto, hoy), 'movimientos'
        if not recibos:
            return JsonResponse({'error': f'No tengo con qué predecir {presupuesto.categoria}: procesa sus recibos de Drive '
                                          f'(botón verde) o registra algún pago con "{presupuesto.categoria}" en la descripción.'},
                                status=400)

        pred = prediccion_variable(recibos, categoria_lower, anio, mes, hoy, fuente)
        siguiente, paso = proximo_pago(recibos, categoria_lower, hoy)
        if siguiente is None:
            return JsonResponse({'error': 'Los recibos no traen fecha de emisión; no puedo proyectar.'}, status=400)

        # Lo que se guarda en el concepto es el siguiente pago (sea del mes que entra o del que sigue).
        presupuesto.monto_presupuestado = siguiente.monto
        presupuesto.fecha_proximo_recibo = siguiente.fecha
        presupuesto.save(update_fields=['monto_presupuestado', 'fecha_proximo_recibo'])

        nombre = nombre_mes(mes)
        base = (f'{len(recibos)} recibo(s)' if fuente == 'recibos' else f'{len(recibos)} pago(s) en tus movimientos')
        if pred.fuente == 'no_toca':
            mensaje = (f'En {nombre} no toca pagar {presupuesto.categoria} (se cobra cada ~{paso} días); '
                       f'el siguiente cae el {siguiente.fecha:%d/%m/%Y} por ~${siguiente.monto:,.2f}.')
        elif pred.exacto:
            mensaje = f'{nombre.capitalize()}: ${pred.monto:,.2f} el {pred.fecha:%d/%m/%Y} (recibo en mano, monto exacto).'
        else:
            mensaje = f'{nombre.capitalize()}: ~${pred.monto:,.2f} el {pred.fecha:%d/%m/%Y} (estimado con {base}, cada ~{paso} días).'

        return JsonResponse({
            'success': True,
            'mes': nombre,
            'monto_predicho': pred.monto,
            'fecha_predicha': pred.fecha.strftime('%Y-%m-%d') if pred.fecha else None,
            'exacto': pred.exacto,
            'fuente': fuente,
            'siguiente_pago': {'monto': siguiente.monto, 'fecha': siguiente.fecha.strftime('%Y-%m-%d')},
            'mensaje': mensaje,
        })

    except Exception as e:
        logger.exception("Error al predecir recibo")
        return JsonResponse({'error': f'Ocurrió un error al predecir: {str(e)}'}, status=500)

@login_required
def revisar_historicos(request):
    """
    Vista para revisar el historial de recibos procesados (luz, agua, gas).
    """
    
    historicos = HistorialReciboServicio.objects.filter(
        propietario=request.user
    ).select_related('presupuesto').order_by('-fecha_emision', '-id')
    
    return render(request, 'revisar_historicos.html', {
        'historicos': historicos
    })
