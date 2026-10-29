# Conciliación bancaria: saldo del estado de cuenta por cuenta y mes.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('finanzas', '0025_ahorro_como_transferencia'),
    ]

    operations = [
        migrations.CreateModel(
            name='SaldoEstadoCuenta',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('anio', models.PositiveIntegerField()),
                ('mes', models.PositiveSmallIntegerField()),
                ('saldo_banco', models.DecimalField(decimal_places=2, max_digits=20)),
                ('nota', models.CharField(blank=True, default='', max_length=200)),
                ('actualizado', models.DateTimeField(auto_now=True)),
                ('cuenta', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='saldos_banco', to='finanzas.cuenta')),
            ],
            options={
                'ordering': ['cuenta', 'anio', 'mes'],
                'unique_together': {('cuenta', 'anio', 'mes')},
            },
        ),
    ]
