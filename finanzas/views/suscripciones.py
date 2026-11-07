import json
import logging
from datetime import timedelta

from django.utils import timezone
from django.urls import reverse
from django.contrib import messages
from django.http import HttpResponse, JsonResponse
from django.contrib.auth.models import User
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.shortcuts import render, redirect


from ..services import (
    MercadoPagoService, RISCService, AccountService
)
from ..models import (
    Suscripcion
)

logger = logging.getLogger(__name__)

@login_required
def gestionar_suscripcion(request):
    """
    Muestra el estado de la suscripción y genera el link de pago si es necesario.
    """
    suscripcion, created = Suscripcion.objects.get_or_create(usuario=request.user)
    
    link_pago = None
    # Sin acceso, o cancelada (aún con días pagados): ofrecer el link para (re)activar
    if not suscripcion.is_active() or suscripcion.esta_cancelada:
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
@require_POST
def cancelar_suscripcion(request):
    """
    Cancela el cobro recurrente en Mercado Pago. El usuario conserva Premium
    hasta la fecha que ya pagó (``fecha_fin``).
    """
    # Volver a la página desde la que se canceló (perfil por defecto)
    destino = 'gestionar_suscripcion' if request.POST.get('next') == 'gestionar_suscripcion' else 'mi_perfil'
    try:
        suscripcion, cancelada = AccountService.cancelar_suscripcion(request.user)
    except Exception as e:
        logger.exception(f"Error cancelando la suscripción de {request.user.username}: {e}")
        messages.error(request, "No pudimos cancelar tu suscripción en Mercado Pago. Intenta de nuevo en unos minutos.")
        return redirect(destino)

    if not cancelada:
        messages.info(request, "No tienes una suscripción activa que cancelar.")
    else:
        fecha_fin = timezone.localtime(suscripcion.fecha_fin).strftime('%d/%m/%Y')
        messages.success(request, f"Tu suscripción se canceló: no habrá más cobros. Conservas Premium hasta el {fecha_fin}.")
    return redirect(destino)

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
                    suscripcion_obj.fecha_cancelacion = None
                elif status == 'cancelled':
                    # Cancelada (desde el perfil o desde Mercado Pago): conserva acceso hasta fecha_fin
                    suscripcion_obj.estado = 'cancelada'
                    suscripcion_obj.fecha_cancelacion = suscripcion_obj.fecha_cancelacion or timezone.now()
                elif status == 'paused':
                    # Pago rechazado: sin acceso hasta que Mercado Pago vuelva a cobrar
                    suscripcion_obj.estado = 'pausada'
                
                suscripcion_obj.save()

    except (json.JSONDecodeError, KeyError, Suscripcion.DoesNotExist) as e:
        logger.error(f"Error procesando webhook de Mercado Pago: {e}")
        return HttpResponse(status=400)

    # Devolvemos un 200 OK para que Mercado Pago sepa que recibimos la notificación
    return HttpResponse(status=200)

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
    
