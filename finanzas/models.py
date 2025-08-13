from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from django.conf import settings


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
    id_prestamo_ref = models.CharField(max_length=10, blank=True, null=True)

    def __str__(self):
        return f"{self.id} - {self.descripcion}"

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