import logging
from datetime import timedelta
from statistics import median

from django.utils import timezone
from django.contrib import messages
from django.http import JsonResponse
from django.urls import reverse
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404

from ..forms import PresupuestoForm
from ..services import GoogleDriveService
from ..tasks import process_drive_utility_bills, carpeta_recibos
from ..models import Presupuesto, HistorialReciboServicio

logger = logging.getLogger(__name__)
CATEGORIAS_RECIBOS = ('agua', 'luz', 'gas')


def cadencia_dias(fechas, categoria):
    """Días típicos entre recibos: mediana de los últimos gaps; default por categoría con <2 fechas."""
    if len(fechas) >= 2:
        gaps = [(fechas[i] - fechas[i - 1]).days for i in range(1, len(fechas))]
        return max(1, int(round(median(gaps[-6:]))))  # max(1,..) evita loop infinito si hay fechas duplicadas
    return 30 if categoria == 'gas' else 61  # ponytail: agua/luz suelen ser bimestrales; gas mensual


def proxima_fecha(base, paso, hoy):
    """Primera fecha de facturación estrictamente posterior a hoy, anclada al último recibo."""
    f = base + timedelta(days=paso)
    while f <= hoy:
        f += timedelta(days=paso)
    return f


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


@login_required
def presupuesto_view(request):
    presupuestos = Presupuesto.objects.filter(propietario=request.user).order_by('-monto_presupuestado')
    return render(request, 'presupuesto.html', {'presupuestos': presupuestos})

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
    if categoria_lower not in CATEGORIAS_RECIBOS:
        return _aviso(request, f'La búsqueda automática de recibos no está configurada para la categoría: {presupuesto.categoria}', 400)

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
    if categoria_lower not in CATEGORIAS_RECIBOS:
        return JsonResponse({'error': 'Procesamiento no configurado para esta categoría'}, status=400)

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
    
    if categoria_lower not in CATEGORIAS_RECIBOS:
        return JsonResponse({'error': 'Predicción no configurada para esta categoría'}, status=400)

    try:
        historial = list(
            HistorialReciboServicio.objects.filter(presupuesto=presupuesto).order_by('fecha_emision')
        )
        if not historial:
            return JsonResponse({'error': 'No hay historial de recibos. Asegúrate de procesar tus recibos primero.'}, status=400)

        fechas = sorted(h.fecha_emision for h in historial if h.fecha_emision)
        montos = [float(h.monto_total) for h in historial]

        # Próxima fecha = primer ciclo futuro, anclado al último recibo con la cadencia real (mediana de días).
        hoy = timezone.localdate()
        paso = cadencia_dias(fechas, categoria_lower)
        base = fechas[-1] if fechas else hoy
        fecha_obj = proxima_fecha(base, paso, hoy)

        monto_predicho = estimar_monto(montos)
        razonamiento = (f"{len(montos)} recibo(s) · cadencia ~{paso} días desde {base:%d/%m/%Y} · "
                        f"regresión lineal sobre últimos {min(len(montos), 6)}")

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