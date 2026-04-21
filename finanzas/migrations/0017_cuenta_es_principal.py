# Generated manually
from django.db import migrations, models

class Migration(migrations.Migration):

    dependencies = [
        ('finanzas', '0016_merge_20260411_2049'),
    ]

    operations = [
        migrations.AddField(
            model_name='cuenta',
            name='es_principal',
            field=models.BooleanField(default=False, help_text='Marcar como tarjeta principal o preferida'),
        ),
    ]
