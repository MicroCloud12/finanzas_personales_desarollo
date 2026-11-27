"""
Núcleo contable de Finanzas Personales: el "libro mayor" (con cifrado Nivel 2 por usuario).

Principios (partida doble simplificada para finanzas personales):

* ``Cuenta`` es el único catálogo de cuentas. Hay cuentas de ACTIVO (efectivo,
  débito, ahorro, inversión) y de PASIVO (tarjeta de crédito, préstamo).
* ``registro_transacciones`` es el libro diario. Cada movimiento tiene como
  máximo una cuenta de la que SALE dinero (``origen``) y una a la que ENTRA
  (``destino``). La categoría hace las veces de "cuenta de resultados".
* El saldo de una cuenta NUNCA se guarda ni se muta: se deriva del libro
  (saldo inicial + entradas - salidas). Editar o borrar un movimiento corrige
  el saldo automáticamente porque no hay nada que "revertir".
* Un pago de préstamo se divide en capital (reduce el pasivo) e interés+IVA
  (es gasto). Solo el interés entra al estado de resultados.

Convenciones por tipo de movimiento::

    INGRESO          -> entra a `destino`               (origen = None)
    GASTO            -> sale de `origen`                (destino = None)
                        si `origen` es una tarjeta de crédito, la deuda sube
    TRANSFERENCIA    -> sale de `origen`, entra a `destino`
                        (pagar una tarjeta = transferencia débito -> tarjeta;
                         ahorrar = transferencia débito -> cuenta de ahorro)
    PAGO_MENSUALIDAD -> sale `monto` de `origen`; entra `monto - monto_interes`
                        al préstamo `destino`; `monto_interes` es gasto
    PAGO_CAPITAL     -> igual que mensualidad, pero todo es capital
"""
import calendar
from collections import defaultdict
from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.signals import setting_changed
from django.db import models
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from django.utils import timezone

from .crypto import blind_index, clear_key_cache, global_blind_index
from .fields import (
    EncryptedCharField,
    EncryptedDecimalField,
    EncryptedJSONField,
    EncryptedQuerySet,
)

CERO = Decimal('0.00')

TIPOS_PAGO_DEUDA = ('PAGO_MENSUALIDAD', 'PAGO_CAPITAL')

_EncryptedManagerBase = models.Manager.from_queryset(EncryptedQuerySet)


class LlaveUsuario(models.Model):
    """Llave de cifrado de datos (DEK) única por usuario, envuelta con DATA_ENCRYPTION_KEY."""
    usuario = models.OneToOneField(User, on_delete=models.CASCADE, related_name='llave_cifrado')
    dek_cifrada = models.CharField(max_length=255)
    creada = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Llave de cifrado de usuario #{self.usuario_id}"


@receiver(post_save, sender=User)
def _limpiar_cache_llave_al_crear_usuario(sender, instance, created, **kwargs):
    if created and instance.pk:
        clear_key_cache(instance.pk)


@receiver(post_delete, sender=User)
def _limpiar_cache_llave_al_borrar_usuario(sender, instance, **kwargs):
    if instance.pk:
        clear_key_cache(instance.pk)


@receiver(setting_changed)
def _limpiar_cache_al_cambiar_setting(sender, setting, **kwargs):
    if setting == 'DATA_ENCRYPTION_KEY':
        clear_key_cache()


def _sync_blind_hashes(instance, kwargs_save: dict) -> None:
    """Calcula las columnas `*_hash` declaradas en `BLIND_INDEX_FIELDS` y las añade a `update_fields` si aplica."""
    blind_map = getattr(instance.__class__, 'BLIND_INDEX_FIELDS', None)
    if not blind_map:
        return
    uid = getattr(instance, 'propietario_id', None) or getattr(instance, 'usuario_id', None)
    update_fields = kwargs_save.get('update_fields')
    extra_fields = set(update_fields) if update_fields is not None else None

    for src_field, (hash_field, mode) in blind_map.items():
        if extra_fields is not None and src_field not in extra_fields and hash_field not in extra_fields:
            continue
        val = getattr(instance, src_field, None)
        if mode == 'global':
            nuevo_hash = None if (val is None and instance._meta.get_field(hash_field).null) else global_blind_index(val)
        elif uid:
            nuevo_hash = blind_index(uid, val)
        else:
            nuevo_hash = ''
        setattr(instance, hash_field, nuevo_hash)
        if extra_fields is not None:
            extra_fields.add(hash_field)

    if extra_fields is not None:
        kwargs_save['update_fields'] = list(extra_fields)


def _entradas_salidas(tx):
    """
    {cuenta_id: [entradas, salidas]} de un queryset de movimientos.
    entradas = sum(monto - monto_interes) con destino=cuenta; salidas = sum(monto) con origen=cuenta.
    """
    res = {}
    for mov in tx.only('origen_id', 'destino_id', 'monto', 'monto_interes'):
        monto = mov.monto or CERO
        if mov.destino_id is not None:
            interes = mov.monto_interes or CERO
            res.setdefault(mov.destino_id, [CERO, CERO])[0] += monto - interes
        if mov.origen_id is not None:
            res.setdefault(mov.origen_id, [CERO, CERO])[1] += monto
    return res


def _rango(usuario, desde=None, hasta=None):
    tx = registro_transacciones.objects.filter(propietario=usuario)
    if desde is not None:
        tx = tx.filter(fecha__gte=desde)
    if hasta is not None:
        tx = tx.filter(fecha__lte=hasta)
    return tx


