"""Señales de la app.

allauth sustituye `SocialAccount.extra_data` con lo que manda Google en cada inicio de sesión; la
marca `drive_ok` (permiso de Drive concedido, ver la vista `drive_conectado`) la ponemos nosotros,
así que hay que conservarla al guardar.
"""
from django.db.models.signals import pre_save
from django.dispatch import receiver

from allauth.socialaccount.models import SocialAccount


@receiver(pre_save, sender=SocialAccount)
def conservar_marca_drive(sender, instance, **kwargs):
    if not instance.pk or 'drive_ok' in (instance.extra_data or {}):
        return
    anterior = SocialAccount.objects.filter(pk=instance.pk).values_list('extra_data', flat=True).first()
    if anterior and anterior.get('drive_ok'):
        instance.extra_data = {**(instance.extra_data or {}), 'drive_ok': True}
