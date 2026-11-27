# Generated for Level 2 per-user encryption schema transition

import django.db.models.deletion
import finanzas.fields
from decimal import Decimal
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('finanzas', '0033_planes_y_uso_ia'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='LlaveUsuario',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('dek_cifrada', models.CharField(max_length=255)),
                ('creada', models.DateTimeField(auto_now_add=True)),
                ('usuario', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='llave_cifrado', to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.AlterUniqueTogether(
            name='aliascomercio',
            unique_together=set(),
        ),
        migrations.AlterUniqueTogether(
            name='cuenta',
            unique_together=set(),
        ),
        migrations.AlterUniqueTogether(
            name='deuda',
            unique_together=set(),
        ),
        migrations.AlterUniqueTogether(
            name='presupuesto',
            unique_together=set(),
        ),
        migrations.AddField(
            model_name='aliascomercio',
            name='texto_banco_hash',
            field=models.CharField(db_index=True, default='', editable=False, max_length=64),
        ),
        migrations.AddField(
            model_name='cuenta',
            name='nombre_hash',
            field=models.CharField(db_index=True, default='', editable=False, max_length=64),
        ),
        migrations.AddField(
            model_name='deuda',
            name='nombre_hash',
            field=models.CharField(db_index=True, default='', editable=False, max_length=64),
        ),
        migrations.AddField(
            model_name='factura',
            name='archivo_drive_hash',
            field=models.CharField(blank=True, db_index=True, editable=False, max_length=64, null=True),
        ),
        migrations.AddField(
            model_name='historialreciboservicio',
            name='archivo_drive_hash',
            field=models.CharField(default='', editable=False, max_length=64),
        ),
        migrations.AddField(
            model_name='presupuesto',
            name='categoria_hash',
            field=models.CharField(db_index=True, default='', editable=False, max_length=64),
        ),
        migrations.AlterField(
            model_name='aliascomercio',
            name='categoria',
            field=finanzas.fields.EncryptedCharField(blank=True, default='', max_length=100),
        ),
        migrations.AlterField(
            model_name='aliascomercio',
            name='descripcion',
            field=finanzas.fields.EncryptedCharField(help_text="Como quieres verlo, ej. 'DIDI'", max_length=100),
        ),
        migrations.AlterField(
            model_name='aliascomercio',
            name='texto_banco',
            field=finanzas.fields.EncryptedCharField(help_text="Como lo escribe el banco, ej. 'SUPER RIDES'", max_length=100),
        ),
        migrations.AlterField(
            model_name='amortizacionpendiente',
            name='datos_json',
            field=finanzas.fields.EncryptedJSONField(),
        ),
        migrations.AlterField(
            model_name='amortizacionpendiente',
            name='nombre_archivo',
            field=finanzas.fields.EncryptedCharField(max_length=255),
        ),
        migrations.AlterField(
            model_name='cuenta',
            name='nombre',
            field=finanzas.fields.EncryptedCharField(help_text='Ej. Tarjeta Banamex, Efectivo Quincena, NuBank', max_length=50),
        ),
        migrations.AlterField(
            model_name='cuenta',
            name='saldo_inicial',
            field=finanzas.fields.EncryptedDecimalField(decimal_places=2, default=Decimal('0.00'), help_text='Activos: dinero que había antes del primer movimiento registrado. Pasivos: deuda que había antes del primer movimiento registrado.', max_digits=20),
        ),
        migrations.AlterField(
            model_name='cuenta',
            name='terminacion',
            field=finanzas.fields.EncryptedCharField(blank=True, help_text='Últimos 4 dígitos de la tarjeta (opcional)', max_length=4, null=True),
        ),
        migrations.AlterField(
            model_name='deuda',
            name='monto_total',
            field=finanzas.fields.EncryptedDecimalField(decimal_places=2, help_text='Para préstamos: el monto original. Para tarjetas de crédito: el límite de crédito total.', max_digits=12),
        ),
        migrations.AlterField(
            model_name='deuda',
            name='nombre',
            field=finanzas.fields.EncryptedCharField(help_text="Un nombre único para identificar esta deuda (ej. 'Préstamo Coche')", max_length=100),
        ),
        migrations.AlterField(
            model_name='deuda',
            name='saldo_legado',
            field=finanzas.fields.EncryptedDecimalField(blank=True, decimal_places=2, editable=False, max_digits=12, null=True),
        ),
        migrations.AlterField(
            model_name='deuda',
            name='tasa_interes',
            field=finanzas.fields.EncryptedDecimalField(decimal_places=2, help_text='Tasa de interés anual (%)', max_digits=5),
        ),
        migrations.AlterField(
            model_name='factura',
            name='archivo_drive_id',
            field=finanzas.fields.EncryptedCharField(blank=True, help_text='ID del archivo en Google Drive para ver la imagen original', max_length=255, null=True),
        ),
        migrations.AlterField(
            model_name='factura',
            name='datos_facturacion',
            field=finanzas.fields.EncryptedJSONField(default=dict, help_text='Datos técnicos extraídos para el portal de facturación'),
        ),
        migrations.AlterField(
            model_name='factura',
            name='tienda',
            field=finanzas.fields.EncryptedCharField(help_text='Nombre extraído del establecimiento', max_length=150),
        ),
        migrations.AlterField(
            model_name='factura',
            name='total',
            field=finanzas.fields.EncryptedDecimalField(decimal_places=2, help_text='Monto total del consumo', max_digits=12),
        ),
        migrations.AlterField(
            model_name='historialreciboservicio',
            name='archivo_drive_id',
            field=finanzas.fields.EncryptedCharField(max_length=255),
        ),
        migrations.AlterField(
            model_name='historialreciboservicio',
            name='datos_json',
            field=finanzas.fields.EncryptedJSONField(default=dict),
        ),
        migrations.AlterField(
            model_name='historialreciboservicio',
            name='monto_total',
            field=finanzas.fields.EncryptedDecimalField(decimal_places=2, max_digits=12),
        ),
        migrations.AlterField(
            model_name='inversiones',
            name='cantidad_titulos',
            field=finanzas.fields.EncryptedDecimalField(decimal_places=10, max_digits=19),
        ),
        migrations.AlterField(
            model_name='inversiones',
            name='costo_total_adquisicion',
            field=finanzas.fields.EncryptedDecimalField(decimal_places=10, max_digits=20),
        ),
        migrations.AlterField(
            model_name='inversiones',
            name='emisora_ticker',
            field=finanzas.fields.EncryptedCharField(blank=True, max_length=10, null=True),
        ),
        migrations.AlterField(
            model_name='inversiones',
            name='ganancia_perdida',
            field=finanzas.fields.EncryptedDecimalField(blank=True, decimal_places=10, max_digits=20, null=True),
        ),
        migrations.AlterField(
            model_name='inversiones',
            name='ganancia_perdida_no_realizada',
            field=finanzas.fields.EncryptedDecimalField(decimal_places=10, max_digits=20),
        ),
        migrations.AlterField(
            model_name='inversiones',
            name='nombre_activo',
            field=finanzas.fields.EncryptedCharField(max_length=100),
        ),
        migrations.AlterField(
            model_name='inversiones',
            name='precio_actual_titulo',
            field=finanzas.fields.EncryptedDecimalField(decimal_places=10, max_digits=19),
        ),
        migrations.AlterField(
            model_name='inversiones',
            name='precio_compra_titulo',
            field=finanzas.fields.EncryptedDecimalField(decimal_places=10, max_digits=19),
        ),
        migrations.AlterField(
            model_name='inversiones',
            name='tipo_cambio_compra',
            field=finanzas.fields.EncryptedDecimalField(blank=True, decimal_places=4, max_digits=10, null=True),
        ),
        migrations.AlterField(
            model_name='inversiones',
            name='valor_actual_mercado',
            field=finanzas.fields.EncryptedDecimalField(decimal_places=10, max_digits=20),
        ),
        migrations.AlterField(
            model_name='pagoamortizacion',
            name='capital',
            field=finanzas.fields.EncryptedDecimalField(decimal_places=2, max_digits=10),
        ),
        migrations.AlterField(
            model_name='pagoamortizacion',
            name='interes',
            field=finanzas.fields.EncryptedDecimalField(decimal_places=2, max_digits=10),
        ),
        migrations.AlterField(
            model_name='pagoamortizacion',
            name='iva',
            field=finanzas.fields.EncryptedDecimalField(decimal_places=2, default=Decimal('0.00'), help_text='IVA sobre los intereses', max_digits=10),
        ),
        migrations.AlterField(
            model_name='pagoamortizacion',
            name='pago_total',
            field=finanzas.fields.EncryptedDecimalField(decimal_places=2, help_text='Suma de capital + interés + IVA', max_digits=10),
        ),
        migrations.AlterField(
            model_name='pagoamortizacion',
            name='saldo_insoluto',
            field=finanzas.fields.EncryptedDecimalField(decimal_places=2, help_text='Saldo pendiente después de este pago', max_digits=12),
        ),
        migrations.AlterField(
            model_name='pendinginvestment',
            name='datos_json',
            field=finanzas.fields.EncryptedJSONField(),
        ),
        migrations.AlterField(
            model_name='portfoliohistory',
            name='capital_invertido',
            field=finanzas.fields.EncryptedDecimalField(decimal_places=2, max_digits=20),
        ),
        migrations.AlterField(
            model_name='portfoliohistory',
            name='ganancia_no_realizada',
            field=finanzas.fields.EncryptedDecimalField(decimal_places=2, max_digits=20),
        ),
        migrations.AlterField(
            model_name='portfoliohistory',
            name='valor_total',
            field=finanzas.fields.EncryptedDecimalField(decimal_places=2, max_digits=20),
        ),
        migrations.AlterField(
            model_name='presupuesto',
            name='categoria',
            field=finanzas.fields.EncryptedCharField(help_text='Ej. Vivienda, Alimentación, Transporte', max_length=100),
        ),
        migrations.AlterField(
            model_name='presupuesto',
            name='monto_presupuestado',
            field=finanzas.fields.EncryptedDecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=12),
        ),
        migrations.AlterField(
            model_name='presupuesto',
            name='monto_real',
            field=finanzas.fields.EncryptedDecimalField(decimal_places=2, default=Decimal('0.00'), help_text='Monto real gastado o facturado', max_digits=12),
        ),
        migrations.AlterField(
            model_name='registro_transacciones',
            name='categoria',
            field=finanzas.fields.EncryptedCharField(max_length=100),
        ),
        migrations.AlterField(
            model_name='registro_transacciones',
            name='cuenta_destino',
            field=finanzas.fields.EncryptedCharField(blank=True, default='', editable=False, max_length=100),
        ),
        migrations.AlterField(
            model_name='registro_transacciones',
            name='cuenta_origen',
            field=finanzas.fields.EncryptedCharField(blank=True, default='', editable=False, max_length=100),
        ),
        migrations.AlterField(
            model_name='registro_transacciones',
            name='datos_extra',
            field=finanzas.fields.EncryptedJSONField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name='registro_transacciones',
            name='descripcion',
            field=finanzas.fields.EncryptedCharField(max_length=100),
        ),
        migrations.AlterField(
            model_name='registro_transacciones',
            name='monto',
            field=finanzas.fields.EncryptedDecimalField(decimal_places=3, max_digits=20),
        ),
        migrations.AlterField(
            model_name='registro_transacciones',
            name='monto_interes',
            field=finanzas.fields.EncryptedDecimalField(decimal_places=3, default=Decimal('0.00'), max_digits=20),
        ),
        migrations.AlterField(
            model_name='saldoestadocuenta',
            name='nota',
            field=finanzas.fields.EncryptedCharField(blank=True, default='', max_length=200),
        ),
        migrations.AlterField(
            model_name='saldoestadocuenta',
            name='saldo_banco',
            field=finanzas.fields.EncryptedDecimalField(decimal_places=2, max_digits=20),
        ),
        migrations.AlterField(
            model_name='transaccionpendiente',
            name='datos_json',
            field=finanzas.fields.EncryptedJSONField(),
        ),
    ]
