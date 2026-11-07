# Cancelar suscripción desde el perfil: guarda cuándo se pidió la cancelación.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('finanzas', '0028_eliminar_modelos_sin_uso'),
    ]

    operations = [
        migrations.AddField(
            model_name='suscripcion',
            name='fecha_cancelacion',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
