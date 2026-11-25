from django.db import migrations, models


def marcar_fijos_con_dia_pago(apps, schema_editor):
    Presupuesto = apps.get_model('finanzas', 'Presupuesto')
    Presupuesto.objects.filter(dia_pago__isnull=False).update(es_fijo=True)


class Migration(migrations.Migration):

    dependencies = [
        ('finanzas', '0031_presupuesto_dia_pago'),
    ]

    operations = [
        migrations.AddField(
            model_name='presupuesto',
            name='es_fijo',
            field=models.BooleanField(
                default=False,
                help_text='Actívalo si pagas un monto fijo cada mes (renta, muchacha, suscripción), aunque no tenga un solo día de pago.',
            ),
        ),
        migrations.AlterField(
            model_name='presupuesto',
            name='dia_pago',
            field=models.PositiveIntegerField(
                blank=True,
                help_text='Día del mes en que lo pagas (1-31), opcional en gastos de monto fijo.',
                null=True,
            ),
        ),
        migrations.RunPython(marcar_fijos_con_dia_pago, migrations.RunPython.noop),
    ]
