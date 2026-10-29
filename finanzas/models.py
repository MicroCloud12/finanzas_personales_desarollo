"""
Núcleo contable de Finanzas Personales: el "libro mayor".

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
from decimal import Decimal

from django.db import models
from django.db.models import F, Q, Sum
from django.conf import settings
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.utils import timezone


CERO = Decimal('0.00')

TIPOS_PAGO_DEUDA = ('PAGO_MENSUALIDAD', 'PAGO_CAPITAL')
TIPOS_CON_ORIGEN = ('GASTO', 'TRANSFERENCIA', 'PAGO_MENSUALIDAD', 'PAGO_CAPITAL')
TIPOS_CON_DESTINO = ('INGRESO', 'TRANSFERENCIA', 'PAGO_MENSUALIDAD', 'PAGO_CAPITAL')


class CuentaQuerySet(models.QuerySet):
    def activos(self):
        return self.filter(tipo__in=Cuenta.TIPOS_ACTIVO)

    def pasivos(self):
        return self.filter(tipo__in=Cuenta.TIPOS_PASIVO)

    def liquidas(self):
        """Dinero disponible para gastar: efectivo y débito."""
        return self.filter(tipo__in=Cuenta.TIPOS_LIQUIDOS)


class CuentaManager(models.Manager.from_queryset(CuentaQuerySet)):

    def flujos_netos(self, usuario, hasta=None, desde=None):
        """
        Devuelve {cuenta_id: neto} donde neto = entradas - salidas del libro.
        entradas = sum(monto - monto_interes) de movimientos con destino=cuenta
        salidas  = sum(monto) de movimientos con origen=cuenta
        """
        tx = registro_transacciones.objects.filter(propietario=usuario)
        if hasta is not None:
            tx = tx.filter(fecha__lte=hasta)
        if desde is not None:
            tx = tx.filter(fecha__gte=desde)

        salidas = tx.filter(origen__isnull=False).values('origen').annotate(
            total=Sum('monto')).values_list('origen', 'total')
        entradas = tx.filter(destino__isnull=False).values('destino').annotate(
            total=Sum(F('monto') - F('monto_interes'))).values_list('destino', 'total')

        netos = {}
        for cuenta_id, total in entradas:
            netos[cuenta_id] = netos.get(cuenta_id, CERO) + (total or CERO)
        for cuenta_id, total in salidas:
            netos[cuenta_id] = netos.get(cuenta_id, CERO) - (total or CERO)
        return netos

    def entradas_salidas(self, usuario, desde=None, hasta=None):
        """{cuenta_id: {'entradas': x, 'salidas': y}} en el rango de fechas (inclusive)."""
        tx = registro_transacciones.objects.filter(propietario=usuario)
        if desde is not None:
            tx = tx.filter(fecha__gte=desde)
        if hasta is not None:
            tx = tx.filter(fecha__lte=hasta)
        resultado = {}
        for cuenta_id, total in tx.filter(destino__isnull=False).values('destino').annotate(
                total=Sum(F('monto') - F('monto_interes'))).values_list('destino', 'total'):
            resultado.setdefault(cuenta_id, {'entradas': CERO, 'salidas': CERO})['entradas'] += (total or CERO)
        for cuenta_id, total in tx.filter(origen__isnull=False).values('origen').annotate(
                total=Sum('monto')).values_list('origen', 'total'):
            resultado.setdefault(cuenta_id, {'entradas': CERO, 'salidas': CERO})['salidas'] += (total or CERO)
        return resultado

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

    propietario = models.ForeignKey(User, on_delete=models.CASCADE)
    nombre = models.CharField(max_length=50, help_text="Ej. Tarjeta Banamex, Efectivo Quincena, NuBank")
    terminacion = models.CharField(max_length=4, blank=True, null=True, help_text="Últimos 4 dígitos de la tarjeta (opcional)")
    tipo = models.CharField(max_length=15, choices=TIPO_CUENTA, default='DEBITO')
    es_principal = models.BooleanField(default=False, help_text="Marcar como tarjeta principal o preferida")
    saldo_inicial = models.DecimalField(
        max_digits=20, decimal_places=2, default=CERO,
        help_text="Activos: dinero que había antes del primer movimiento registrado. "
                  "Pasivos: deuda que había antes del primer movimiento registrado.")
    fecha_saldo_inicial = models.DateField(
        null=True, blank=True,
        help_text="Fecha a la que corresponde el saldo inicial (informativo).")

    objects = CuentaManager()

    class Meta:
        unique_together = ['propietario', 'nombre']

    def __str__(self):
        if self.terminacion:
            return f"{self.nombre} (**{self.terminacion})"
        return self.nombre

    # ----- naturaleza -----
    @property
    def es_pasivo(self):
        return self.tipo in self.TIPOS_PASIVO

    @property
    def es_activo(self):
        return not self.es_pasivo

    @property
    def naturaleza(self):
        return 'PASIVO' if self.es_pasivo else 'ACTIVO'

    # ----- saldos derivados del libro -----
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

    def save(self, *args, **kwargs):
        if self.es_principal:
            Cuenta.objects.filter(propietario=self.propietario).exclude(pk=self.pk).update(es_principal=False)
        super().save(*args, **kwargs)
        # Mantener sincronizado el nombre de la deuda ligada (si existe)
        deuda = getattr(self, 'deuda', None)
        if deuda is not None and deuda.nombre != self.nombre:
            Deuda.objects.filter(pk=deuda.pk).update(nombre=self.nombre)


class SaldoEstadoCuenta(models.Model):
    """
    Saldo que reporta el banco (estado de cuenta) al cierre de un mes, para
    conciliarlo contra el saldo derivado del libro. Activos: saldo disponible.
    Pasivos (tarjeta/préstamo): lo que se debe según el estado de cuenta.
    """
    cuenta = models.ForeignKey(Cuenta, on_delete=models.CASCADE, related_name='saldos_banco')
    anio = models.PositiveIntegerField()
    mes = models.PositiveSmallIntegerField()
    saldo_banco = models.DecimalField(max_digits=20, decimal_places=2)
    # Fecha exacta a la que corresponde el saldo (si viene de una captura a mitad de mes).
    # Si es None se asume el cierre del mes.
    fecha = models.DateField(null=True, blank=True)
    nota = models.CharField(max_length=200, blank=True, default='')
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['cuenta', 'anio', 'mes']
        ordering = ['cuenta', 'anio', 'mes']

    def __str__(self):
        return f"{self.cuenta.nombre} {self.anio}-{self.mes:02d}: {self.saldo_banco}"


class TransaccionManager(models.Manager):
    """Consultas agregadas sobre el libro diario (dashboard, reportes)."""

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
        es_pago_deuda = Q(tipo__in=TIPOS_PAGO_DEUDA) | Q(tipo='TRANSFERENCIA', destino__tipo__in=pasivos)
        agregados = qs.aggregate(
            ingresos=Sum('monto', filter=Q(tipo='INGRESO') & ~Q(destino__tipo__in=pasivos)),
            reembolsos=Sum('monto', filter=Q(tipo='INGRESO', destino__tipo__in=pasivos)),
            gastos_consumo=Sum('monto', filter=Q(tipo='GASTO')),
            gastos_tarjeta=Sum('monto', filter=Q(tipo='GASTO', origen__tipo='CREDITO')),
            intereses=Sum('monto_interes', filter=Q(tipo__in=TIPOS_PAGO_DEUDA)),
            pagos_deuda=Sum('monto', filter=es_pago_deuda),
            abonos_capital=Sum(F('monto') - F('monto_interes'), filter=es_pago_deuda),
            ahorro_entradas=Sum('monto', filter=Q(destino__tipo='AHORRO') & ~Q(origen__tipo='AHORRO')),
            ahorro_salidas=Sum('monto', filter=Q(origen__tipo='AHORRO') & ~Q(destino__tipo='AHORRO')),
            transferencias=Sum('monto', filter=Q(tipo='TRANSFERENCIA')),
        )
        r = {k: (v or CERO) for k, v in agregados.items()}
        r['gastos'] = r['gastos_consumo'] + r['intereses']
        r['resultado'] = r['ingresos'] - r['gastos']
        r['ahorro_neto'] = r['ahorro_entradas'] - r['ahorro_salidas']
        return r

    def balance_dashboard(self, usuario, year=None, month=None):
        return self.resultado(self.del_mes(usuario, year, month))

    def gastos_por_categoria(self, usuario, year, month):
        """[{'categoria': X, 'total': N}, ...] incluyendo intereses de deuda como categoría."""
        qs = self.del_mes(usuario, year, month)
        filas = list(qs.filter(tipo='GASTO').values('categoria').annotate(total=Sum('monto')))
        intereses = qs.filter(tipo__in=TIPOS_PAGO_DEUDA).aggregate(t=Sum('monto_interes'))['t'] or CERO
        if intereses:
            filas.append({'categoria': 'Intereses de deuda', 'total': intereses})
        return sorted(filas, key=lambda f: f['total'], reverse=True)

    def ingresos_por_categoria(self, usuario, year, month):
        return list(self.del_mes(usuario, year, month)
                    .filter(tipo='INGRESO').exclude(destino__tipo__in=Cuenta.TIPOS_PASIVO)
                    .values('categoria').annotate(total=Sum('monto')).order_by('-total'))

    def ahorro_por_mes(self, usuario, year):
        """Flujo neto mensual hacia cuentas de AHORRO en el año: {'YYYY-MM': neto}."""
        from django.db.models.functions import TruncMonth
        base = self.filter(propietario=usuario, fecha__year=year)
        entradas = (base.filter(destino__tipo='AHORRO').exclude(origen__tipo='AHORRO')
                    .annotate(mes=TruncMonth('fecha')).values('mes')
                    .annotate(total=Sum(F('monto') - F('monto_interes'))))
        salidas = (base.filter(origen__tipo='AHORRO').exclude(destino__tipo='AHORRO')
                   .annotate(mes=TruncMonth('fecha')).values('mes').annotate(total=Sum('monto')))
        por_mes = {}
        for fila in entradas:
            k = fila['mes'].strftime('%Y-%m')
            por_mes[k] = por_mes.get(k, CERO) + (fila['total'] or CERO)
        for fila in salidas:
            k = fila['mes'].strftime('%Y-%m')
            por_mes[k] = por_mes.get(k, CERO) - (fila['total'] or CERO)
        return por_mes

    def movimientos_entre_cuentas(self, usuario, year, month):
        """
        Dinero que pasó entre cuentas propias en el mes (no es gasto ni ingreso):
        {cuenta_id: neto recibido (+) o enviado (-)} considerando solo transferencias
        y pagos de deuda. Para pasivos, lo recibido es el abono a capital.
        """
        qs = self.del_mes(usuario, year, month).filter(tipo__in=('TRANSFERENCIA',) + TIPOS_PAGO_DEUDA)
        netos = {}
        for cuenta_id, total in qs.filter(destino__isnull=False).values('destino').annotate(
                total=Sum(F('monto') - F('monto_interes'))).values_list('destino', 'total'):
            netos[cuenta_id] = netos.get(cuenta_id, CERO) + (total or CERO)
        for cuenta_id, total in qs.filter(origen__isnull=False).values('origen').annotate(
                total=Sum('monto')).values_list('origen', 'total'):
            netos[cuenta_id] = netos.get(cuenta_id, CERO) - (total or CERO)
        return netos

    def movimientos_de_cuenta(self, cuenta, year=None, month=None):
        qs = self.filter(propietario=cuenta.propietario).filter(Q(origen=cuenta) | Q(destino=cuenta))
        if year and month:
            qs = qs.filter(fecha__year=year, fecha__month=month)
        return qs


class registro_transacciones(models.Model):
    propietario = models.ForeignKey(User, on_delete=models.CASCADE)
    fecha = models.DateField(db_index=True)
    descripcion = models.CharField(max_length=100)
    categoria = models.CharField(max_length=100, db_index=True)
    monto = models.DecimalField(max_digits=20, decimal_places=3)

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
    # Parte del monto que es gasto financiero (interés + IVA) en pagos de préstamo.
    # El resto (monto - monto_interes) es capital y reduce el pasivo.
    monto_interes = models.DecimalField(max_digits=20, decimal_places=3, default=CERO)

    # Nombres de cuenta tal como se capturaron antes de la migración al libro mayor.
    # Se conservan solo para auditoría; los reportes usan `origen`/`destino`.
    cuenta_origen = models.CharField(max_length=100, blank=True, default='', editable=False)
    cuenta_destino = models.CharField(max_length=100, blank=True, default='', editable=False)

    deuda_asociada = models.ForeignKey('Deuda', on_delete=models.SET_NULL, null=True, blank=True, related_name='pagos')
    datos_extra = models.JSONField(null=True, blank=True)

    objects = TransaccionManager()

    class Meta:
        ordering = ['-fecha', '-id']

    def __str__(self):
        return f"{self.id} - {self.descripcion}"

    # ----- helpers -----
    @property
    def monto_capital(self):
        return (self.monto or CERO) - (self.monto_interes or CERO)

    @property
    def es_pago_deuda(self):
        return self.tipo in TIPOS_PAGO_DEUDA or (
            self.tipo == 'TRANSFERENCIA' and self.destino_id and self.destino.es_pasivo)

    @property
    def cuenta_principal(self):
        """Cuenta "protagonista" para mostrar en listados."""
        return self.destino if self.tipo == 'INGRESO' else self.origen

    def clean(self):
        errores = {}
        if self.tipo == 'INGRESO':
            # Un ingreso solo tiene cuenta destino. Si llegó en origen, lo movemos.
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
            # Mandar dinero a un préstamo ES pagar una mensualidad (así se divide en capital/interés).
            self.tipo = 'PAGO_MENSUALIDAD'
        elif self.tipo == 'TRANSFERENCIA' and self.destino is None and self.origen is not None:
            # Una "transferencia" (SPEI) a alguien que no es una cuenta tuya es dinero que
            # se va: contablemente es un GASTO (renta, un pago a un tercero, etc.).
            self.tipo = 'GASTO'
        if self.tipo not in TIPOS_PAGO_DEUDA:
            self.monto_interes = CERO
        # La deuda asociada se deriva de la cuenta destino (pagos a préstamo / tarjeta)
        # o de la cuenta origen (compras con tarjeta).
        self.deuda_asociada = None
        for cuenta in (self.destino, self.origen):
            if cuenta is not None and cuenta.es_pasivo:
                self.deuda_asociada = getattr(cuenta, 'deuda', None)
                break

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        self._normalizar()

        # Pago de mensualidad: tomamos la siguiente cuota pendiente de la tabla de
        # amortización para saber cuánto del pago es interés (+IVA) y cuánto capital.
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
        # Si este movimiento pagaba una cuota, la cuota vuelve a quedar pendiente.
        PagoAmortizacion.objects.filter(transaccion_pago=self).update(pagado=False, transaccion_pago=None)
        super().delete(*args, **kwargs)


class GoogleCredentials(models.Model):
    # Un enlace uno-a-uno con el usuario de Django. Cada usuario solo puede tener un set de credenciales.
    user = models.OneToOneField(User, on_delete=models.CASCADE)

    # Usamos TextField porque los tokens pueden ser largos
    token = models.TextField()
    refresh_token = models.TextField(null=True, blank=True)
    token_uri = models.CharField(max_length=255)
    client_id = models.CharField(max_length=255)
    client_secret = models.CharField(max_length=255)
    scopes = models.TextField()

    def __str__(self):
        return f"Credenciales de Google para {self.user.username}"
    
class TransaccionPendiente(models.Model):
    ESTADOS = (
        ('pendiente', 'Pendiente'),
        ('aprobada', 'Aprobada'),
        ('rechazada', 'Rechazada'),
    )
    
    propietario = models.ForeignKey(User, on_delete=models.CASCADE)
    datos_json = models.JSONField() # Aquí guardaremos el resultado de Gemini
    estado = models.CharField(max_length=10, choices=ESTADOS, default='pendiente')
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        # Intenta mostrar una descripción o el total para que sea fácil de leer en el admin
        descripcion = self.datos_json.get('descripcion_corta')
        return f"Pendiente de {self.propietario.username} - {descripcion}"
    
class inversiones(models.Model):
    """
    Modelo de Inversiones mejorado para soportar acciones fraccionadas y
    diferentes tipos de activos.
    """
    # --- CAMPO NUEVO PARA CLASIFICAR LA INVERSIÓN ---
    TIPO_INVERSION_CHOICES = [
        ('ACCION', 'Acción'),
        ('CRIPTO', 'Criptomoneda'),
        ('FONDO', 'Fondo de Inversión'),
        ('BONOS', 'Bonos'),
        ('FIBRAS', 'Fibras'),
        ('BIENES_RAICES', 'Bienes Raíces'),
        # Podemos añadir más en el futuro (Bonos, Fibras, etc.)
    ]
    tipo_inversion = models.CharField(
        max_length=30,
        choices=TIPO_INVERSION_CHOICES,
        default='ACCION'
    )

    propietario = models.ForeignKey(User, on_delete=models.CASCADE)
    
    # Este campo ahora es opcional. No aplica para Cripto o Fondos.
    emisora_ticker = models.CharField(max_length=10, blank=True, null=True)
    
    # Renombramos este campo para que sea más genérico
    nombre_activo = models.CharField(max_length=100)
    
    # --- CORRECCIÓN PARA ACCIONES FRACCIONADAS ---
    # Cambiamos de PositiveIntegerField a DecimalField
    cantidad_titulos = models.DecimalField(max_digits=19, decimal_places=10)

    fecha_compra = models.DateField()
    precio_compra_titulo = models.DecimalField(max_digits=19, decimal_places=10)
    tipo_cambio_compra = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    
    # Campos calculados (no necesitan cambios)
    costo_total_adquisicion = models.DecimalField(max_digits=20, decimal_places=10)
    precio_actual_titulo = models.DecimalField(max_digits=19, decimal_places=10)
    valor_actual_mercado = models.DecimalField(max_digits=20, decimal_places=10)
    ganancia_perdida_no_realizada = models.DecimalField(max_digits=20, decimal_places=10)
    ganancia_perdida = models.DecimalField(max_digits=20, decimal_places=10, null=True, blank=True)

    def __str__(self):
        return f"{self.get_tipo_inversion_display()} de {self.propietario.username} en {self.nombre_activo}"

    @property
    def porcentaje_rendimiento(self):
        if self.costo_total_adquisicion and self.costo_total_adquisicion > 0:
            return (self.ganancia_perdida_no_realizada / self.costo_total_adquisicion) * 100
        return 0

    def save(self, *args, **kwargs):
        # La lógica de cálculo sigue funcionando igual
        self.costo_total_adquisicion = self.cantidad_titulos * self.precio_compra_titulo
        self.valor_actual_mercado = self.cantidad_titulos * self.precio_actual_titulo
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
    id_suscripcion_mercadopago = models.CharField(max_length=100, blank=True, null=True)

    def is_active(self):
        """
        Verifica si la suscripción está activa.
        Ahora compara solo las fechas para evitar problemas de zona horaria.
        """
        if self.estado != 'activa' or not self.fecha_fin:
            return False
        
        # Comparamos si la fecha de fin es hoy o una fecha futura.
        return self.fecha_fin.date() >= timezone.now().date()

    def __str__(self):
        return f"Suscripción de {self.usuario.username} - {self.get_estado_display()}"

class GananciaMensual(models.Model):
    """Almacena la suma de ganancias/pérdidas no realizadas por mes para un usuario."""
    propietario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    mes = models.CharField(max_length=7) # Formato YYYY-MM
    total = models.DecimalField(max_digits=20, decimal_places=2)

    class Meta:
        # Clave única para que no haya dos entradas para el mismo mes y usuario
        unique_together = ('propietario', 'mes')

    def __str__(self):
        return f"{self.propietario.username} - {self.mes} - ${self.total}"
    
class PendingInvestment(models.Model):
    ESTADOS = (
        ('pendiente', 'Pendiente'),
        ('aprobada', 'Aprobada'),
        ('rechazada', 'Rechazada'),
    )
    
    propietario = models.ForeignKey(User, on_delete=models.CASCADE)
    datos_json = models.JSONField()
    estado = models.CharField(max_length=10, choices=ESTADOS, default='pendiente')
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        nombre_activo = self.datos_json.get('nombre_activo', 'N/A')
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

    propietario = models.ForeignKey(User, on_delete=models.CASCADE)
    nombre = models.CharField(
        max_length=100,
        help_text="Un nombre único para identificar esta deuda (ej. 'Préstamo Coche')"
    )
    cuenta = models.OneToOneField(
        'Cuenta', on_delete=models.CASCADE, null=True, blank=True, related_name='deuda',
        help_text="Cuenta de pasivo en el libro mayor donde se lleva el saldo de esta deuda.")

    tipo_deuda = models.CharField(max_length=20, choices=TIPO_DEUDA_CHOICES, default='PRESTAMO')
    monto_total = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        help_text="Para préstamos: el monto original. Para tarjetas de crédito: el límite de crédito total."
    )
    tasa_interes = models.DecimalField(max_digits=5, decimal_places=2, help_text="Tasa de interés anual (%)")
    plazo_meses = models.PositiveIntegerField(default=1, help_text="Para tarjetas de crédito, puede ser 1.")
    fecha_adquisicion = models.DateField(default=timezone.now)
    # Valor que tenía el antiguo campo mutable `saldo_pendiente` antes de migrar al
    # libro mayor. Solo para auditoría/conciliación; no se usa en cálculos.
    saldo_legado = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, editable=False)
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

    class Meta:
        unique_together = ['propietario', 'nombre']

    def __str__(self):
        return self.nombre

    # ----- saldos (derivados del libro vía la cuenta ligada) -----
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
        return (self.monto_total or CERO) - self.saldo_pendiente

    @property
    def total_gastado(self):
        """Tarjeta: lo usado del límite. Préstamo: capital ya pagado."""
        if self.es_tarjeta:
            return self.saldo_pendiente
        return (self.monto_total or CERO) - self.saldo_pendiente

    @property
    def total_pagado(self):
        return self.total_gastado if not self.es_tarjeta else (self.monto_total or CERO) - self.disponible

    @property
    def valor_barra(self):
        """Valor para la barra de progreso: tarjeta -> disponible; préstamo -> deuda restante."""
        return self.disponible if self.es_tarjeta else self.saldo_pendiente

    @property
    def porcentaje_barra(self):
        total = self.monto_total or CERO
        if total <= 0:
            return 0
        pct = (self.valor_barra / total) * 100
        return max(0, min(100, int(pct)))

    # ----- ciclo de vida -----
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
        cuenta = Cuenta.objects.filter(propietario=self.propietario, nombre=self.nombre).first()
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

    def save(self, *args, **kwargs):
        saldo_inicial = kwargs.pop('saldo_inicial', None)
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
        if not self.dia_corte:
            return None
        import calendar
        from datetime import timedelta
        hoy = timezone.now().date()
        try:
            fecha_este_mes = hoy.replace(day=self.dia_corte)
        except ValueError:
            _, last_day = calendar.monthrange(hoy.year, hoy.month)
            fecha_este_mes = hoy.replace(day=last_day)

        if fecha_este_mes < hoy:
            mes_siguiente = (fecha_este_mes.replace(day=1) + timedelta(days=32)).replace(day=1)
            try:
                return mes_siguiente.replace(day=self.dia_corte)
            except ValueError:
                _, last_day = calendar.monthrange(mes_siguiente.year, mes_siguiente.month)
                return mes_siguiente.replace(day=last_day)
        return fecha_este_mes

    @property
    def proxima_fecha_pago(self):
        if not self.dia_pago:
            return None
        import calendar
        from datetime import timedelta
        hoy = timezone.now().date()
        try:
            fecha_este_mes = hoy.replace(day=self.dia_pago)
        except ValueError:
            _, last_day = calendar.monthrange(hoy.year, hoy.month)
            fecha_este_mes = hoy.replace(day=last_day)

        if fecha_este_mes < hoy:
            mes_siguiente = (fecha_este_mes.replace(day=1) + timedelta(days=32)).replace(day=1)
            try:
                return mes_siguiente.replace(day=self.dia_pago)
            except ValueError:
                _, last_day = calendar.monthrange(mes_siguiente.year, mes_siguiente.month)
                return mes_siguiente.replace(day=last_day)
        return fecha_este_mes


class PagoAmortizacion(models.Model):
    deuda = models.ForeignKey(Deuda, on_delete=models.CASCADE, related_name='amortizacion')
    numero_cuota = models.PositiveIntegerField()
    fecha_vencimiento = models.DateField()
    capital = models.DecimalField(max_digits=10, decimal_places=2)
    interes = models.DecimalField(max_digits=10, decimal_places=2)
    iva = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, help_text="IVA sobre los intereses")
    saldo_insoluto = models.DecimalField(max_digits=12, decimal_places=2, help_text="Saldo pendiente después de este pago")
    pago_total = models.DecimalField(max_digits=10, decimal_places=2, help_text="Suma de capital + interés + IVA")
    pagado = models.BooleanField(default=False)
    transaccion_pago = models.OneToOneField(registro_transacciones, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        ordering = ['numero_cuota']

    # --- MÉTODO SAVE CORREGIDO PARA LA AMORTIZACIÓN ---
    def save(self, *args, **kwargs):
        # Esta lógica SOLO calcula el pago_total, pero NO el saldo_insoluto.
        # Esto previene el error de recálculo al simplemente marcar una cuota como pagada.
        self.pago_total = self.capital + self.interes + self.iva
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Cuota {self.numero_cuota} de {self.deuda.nombre}"
    
class AmortizacionPendiente(models.Model):
    """
    Almacena una tabla de amortización completa extraída por la IA,
    pendiente de la revisión y aprobación del usuario.
    """
    propietario = models.ForeignKey(User, on_delete=models.CASCADE)
    # A qué deuda se asociará esta tabla de amortización
    deuda = models.ForeignKey(Deuda, on_delete=models.CASCADE, related_name='amortizaciones_pendientes')
    # Aquí guardaremos la lista completa de cuotas extraídas por Gemini
    datos_json = models.JSONField()
    nombre_archivo = models.CharField(max_length=255)
    estado = models.CharField(max_length=10, choices=(('pendiente', 'Pendiente'), ('aprobada', 'Aprobada')), default='pendiente')
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Amortización Pendiente para '{self.deuda.nombre}' del archivo '{self.nombre_archivo}'"
    
class TiendaFacturacion(models.Model):
    """
    TABLA 1: CONFIGURACIÓN (El Cerebro)
    Define qué datos necesitamos pedirle a la IA para cada tienda.
    Ejemplo:
      - Tienda: "WALMART"
      - Campos: ["Ticket #", "TR #", "Fecha"]
      - URL: "https://facturacion.walmartmexico.com.mx/"
    """
    tienda = models.CharField(
        max_length=150, 
        unique=True, 
        help_text="Nombre normalizado de la tienda (ej. WALMART, OXXO)"
    )
    
    # Lista de campos que Gemini debe buscar obligatoriamente
    campos_requeridos = models.JSONField(
        default=list, 
        help_text="Lista de llaves que necesitamos extraer (ej. ['Folio', 'RFC', 'Código'])"
    )
    
    # Campo NUEVO: Para que el usuario sepa dónde facturar
    url_portal = models.URLField(
        max_length=500, 
        blank=True, 
        null=True, 
        help_text="Link directo al portal de facturación de esta tienda"
    )
    
    # Campo NUEVO: Para distinguir borrador de final
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
    
    propietario = models.ForeignKey(User, on_delete=models.CASCADE)
    
    # Relación opcional con la configuración (si existe)
    configuracion_tienda = models.ForeignKey(
        TiendaFacturacion, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='facturas_generadas'
    )
    
    tienda = models.CharField(max_length=150, help_text="Nombre extraído del establecimiento", db_index=True)
    fecha_emision = models.DateField(help_text="Fecha detectada en el ticket", null=True, blank=True, db_index=True)
    total = models.DecimalField(max_digits=12, decimal_places=2, help_text="Monto total del consumo")
    
    # Aquí vive la magia: El JSON con los campos específicos que pidió la Tabla 1
    # Ej: { "folio": "12345", "ticket_id": "ABC", "rfc_tienda": "..." }
    datos_facturacion = models.JSONField(
        default=dict, 
        help_text="Datos técnicos extraídos para el portal de facturación"
    )
    
    # Campo NUEVO: Referencia al archivo original en Drive para auditoría
    archivo_drive_id = models.CharField(
        max_length=255, 
        blank=True, 
        null=True, 
        help_text="ID del archivo en Google Drive para ver la imagen original"
    )
    
    estado = models.CharField(max_length=15, choices=ESTADOS, default='pendiente')
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_actualizacion = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-fecha_emision']
        verbose_name = 'Factura'
        verbose_name_plural = 'Facturas'
    
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
    
    # Valor total de mercado de todos los activos ese día
    valor_total = models.DecimalField(max_digits=20, decimal_places=2)
    
    # Capital total invertido (cash flow) hasta ese día
    capital_invertido = models.DecimalField(max_digits=20, decimal_places=2)
    
    # Ganancia no realizada (valor_total - capital_invertido)
    ganancia_no_realizada = models.DecimalField(max_digits=20, decimal_places=2)
    
    class Meta:
        unique_together = ['usuario', 'fecha']
        ordering = ['fecha']

    def __str__(self):
        return f"{self.usuario.username} - {self.fecha}: ${self.valor_total}"


class Presupuesto(models.Model):
    propietario = models.ForeignKey(User, on_delete=models.CASCADE, related_name='presupuestos')
    categoria = models.CharField(max_length=100, help_text="Ej. Vivienda, Alimentación, Transporte")
    monto_presupuestado = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    monto_real = models.DecimalField(max_digits=12, decimal_places=2, default=0.00, help_text="Monto real gastado o facturado")
    
    es_recurrente = models.BooleanField(default=True, help_text="Si es verdadero, aplica para todos los meses")
    mes = models.IntegerField(null=True, blank=True, help_text="Mes específico (1-12) si no es recurrente")
    anio = models.IntegerField(null=True, blank=True, help_text="Año específico si no es recurrente")
    fecha_proximo_recibo = models.DateField(null=True, blank=True, help_text="Fecha estimada del próximo recibo (generada por IA)")
    
    class Meta:
        verbose_name = "Presupuesto"
        verbose_name_plural = "Presupuestos"
        unique_together = ['propietario', 'categoria', 'mes', 'anio']

    def __str__(self):
        if self.es_recurrente:
            return f"{self.categoria} - ${self.monto_presupuestado} (Recurrente)"
        return f"{self.categoria} - ${self.monto_presupuestado} ({self.mes}/{self.anio})"

class HistorialReciboServicio(models.Model):
    propietario = models.ForeignKey(User, on_delete=models.CASCADE)
    presupuesto = models.ForeignKey(Presupuesto, on_delete=models.CASCADE, related_name='historial_recibos')
    fecha_emision = models.DateField(null=True, blank=True)
    monto_total = models.DecimalField(max_digits=12, decimal_places=2)
    datos_json = models.JSONField(default=dict)
    archivo_drive_id = models.CharField(max_length=255, unique=True)
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Recibo de {self.presupuesto.categoria} - {self.fecha_emision} - ${self.monto_total}"
