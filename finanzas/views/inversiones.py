import logging
from decimal import Decimal

from django.contrib import messages
from django.http import JsonResponse
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.db.models import Sum
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.shortcuts import render, redirect, get_object_or_404


from ..utils import parse_date_safely
from ..tasks import (
    process_drive_investments,
    update_user_portfolio_history,
)
from ..forms import (
    InversionForm
)
from ..services import StockPriceService
from ..models import Suscripcion, inversiones, PendingInvestment, PortfolioHistory

logger = logging.getLogger(__name__)

@login_required
def vista_portafolio(request):
    """
    Vista dedicada para el Portafolio de Inversiones.
    """
    suscripcion, created = Suscripcion.objects.get_or_create(usuario=request.user)
    es_usuario_premium = suscripcion.is_active()

    # --- LÓGICA DE ACTIVOS ---
    mis_inversiones = inversiones.objects.filter(propietario=request.user).order_by('-valor_actual_mercado')
    
    # Totales Generales
    agregados = mis_inversiones.aggregate(
        total_invertido=Sum('costo_total_adquisicion'),
        valor_actual=Sum('valor_actual_mercado')
    )
    
    total_invertido = agregados['total_invertido'] or Decimal('0.00')
    valor_total = agregados['valor_actual'] or Decimal('0.00')
    ganancia_total = valor_total - total_invertido
    
    # Porcentaje de ganancia total
    porcentaje_ganancia = 0
    if total_invertido > 0:
        porcentaje_ganancia = ((valor_total - total_invertido) / total_invertido) * 100

    # --- GRÁFICA DE RENDIMIENTO (evolución diaria del portafolio) ---
    historial = PortfolioHistory.objects.filter(usuario=request.user).order_by('fecha')
    perf_labels = []
    perf_valores = []
    perf_ganancias = []
    for h in historial:
        perf_labels.append(h.fecha.strftime('%Y-%m-%d'))
        perf_valores.append(float(h.valor_total))
        perf_ganancias.append(float(h.ganancia_no_realizada))

    context = {
        'inversiones': mis_inversiones,
        'valor_total': valor_total,
        'total_invertido': total_invertido,
        'ganancia_total': ganancia_total,
        'porcentaje_ganancia': porcentaje_ganancia,
        'es_usuario_premium': es_usuario_premium,
        # Series para la gráfica de rendimiento (listas crudas; json_script las serializa)
        'perf_labels': perf_labels,
        'perf_valores': perf_valores,
        'perf_ganancias': perf_ganancias,
    }
    return render(request, 'portafolio.html', context)

@login_required
def iniciar_procesamiento_inversiones(request):
    """Inicia el procesamiento automático de inversiones."""
    try:
        task = process_drive_investments.delay(request.user.id)
        return JsonResponse({"task_id": task.id}, status=202)
    except Exception as e:
        return JsonResponse({"error": f"No se pudo iniciar la tarea: {str(e)}"}, status=400)

@login_required
def vista_procesamiento_inversiones(request):
    return render(request, 'procesamiento.html', {
        'titulo': 'Procesamiento de Inversiones',
        'subtitulo': 'Sincroniza tus estados de cuenta y movimientos.',
        'icono': 'M13 7h8m0 0v8m0-8l-8 8-4-4-6 6',
        'descripcion': 'Busca y procesa nuevas inversiones en tu Google Drive.',
        'start_url': reverse('procesar_drive_inversiones'),
        'redirect_url': reverse('revisar_inversiones'),
    })

@login_required
def revisar_inversiones(request):
    """
    Muestra todas las inversiones pendientes para que el usuario las revise.
    """
    pending_investments = PendingInvestment.objects.filter(propietario=request.user, estado='pendiente')
    
    # Formateamos la fecha de manera segura para mostrarla en el template
    for investment in pending_investments:
        fecha_cruda = investment.datos_json.get("fecha_compra") or investment.datos_json.get("fecha")
        fecha_obj = parse_date_safely(fecha_cruda)
        investment.fecha_formateada = fecha_obj.strftime("%d/%m/%Y")
        
    context = {'pending_investments': pending_investments}
    return render(request, 'revisar_inversiones.html', context)