class CuentaManager(_EncryptedManagerBase):

    def por_nombre(self, usuario, nombre):
        nombre = (nombre or '').strip()
        if not nombre:
            return None
        uid = usuario.pk if hasattr(usuario, 'pk') else int(usuario)
        return self.filter(propietario_id=uid, nombre_hash=blind_index(uid, nombre)).first()

    def flujos_netos(self, usuario, hasta=None, desde=None):
        """{cuenta_id: neto} donde neto = entradas - salidas del libro."""
        return {c: e - s for c, (e, s) in _entradas_salidas(_rango(usuario, desde, hasta)).items()}

    def entradas_salidas(self, usuario, desde=None, hasta=None):
        """{cuenta_id: {'entradas': x, 'salidas': y}} en el rango de fechas (inclusive)."""
        return {c: {'entradas': e, 'salidas': s}
                for c, (e, s) in _entradas_salidas(_rango(usuario, desde, hasta)).items()}

    def saldos(self, usuario, hasta=None):
        """
        Devuelve {cuenta_id: saldo} para todas las cuentas del usuario.
        Activo: saldo = saldo_inicial + neto.  Pasivo (lo que debes): saldo_inicial - neto.
        """
        netos = self.flujos_netos(usuario, hasta=hasta)
        saldos = {}
        for cuenta in self.filter(propietario=usuario):
            saldos[cuenta.id] = cuenta.saldo_desde_neto(netos.get(cuenta.id, CERO))
        return saldos

    def con_saldos(self, usuario, hasta=None):
        """Lista de cuentas del usuario con el atributo ``saldo`` ya calculado."""
        netos = self.flujos_netos(usuario, hasta=hasta)
        cuentas = list(self.filter(propietario=usuario).order_by('-es_principal', 'tipo', 'nombre'))
        for cuenta in cuentas:
            cuenta.saldo_calculado = cuenta.saldo_desde_neto(netos.get(cuenta.id, CERO))
        return cuentas

    def resumen_balance(self, usuario, hasta=None):
        """Mini balance general: activos, pasivos y patrimonio neto."""
        cuentas = self.con_saldos(usuario, hasta=hasta)
        activos = sum((c.saldo_calculado for c in cuentas if c.es_activo), CERO)
        pasivos = sum((c.saldo_calculado for c in cuentas if c.es_pasivo), CERO)
        liquido = sum((c.saldo_calculado for c in cuentas if c.tipo in Cuenta.TIPOS_LIQUIDOS), CERO)
        ahorro = sum((c.saldo_calculado for c in cuentas if c.tipo == 'AHORRO'), CERO)
        return {
            'cuentas': cuentas,
            'activos': activos,
            'pasivos': pasivos,
            'patrimonio': activos - pasivos,
            'liquido': liquido,
            'ahorro': ahorro,
        }


class Cuenta(models.Model):
    TIPO_CUENTA = (
        ('EFECTIVO', 'Efectivo'),
        ('DEBITO', 'Cuenta / Tarjeta de Débito'),
        ('AHORRO', 'Cuenta de Ahorro'),
        ('INVERSION', 'Cuenta de Inversión'),
        ('CREDITO', 'Tarjeta de Crédito'),
        ('PRESTAMO', 'Préstamo'),
    )
    TIPOS_ACTIVO = ('EFECTIVO', 'DEBITO', 'AHORRO', 'INVERSION')
    TIPOS_PASIVO = ('CREDITO', 'PRESTAMO')
    TIPOS_LIQUIDOS = ('EFECTIVO', 'DEBITO')
    BLIND_INDEX_FIELDS = {'nombre': ('nombre_hash', 'user')}

    propietario = models.ForeignKey(User, on_delete=models.CASCADE)
    nombre = EncryptedCharField(max_length=50, help_text="Ej. Tarjeta Banamex, Efectivo Quincena, NuBank")
    nombre_hash = models.CharField(max_length=64, editable=False, default='', db_index=True)
    terminacion = EncryptedCharField(max_length=4, blank=True, null=True, help_text="Últimos 4 dígitos de la tarjeta (opcional)")
    tipo = models.CharField(max_length=15, choices=TIPO_CUENTA, default='DEBITO')
    es_principal = models.BooleanField(default=False, help_text="Marcar como tarjeta principal o preferida")
    saldo_inicial = EncryptedDecimalField(
        max_digits=20, decimal_places=2, default=CERO,
        help_text="Activos: dinero que había antes del primer movimiento registrado. "
                  "Pasivos: deuda que había antes del primer movimiento registrado.")
    fecha_saldo_inicial = models.DateField(
        null=True, blank=True,
        help_text="Fecha a la que corresponde el saldo inicial (informativo).")

    objects = CuentaManager()

    class Meta:
        unique_together = ['propietario', 'nombre_hash']

    def __str__(self):
        if self.terminacion:
            return f"{self.nombre} (**{self.terminacion})"
        return self.nombre

    @property
    def es_pasivo(self):
        return self.tipo in self.TIPOS_PASIVO

    @property
    def es_activo(self):
        return not self.es_pasivo

    def saldo_desde_neto(self, neto):
        neto = neto or CERO
        inicial = self.saldo_inicial or CERO
        return (inicial - neto) if self.es_pasivo else (inicial + neto)

    def neto(self, hasta=None):
        return Cuenta.objects.flujos_netos(self.propietario, hasta=hasta).get(self.id, CERO)

    def saldo(self, hasta=None):
        """Activo: cuánto dinero hay. Pasivo: cuánto se debe."""
        if self.pk is None:
            return self.saldo_inicial or CERO
        if hasta is None and hasattr(self, 'saldo_calculado'):
            return self.saldo_calculado
        return self.saldo_desde_neto(self.neto(hasta=hasta))

    def ajustar_saldo_inicial_para(self, saldo_real, hasta=None):
        """
        Conciliación: fija ``saldo_inicial`` para que el saldo derivado del libro
        coincida con ``saldo_real`` (lo que dice el banco / estado de cuenta).
        Devuelve la diferencia que había (partida conciliatoria).
        """
        saldo_real = Decimal(str(saldo_real))
        actual = self.saldo(hasta=hasta)
        diferencia = saldo_real - actual
        if diferencia != 0:
            self.saldo_inicial = (self.saldo_inicial or CERO) + diferencia
            self.save(update_fields=['saldo_inicial'])
            if hasattr(self, 'saldo_calculado'):
                self.saldo_calculado = saldo_real
        return diferencia

    def validate_unique(self, exclude=None):
        if self.propietario_id:
            self.nombre_hash = blind_index(self.propietario_id, self.nombre)
        super().validate_unique(exclude=exclude)

    def save(self, *args, **kwargs):
        _sync_blind_hashes(self, kwargs)
        if self.es_principal:
            Cuenta.objects.filter(propietario=self.propietario).exclude(pk=self.pk).update(es_principal=False)
        super().save(*args, **kwargs)
        # Mantener sincronizado el nombre de la deuda ligada (si existe)
        deuda = getattr(self, 'deuda', None)
        if deuda is not None and deuda.nombre != self.nombre:
            deuda.nombre = self.nombre
            deuda.save(update_fields=['nombre', 'nombre_hash'])


