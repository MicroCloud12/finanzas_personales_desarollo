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
    from ..services import get_gemini_service
    from datetime import datetime
    
    if request.headers.get('x-requested-with') != 'XMLHttpRequest':
        return JsonResponse({'error': 'Método no permitido'}, status=405)

    presupuesto = get_object_or_404(Presupuesto, id=presupuesto_id, propietario=request.user)
    categoria_lower = presupuesto.categoria.lower().strip()
    
    if categoria_lower not in ['agua', 'luz', 'gas']:
        return JsonResponse({'error': 'Predicción no configurada para esta categoría'}, status=400)

    try:
        gemini_service = get_gemini_service()
                
        # 1. Obtener todo el historial de la base de datos
        historial = HistorialReciboServicio.objects.filter(presupuesto=presupuesto).order_by('fecha_emision')
        if not historial.exists():
            return JsonResponse({'error': 'No hay historial de recibos. Asegúrate de procesar tus recibos primero.'}, status=400)
            
        datos_historial = []
        for h in historial:
            datos_historial.append({
                "fecha_emision": str(h.fecha_emision) if h.fecha_emision else "Desconocida",
                "monto_total": float(h.monto_total),
                "consumo": h.datos_json.get("consumo", "Desconocido")
            })
            
        contexto_data = {
            "fecha_actual_sistema": timezone.localtime(timezone.now()).strftime('%Y-%m-%d'),
            "historial_recibos": datos_historial
        }
        contexto = json.dumps(contexto_data)
        
        # 2. Pedir predicción a Gemini
        prediccion = gemini_service.extract_from_text("prediccion_servicio", "", contexto)
        
        if isinstance(prediccion, list):
            prediccion = prediccion[0] if prediccion else {}
            
        monto_predicho = prediccion.get("monto_predicho", 0)
        fecha_predicha = prediccion.get("fecha_predicha", "")
        razonamiento = prediccion.get("razonamiento", "Sin razonamiento proporcionado por la IA.")
        
        try:
            monto_predicho = float(monto_predicho)
        except:
            monto_predicho = 0.0
            
        fecha_obj = None
        if fecha_predicha:
            try:
                fecha_obj = datetime.strptime(fecha_predicha, '%Y-%m-%d').date()
            except ValueError:
                pass
                
        # 3. Actualizar presupuesto
        actualizado = False
        if monto_predicho > 0:
            presupuesto.monto_presupuestado = monto_predicho
            actualizado = True
            
        if fecha_obj:
            presupuesto.fecha_proximo_recibo = fecha_obj
            actualizado = True
            
        if actualizado:
            presupuesto.save()
            
        return JsonResponse({
            'success': True,
            'monto_predicho': monto_predicho,
            'fecha_predicha': fecha_predicha,
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