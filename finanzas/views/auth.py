import logging

from django.utils import timezone
from django.contrib import messages
from django.contrib.auth import login, logout
from django.core.mail import send_mail
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.shortcuts import render, redirect


from allauth.socialaccount.models import SocialAccount

from ..forms import FormularioRegistroPersonalizado
from ..models import Suscripcion
from ..services import AccountService

logger = logging.getLogger(__name__)

def enviar_pregunta(request):
    if request.method == "POST":
        email = request.POST.get("email")
        message = request.POST.get("message")
        subject = "Nueva pregunta desde el sitio"
        body = f"Correo: {email}\n\nMensaje:\n{message}"
        send_mail(subject, body, None, [settings.EMAIL_HOST_USER])  # None = DEFAULT_FROM_EMAIL
        messages.success(request, "Tu mensaje ha sido enviado correctamente.")
    return redirect('home')

def home(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    return render(request, 'index.html')

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

def politica_privacidad(request):
    """
    Muestra la política de privacidad de la aplicación.
    """
    return render(request, 'privacy_policy.html')

def terminos_servicio(request):
    """
    Muestra los términos de servicio de la aplicación.
    """
    return render(request, 'terms_of_service.html')

@login_required
def mi_perfil(request):
    """
    Muestra y permite editar el perfil del usuario.
    """
    context = {
        'suscripcion': Suscripcion.objects.filter(usuario=request.user).first(),
        # La conexión real con Drive vive en la cuenta social de allauth
        'google_cuenta': SocialAccount.objects.filter(user=request.user, provider='google').first(),
        'today': timezone.now().date(),
        'palabra_confirmacion': AccountService.PALABRA_CONFIRMACION,
    }
    return render(request, 'mi_perfil.html', context)


@login_required
@require_POST
def eliminar_cuenta_usuario(request):
    """
    Borra definitivamente la cuenta del usuario y toda su información.
    El usuario confirma tecleando la palabra ELIMINAR (se valida también aquí,
    no solo en el navegador).
    """
    confirmacion = request.POST.get('confirmacion', '').strip().upper()
    if confirmacion != AccountService.PALABRA_CONFIRMACION:
        messages.error(request, f"Para eliminar tu cuenta escribe {AccountService.PALABRA_CONFIRMACION} en el cuadro de confirmación.")
        return redirect('mi_perfil')

    user = request.user
    try:
        AccountService.eliminar_cuenta(user)
    except Exception as e:
        logger.exception(f"No se pudo eliminar la cuenta de {user.username}: {e}")
        messages.error(request, "No pudimos cancelar tu suscripción en Mercado Pago, así que tu cuenta NO se eliminó. Intenta de nuevo en unos minutos.")
        return redirect('mi_perfil')

    # logout() limpia la sesión; el mensaje va después para que no se pierda con ella
    logout(request)
    messages.success(request, "Tu cuenta y toda tu información fueron eliminadas. ¡Gracias por usar la app!")
    return redirect('home')

