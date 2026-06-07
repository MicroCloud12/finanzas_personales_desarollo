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
def gestionar_suscripcion(request):
    """
    Muestra el estado de la suscripción y genera el link de pago si es necesario.
    """
    suscripcion, created = Suscripcion.objects.get_or_create(usuario=request.user)
    
    link_pago = None
    if not suscripcion.is_active():
        try:
            mp_service = MercadoPagoService()
            # La vista construye la URL absoluta y se la pasa al servicio
            success_url = request.build_absolute_uri(reverse('suscripcion_exitosa'))
            link_pago = mp_service.crear_link_suscripcion(request.user, success_url)
        except Exception as e:
            messages.error(request, f"Error al generar link de pago: {e}")

    context = {
        'suscripcion': suscripcion,
        'link_pago': link_pago
    }
    return render(request, 'gestionar_suscripcion.html', context)

@login_required
def suscripcion_exitosa(request):
    messages.success(request, "¡Tu pago se está procesando! La activación puede tardar unos minutos.")
    return redirect('gestionar_suscripcion')

@login_required
def suscripcion_fallida(request):
    messages.error(request, "Hubo un problema con tu pago. Por favor, intenta de nuevo.")
    return redirect('gestionar_suscripcion')

@csrf_exempt
def mercadopago_webhook(request):
    """
    Recibe notificaciones de MercadoPago para actualizar el estado de las suscripciones.
    """
    if request.method != 'POST':
        return HttpResponse(status=405) # Method Not Allowed

    try:
        data = json.loads(request.body)
        topic = data.get("type")

        if topic == "subscription_preapproval":
            subscription_id = data.get("data", {}).get("id")
            if not subscription_id:
                return HttpResponse(status=400) # Bad Request, no ID provided

            mp_service = MercadoPagoService()
            # Obtenemos los detalles de la suscripción desde la API de Mercado Pago
            subscription_details = mp_service.sdk.preapproval().get(subscription_id)
            
            if subscription_details["status"] == 200:
                sub_data = subscription_details["response"]
                payer_email = sub_data.get("payer_email")
                status = sub_data.get("status")

                # Buscamos al usuario por su email
                user = User.objects.filter(email=payer_email).first()
                if not user:
                    return HttpResponse(status=404) # User not found

                suscripcion_obj = Suscripcion.objects.get(usuario=user)

                # ¡La magia! Actualizamos nuestro modelo según el estado de Mercado Pago
                if status == 'authorized':
                    suscripcion_obj.estado = 'activa'
                    suscripcion_obj.id_suscripcion_mercadopago = subscription_id
                    suscripcion_obj.fecha_inicio = timezone.now()
                    suscripcion_obj.fecha_fin = timezone.now() + timedelta(days=31)
                elif status in ['paused', 'cancelled']:
                    suscripcion_obj.estado = 'cancelada'
                
                suscripcion_obj.save()

    except (json.JSONDecodeError, KeyError, Suscripcion.DoesNotExist) as e:
        # Log del error sería ideal aquí en un sistema de producción
        print(f"Error procesando webhook: {e}")
        return HttpResponse(status=400)

    # Devolvemos un 200 OK para que Mercado Pago sepa que recibimos la notificación
    return HttpResponse(status=200)

'''
Inversiones
'''
@csrf_exempt # Es crucial para permitir que un servicio externo como Google haga POST
def risc_webhook(request):
    """
    Endpoint para recibir y procesar notificaciones de seguridad de Google RISC.
    """
    if request.method != 'POST':
        return HttpResponse(status=405) # Method Not Allowed

    try:
        # El cuerpo del request es el token de seguridad (JWT)
        security_token = request.body.decode('utf-8')
        
        # 1. Validamos el token usando nuestro servicio
        risc_service = RISCService()
        payload = risc_service.validate_token(security_token)
        
        # 2. Procesamos los eventos dentro del token
        risc_service.process_security_event(payload)

        # 3. Respondemos a Google que hemos recibido y aceptado el evento
        return HttpResponse(status=202) # Accepted

    except (ValueError, json.JSONDecodeError) as e:
        # Si hay un error de validación o formato, lo registramos y respondemos mal
        logger.error(f"Error procesando el webhook de RISC: {e}")
        return JsonResponse({'error': str(e)}, status=400) # Bad Request
    
