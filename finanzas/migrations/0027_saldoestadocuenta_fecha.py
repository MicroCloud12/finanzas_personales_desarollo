from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('finanzas', '0026_saldoestadocuenta'),
    ]

    operations = [
        migrations.AddField(
            model_name='saldoestadocuenta',
            name='fecha',
            field=models.DateField(blank=True, null=True),
        ),
    ]
