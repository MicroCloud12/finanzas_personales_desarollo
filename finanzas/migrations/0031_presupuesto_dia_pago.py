# Presupuesto: día de pago para los gastos de monto fijo (renta, mensualidades, suscripciones).

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('finanzas', '0030_aliascomercio'),
    ]

    operations = [
        migrations.AddField(
            model_name='presupuesto',
            name='dia_pago',
            field=models.PositiveIntegerField(blank=True, help_text='Día del mes en que lo pagas (1-31) si es de monto fijo. Déjalo vacío si se estima con recibos.', null=True),
        ),
    ]
