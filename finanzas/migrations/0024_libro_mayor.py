# Migración al "libro mayor": saldos derivados de los movimientos.
#
# 1. Cuenta gana saldo_inicial / fecha_saldo_inicial y los tipos AHORRO y PRESTAMO.
# 2. Deuda se liga 1:1 con una Cuenta de pasivo; su antiguo campo mutable
#    `saldo_pendiente` se conserva como `saldo_legado` (solo auditoría).
# 3. registro_transacciones gana origen/destino (FK a Cuenta) y monto_interes;
#    los nombres de texto se conservan como campos de solo lectura.
# 4. RunPython: liga deudas, convierte nombres a FK, concilia saldos iniciales.
# 5. Se elimina tipo_pago (su información ya vive en tipo + origen/destino).

from decimal import Decimal

import django.db.models.deletion
from django.db import migrations, models

from . import _libro_mayor


class Migration(migrations.Migration):

    dependencies = [
        ('finanzas', '0023_presupuesto_monto_real'),
    ]

    operations = [
        # --- Cuenta ---
        migrations.AddField(
            model_name='cuenta',
            name='saldo_inicial',
            field=models.DecimalField(decimal_places=2, default=Decimal('0.00'), help_text='Activos: dinero que había antes del primer movimiento registrado. Pasivos: deuda que había antes del primer movimiento registrado.', max_digits=20),
        ),
        migrations.AddField(
            model_name='cuenta',
            name='fecha_saldo_inicial',
            field=models.DateField(blank=True, help_text='Fecha a la que corresponde el saldo inicial (informativo).', null=True),
        ),
        migrations.AlterField(
            model_name='cuenta',
            name='tipo',
            field=models.CharField(choices=[('EFECTIVO', 'Efectivo'), ('DEBITO', 'Cuenta / Tarjeta de Débito'), ('AHORRO', 'Cuenta de Ahorro'), ('INVERSION', 'Cuenta de Inversión'), ('CREDITO', 'Tarjeta de Crédito'), ('PRESTAMO', 'Préstamo')], default='DEBITO', max_length=15),
        ),
        # --- Deuda ---
        migrations.AddField(
            model_name='deuda',
            name='cuenta',
            field=models.OneToOneField(blank=True, help_text='Cuenta de pasivo en el libro mayor donde se lleva el saldo de esta deuda.', null=True, on_delete=django.db.models.deletion.CASCADE, related_name='deuda', to='finanzas.cuenta'),
        ),
        migrations.RenameField(
            model_name='deuda',
            old_name='saldo_pendiente',
            new_name='saldo_legado',
        ),
        migrations.AlterField(
            model_name='deuda',
            name='saldo_legado',
            field=models.DecimalField(blank=True, decimal_places=2, editable=False, max_digits=12, null=True),
        ),
        # --- registro_transacciones ---
        migrations.AlterModelOptions(
            name='registro_transacciones',
            options={'ordering': ['-fecha', '-id']},
        ),
        migrations.AddField(
            model_name='registro_transacciones',
            name='origen',
            field=models.ForeignKey(blank=True, help_text='Cuenta de la que SALE el dinero', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='movimientos_salida', to='finanzas.cuenta'),
        ),
        migrations.AddField(
            model_name='registro_transacciones',
            name='destino',
            field=models.ForeignKey(blank=True, help_text='Cuenta a la que ENTRA el dinero', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='movimientos_entrada', to='finanzas.cuenta'),
        ),
        migrations.AddField(
            model_name='registro_transacciones',
            name='monto_interes',
            field=models.DecimalField(decimal_places=3, default=Decimal('0.00'), max_digits=20),
        ),
        migrations.AlterField(
            model_name='registro_transacciones',
            name='cuenta_origen',
            field=models.CharField(blank=True, default='', editable=False, max_length=100),
        ),
        migrations.AlterField(
            model_name='registro_transacciones',
            name='cuenta_destino',
            field=models.CharField(blank=True, default='', editable=False, max_length=100),
        ),
        # --- Datos ---
        migrations.RunPython(_libro_mayor.migrar_a_libro_mayor, _libro_mayor.revertir),
        # --- Limpieza ---
        migrations.RemoveField(
            model_name='registro_transacciones',
            name='tipo_pago',
        ),
    ]
