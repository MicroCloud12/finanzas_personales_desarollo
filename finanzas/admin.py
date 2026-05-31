from django.contrib import admin
from .models import registro_transacciones, TransaccionPendiente, inversiones, Suscripcion, PendingInvestment, Presupuesto

# Registramos los modelos para que aparezcan en el panel de admin
admin.site.register(registro_transacciones)
admin.site.register(TransaccionPendiente)
admin.site.register(inversiones)
admin.site.register(Suscripcion) # <-- Esta línea es la importante
admin.site.register(PendingInvestment)
admin.site.register(Presupuesto)
#admin.site.register(Venta)