"""
Lógica de la migración de datos al libro mayor (usada por 0024_libro_mayor).

Está en un módulo aparte (con guion bajo, para que Django no lo trate como
migración) para poder probarla con pruebas unitarias.

Trabaja únicamente con campos y consultas (sin métodos de modelo) para que
funcione igual con los modelos "históricos" que Django entrega a RunPython.
"""
from decimal import Decimal
from collections import defaultdict

from django.db.models import F, Sum

CERO = Decimal('0.00')
NOMBRES_VACIOS = {'', 'N/A', 'NA', 'SIN CUENTA', 'OTRA CUENTA', 'NONE', '-'}
TIPOS_PAGO_DEUDA = ('PAGO_MENSUALIDAD', 'PAGO_CAPITAL')
TIPO_CUENTA_POR_DEUDA = {'PRESTAMO': 'PRESTAMO', 'TARJETA_CREDITO': 'CREDITO'}


def _normaliza(nombre):
    return (nombre or '').strip().upper()


def _indice_cuentas(Cuenta):
    """{(propietario_id, NOMBRE): cuenta} para cruzar nombres rápidamente."""
    indice = {}
    for c in Cuenta.objects.all():
        indice[(c.propietario_id, _normaliza(c.nombre))] = c
    return indice


def ligar_deudas_a_cuentas(apps, reporte):
    """Paso 1: cada Deuda queda ligada a una Cuenta de pasivo (se crea si no existe)."""
    Cuenta = apps.get_model('finanzas', 'Cuenta')
    Deuda = apps.get_model('finanzas', 'Deuda')
    indice = _indice_cuentas(Cuenta)

    for deuda in Deuda.objects.all():
        tipo_cuenta = TIPO_CUENTA_POR_DEUDA.get(deuda.tipo_deuda, 'PRESTAMO')
        cuenta = indice.get((deuda.propietario_id, _normaliza(deuda.nombre)))
        if cuenta is None:
            cuenta = Cuenta.objects.create(
                propietario_id=deuda.propietario_id, nombre=deuda.nombre, tipo=tipo_cuenta,
                fecha_saldo_inicial=deuda.fecha_adquisicion)
            indice[(deuda.propietario_id, _normaliza(deuda.nombre))] = cuenta
            reporte['cuentas_creadas'] += 1
        elif cuenta.tipo != tipo_cuenta:
            cuenta.tipo = tipo_cuenta
            cuenta.save(update_fields=['tipo'])
            reporte['cuentas_retipadas'] += 1
        if deuda.cuenta_id != cuenta.id:
            deuda.cuenta_id = cuenta.id
            deuda.save(update_fields=['cuenta'])

    # Tarjetas de crédito dadas de alta como Cuenta pero sin su Deuda (detalle).
    for cuenta in Cuenta.objects.filter(tipo__in=('CREDITO', 'PRESTAMO')):
        if not Deuda.objects.filter(cuenta_id=cuenta.id).exists():
            if Deuda.objects.filter(propietario_id=cuenta.propietario_id, nombre=cuenta.nombre).exists():
                continue
            Deuda.objects.create(
                propietario_id=cuenta.propietario_id, nombre=cuenta.nombre, cuenta_id=cuenta.id,
                tipo_deuda='TARJETA_CREDITO' if cuenta.tipo == 'CREDITO' else 'PRESTAMO',
                monto_total=CERO, tasa_interes=CERO, plazo_meses=1,
                requiere_configuracion_adicional=True)
            reporte['deudas_creadas'] += 1
    return indice


def _interes_de_cuota(PagoAmortizacion, transaccion_id):
    cuota = PagoAmortizacion.objects.filter(transaccion_pago_id=transaccion_id).first()
    if cuota is None:
        return CERO
    return (cuota.interes or CERO) + (cuota.iva or CERO)