@login_required
def aprobar_inversion(request, inversion_id):
    """
    Aprueba una inversión pendiente, la convierte en una inversión real y la elimina de la lista de pendientes.
    """
    pending = get_object_or_404(PendingInvestment, id=inversion_id, propietario=request.user)
    
    if request.method == 'POST':
        datos = pending.datos_json
        # Valor de mercado calculado en la tarea; si no existe, el precio de compra.
        precio_actual = datos.get("valor_actual_mercado", datos.get("precio_por_titulo", "0.0"))
        tipo_cambio = datos.get("tipo_cambio")
        # save() calcula costo_total_adquisicion, valor_actual_mercado y la ganancia.
        inversiones.objects.create(
            propietario=request.user,
            fecha_compra=parse_date_safely(datos.get("fecha_compra")),
            emisora_ticker=datos.get("emisora_ticker"),
            nombre_activo=datos.get("nombre_activo"),
            cantidad_titulos=Decimal(datos.get("cantidad_titulos", "0.0")),
            precio_compra_titulo=Decimal(datos.get("precio_por_titulo", "0.0")),
            precio_actual_titulo=Decimal(precio_actual) / Decimal(datos.get("cantidad_titulos", "1.0")),
            tipo_cambio_compra=Decimal(tipo_cambio) if tipo_cambio is not None else None,
        )
        pending.estado = 'aprobada'
        pending.save()
        
        update_user_portfolio_history.delay(request.user.id)
        
        messages.success(request, f"Inversión en {datos.get('nombre_activo')} aprobada correctamente.")
        return redirect('revisar_inversiones')

    return redirect('revisar_inversiones')

@login_required
def rechazar_inversion(request, inversion_id):
    """
    Rechaza (elimina) una inversión pendiente.
    """
    PendingInvestment.objects.filter(id=inversion_id, propietario=request.user).update(estado='rechazada')
    return redirect('revisar_inversiones')

@login_required
def lista_inversiones(request):
    """
    Muestra todas las inversiones del usuario logueado.
    """
    suscripcion, created = Suscripcion.objects.get_or_create(usuario=request.user)
    lista = inversiones.objects.filter(propietario=request.user).order_by('-fecha_compra')
    es_usuario_premium = suscripcion.is_active()
    context = {'inversiones': lista, 'es_usuario_premium': es_usuario_premium}
    return render(request, 'lista_inversiones.html', context)

@login_required
def editar_inversion(request, inversion_id):
    inversion = get_object_or_404(inversiones, id=inversion_id, propietario=request.user)
    if request.method == 'POST':
        form = InversionForm(request.POST, instance=inversion)
        if form.is_valid():
            form.save()
            update_user_portfolio_history.delay(request.user.id)
            return redirect('lista_inversiones')
    else:
        form = InversionForm(instance=inversion)
    return render(request, 'form_simple.html', {
        'form': form, 'titulo': 'Editar Inversión', 'boton': 'Actualizar', 'cancel_url': reverse('lista_inversiones')})

@login_required
@require_POST
def eliminar_inversion(request, inversion_id):
    get_object_or_404(inversiones, id=inversion_id, propietario=request.user).delete()
    update_user_portfolio_history.delay(request.user.id)
    next_url = request.POST.get('next', '')
    if not url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        next_url = 'lista_inversiones'   # nunca redirigir a otro dominio
    return redirect(next_url)

@login_required
def crear_inversion(request):
    """
    Maneja la creación de una nueva inversión, obteniendo el precio actual de una API.
    """
    if request.method == 'POST':
        form = InversionForm(request.POST)
        if form.is_valid():
            nueva_inversion = form.save(commit=False)
            nueva_inversion.propietario = request.user
            # Precio de caché/API; si falla o no hay ticker (cripto, fondos) se usa el de compra.
            ticker = (form.cleaned_data.get('emisora_ticker') or '').upper()
            try:
                precio = StockPriceService().get_current_price(ticker)
            except Exception as e:
                logger.warning(f"Error al obtener precio síncrono para {ticker}: {e}")
                precio = None
            nueva_inversion.precio_actual_titulo = Decimal(str(precio)) if precio is not None else nueva_inversion.precio_compra_titulo
            nueva_inversion.save()
            update_user_portfolio_history.delay(request.user.id)
            messages.success(request, f"Inversión en {ticker or nueva_inversion.nombre_activo} guardada con éxito.")
            return redirect('lista_inversiones')
    else:
        form = InversionForm()
    
    return render(request, 'form_simple.html', {
        'form': form, 'titulo': 'Añadir Nueva Inversión', 'boton': 'Guardar Inversión', 'cancel_url': reverse('lista_inversiones')})