class SaldoEstadoCuenta(models.Model):
    """
    Saldo que reporta el banco (estado de cuenta) al cierre de un mes, para
    conciliarlo contra el saldo derivado del libro. Activos: saldo disponible.
    Pasivos (tarjeta/préstamo): lo que se debe según el estado de cuenta.
    """
    cuenta = models.ForeignKey(Cuenta, on_delete=models.CASCADE, related_name='saldos_banco')
    anio = models.PositiveIntegerField()
    mes = models.PositiveSmallIntegerField()
    saldo_banco = EncryptedDecimalField(max_digits=20, decimal_places=2)
    fecha = models.DateField(null=True, blank=True)
    nota = EncryptedCharField(max_length=200, blank=True, default='')
    actualizado = models.DateTimeField(auto_now=True)

    objects = _EncryptedManagerBase()

    class Meta:
        unique_together = ['cuenta', 'anio', 'mes']
        ordering = ['cuenta', 'anio', 'mes']

    def __str__(self):
        return f"{self.cuenta.nombre} {self.anio}-{self.mes:02d}: {self.saldo_banco}"


class TransaccionManager(_EncryptedManagerBase):
    """Consultas agregadas sobre el libro diario (dashboard, reportes), calculadas en Python sobre datos descifrados."""

    def del_mes(self, usuario, year=None, month=None):
        now = timezone.now()
        year = year or now.year
        month = month or now.month
        return self.filter(propietario=usuario, fecha__year=year, fecha__month=month)

    def resultado(self, qs):
        """
        Estado de resultados de un queryset de movimientos:
        ingresos (a cuentas de activo), gastos de consumo, intereses de deuda,
        pagos a deuda, abonos a capital, ahorro neto y transferencias.
        """
        pasivos = Cuenta.TIPOS_PASIVO
        ingresos = CERO
        reembolsos = CERO
        gastos_consumo = CERO
        gastos_tarjeta = CERO
        intereses = CERO
        pagos_deuda = CERO
        abonos_capital = CERO
        ahorro_entradas = CERO
        ahorro_salidas = CERO
        transferencias = CERO

        for mov in qs.select_related('origen', 'destino'):
            monto = mov.monto or CERO
            interes = mov.monto_interes or CERO
            origen_tipo = mov.origen.tipo if mov.origen_id and mov.origen else None
            destino_tipo = mov.destino.tipo if mov.destino_id and mov.destino else None

            if mov.tipo == 'INGRESO':
                if destino_tipo in pasivos:
                    reembolsos += monto
                else:
                    ingresos += monto
            elif mov.tipo == 'GASTO':
                gastos_consumo += monto
                if origen_tipo == 'CREDITO':
                    gastos_tarjeta += monto
            elif mov.tipo == 'TRANSFERENCIA':
                transferencias += monto

            if mov.tipo in TIPOS_PAGO_DEUDA:
                intereses += interes

            es_pago_deuda = (mov.tipo in TIPOS_PAGO_DEUDA) or (mov.tipo == 'TRANSFERENCIA' and destino_tipo in pasivos)
            if es_pago_deuda:
                pagos_deuda += monto
                abonos_capital += monto - interes

            if destino_tipo == 'AHORRO' and origen_tipo != 'AHORRO':
                ahorro_entradas += monto
            if origen_tipo == 'AHORRO' and destino_tipo != 'AHORRO':
                ahorro_salidas += monto

        gastos = gastos_consumo + intereses
        return {
            'ingresos': ingresos,
            'reembolsos': reembolsos,
            'gastos_consumo': gastos_consumo,
            'gastos_tarjeta': gastos_tarjeta,
            'intereses': intereses,
            'pagos_deuda': pagos_deuda,
            'abonos_capital': abonos_capital,
            'ahorro_entradas': ahorro_entradas,
            'ahorro_salidas': ahorro_salidas,
            'transferencias': transferencias,
            'gastos': gastos,
            'resultado': ingresos - gastos,
            'ahorro_neto': ahorro_entradas - ahorro_salidas,
        }

    def balance_dashboard(self, usuario, year=None, month=None):
        return self.resultado(self.del_mes(usuario, year, month))

    def gastos_por_categoria(self, usuario, year, month):
        """[{'categoria': X, 'total': N}, ...] incluyendo intereses de deuda como categoría."""
        qs = self.del_mes(usuario, year, month)
        totales = defaultdict(lambda: CERO)
        intereses = CERO
        for mov in qs.only('tipo', 'categoria', 'monto', 'monto_interes'):
            if mov.tipo == 'GASTO':
                totales[mov.categoria] += mov.monto or CERO
            elif mov.tipo in TIPOS_PAGO_DEUDA:
                intereses += mov.monto_interes or CERO
        filas = [{'categoria': cat, 'total': tot} for cat, tot in totales.items()]
        if intereses:
            filas.append({'categoria': 'Intereses de deuda', 'total': intereses})
        return sorted(filas, key=lambda f: f['total'], reverse=True)

    def ingresos_por_categoria(self, usuario, year, month):
        qs = self.del_mes(usuario, year, month).filter(tipo='INGRESO').exclude(destino__tipo__in=Cuenta.TIPOS_PASIVO)
        totales = defaultdict(lambda: CERO)
        for mov in qs.only('categoria', 'monto'):
            totales[mov.categoria] += mov.monto or CERO
        filas = [{'categoria': cat, 'total': tot} for cat, tot in totales.items()]
        return sorted(filas, key=lambda f: f['total'], reverse=True)

    def ahorro_por_mes(self, usuario, year):
        """Flujo neto mensual hacia cuentas de AHORRO en el año: {'YYYY-MM': neto}."""
        base = self.filter(propietario=usuario, fecha__year=year).select_related('origen', 'destino')
        por_mes = {}
        for mov in base:
            origen_tipo = mov.origen.tipo if mov.origen_id and mov.origen else None
            destino_tipo = mov.destino.tipo if mov.destino_id and mov.destino else None
            monto = mov.monto or CERO
            interes = mov.monto_interes or CERO
            k = mov.fecha.strftime('%Y-%m')
            if destino_tipo == 'AHORRO' and origen_tipo != 'AHORRO':
                por_mes[k] = por_mes.get(k, CERO) + (monto - interes)
            elif origen_tipo == 'AHORRO' and destino_tipo != 'AHORRO':
                por_mes[k] = por_mes.get(k, CERO) - monto
        return por_mes

    def movimientos_entre_cuentas(self, usuario, year, month):
        """
        Dinero que pasó entre cuentas propias en el mes (no es gasto ni ingreso):
        {cuenta_id: neto recibido (+) o enviado (-)} considerando solo transferencias
        y pagos de deuda. Para pasivos, lo recibido es el abono a capital.
        """
        qs = self.del_mes(usuario, year, month).filter(tipo__in=('TRANSFERENCIA',) + TIPOS_PAGO_DEUDA)
        return {c: e - s for c, (e, s) in _entradas_salidas(qs).items()}


