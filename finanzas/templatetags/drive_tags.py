"""Google Drive se conecta aparte del login.

Entrar con Google solo pide nombre y correo. Leer Drive es un permiso "restringido" para
Google, así que se pide únicamente cuando el usuario pulsa "Conectar Google Drive": allauth
vuelve a mandar a Google con ese permiso extra (process=connect + scope) y Google regresa a la
vista `drive_conectado`, que comprueba el permiso y deja la marca `drive_ok` en la cuenta social.
"""
from urllib.parse import quote, urlencode

from django import template
from django.conf import settings
from django.urls import reverse

from allauth.socialaccount.models import SocialAccount

register = template.Library()

# offline + consent: para que Google entregue un refresh token con el permiso de Drive.
# include_granted_scopes: conserva también el de identidad en el mismo token.
AUTH_PARAMS_DRIVE = 'access_type=offline&prompt=consent&include_granted_scopes=true'


def cuenta_google(user):
    if not getattr(user, 'is_authenticated', False):
        return None
    return SocialAccount.objects.filter(user=user, provider='google').first()


@register.filter
def tiene_drive(user):
    """True si el usuario ya dio permiso de lectura a su Drive."""
    cuenta = cuenta_google(user)
    return bool(cuenta and (cuenta.extra_data or {}).get('drive_ok'))


@register.simple_tag(takes_context=True)
def url_conectar_drive(context):
    """Enlace a Google pidiendo el permiso de Drive; al terminar regresa a la página actual."""
    request = context['request']
    regreso = reverse('drive_conectado') + '?next=' + quote(request.get_full_path(), safe='')
    # Misma URL que arma {% provider_login_url %}, sin depender de que la SocialApp exista al renderizar.
    return reverse('google_login') + '?' + urlencode({
        'process': 'connect', 'scope': settings.GOOGLE_DRIVE_SCOPE,
        'auth_params': AUTH_PARAMS_DRIVE, 'next': regreso})
