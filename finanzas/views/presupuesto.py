import calendar
import logging
from datetime import date, timedelta
from statistics import median

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
from ..models import Presupuesto, HistorialReciboServicio, proximo_dia_del_mes

logger = logging.getLogger(__name__)
DIAS_QUINCENA = (13, 28)   # días en que cae la nómina; el plan de apartado va de una nómina a la siguiente
DIAS_POR_QUINCENA = 15


def cadencia_dias(fechas, categoria):
    """Días típicos entre recibos: mediana de los últimos gaps; default por categoría con <2 fechas."""
    if len(fechas) >= 2:
        gaps = [(fechas[i] - fechas[i - 1]).days for i in range(1, len(fechas))]
        return max(1, int(round(median(gaps[-6:]))))  # max(1,..) evita loop infinito si hay fechas duplicadas
    return 61 if categoria in ('agua', 'luz') else 30  # ponytail: agua/luz suelen ser bimestrales; el resto mensual


def proxima_fecha(base, paso, hoy):
    """Primera fecha de facturación estrictamente posterior a hoy, anclada al último recibo."""
    f = base + timedelta(days=paso)
    while f <= hoy:
        f += timedelta(days=paso)
    return f


DIAS_PARA_PAGAR = 12   # si el recibo no trae fecha límite: lo típico entre que se emite y vence (CFE: ~12 días)


def _vence(recibo):
    """Fecha límite de pago del recibo: la que leyó la IA o, si no venía, emisión + DIAS_PARA_PAGAR."""
    texto = (recibo.datos_json or {}).get('fecha_limite_pago')
    try:
        if texto:
            return date.fromisoformat(str(texto)[:10])
    except ValueError:
        pass
    return recibo.fecha_emision + timedelta(days=DIAS_PARA_PAGAR) if recibo.fecha_emision else None


def proximo_recibo(historial, categoria, hoy):
    """(fecha, monto, días entre recibos, ya_facturado) a partir de los recibos, del más viejo al más nuevo.
    Si el último recibo todavía no vence, ESE es el próximo pago (monto exacto, no estimado); si ya venció,
    el siguiente ciclo: su vencimiento más la cadencia real, con el monto proyectado por tendencia."""
    fechas = sorted(h.fecha_emision for h in historial if h.fecha_emision)
    paso = cadencia_dias(fechas, categoria)
    ultimo = historial[-1]
    limite = _vence(ultimo)
    if limite and limite >= hoy:
        return limite, float(ultimo.monto_total), paso, True
    base = limite or (fechas[-1] if fechas else None)
    fecha = proxima_fecha(base, paso, hoy) if base else None
    return fecha, estimar_monto([float(h.monto_total) for h in historial]), paso, False


def estimar_monto(montos):
    """Extrapola un periodo con regresión lineal sobre los últimos 6 recibos; acota ±25% sobre la media."""
    ys = montos[-6:]
    n = len(ys)
    if n <= 1:
        return round(ys[0], 2) if ys else 0.0
    mx = (n - 1) / 2
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in range(n))
    sxy = sum((x - mx) * (y - my) for x, y in enumerate(ys))
    slope = sxy / sxx if sxx else 0.0
    pred = my + slope * (n - mx)  # siguiente punto (x = n)
    return round(min(max(pred, my * 0.75), my * 1.25), 2)


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
    filas, total, antes = [], 0.0, 0.0
    for p in presupuestos:
        fecha, monto, paso, facturado = estimacion(p, hoy)
        if p.es_recurrente:
            por_quincena = round(monto * DIAS_POR_QUINCENA / max(paso, 1), 2)
        else:  # un solo pago: lo que falte repartido en las quincenas que quedan
            quincenas = max(1, ((fecha - hoy).days // DIAS_POR_QUINCENA) + 1) if fecha else 1
            por_quincena = round(monto / quincenas, 2)
        vence_antes = bool(fecha and fecha < nomina)
        filas.append({'p': p, 'proximo': fecha, 'estimado': monto, 'cada_dias': paso, 'facturado': facturado,
                      'por_quincena': por_quincena, 'vence_antes': vence_antes})
        total += por_quincena
        if vence_antes:
            antes += monto
    return {'filas': filas, 'total_quincena': round(total, 2), 'proxima_nomina': nomina,
            'vence_antes': round(antes, 2), 'n_vencen': sum(1 for f in filas if f['vence_antes'])}


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
    if not _es_ajax(request):
        return JsonResponse({'error': 'Método no permitido'}, status=405)

    presupuesto = get_object_or_404(Presupuesto, id=presupuesto_id, propietario=request.user)
    categoria_lower = presupuesto.categoria.lower().strip()
    if presupuesto.dia_pago:
        return JsonResponse({'error': f'{presupuesto.categoria} es de monto fijo; no hay nada que predecir.'}, status=400)

    try:
        historial = list(
            HistorialReciboServicio.objects.filter(presupuesto=presupuesto).order_by('fecha_emision', 'id')
        )
        if not historial:
            return JsonResponse({'error': 'No hay historial de recibos. Asegúrate de procesar tus recibos primero.'}, status=400)

        hoy = timezone.localdate()
        fecha_obj, monto_predicho, paso, facturado = proximo_recibo(historial, categoria_lower, hoy)
        if fecha_obj is None:
            return JsonResponse({'error': 'Los recibos no traen fecha de emisión; no puedo proyectar.'}, status=400)
        razonamiento = (f"el último recibo vence el {fecha_obj:%d/%m/%Y}: ese es el próximo pago" if facturado else
                        f"{len(historial)} recibo(s) · cadencia ~{paso} días · regresión lineal sobre últimos {min(len(historial), 6)}")

        presupuesto.monto_presupuestado = monto_predicho
        presupuesto.fecha_proximo_recibo = fecha_obj
        presupuesto.save(update_fields=['monto_presupuestado', 'fecha_proximo_recibo'])

        return JsonResponse({
            'success': True,
            'monto_predicho': monto_predicho,
            'fecha_predicha': fecha_obj.strftime('%Y-%m-%d'),
            'razonamiento': razonamiento
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