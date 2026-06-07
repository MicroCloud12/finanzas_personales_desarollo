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

def enviar_pregunta(request):
    if request.method == "POST":
        email = request.POST.get("email")
        message = request.POST.get("message")
        subject = "Nueva pregunta desde el sitio"
        body = f"Correo: {email}\n\nMensaje:\n{message}"
        send_mail(subject, body, settings.EMAIL_BACKEND, [settings.EMAIL_HOST_USER])
        messages.success(request, "Tu mensaje ha sido enviado correctamente.")
    return redirect('home')

'''
Vista de inicio, redirige a la página de inicio,
inicio de sesión y registro.
'''
def home(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    return render(request, 'index.html')

def iniciosesion(request):
    return render(request, 'dashboard.html')

def registro(request):
    if request.method == 'POST':
        form = FormularioRegistroPersonalizado(request.POST)

        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect('dashboard')
    else:
        form = FormularioRegistroPersonalizado()
    
    context = {'form': form}
    return render(request, 'registro.html', context)

'''
Views relacionadas a las transacciones
'''
def politica_privacidad(request):
    """
    Muestra la política de privacidad de la aplicación.
    """
    return render(request, 'privacy_policy.html')

def terminos_servicio(request):
    """
    Muestra los términos de servicio de la aplicación.
    """
    return render(request, 'terminos_servicio.html')

@login_required
def mi_perfil(request):
    """
    Muestra y permite editar el perfil del usuario.
    """
    try:
        suscripcion = request.user.suscripcion
    except Suscripcion.DoesNotExist:
        suscripcion = None
        
    try:
        google_creds = GoogleCredentials.objects.get(user=request.user)
    except GoogleCredentials.DoesNotExist:
        google_creds = None

    context = {
        'suscripcion': suscripcion,
        'google_creds': google_creds,
        'today': timezone.now().date(),
    }
    return render(request, 'mi_perfil.html', context)