class registro_transacciones(models.Model):
    propietario = models.ForeignKey(User, on_delete=models.CASCADE)
    fecha = models.DateField(db_index=True)
    descripcion = EncryptedCharField(max_length=100)
    categoria = EncryptedCharField(max_length=100)
    monto = EncryptedDecimalField(max_digits=20, decimal_places=3)

    TIPO_CHOICES = [
        ('INGRESO', 'Ingreso'),
        ('GASTO', 'Gasto'),
        ('TRANSFERENCIA', 'Transferencia'),
        ('PAGO_MENSUALIDAD', 'Pago de Mensualidad'),
        ('PAGO_CAPITAL', 'Pago a Capital'),
    ]
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES, db_index=True)

    # --- Libro mayor: de qué cuenta sale y a cuál entra ---
    origen = models.ForeignKey(
        'Cuenta', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='movimientos_salida', help_text="Cuenta de la que SALE el dinero")
    destino = models.ForeignKey(
        'Cuenta', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='movimientos_entrada', help_text="Cuenta a la que ENTRA el dinero")
    monto_interes = EncryptedDecimalField(max_digits=20, decimal_places=3, default=CERO)

    cuenta_origen = EncryptedCharField(max_length=100, blank=True, default='', editable=False)
    cuenta_destino = EncryptedCharField(max_length=100, blank=True, default='', editable=False)

    deuda_asociada = models.ForeignKey('Deuda', on_delete=models.SET_NULL, null=True, blank=True, related_name='pagos')
    datos_extra = EncryptedJSONField(null=True, blank=True)

    objects = TransaccionManager()

    class Meta:
        ordering = ['-fecha', '-id']

    def __str__(self):
        return f"{self.id} - {self.descripcion}"

    @property
    def monto_capital(self):
        return (self.monto or CERO) - (self.monto_interes or CERO)

    @property
    def es_pago_deuda(self):
        return self.tipo in TIPOS_PAGO_DEUDA or (
            self.tipo == 'TRANSFERENCIA' and self.destino_id and self.destino.es_pasivo)

    def clean(self):
        errores = {}
        if self.tipo == 'INGRESO':
            if self.origen_id and not self.destino_id:
                self.destino, self.origen = self.origen, None
            elif self.origen_id:
                self.origen = None
            if not self.destino_id:
                errores['destino'] = 'Indica a qué cuenta entra el ingreso.'
        elif self.tipo == 'GASTO':
            self.destino = None
            if not self.origen_id:
                errores['origen'] = 'Indica con qué cuenta o tarjeta pagaste.'
        elif self.tipo == 'TRANSFERENCIA':
            if not self.origen_id:
                errores['origen'] = 'Indica de qué cuenta sale el dinero.'
            if not self.destino_id:
                errores['destino'] = 'Indica a qué cuenta o tarjeta llega el dinero.'
            if self.origen_id and self.origen_id == self.destino_id:
                errores['destino'] = 'Origen y destino no pueden ser la misma cuenta.'
        elif self.tipo in TIPOS_PAGO_DEUDA:
            if not self.origen_id:
                errores['origen'] = 'Indica de qué cuenta sale el pago.'
            if not self.destino_id:
                errores['destino'] = 'Indica qué préstamo estás pagando.'
            elif self.destino.tipo != 'PRESTAMO':
                errores['destino'] = ('Los pagos de mensualidad/capital son para préstamos. '
                                      'Para pagar una tarjeta usa una Transferencia hacia la tarjeta.')
        if self.monto is not None and self.monto <= 0:
            errores['monto'] = 'El monto debe ser mayor a cero.'
        if self.monto_interes and self.monto is not None and self.monto_interes > self.monto:
            errores['monto_interes'] = 'El interés no puede ser mayor al monto pagado.'
        for campo in ('origen', 'destino'):
            cuenta = getattr(self, campo)
            if cuenta is not None and self.propietario_id and cuenta.propietario_id != self.propietario_id:
                errores[campo] = 'Esa cuenta no pertenece a este usuario.'
        if errores:
            raise ValidationError(errores)

    def _normalizar(self):
        """Aplica las mismas reglas que clean() sin lanzar errores (para guardados programáticos)."""
        if self.tipo == 'INGRESO':
            if self.origen_id and not self.destino_id:
                self.destino, self.origen = self.origen, None
            else:
                self.origen = None
        elif self.tipo == 'GASTO':
            self.destino = None
        elif self.tipo == 'TRANSFERENCIA' and self.destino is not None and self.destino.tipo == 'PRESTAMO':
            self.tipo = 'PAGO_MENSUALIDAD'
        elif self.tipo == 'TRANSFERENCIA' and self.destino is None and self.origen is not None:
            self.tipo = 'GASTO'
        if self.tipo not in TIPOS_PAGO_DEUDA:
            self.monto_interes = CERO
        self.deuda_asociada = None
        for cuenta in (self.destino, self.origen):
            if cuenta is not None and cuenta.es_pasivo:
                self.deuda_asociada = getattr(cuenta, 'deuda', None)
                break

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        self._normalizar()

        cuota = None
        if is_new and self.tipo == 'PAGO_MENSUALIDAD' and self.deuda_asociada_id:
            cuota = PagoAmortizacion.objects.filter(
                deuda=self.deuda_asociada, pagado=False).order_by('numero_cuota').first()
            if cuota is not None and not self.monto_interes:
                interes = (cuota.interes or CERO) + (cuota.iva or CERO)
                self.monto_interes = min(interes, self.monto or CERO)

        super().save(*args, **kwargs)

        if cuota is not None:
            cuota.pagado = True
            cuota.transaccion_pago = self
            cuota.save(update_fields=['pagado', 'transaccion_pago'])

    def delete(self, *args, **kwargs):
        PagoAmortizacion.objects.filter(transaccion_pago=self).update(pagado=False, transaccion_pago=None)
        super().delete(*args, **kwargs)