def migrar_transacciones(apps, reporte, indice=None):
    """
    Paso 2: convierte los nombres de cuenta (texto) en claves foráneas y
    unifica la semántica origen/destino por tipo de movimiento.
    """
    Cuenta = apps.get_model('finanzas', 'Cuenta')
    Deuda = apps.get_model('finanzas', 'Deuda')
    Tx = apps.get_model('finanzas', 'registro_transacciones')
    PagoAmortizacion = apps.get_model('finanzas', 'PagoAmortizacion')
    indice = indice or _indice_cuentas(Cuenta)
    cuenta_de_deuda = {d.id: d.cuenta_id for d in Deuda.objects.all()}
    deuda_de_cuenta = {c_id: d_id for d_id, c_id in cuenta_de_deuda.items() if c_id}

    def buscar(propietario_id, nombre):
        nombre_n = _normaliza(nombre)
        if nombre_n in NOMBRES_VACIOS:
            return None
        cuenta = indice.get((propietario_id, nombre_n))
        if cuenta is None:
            reporte['nombres_sin_cuenta'][nombre.strip()] += 1
            return None
        return cuenta

    campos_tx = {f.name for f in Tx._meta.get_fields()}
    tiene_tipo_pago = 'tipo_pago' in campos_tx

    for tx in Tx.objects.all().iterator(chunk_size=500):
        origen = buscar(tx.propietario_id, tx.cuenta_origen)
        destino = buscar(tx.propietario_id, tx.cuenta_destino)
        cuenta_deuda_id = cuenta_de_deuda.get(tx.deuda_asociada_id) if tx.deuda_asociada_id else None
        interes = CERO

        if tx.tipo == 'INGRESO':
            # Antes: el campo "origen" guardaba la cuenta a la que ENTRABA el ingreso.
            destino_final = origen or destino
            origen_final = None
        elif tx.tipo == 'GASTO':
            origen_final = origen
            destino_final = None
            # Compra con tarjeta registrada vía deuda_asociada (tipo_pago TARJETA_CREDITO)
            if origen_final is None and cuenta_deuda_id and tiene_tipo_pago and getattr(tx, 'tipo_pago', '') == 'TARJETA_CREDITO':
                origen_final = Cuenta.objects.get(id=cuenta_deuda_id)
        elif tx.tipo == 'TRANSFERENCIA':
            origen_final = origen
            destino_final = destino
            if destino_final is None and cuenta_deuda_id:
                destino_final = Cuenta.objects.get(id=cuenta_deuda_id)
        elif tx.tipo in TIPOS_PAGO_DEUDA:
            origen_final = origen
            destino_final = Cuenta.objects.get(id=cuenta_deuda_id) if cuenta_deuda_id else destino
            if tx.tipo == 'PAGO_MENSUALIDAD':
                interes = min(_interes_de_cuota(PagoAmortizacion, tx.id), tx.monto or CERO)
        else:
            origen_final, destino_final = origen, destino

        tx.origen_id = origen_final.id if origen_final else None
        tx.destino_id = destino_final.id if destino_final else None
        tx.monto_interes = interes
        # deuda_asociada se deriva de la cuenta de pasivo involucrada
        tx.deuda_asociada_id = None
        for cuenta in (destino_final, origen_final):
            if cuenta is not None and cuenta.tipo in ('CREDITO', 'PRESTAMO'):
                tx.deuda_asociada_id = deuda_de_cuenta.get(cuenta.id)
                break
        tx.save(update_fields=['origen', 'destino', 'monto_interes', 'deuda_asociada'])
        reporte['transacciones'] += 1
        if tx.origen_id is None and tx.destino_id is None:
            reporte['transacciones_sin_cuenta'] += 1


def conciliar_saldos_de_deudas(apps, reporte):
    """
    Paso 3 (conciliación): el saldo derivado del libro debe coincidir con la
    deuda real que el sistema anterior tenía en `saldo_legado`.
    La diferencia se registra como saldo inicial de la cuenta de pasivo.

      Sistema anterior: tarjeta  -> saldo_legado = crédito DISPONIBLE  => deuda = límite - disponible
                        préstamo -> saldo_legado = lo que se DEBE
      Libro mayor:      deuda = saldo_inicial - neto   =>  saldo_inicial = deuda + neto
    """
    Cuenta = apps.get_model('finanzas', 'Cuenta')
    Deuda = apps.get_model('finanzas', 'Deuda')
    Tx = apps.get_model('finanzas', 'registro_transacciones')

    for deuda in Deuda.objects.exclude(cuenta__isnull=True):
        if deuda.saldo_legado is None:
            continue
        if deuda.tipo_deuda == 'TARJETA_CREDITO':
            deuda_real = (deuda.monto_total or CERO) - deuda.saldo_legado
        else:
            deuda_real = deuda.saldo_legado
        entradas = Tx.objects.filter(destino_id=deuda.cuenta_id).aggregate(
            t=Sum(F('monto') - F('monto_interes')))['t'] or CERO
        salidas = Tx.objects.filter(origen_id=deuda.cuenta_id).aggregate(t=Sum('monto'))['t'] or CERO
        neto = entradas - salidas
        saldo_inicial = deuda_real + neto
        Cuenta.objects.filter(id=deuda.cuenta_id).update(saldo_inicial=saldo_inicial)
        reporte['deudas_conciliadas'] += 1
        if saldo_inicial != 0:
            reporte['ajustes_saldo_inicial'][deuda.nombre] = saldo_inicial


