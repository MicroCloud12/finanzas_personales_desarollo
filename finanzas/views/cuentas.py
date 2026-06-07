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
def gestionar_cuentas(request):
    cuentas = Cuenta.objects.filter(propietario=request.user)
    
    if request.method == 'POST':
        form = CuentaForm(request.POST)
        if form.is_valid():
            cuenta = form.save(commit=False)
            cuenta.propietario = request.user
            cuenta.save()
            
            if cuenta.tipo == 'CREDITO':
                Deuda.objects.get_or_create(
                    propietario=request.user,
                    nombre=cuenta.nombre,
                    defaults={
                        'tipo_deuda': 'TARJETA_CREDITO',
                        'monto_total': Decimal('0.00'),
                        'tasa_interes': Decimal('0.00'),
                        'plazo_meses': 1,
                        'requiere_configuracion_adicional': True
                    }
                )

            messages.success(request, f"La cuenta '{cuenta.nombre}' se ha registrado exitosamente.")
            return redirect('dashboard') # Una vez que guardan, los dejamos ir al dashboard
    else:
        form = CuentaForm()

    context = {
        'form': form,
        'cuentas': cuentas,
        # Si no tiene cuentas, le mostramos un mensaje diferente en el HTML
        'es_onboarding': not cuentas.exists() 
    }
    return render(request, 'gestionar_cuentas.html', context)

@login_required
def editar_cuenta(request, cuenta_id):
    cuenta = get_object_or_404(Cuenta, id=cuenta_id, propietario=request.user)
    if request.method == 'POST':
        form = CuentaForm(request.POST, instance=cuenta)
        if form.is_valid():
            form.save()
            messages.success(request, f"La cuenta '{cuenta.nombre}' ha sido actualizada.")
            return redirect('gestionar_cuentas')
    else:
        form = CuentaForm(instance=cuenta)
    return render(request, 'editar_cuenta.html', {'form': form, 'cuenta': cuenta})

@login_required
@require_POST
def eliminar_cuenta(request, cuenta_id):
    cuenta = get_object_or_404(Cuenta, id=cuenta_id, propietario=request.user)
    nombre = cuenta.nombre
    cuenta.delete()
    messages.success(request, f"La cuenta '{nombre}' ha sido eliminada correctamente.")
    return redirect('gestionar_cuentas')

