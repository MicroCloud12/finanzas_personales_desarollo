# Finanzas Personales

Este proyecto es una aplicación web desarrollada en Django para llevar el control de finanzas personales.

## Características principales

- Registro de transacciones de ingresos y gastos.
- Administración de inversiones y cálculo de ganancias mensuales.
- Integración con Google Drive y Gemini para procesar tickets de compra en imágenes o PDF.
- Tareas asíncronas gestionadas con Celery y Redis.

## Requisitos

- Python 3.11+
- Redis en funcionamiento (por defecto en `redis://localhost:6379/0`).
- Las dependencias listadas en `requirements.txt`.

Instale todo con:

```bash
pip install -r requirements.txt
```

## Ejecución del servidor

Active su entorno virtual e inicie el servidor de desarrollo:

```bash
python manage.py migrate
python manage.py runserver
```

## Cálculo de ganancias mensuales

El comando `update_monthly_profits` calcula y almacena las ganancias o pérdidas no realizadas de todas las inversiones. Ejecútelo así:

```bash
python manage.py update_monthly_profits
```

Este proceso consultará la API de precios y almacenará los resultados en la tabla `GananciaMensual`. El dashboard leerá estos datos ya guardados.

### Programar la actualización

Puede automatizar este comando de dos maneras:

#### Con Celery Beat

1. Asegúrese de que `celery` esté configurado correctamente. Inicie un worker con:

```bash
celery -A config worker -l info
```

2. Inicie un proceso `beat` para lanzar el comando de forma periódica (por ejemplo, cada día primero de mes):

```bash
celery -A config beat -l info
```

Configure el intervalo en `CELERY_BEAT_SCHEDULE` dentro de `config/settings.py` si desea personalizar la frecuencia.

#### Con Cron

También puede usar cron si prefiere ejecutar el comando mediante un cron job. Un ejemplo para ejecutarlo cada primero de mes a las 2:00 a.m. sería:

```
0 2 1 * * cd /ruta/al/proyecto && /usr/bin/python manage.py update_monthly_profits >> cron.log 2>&1
```

De esta forma el dashboard siempre utilizará la información precalculada.


#### Accesar a la base de datos en Docker 
1. Ejecutar: docker-compose exec db /bin/bash
2. Después Ejecutar: mysql -u finanzas_user -p finanzas_db
3. Contrasñea: se encuentra dentro del .env