class TransaccionPendiente(models.Model):
    ESTADOS = (
        ('pendiente', 'Pendiente'),
        ('aprobada', 'Aprobada'),
        ('rechazada', 'Rechazada'),
    )

    propietario = models.ForeignKey(User, on_delete=models.CASCADE)
    datos_json = EncryptedJSONField()
    estado = models.CharField(max_length=10, choices=ESTADOS, default='pendiente')
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    objects = _EncryptedManagerBase()

    def __str__(self):
        descripcion = (self.datos_json or {}).get('descripcion_corta')
        return f"Pendiente de {self.propietario.username} - {descripcion}"


class inversiones(models.Model):
    """
    Modelo de Inversiones mejorado para soportar acciones fraccionadas y
    diferentes tipos de activos.
    """
    TIPO_INVERSION_CHOICES = [
        ('ACCION', 'Acción'),
        ('CRIPTO', 'Criptomoneda'),
        ('FONDO', 'Fondo de Inversión'),
        ('BONOS', 'Bonos'),
        ('FIBRAS', 'Fibras'),
        ('BIENES_RAICES', 'Bienes Raíces'),
    ]
    tipo_inversion = models.CharField(
        max_length=30,
        choices=TIPO_INVERSION_CHOICES,
        default='ACCION'
    )

    propietario = models.ForeignKey(User, on_delete=models.CASCADE)
    emisora_ticker = EncryptedCharField(max_length=10, blank=True, null=True)
    nombre_activo = EncryptedCharField(max_length=100)
    cantidad_titulos = EncryptedDecimalField(max_digits=19, decimal_places=10)
    fecha_compra = models.DateField()
    precio_compra_titulo = EncryptedDecimalField(max_digits=19, decimal_places=10)
    tipo_cambio_compra = EncryptedDecimalField(max_digits=10, decimal_places=4, null=True, blank=True)

    costo_total_adquisicion = EncryptedDecimalField(max_digits=20, decimal_places=10)
    precio_actual_titulo = EncryptedDecimalField(max_digits=19, decimal_places=10)
    valor_actual_mercado = EncryptedDecimalField(max_digits=20, decimal_places=10)
    ganancia_perdida_no_realizada = EncryptedDecimalField(max_digits=20, decimal_places=10)
    ganancia_perdida = EncryptedDecimalField(max_digits=20, decimal_places=10, null=True, blank=True)

    objects = _EncryptedManagerBase()

    def __str__(self):
        return f"{self.get_tipo_inversion_display()} de {self.propietario.username} en {self.nombre_activo}"

    @property
    def porcentaje_rendimiento(self):
        if self.costo_total_adquisicion and self.costo_total_adquisicion > 0:
            return (self.ganancia_perdida_no_realizada / self.costo_total_adquisicion) * 100
        return 0

    def save(self, *args, **kwargs):
        cantidad = Decimal(str(self.cantidad_titulos or 0))
        compra = Decimal(str(self.precio_compra_titulo or 0))
        actual = Decimal(str(self.precio_actual_titulo or 0))
        self.costo_total_adquisicion = cantidad * compra
        self.valor_actual_mercado = cantidad * actual
        self.ganancia_perdida_no_realizada = self.valor_actual_mercado - self.costo_total_adquisicion
        super().save(*args, **kwargs)


class Suscripcion(models.Model):
    """
    Almacena el estado de la suscripción de un usuario.
    """
    ESTADOS = (
        ('activa', 'Activa'),
        ('cancelada', 'Cancelada'),
        ('pausada', 'Pausada'),
        ('pendiente', 'Pendiente de Pago'),
    )

    usuario = models.OneToOneField(User, on_delete=models.CASCADE, related_name='suscripcion')
    estado = models.CharField(max_length=15, choices=ESTADOS, default='pendiente')
    fecha_inicio = models.DateTimeField(null=True, blank=True)
    fecha_fin = models.DateTimeField(null=True, blank=True)
    fecha_cancelacion = models.DateTimeField(null=True, blank=True)
    id_suscripcion_mercadopago = models.CharField(max_length=100, blank=True, null=True)
    PLANES = (('gratis', 'Gratis'), ('personal', 'Personal'), ('pro', 'Pro'))
    plan = models.CharField(max_length=10, choices=PLANES, default='personal')
    periodo = models.CharField(max_length=7, choices=(('mensual', 'Mensual'), ('anual', 'Anual')), default='mensual')

    def is_active(self):
        if self.estado not in ('activa', 'cancelada') or not self.fecha_fin:
            return False
        return self.fecha_fin.date() >= timezone.now().date()

    @property
    def esta_cancelada(self):
        return self.estado == 'cancelada'

    @property
    def puede_cancelarse(self):
        return self.estado == 'activa' and self.is_active()

    def cancelar(self):
        self.estado = 'cancelada'
        self.fecha_cancelacion = timezone.now()
        self.save(update_fields=['estado', 'fecha_cancelacion'])

    def __str__(self):
        return f"Suscripción de {self.usuario.username} - {self.get_estado_display()}"


class UsoIA(models.Model):
    """Documentos mandados a la IA por usuario y mes (la cuota de cada plan, ver planes.py)."""
    usuario = models.ForeignKey(User, on_delete=models.CASCADE, related_name='uso_ia')
    anio = models.PositiveIntegerField()
    mes = models.PositiveSmallIntegerField()
    documentos = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = ('usuario', 'anio', 'mes')

    def __str__(self):
        return f"{self.usuario.username} {self.anio}-{self.mes:02d}: {self.documentos} documentos"


