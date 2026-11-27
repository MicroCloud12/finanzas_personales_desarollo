"""
Paso 2 de cifrado Nivel 2:
  1. Cifra todos los registros existentes que aún estén en texto plano y calcula todos los *_hash.
  2. Activa las restricciones de unicidad sobre las columnas *_hash ya pobladas.
"""
from django.db import migrations, models
from . import _cifrado_datos


class Migration(migrations.Migration):

    dependencies = [
        ('finanzas', '0034_cifrado_esquema'),
    ]

    operations = [
        migrations.RunPython(
            _cifrado_datos.cifrar_datos_existentes,
            reverse_code=migrations.RunPython.noop,
        ),
        migrations.AlterField(
            model_name='historialreciboservicio',
            name='archivo_drive_hash',
            field=models.CharField(default='', editable=False, max_length=64, unique=True),
        ),
        migrations.AlterUniqueTogether(
            name='aliascomercio',
            unique_together={('propietario', 'texto_banco_hash')},
        ),
        migrations.AlterUniqueTogether(
            name='cuenta',
            unique_together={('propietario', 'nombre_hash')},
        ),
        migrations.AlterUniqueTogether(
            name='deuda',
            unique_together={('propietario', 'nombre_hash')},
        ),
        migrations.AlterUniqueTogether(
            name='presupuesto',
            unique_together={('propietario', 'categoria_hash', 'mes', 'anio')},
        ),
    ]
