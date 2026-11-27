from django.contrib import admin
from .models import Suscripcion, TiendaFacturacion, UsoIA


# Por privacidad (Nivel 2), los modelos financieros personales (transacciones, cuentas,
# saldos, deudas, inversiones, presupuestos y facturas) NO se exponen en /admin/.
@admin.register(Suscripcion)
class SuscripcionAdmin(admin.ModelAdmin):
    list_display = ('usuario', 'plan', 'periodo', 'estado', 'fecha_inicio', 'fecha_fin')
    list_filter = ('plan', 'periodo', 'estado')
    search_fields = ('usuario__username', 'usuario__email', 'id_suscripcion_mercadopago')


@admin.register(UsoIA)
class UsoIAAdmin(admin.ModelAdmin):
    list_display = ('usuario', 'anio', 'mes', 'documentos')
    list_filter = ('anio', 'mes')
    search_fields = ('usuario__username', 'usuario__email')


@admin.register(TiendaFacturacion)
class TiendaFacturacionAdmin(admin.ModelAdmin):
    list_display = ('tienda', 'url_portal', 'configuracion_finalizada')
    list_filter = ('configuracion_finalizada',)
    search_fields = ('tienda',)