class PendingInvestment(models.Model):
    ESTADOS = (
        ('pendiente', 'Pendiente'),
        ('aprobada', 'Aprobada'),
        ('rechazada', 'Rechazada'),
    )

    propietario = models.ForeignKey(User, on_delete=models.CASCADE)
    datos_json = EncryptedJSONField()
    estado = models.CharField(max_length=10, choices=ESTADOS, default='pendiente')
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    objects = _EncryptedManagerBase()

    def __str__(self):
        nombre_activo = (self.datos_json or {}).get('nombre_activo', 'N/A')
        return f"Inversión Pendiente de {self.propietario.username} en {nombre_activo}"


class Deuda(models.Model):
    """
    Detalle de un pasivo (tasa, plazo, fechas de corte/pago, tabla de amortización).
    El SALDO vive en la ``Cuenta`` ligada y se deriva del libro de movimientos:
    ``saldo_pendiente`` siempre significa "lo que debes hoy", tanto para
    tarjetas como para préstamos.
    """
    TIPO_DEUDA_CHOICES = [
        ('PRESTAMO', 'Préstamo a Plazo'),
        ('TARJETA_CREDITO', 'Tarjeta de Crédito'),
    ]
    TIPO_CUENTA_POR_DEUDA = {'PRESTAMO': 'PRESTAMO', 'TARJETA_CREDITO': 'CREDITO'}
    BLIND_INDEX_FIELDS = {'nombre': ('nombre_hash', 'user')}

    propietario = models.ForeignKey(User, on_delete=models.CASCADE)
    nombre = EncryptedCharField(
        max_length=100,
        help_text="Un nombre único para identificar esta deuda (ej. 'Préstamo Coche')"
    )
    nombre_hash = models.CharField(max_length=64, editable=False, default='', db_index=True)
    cuenta = models.OneToOneField(
        'Cuenta', on_delete=models.CASCADE, null=True, blank=True, related_name='deuda',
        help_text="Cuenta de pasivo en el libro mayor donde se lleva el saldo de esta deuda.")

    tipo_deuda = models.CharField(max_length=20, choices=TIPO_DEUDA_CHOICES, default='PRESTAMO')
    monto_total = EncryptedDecimalField(
        max_digits=12,
        decimal_places=2,
        help_text="Para préstamos: el monto original. Para tarjetas de crédito: el límite de crédito total."
    )
    tasa_interes = EncryptedDecimalField(max_digits=5, decimal_places=2, help_text="Tasa de interés anual (%)")
    plazo_meses = models.PositiveIntegerField(default=1, help_text="Para tarjetas de crédito, puede ser 1.")
    fecha_adquisicion = models.DateField(default=timezone.now)
    saldo_legado = EncryptedDecimalField(max_digits=12, decimal_places=2, null=True, blank=True, editable=False)
    requiere_configuracion_adicional = models.BooleanField(
        default=False,
        help_text="Indica si la deuda se generó automáticamente y necesita que se configuren sus detalles (monto, tasa, etc.)"
    )

    dia_corte = models.PositiveIntegerField(
        null=True, blank=True,
        help_text="Día del mes en que corta la tarjeta (1-31). Ej: 6"
    )
    dia_pago = models.PositiveIntegerField(
        null=True, blank=True,
        help_text="Día límite de pago del mes (1-31). Ej: 30"
    )

    objects = _EncryptedManagerBase()

    class Meta:
        unique_together = ['propietario', 'nombre_hash']

    def __str__(self):
        return self.nombre

    @property
    def es_tarjeta(self):
        return self.tipo_deuda == 'TARJETA_CREDITO'

    @property
    def saldo_pendiente(self):
        """Lo que se debe hoy (tarjeta: saldo usado; préstamo: capital pendiente)."""
        if self.cuenta_id:
            return self.cuenta.saldo()
        return self.saldo_legado or CERO

    @property
    def disponible(self):
        """Tarjetas: crédito disponible = límite - lo que se debe."""
        return Decimal(str(self.monto_total or CERO)) - self.saldo_pendiente

    @property
    def total_gastado(self):
        """Tarjeta: lo usado del límite. Préstamo: capital ya pagado."""
        if self.es_tarjeta:
            return self.saldo_pendiente
        return Decimal(str(self.monto_total or CERO)) - self.saldo_pendiente

    @property
    def valor_barra(self):
        return self.disponible if self.es_tarjeta else self.saldo_pendiente

    @property
    def porcentaje_barra(self):
        total = Decimal(str(self.monto_total or CERO))
        if total <= 0:
            return 0
        pct = (self.valor_barra / total) * 100
        return max(0, min(100, int(pct)))

    def asegurar_cuenta(self, saldo_inicial=None):
        """Crea o liga la cuenta de pasivo correspondiente en el libro mayor."""
        tipo_cuenta = self.TIPO_CUENTA_POR_DEUDA[self.tipo_deuda]
        if self.cuenta_id:
            cambios = []
            if self.cuenta.tipo != tipo_cuenta:
                self.cuenta.tipo = tipo_cuenta
                cambios.append('tipo')
            if self.cuenta.nombre != self.nombre:
                self.cuenta.nombre = self.nombre
                cambios.append('nombre')
            if cambios:
                self.cuenta.save(update_fields=cambios)
            return self.cuenta
        cuenta = Cuenta.objects.por_nombre(self.propietario, self.nombre)
        if cuenta is None:
            if saldo_inicial is None:
                saldo_inicial = self.monto_total if self.tipo_deuda == 'PRESTAMO' else CERO
            cuenta = Cuenta.objects.create(
                propietario=self.propietario, nombre=self.nombre, tipo=tipo_cuenta,
                saldo_inicial=saldo_inicial or CERO, fecha_saldo_inicial=self.fecha_adquisicion)
        elif cuenta.tipo != tipo_cuenta:
            cuenta.tipo = tipo_cuenta
            cuenta.save(update_fields=['tipo'])
        self.cuenta = cuenta
        return cuenta

    def validate_unique(self, exclude=None):
        if self.propietario_id:
            self.nombre_hash = blind_index(self.propietario_id, self.nombre)
        super().validate_unique(exclude=exclude)

    def save(self, *args, **kwargs):
        saldo_inicial = kwargs.pop('saldo_inicial', None)
        _sync_blind_hashes(self, kwargs)
        super().save(*args, **kwargs)
        if not self.cuenta_id or self.cuenta.nombre != self.nombre:
            self.asegurar_cuenta(saldo_inicial=saldo_inicial)
            super().save(update_fields=['cuenta'])

    def delete(self, *args, **kwargs):
        cuenta = self.cuenta if self.cuenta_id else None
        resultado = super().delete(*args, **kwargs)
        if cuenta is not None:
            cuenta.delete()
        return resultado

    @property
    def proxima_fecha_corte(self):
        return proximo_dia_del_mes(self.dia_corte)

    @property
    def proxima_fecha_pago(self):
        return proximo_dia_del_mes(self.dia_pago)