def nuevo_reporte():
    return {
        'cuentas_creadas': 0, 'cuentas_retipadas': 0, 'deudas_creadas': 0,
        'transacciones': 0, 'transacciones_sin_cuenta': 0,
        'nombres_sin_cuenta': defaultdict(int),
        'deudas_conciliadas': 0, 'ajustes_saldo_inicial': {},
    }


def migrar_a_libro_mayor(apps, schema_editor=None, verbose=True):
    reporte = nuevo_reporte()
    indice = ligar_deudas_a_cuentas(apps, reporte)
    migrar_transacciones(apps, reporte, indice)
    conciliar_saldos_de_deudas(apps, reporte)
    if verbose:
        print("\n[libro mayor] Migración de datos:")
        print(f"  cuentas creadas para deudas: {reporte['cuentas_creadas']}, retipadas: {reporte['cuentas_retipadas']}, deudas creadas para tarjetas: {reporte['deudas_creadas']}")
        print(f"  transacciones migradas: {reporte['transacciones']} (sin ninguna cuenta reconocida: {reporte['transacciones_sin_cuenta']})")
        if reporte['nombres_sin_cuenta']:
            print("  nombres de cuenta que no existen en el catálogo (revísalos con `manage.py conciliar_saldos`):")
            for nombre, n in sorted(reporte['nombres_sin_cuenta'].items(), key=lambda x: -x[1]):
                print(f"    - {nombre!r}: {n} movimientos")
        print(f"  deudas conciliadas: {reporte['deudas_conciliadas']}")
        for nombre, saldo in reporte['ajustes_saldo_inicial'].items():
            print(f"    - {nombre}: saldo inicial de pasivo = {saldo}")
    return reporte


def revertir(apps, schema_editor=None):
    """Reversa: solo limpia los campos nuevos; los nombres de texto siguen intactos."""
    Tx = apps.get_model('finanzas', 'registro_transacciones')
    Tx.objects.update(origen=None, destino=None, monto_interes=CERO)


# ---------------------------------------------------------------------------
# 0025: los ahorros no son gasto. Todo movimiento con categoría "Ahorro" (o cuyo
# destino de texto era la antigua "Cuenta Ahorro") pasa a ser una TRANSFERENCIA
# hacia la cuenta de tipo AHORRO del usuario (se crea si no existe).
# ---------------------------------------------------------------------------
def migrar_ahorros(apps, schema_editor=None, verbose=True):
    from django.db.models import Q
    Cuenta = apps.get_model('finanzas', 'Cuenta')
    Tx = apps.get_model('finanzas', 'registro_transacciones')

    filtro_ahorro = (Q(categoria__iexact='Ahorro') | Q(cuenta_destino__iexact='Cuenta Ahorro')
                     | Q(cuenta_destino__icontains='ahorro'))
    candidatos = Tx.objects.filter(filtro_ahorro, tipo__in=('GASTO', 'TRANSFERENCIA')).exclude(destino__tipo='AHORRO')
    usuarios = candidatos.values_list('propietario_id', flat=True).distinct()

    resumen = []
    for propietario_id in usuarios:
        ahorro = Cuenta.objects.filter(propietario_id=propietario_id, tipo='AHORRO').order_by('id').first()
        if ahorro is None:
            ahorro = Cuenta.objects.filter(propietario_id=propietario_id, nombre__icontains='ahorro').order_by('id').first()
            if ahorro is not None:
                ahorro.tipo = 'AHORRO'
                ahorro.save(update_fields=['tipo'])
            else:
                ahorro = Cuenta.objects.create(propietario_id=propietario_id, nombre='Cuenta Ahorro', tipo='AHORRO')
        qs = candidatos.filter(propietario_id=propietario_id)
        sin_origen = qs.filter(origen__isnull=True).count()
        n = qs.update(destino_id=ahorro.id, tipo='TRANSFERENCIA', monto_interes=CERO)
        resumen.append((propietario_id, ahorro.nombre, n, sin_origen))

    if verbose and resumen:
        print("\n[libro mayor] Ahorros reclasificados como transferencias a la cuenta de ahorro:")
        for propietario_id, nombre, n, sin_origen in resumen:
            extra = f" ({sin_origen} sin cuenta de origen reconocida; revísalos con conciliar_saldos)" if sin_origen else ""
            print(f"  usuario {propietario_id}: {n} movimientos -> '{nombre}'{extra}")
    return resumen
