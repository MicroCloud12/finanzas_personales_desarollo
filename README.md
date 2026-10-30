# Finanzas Personales

Este proyecto es una aplicación web desarrollada en Django para llevar el control de finanzas personales.

## Características principales

- Registro de transacciones en un **libro mayor**: cada movimiento sale de una cuenta y/o entra a otra, y los saldos se derivan de los movimientos (ver [Modelo contable](#modelo-contable-libro-mayor)).
- Administración de inversiones e historial diario del portafolio.
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

## Worker de Celery

El procesamiento de Drive (tickets, inversiones, amortizaciones, facturas y recibos) corre en Celery:

```bash
celery -A config worker -l info -P gevent -c 4
```

## Precios e historial del portafolio

```bash
python manage.py update_prices              # precio actual de cada inversión (Twelve Data)
python manage.py update_portfolio_history   # recalcula la gráfica de rendimiento diario
```

Para tenerlos al día puede programarlos con cron, por ejemplo cada noche:

```
0 2 * * * cd /ruta/al/proyecto && python manage.py update_prices && python manage.py update_portfolio_history >> cron.log 2>&1
```

#### Accesar a la base de datos en Docker 
1. Ejecutar: docker-compose exec db /bin/bash
2. Después Ejecutar: mysql -u finanzas_user -p finanzas_db
3. Contrasñea: se encuentra dentro del .env

## Modelo contable (libro mayor)

Desde la migración `0024_libro_mayor` el proyecto lleva las finanzas como un libro
mayor sencillo (partida doble simplificada):

- **`Cuenta`** es el único catálogo. Tipos de **activo**: `EFECTIVO`, `DEBITO`, `AHORRO`,
  `INVERSION`. Tipos de **pasivo**: `CREDITO` (tarjeta) y `PRESTAMO`. Cada `Deuda`
  (tasa, plazo, corte, amortización) está ligada 1:1 a su cuenta de pasivo.
- **`registro_transacciones`** es el libro diario. Cada movimiento tiene `origen`
  (cuenta de la que sale el dinero) y/o `destino` (cuenta a la que entra):

  | Tipo | Sale de `origen` | Entra a `destino` | ¿Es gasto? |
  |---|---|---|---|
  | `INGRESO` | — | sí | no (es ingreso) |
  | `GASTO` | sí (débito, efectivo **o tarjeta**) | — | sí |
  | `TRANSFERENCIA` | sí | sí (otra cuenta, **pagar tarjeta**, **ahorrar**) | no |
  | `PAGO_MENSUALIDAD` | `monto` | `monto - monto_interes` al préstamo | solo `monto_interes` |
  | `PAGO_CAPITAL` | `monto` | `monto` al préstamo | no |

- **El saldo nunca se guarda**: `Cuenta.saldo()` = `saldo_inicial` + entradas − salidas
  (para pasivos: `saldo_inicial` − entradas + salidas = lo que se debe). Editar o
  borrar un movimiento corrige el saldo solo; no hay nada que "revertir".
- El dashboard muestra **Ingresos**, **Gastos** (incluye compras con tarjeta e intereses;
  los pagos a tarjeta/abonos a capital no son gasto), **Balance del mes** (ingresos − gastos),
  **Disponible** (saldo de efectivo + débito), **Ahorro** (saldo de cuentas `AHORRO`) y
  **Deuda total** (saldo de cuentas de pasivo).

### Aplicar la migración sobre tu base de datos

```bash
python manage.py migrate finanzas
```

La migración liga cada deuda a su cuenta, convierte los nombres de cuenta en texto a
referencias reales, divide los pagos de préstamo en capital/interés usando la tabla de
amortización y **concilia** los saldos de las deudas contra el valor que tenía el campo
antiguo `saldo_pendiente` (conservado como `saldo_legado`). Al terminar imprime los
nombres de cuenta que no se pudieron reconocer.

### Pantalla "Resumen" (estado de resultados, cuadre y conciliación)

En el menú, **Resumen** muestra para el mes elegido: el estado de resultados contra el mes
anterior con variación $ y % y la bandera **Revisar** (cambio ≥ $500 y ≥ 20 %, umbrales
ajustables en la propia pantalla), el dinero que pasó entre tus cuentas (ahorro, pagos de
deuda, traspasos: no es gasto), el cuadre de cada cuenta (saldo inicial + entradas − salidas
= saldo final) y la **conciliación** contra el banco: capturas el saldo final de cada estado
de cuenta y la página te dice si CUADRA o cuánto falta por registrar. Arriba, en lenguaje
claro, qué cambió y qué conviene revisar.

### Conciliar y revisar (por terminal)

```bash
# Saldos de todas las cuentas según el libro + movimientos sin cuenta
python manage.py conciliar_saldos                      # todos los usuarios
python manage.py conciliar_saldos --usuario <username>  # solo uno

# Ligar movimientos viejos capturados con un nombre que ya no existe
python manage.py conciliar_saldos --usuario <username> --ligar "Efectivo Quincena=Efectivo"

# Fijar el saldo real de hoy (lo que dice el banco / lo que debes) de una cuenta
python manage.py conciliar_saldos --usuario <username> --set "BBVA=12345.67" --set "Tarjeta Nu=2300"

# Estado de resultados, flujo de efectivo y balance general del mes
python manage.py estado_financiero --usuario <username> --mes 2026-10
```

### Pruebas

La cadena de migraciones histórica no corre en una base vacía, así que las pruebas usan
SQLite con tablas generadas desde los modelos:

```bash
python manage.py test finanzas --settings=test_settings
```
