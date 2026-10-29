# Los ahorros no son gasto: se reclasifican como transferencias a la cuenta de
# tipo AHORRO del usuario (se crea "Cuenta Ahorro" si no existe).

from django.db import migrations

from . import _libro_mayor


class Migration(migrations.Migration):

    dependencies = [
        ('finanzas', '0024_libro_mayor'),
    ]

    operations = [
        migrations.RunPython(_libro_mayor.migrar_ahorros, migrations.RunPython.noop),
    ]
