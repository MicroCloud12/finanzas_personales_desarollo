import logging
from decimal import Decimal

from django.contrib import messages
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404


from ..forms import (
    CuentaForm
)
from ..models import (
    Deuda, Cuenta
)

logger = logging.getLogger(__name__)

@login_required
def gestionar_cuentas(request):
    cuentas = Cuenta.objects.filter(propietario=request.user).order_by('-es_principal', 'tipo', 'nombre')

    if request.method == 'POST':
        form = CuentaForm(request.POST)
        if form.is_valid():
            form.instance.propietario = request.user
            cuenta = form.save()

            # Tarjetas y préstamos llevan su detalle (tasa, corte, amortización) en Deuda.
            if cuenta.tipo in ('CREDITO', 'PRESTAMO'):
                Deuda.objects.get_or_create(
                    cuenta=cuenta,
                    defaults={
                        'propietario': request.user,
                        'nombre': cuenta.nombre,
                        'tipo_deuda': 'TARJETA_CREDITO' if cuenta.tipo == 'CREDITO' else 'PRESTAMO',
                        'monto_total': Decimal('0.00'),
                        'tasa_interes': Decimal('0.00'),
                        'plazo_meses': 1,
                        'requiere_configuracion_adicional': True
                    }
                )

            messages.success(request, f"La cuenta '{cuenta.nombre}' se ha registrado exitosamente.")
            return redirect('dashboard')
    else:
        form = CuentaForm()

    context = {
        'form': form,
        'cuentas': cuentas,
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

