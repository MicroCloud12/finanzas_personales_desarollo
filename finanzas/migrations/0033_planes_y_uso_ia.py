from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('finanzas', '0032_presupuesto_es_fijo'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='suscripcion',
            name='plan',
            field=models.CharField(choices=[('gratis', 'Gratis'), ('personal', 'Personal'), ('pro', 'Pro')], default='personal', max_length=10),
        ),
        migrations.AddField(
            model_name='suscripcion',
            name='periodo',
            field=models.CharField(choices=[('mensual', 'Mensual'), ('anual', 'Anual')], default='mensual', max_length=7),
        ),
        migrations.CreateModel(
            name='UsoIA',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('anio', models.PositiveIntegerField()),
                ('mes', models.PositiveSmallIntegerField()),
                ('documentos', models.PositiveIntegerField(default=0)),
                ('usuario', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='uso_ia', to=settings.AUTH_USER_MODEL)),
            ],
            options={'unique_together': {('usuario', 'anio', 'mes')}},
        ),
    ]