def proximo_dia_del_mes(dia, hoy=None):
    """Próxima fecha (hoy o después) con ese día del mes; en meses más cortos, su último día."""
    if not dia:
        return None
    hoy = hoy or timezone.now().date()
    y, m = hoy.year, hoy.month
    fecha = date(y, m, min(dia, calendar.monthrange(y, m)[1]))
    if fecha < hoy:
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
        fecha = date(y, m, min(dia, calendar.monthrange(y, m)[1]))
    return fecha


class PagoAmortizacion(models.Model):
    deuda = models.ForeignKey(Deuda, on_delete=models.CASCADE, related_name='amortizacion')
    numero_cuota = models.PositiveIntegerField()
    fecha_vencimiento = models.DateField()
    capital = EncryptedDecimalField(max_digits=10, decimal_places=2)
    interes = EncryptedDecimalField(max_digits=10, decimal_places=2)
    iva = EncryptedDecimalField(max_digits=10, decimal_places=2, default=CERO, help_text="IVA sobre los intereses")
    saldo_insoluto = EncryptedDecimalField(max_digits=12, decimal_places=2, help_text="Saldo pendiente después de este pago")
    pago_total = EncryptedDecimalField(max_digits=10, decimal_places=2, help_text="Suma de capital + interés + IVA")
    pagado = models.BooleanField(default=False)
    transaccion_pago = models.OneToOneField(registro_transacciones, on_delete=models.SET_NULL, null=True, blank=True)

    objects = _EncryptedManagerBase()

    class Meta:
        ordering = ['numero_cuota']

    def save(self, *args, **kwargs):
        cap = Decimal(str(self.capital or CERO))
        inte = Decimal(str(self.interes or CERO))
        iva = Decimal(str(self.iva or CERO))
        self.pago_total = cap + inte + iva
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Cuota {self.numero_cuota} de {self.deuda.nombre}"


class AmortizacionPendiente(models.Model):
    """
    Almacena una tabla de amortización completa extraída por la IA,
    pendiente de la revisión y aprobación del usuario.
    """
    propietario = models.ForeignKey(User, on_delete=models.CASCADE)
    deuda = models.ForeignKey(Deuda, on_delete=models.CASCADE, related_name='amortizaciones_pendientes')
    datos_json = EncryptedJSONField()
    nombre_archivo = EncryptedCharField(max_length=255)
    estado = models.CharField(max_length=10, choices=(('pendiente', 'Pendiente'), ('aprobada', 'Aprobada')), default='pendiente')
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    objects = _EncryptedManagerBase()

    def __str__(self):
        return f"Amortización Pendiente para '{self.deuda.nombre}' del archivo '{self.nombre_archivo}'"


class TiendaFacturacion(models.Model):
    """
    TABLA 1: CONFIGURACIÓN (El Cerebro)
    Define qué datos necesitamos pedirle a la IA para cada tienda.
    """
    tienda = models.CharField(
        max_length=150,
        unique=True,
        help_text="Nombre normalizado de la tienda (ej. WALMART, OXXO)"
    )
    campos_requeridos = models.JSONField(
        default=list,
        help_text="Lista de llaves que necesitamos extraer (ej. ['Folio', 'RFC', 'Código'])"
    )
    url_portal = models.URLField(
        max_length=500,
        blank=True,
        null=True,
        help_text="Link directo al portal de facturación de esta tienda"
    )
    configuracion_finalizada = models.BooleanField(
        default=False,
        help_text="Indica si el usuario ya confirmó que esta configuración es correcta/completa."
    )

    def __str__(self):
        return f"Configuración para {self.tienda}"


class Factura(models.Model):
    """
    TABLA 2: RESULTADOS (La Memoria)
    Guarda los datos extraídos de un ticket específico listos para usarse.
    """
    ESTADOS = (
        ('pendiente', 'Pendiente de Facturar'),
        ('facturado', 'Facturado'),
        ('imposible', 'Datos insuficientes/Error'),
    )
    BLIND_INDEX_FIELDS = {'archivo_drive_id': ('archivo_drive_hash', 'global')}

    propietario = models.ForeignKey(User, on_delete=models.CASCADE)
    configuracion_tienda = models.ForeignKey(
        TiendaFacturacion,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='facturas_generadas'
    )

    tienda = EncryptedCharField(max_length=150, help_text="Nombre extraído del establecimiento")
    fecha_emision = models.DateField(help_text="Fecha detectada en el ticket", null=True, blank=True, db_index=True)
    total = EncryptedDecimalField(max_digits=12, decimal_places=2, help_text="Monto total del consumo")
    datos_facturacion = EncryptedJSONField(
        default=dict,
        help_text="Datos técnicos extraídos para el portal de facturación"
    )
    archivo_drive_id = EncryptedCharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="ID del archivo en Google Drive para ver la imagen original"
    )
    archivo_drive_hash = models.CharField(max_length=64, blank=True, null=True, editable=False, db_index=True)

    estado = models.CharField(max_length=15, choices=ESTADOS, default='pendiente')
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_actualizacion = models.DateTimeField(auto_now=True)

    objects = _EncryptedManagerBase()

    class Meta:
        ordering = ['-fecha_emision']
        verbose_name = 'Factura'
        verbose_name_plural = 'Facturas'

    def save(self, *args, **kwargs):
        _sync_blind_hashes(self, kwargs)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Factura {self.tienda} - ${self.total} ({self.estado})"

    @property
    def get_script_id(self):
        return f"factura-json-{self.id}"


