import logging

from django.utils import timezone
from django.contrib import messages
from django.contrib.auth import login
from django.core.mail import send_mail
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect


from allauth.socialaccount.models import SocialAccount

from ..forms import FormularioRegistroPersonalizado
from ..models import Suscripcion

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
    }
    return render(request, 'mi_perfil.html', context)

