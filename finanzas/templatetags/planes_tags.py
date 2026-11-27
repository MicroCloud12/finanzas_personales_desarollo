"""Etiquetas de los planes: cuota de documentos con IA del mes."""
from django import template

from .. import planes

register = template.Library()


@register.inclusion_tag('partials/_cuota_ia.html', takes_context=True)
def cuota_ia(context):
    """Línea 'X de Y documentos con IA este mes · plan Z' con enlace a los planes."""
    user = context['request'].user
    return {'cuota': planes.resumen_cuota(user)}