class PortfolioHistory(models.Model):
    """
    Almacena el valor total del portafolio día a día.
    Permite graficar la evolución histórica tipo 'stock chart'.
    """
    usuario = models.ForeignKey(User, on_delete=models.CASCADE)
    fecha = models.DateField()
    valor_total = EncryptedDecimalField(max_digits=20, decimal_places=2)
    capital_invertido = EncryptedDecimalField(max_digits=20, decimal_places=2)
    ganancia_no_realizada = EncryptedDecimalField(max_digits=20, decimal_places=2)

    objects = _EncryptedManagerBase()

    class Meta:
        unique_together = ['usuario', 'fecha']
        ordering = ['fecha']

    def __str__(self):
        return f"{self.usuario.username} - {self.fecha}: ${self.valor_total}"


class Presupuesto(models.Model):
    BLIND_INDEX_FIELDS = {'categoria': ('categoria_hash', 'user')}

    propietario = models.ForeignKey(User, on_delete=models.CASCADE, related_name='presupuestos')
    categoria = EncryptedCharField(max_length=100, help_text="Ej. Vivienda, Alimentación, Transporte")
    categoria_hash = models.CharField(max_length=64, editable=False, default='', db_index=True)
    monto_presupuestado = EncryptedDecimalField(max_digits=12, decimal_places=2, default=CERO)
    monto_real = EncryptedDecimalField(max_digits=12, decimal_places=2, default=CERO, help_text="Monto real gastado o facturado")

    es_recurrente = models.BooleanField(default=True, help_text="Si es verdadero, aplica para todos los meses")
    mes = models.IntegerField(null=True, blank=True, help_text="Mes específico (1-12) si no es recurrente")
    anio = models.IntegerField(null=True, blank=True, help_text="Año específico si no es recurrente")
    fecha_proximo_recibo = models.DateField(null=True, blank=True, help_text="Fecha estimada del próximo recibo (generada por IA)")
    es_fijo = models.BooleanField(
        default=False,
        help_text="Actívalo si pagas un monto fijo cada mes (renta, muchacha, suscripción), aunque no tenga un solo día de pago."
    )
    dia_pago = models.PositiveIntegerField(
        null=True, blank=True,
        help_text="Día del mes en que lo pagas (1-31), opcional en gastos de monto fijo."
    )

    objects = _EncryptedManagerBase()

    class Meta:
        verbose_name = "Presupuesto"
        verbose_name_plural = "Presupuestos"
        unique_together = ['propietario', 'categoria_hash', 'mes', 'anio']

    @property
    def usa_monto_fijo(self):
        return bool(self.es_fijo or self.dia_pago)

    def validate_unique(self, exclude=None):
        if self.propietario_id:
            self.categoria_hash = blind_index(self.propietario_id, self.categoria)
        super().validate_unique(exclude=exclude)

    def save(self, *args, **kwargs):
        if self.dia_pago is not None:
            self.es_fijo = True
            if kwargs.get('update_fields') is not None and 'es_fijo' not in kwargs['update_fields']:
                kwargs['update_fields'] = list(kwargs['update_fields']) + ['es_fijo']
        _sync_blind_hashes(self, kwargs)
        super().save(*args, **kwargs)

    def __str__(self):
        if self.es_recurrente:
            return f"{self.categoria} - ${self.monto_presupuestado} (Recurrente)"
        return f"{self.categoria} - ${self.monto_presupuestado} ({self.mes}/{self.anio})"


class HistorialReciboServicio(models.Model):
    BLIND_INDEX_FIELDS = {'archivo_drive_id': ('archivo_drive_hash', 'global')}

    propietario = models.ForeignKey(User, on_delete=models.CASCADE)
    presupuesto = models.ForeignKey(Presupuesto, on_delete=models.CASCADE, related_name='historial_recibos')
    fecha_emision = models.DateField(null=True, blank=True)
    monto_total = EncryptedDecimalField(max_digits=12, decimal_places=2)
    datos_json = EncryptedJSONField(default=dict)
    archivo_drive_id = EncryptedCharField(max_length=255)
    archivo_drive_hash = models.CharField(max_length=64, unique=True, editable=False, default='')
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    objects = _EncryptedManagerBase()

    def validate_unique(self, exclude=None):
        self.archivo_drive_hash = global_blind_index(self.archivo_drive_id)
        super().validate_unique(exclude=exclude)

    def save(self, *args, **kwargs):
        _sync_blind_hashes(self, kwargs)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Recibo de {self.presupuesto.categoria} - {self.fecha_emision} - ${self.monto_total}"


class AliasComercio(models.Model):
    """
    Cómo quiere el usuario que se llame y se clasifique lo que el banco escribe de cierta forma
    ("SUPER RIDES" -> "DIDI", Transporte).
    """
    BLIND_INDEX_FIELDS = {'texto_banco': ('texto_banco_hash', 'user')}

    propietario = models.ForeignKey(User, on_delete=models.CASCADE, related_name='alias_comercios')
    texto_banco = EncryptedCharField(max_length=100, help_text="Como lo escribe el banco, ej. 'SUPER RIDES'")
    texto_banco_hash = models.CharField(max_length=64, editable=False, default='', db_index=True)
    descripcion = EncryptedCharField(max_length=100, help_text="Como quieres verlo, ej. 'DIDI'")
    categoria = EncryptedCharField(max_length=100, blank=True, default='')

    objects = _EncryptedManagerBase()

    class Meta:
        unique_together = ('propietario', 'texto_banco_hash')
        verbose_name = "Alias de comercio"
        verbose_name_plural = "Alias de comercios"

    def validate_unique(self, exclude=None):
        if self.propietario_id:
            self.texto_banco_hash = blind_index(self.propietario_id, self.texto_banco)
        super().validate_unique(exclude=exclude)

    def save(self, *args, **kwargs):
        _sync_blind_hashes(self, kwargs)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.texto_banco} -> {self.descripcion}" + (f" ({self.categoria})" if self.categoria else "")
