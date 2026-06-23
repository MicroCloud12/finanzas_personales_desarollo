import json
import logging
from decimal import Decimal
from datetime import datetime, timedelta
from statistics import median

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
    from ..forms import PresupuestoForm
    from django.contrib import messages
    
    if request.method == 'POST':
        form = PresupuestoForm(request.POST)
        if form.is_valid():
            presupuesto = form.save(commit=False)
            presupuesto.propietario = request.user
            presupuesto.save()
            messages.success(request, 'Concepto de presupuesto guardado exitosamente.')
            return redirect('presupuesto')
    else:
        form = PresupuestoForm()
        
    return render(request, 'crear_presupuesto.html', {'form': form})

@login_required
def editar_presupuesto(request, presupuesto_id):
    from ..forms import PresupuestoForm
    from django.contrib import messages
    from django.shortcuts import get_object_or_404
    
    presupuesto = get_object_or_404(Presupuesto, id=presupuesto_id, propietario=request.user)
    
    if request.method == 'POST':
        form = PresupuestoForm(request.POST, instance=presupuesto)
        if form.is_valid():
            form.save()
            messages.success(request, 'Concepto de presupuesto actualizado exitosamente.')
            return redirect('presupuesto')
    else:
        form = PresupuestoForm(instance=presupuesto)
        
    return render(request, 'editar_presupuesto.html', {'form': form, 'presupuesto': presupuesto})

@login_required
def buscar_recibos_presupuesto(request, presupuesto_id):
    from django.shortcuts import get_object_or_404
    from django.contrib import messages
    from ..services import GoogleDriveService

    presupuesto = get_object_or_404(Presupuesto, id=presupuesto_id, propietario=request.user)
    categoria_lower = presupuesto.categoria.lower().strip()
    
    if categoria_lower not in ['agua', 'luz', 'gas']:
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'error': f'La búsqueda automática de recibos no está configurada para la categoría: {presupuesto.categoria}'}, status=400)
        messages.warning(request, f'La búsqueda automática de recibos no está configurada para la categoría: {presupuesto.categoria}')
        return redirect('presupuesto')
        
    try:
        drive_service = GoogleDriveService(request.user)
        
        # Buscar carpeta principal 'recibos' (insensible a mayúsculas)
        query_recibos = "mimeType='application/vnd.google-apps.folder' and trashed=false and (name='recibos' or name='Recibos' or name='RECIBOS')"
        response_recibos = drive_service.service.files().list(q=query_recibos, spaces='drive', fields='files(id, name)').execute()
        carpetas_recibos = response_recibos.get('files', [])
        
        if not carpetas_recibos:
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({'error': "No se encontró la carpeta 'Recibos' en tu Google Drive. Asegúrate de crearla."}, status=404)
            messages.warning(request, "No se encontró la carpeta 'Recibos' en tu Google Drive. Asegúrate de crearla.")
            return redirect('presupuesto')
            
        carpeta_recibos_id = carpetas_recibos[0]['id']
            
        # Buscar la subcarpeta (ej. 'agua', 'Agua', 'AGUA') dentro de 'recibos'
        cat_title = categoria_lower.capitalize()
        cat_upper = categoria_lower.upper()
        
        query_sub = f"mimeType='application/vnd.google-apps.folder' and '{carpeta_recibos_id}' in parents and trashed=false and (name='{categoria_lower}' or name='{cat_title}' or name='{cat_upper}')"
        response_sub = drive_service.service.files().list(q=query_sub, spaces='drive', fields='files(id, name)').execute()
        carpetas_encontradas = response_sub.get('files', [])
        
        if not carpetas_encontradas:
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({'error': f"Se encontró la carpeta 'Recibos', pero no la subcarpeta '{categoria_lower}'. Asegúrate de crearla."}, status=404)
            messages.warning(request, f"Se encontró la carpeta 'Recibos', pero no la subcarpeta '{categoria_lower}'. Asegúrate de crearla.")
            return redirect('presupuesto')
            
        subcarpeta_id = carpetas_encontradas[0]['id']
        
        # Como paso intermedio, vamos a listar cuántos PDFs o imágenes hay
        archivos = drive_service.service.files().list(
            q=f"'{subcarpeta_id}' in parents and trashed=false",
            fields="files(id, name, mimeType)"
        ).execute().get('files', [])
        
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'cantidad': len(archivos)})
            
        messages.success(request, f"Se encontró la carpeta '{categoria_lower}' en Drive con {len(archivos)} archivo(s). ¡Listo para el siguiente paso!")
        
    except Exception as e:
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'error': f"Error al acceder a Google Drive: {str(e)}. Recuerda vincular tu cuenta."}, status=500)
        messages.error(request, f"Error al acceder a Google Drive: {str(e)}. Recuerda vincular tu cuenta.")
        
    return redirect('presupuesto')

@login_required
def procesar_recibos_anteriores_presupuesto(request, presupuesto_id):
    from django.shortcuts import get_object_or_404
    
    if request.headers.get('x-requested-with') != 'XMLHttpRequest':
        return JsonResponse({'error': 'Método no permitido'}, status=405)

    presupuesto = get_object_or_404(Presupuesto, id=presupuesto_id, propietario=request.user)
    categoria_lower = presupuesto.categoria.lower().strip()
    
    if categoria_lower not in ['agua', 'luz', 'gas']:
        return JsonResponse({'error': 'Procesamiento no configurado para esta categoría'}, status=400)

    try:
        task = process_drive_utility_bills.delay(request.user.id, presupuesto.id, categoria_lower)
        return JsonResponse({
            'success': True,
            'task_id': task.id,
            'mensaje': 'Tus recibos se están procesando en segundo plano. Los resultados aparecerán pronto.'
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({'error': f'Ocurrió un error al encolar la tarea: {str(e)}'}, status=500)

@login_required
def predecir_recibo_presupuesto(request, presupuesto_id):
    from django.shortcuts import get_object_or_404

    if request.headers.get('x-requested-with') != 'XMLHttpRequest':
        return JsonResponse({'error': 'Método no permitido'}, status=405)

    presupuesto = get_object_or_404(Presupuesto, id=presupuesto_id, propietario=request.user)
    categoria_lower = presupuesto.categoria.lower().strip()
    
    if categoria_lower not in ['agua', 'luz', 'gas']:
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
        import traceback
        traceback.print_exc()
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