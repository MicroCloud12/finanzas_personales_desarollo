# Alias de comercios: cómo quiere el usuario que se llame lo que el banco escribe de cierta forma.

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('finanzas', '0029_suscripcion_fecha_cancelacion'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='AliasComercio',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('texto_banco', models.CharField(help_text="Como lo escribe el banco, ej. 'SUPER RIDES'", max_length=100)),
                ('descripcion', models.CharField(help_text="Como quieres verlo, ej. 'DIDI'", max_length=100)),
                ('categoria', models.CharField(blank=True, max_length=100)),
                ('propietario', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='alias_comercios', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Alias de comercio',
                'verbose_name_plural': 'Alias de comercios',
                'unique_together': {('propietario', 'texto_banco')},
            },
        ),
    ]
