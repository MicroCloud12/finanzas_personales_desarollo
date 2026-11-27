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
from .. import planes

logger = logging.getLogger(__name__)

@login_required
def gestionar_suscripcion(request):
    """
    Muestra los tres planes (Gratis, Personal, Pro), el plan vigente y los links de pago de
    Mercado Pago para contratar o cambiar de plan.
    """
    suscripcion, created = Suscripcion.objects.get_or_create(usuario=request.user)
    plan_actual = planes.plan_de(request.user)

    links = {}
    try:
        mp_service = MercadoPagoService()
        success_url = request.build_absolute_uri(reverse('suscripcion_exitosa'))
        for plan in planes.PLANES_DE_PAGO:
            for periodo in planes.PERIODOS:
                links[f"{plan}_{periodo}"] = mp_service.crear_link_suscripcion(request.user, success_url, plan, periodo)
    except Exception as e:
        messages.error(request, f"Error al generar link de pago: {e}")

    tarjetas = []
    for clave in (planes.GRATIS, planes.PERSONAL, planes.PRO):
        datos = planes.PLANES[clave]
        tarjetas.append({
            'clave': clave, 'nombre': datos['nombre'], 'resumen': datos['resumen'],
            'mensual': datos['mensual'], 'anual': datos['anual'], 'anual_por_mes': datos['anual'] // 12,
            'docs_mes': datos['docs_mes'], 'cfdi': datos['cfdi'], 'actual': clave == plan_actual,
            'link_mensual': links.get(f"{clave}_mensual"), 'link_anual': links.get(f"{clave}_anual"),
        })

    context = {
        'suscripcion': suscripcion,
        'plan_actual': plan_actual,
        'nombre_plan_actual': planes.PLANES[plan_actual]['nombre'],
        'tarjetas': tarjetas,
        'cuota': planes.resumen_cuota(request.user),
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

def _aplicar_estado_mp(suscripcion, sub_data, mp_service, subscription_id):
    """Copia a nuestra Suscripcion lo que dice Mercado Pago de un preapproval (authorized/cancelled/paused)."""
    status = sub_data.get("status")
    if status == 'authorized':
        plan, periodo = mp_service.plan_por_preapproval(sub_data.get("preapproval_plan_id"))
        anterior = suscripcion.id_suscripcion_mercadopago
        if anterior and anterior != subscription_id:
            # Cambió de plan: el cobro viejo se cancela para no cobrar dos veces
            try:
                mp_service.cancelar_preapproval(anterior)
            except Exception as e:  # el plan nuevo se activa igual; el viejo se revisa a mano
                logger.error(f"No se pudo cancelar el preapproval anterior {anterior}: {e}")
        suscripcion.estado = 'activa'
        suscripcion.plan = plan
        suscripcion.periodo = periodo
        suscripcion.id_suscripcion_mercadopago = subscription_id
        suscripcion.fecha_inicio = timezone.now()
        suscripcion.fecha_fin = timezone.now() + timedelta(days=planes.DIAS_POR_PERIODO[periodo])
        suscripcion.fecha_cancelacion = None
    elif status == 'cancelled':
        # Cancelada (desde el perfil o desde Mercado Pago): conserva acceso hasta fecha_fin
        suscripcion.estado = 'cancelada'
        suscripcion.fecha_cancelacion = suscripcion.fecha_cancelacion or timezone.now()
    elif status == 'paused':
        # Pago rechazado: sin acceso hasta que Mercado Pago vuelva a cobrar
        suscripcion.estado = 'pausada'
    suscripcion.save()


def _suscripcion_de(subscription_id, sub_data):
    """Encuentra de quién es un preapproval: por el id que ya guardamos, por external_reference
    (id de usuario, si Mercado Pago lo conservó) y, al final, por el correo del pagador. None si nadie."""
    suscripcion = Suscripcion.objects.filter(id_suscripcion_mercadopago=subscription_id).first()
    if suscripcion:
        return suscripcion
    referencia = str(sub_data.get("external_reference") or "")
    user = User.objects.filter(pk=int(referencia)).first() if referencia.isdigit() else None
    if user is None and sub_data.get("payer_email"):
        user = User.objects.filter(email__iexact=sub_data["payer_email"]).first()
    if user is None:
        return None
    return Suscripcion.objects.get_or_create(usuario=user)[0]


def _vincular_preapproval(user, preapproval_id):
    """Liga un preapproval al usuario logueado (regreso desde Mercado Pago). Así la activación no
    depende de que el correo de Mercado Pago sea el mismo que el de la app. False si no se pudo."""
    if Suscripcion.objects.filter(id_suscripcion_mercadopago=preapproval_id).exclude(usuario=user).exists():
        logger.warning(f"{user.username} intentó ligar el preapproval {preapproval_id}, que ya es de otro usuario")
        return False
    mp_service = MercadoPagoService()
    respuesta = mp_service.sdk.preapproval().get(preapproval_id)
    if respuesta.get("status") != 200:
        logger.warning(f"Mercado Pago respondió {respuesta.get('status')} al consultar {preapproval_id}")
        return False
    sub_data = respuesta["response"]
    if sub_data.get("preapproval_plan_id") not in mp_service.planes.values():
        logger.warning(f"El preapproval {preapproval_id} no es de ninguno de nuestros planes")
        return False
    suscripcion, _ = Suscripcion.objects.get_or_create(usuario=user)
    _aplicar_estado_mp(suscripcion, sub_data, mp_service, preapproval_id)
    logger.info(f"Preapproval {preapproval_id} ({sub_data.get('status')}) ligado a {user.username} al regresar de Mercado Pago")
    return True


@login_required
def suscripcion_exitosa(request):
    """Regreso desde Mercado Pago después de pagar. Si la URL trae ``preapproval_id``, se liga esa
    suscripción al usuario que está logueado y se activa de una vez (sin esperar al webhook)."""
    logger.info(f"Regreso de Mercado Pago de {request.user.username} con parámetros {request.GET.dict()}")
    preapproval_id = request.GET.get('preapproval_id')
    if preapproval_id:
        try:
            if _vincular_preapproval(request.user, preapproval_id):
                suscripcion = Suscripcion.objects.get(usuario=request.user)
                if suscripcion.is_active():
                    nombre = planes.PLANES[suscripcion.plan]['nombre']
                    messages.success(request, f"¡Listo! Tu plan {nombre} ya está activo.")
                    return redirect('gestionar_suscripcion')
        except Exception as e:
            logger.exception(f"Error ligando el preapproval {preapproval_id} a {request.user.username}: {e}")
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

                # ¿De quién es? Por id guardado, por external_reference o por correo del pagador
                suscripcion_obj = _suscripcion_de(subscription_id, sub_data)
                if suscripcion_obj is None:
                    # 404: Mercado Pago reintenta más tarde; para entonces el usuario pudo haber
                    # regresado a /suscripcion/exitosa/ y el preapproval ya estará ligado por id
                    logger.warning(f"Webhook del preapproval {subscription_id}: ningún usuario con ese id, "
                                   f"external_reference ni correo {sub_data.get('payer_email')}")
                    return HttpResponse(status=404)

                _aplicar_estado_mp(suscripcion_obj, sub_data, mp_service, subscription_id)

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
    
