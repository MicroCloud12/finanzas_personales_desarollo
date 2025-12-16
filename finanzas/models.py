from django.db import models
from django.db.models import F
from django.conf import settings
from django.utils import timezone
from django.contrib.auth.models import User


class registro_transacciones(models.Model):
    propietario = models.ForeignKey(User, on_delete=models.CASCADE)
    fecha = models.DateField()
    descripcion = models.CharField(max_length=100)
    categoria = models.CharField(max_length=100)
    monto = models.DecimalField(max_digits=65, decimal_places=3)
    TIPO_CHOICES = [
        ('INGRESO', 'Ingreso'),
        ('GASTO', 'Gasto'),
        ('TRANSFERENCIA','Transferencia'),
    ]
    tipo = models.CharField(max_length=15, choices=TIPO_CHOICES)
    cuenta_origen = models.CharField(max_length=100)
    cuenta_destino = models.CharField(max_length=100)
    deuda_asociada = models.ForeignKey('Deuda', on_delete=models.SET_NULL, null=True, blank=True, related_name='pagos')
    
    # Este es el campo que estamos modificando
    TIPO_PAGO_CHOICES = [
        ('MENSUALIDAD', 'Pago de Mensualidad'),
        ('CAPITAL', 'Pago a Capital'),
    ]
    # LA LÍNEA CLAVE ES AÑADIR default='MENSUALIDAD'
    tipo_pago = models.CharField(max_length=15, choices=TIPO_PAGO_CHOICES, default='MENSUALIDAD')
    
    # Campo para guardar metadatos extra (como RFC, Folio de factura, etc.)
    datos_extra = models.JSONField(null=True, blank=True)


    def __str__(self):
        return f"{self.id} - {self.descripcion}"

    # Tu método save que modificamos anteriormente va aquí...
    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)

        if self.deuda_asociada:
            deuda = self.deuda_asociada
            
            if self.tipo_pago == 'CAPITAL':
                deuda.saldo_pendiente -= self.monto
                deuda.save()

                monto_pago_capital = self.monto
                # --- ¡AQUÍ ESTÁ LA CORRECCIÓN CLAVE! ---
                # Ordenamos de la primera a la última para pagar las cuotas en orden.
                cuotas_pendientes = PagoAmortizacion.objects.filter(
                    deuda=deuda, pagado=False
                ).order_by('numero_cuota') # Quitamos el signo '-'

                for cuota in cuotas_pendientes:
                    if monto_pago_capital <= 0:
                        break
                    
                    # Comparamos con el capital de la cuota
                    if monto_pago_capital >= cuota.capital:
                        cuota.pagado = True
                        cuota.save()
                        monto_pago_capital -= cuota.capital
                    else:
                        # Si el pago no cubre toda la cuota, nos detenemos.
                        # Una mejora futura podría ser manejar pagos parciales a capital.
                        break

            elif deuda.tipo_deuda == 'TARJETA_CREDITO':
                # Esta lógica sigue igual
                deuda.saldo_pendiente -= self.monto
                deuda.save()

            elif deuda.tipo_deuda == 'PRESTAMO' and self.tipo_pago == 'MENSUALIDAD':
                # Esta lógica sigue igual
                cuota_a_pagar = PagoAmortizacion.objects.filter(deuda=deuda, pagado=False).order_by('numero_cuota').first()
                if cuota_a_pagar:
                    cuota_a_pagar.pagado = True
                    cuota_a_pagar.transaccion_pago = self
                    cuota_a_pagar.save()
                    deuda.saldo_pendiente = F('saldo_pendiente') - cuota_a_pagar.capital
                    deuda.save()
 
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
    TIPO_DEUDA_CHOICES = [
        ('PRESTAMO', 'Préstamo a Plazo'),
        ('TARJETA_CREDITO', 'Tarjeta de Crédito'),
    ]

    propietario = models.ForeignKey(User, on_delete=models.CASCADE)
    
    # --- PASO 1: Quitamos el unique=True de aquí ---
    nombre = models.CharField(
        max_length=100, 
        help_text="Un nombre único para identificar esta deuda (ej. 'Préstamo Coche')"
    )
    
    tipo_deuda = models.CharField(max_length=20, choices=TIPO_DEUDA_CHOICES, default='PRESTAMO')
    monto_total = models.DecimalField(
        max_digits=12, 
        decimal_places=2, 
        help_text="Para préstamos: el monto original. Para tarjetas de crédito: el límite de crédito total."
    )
    tasa_interes = models.DecimalField(max_digits=5, decimal_places=2, help_text="Tasa de interés anual (%)")
    plazo_meses = models.PositiveIntegerField(default=1, help_text="Para tarjetas de crédito, puede ser 1.")
    fecha_adquisicion = models.DateField(default=timezone.now)
    saldo_pendiente = models.DecimalField(
        max_digits=12, 
        decimal_places=2, 
        blank=True,
        help_text="El monto que se debe actualmente. Se actualiza con cada pago."
    )

    # --- PASO 2: Añadimos la clase Meta con la nueva regla ---
    class Meta:
        unique_together = ['propietario', 'nombre']

    def __str__(self):
        return self.nombre

    def save(self, *args, **kwargs):
        if not self.pk:
            self.saldo_pendiente = self.monto_total
        super().save(*args, **kwargs)

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
    
    tienda = models.CharField(max_length=150, help_text="Nombre extraído del establecimiento")
    fecha_emision = models.DateField(help_text="Fecha detectada en el ticket", null=True, blank=True)
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