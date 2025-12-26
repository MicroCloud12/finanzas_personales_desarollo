from . import views
from django.urls import path
from django.contrib.auth import views as auth_views

urlpatterns = [
    path('', views.home, name='home'),
    path('enviar-pregunta/', views.enviar_pregunta, name='enviar_pregunta'),
    path('transacciones/', views.crear_transacciones, name='crear_transacciones'),
    path('registrousuarios/', views.registro, name='registro_usuarios'),
    path('login/', auth_views.LoginView.as_view(template_name='iniciosesion.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('dashboard/', views.vista_dashboard, name='dashboard'),
    path('listatransacciones/', views.lista_transacciones, name='lista_transacciones'),
    path('transacciones/<int:transaccion_id>/editar/', views.editar_transaccion, name='editar_transaccion'),
    path('transacciones/<int:transaccion_id>/eliminar/', views.eliminar_transaccion, name='eliminar_transaccion'),
    path('api/datos-gastos-categoria/', views.datos_gastos_categoria, name='api_datos_gastos'),
    path('api/datos-flujo-dinero/', views.datos_flujo_dinero, name='api_flujo_dinero'),
    path('api/datos-inversiones/', views.datos_inversiones, name='api_datos_inversiones'),
    path('procesamiento-automatico/', views.vista_procesamiento_automatico, name='procesamiento_automatico'),
    path('procesar-drive/', views.iniciar_procesamiento_drive, name='procesar_drive'),
    path('revisar-tickets/', views.revisar_tickets, name='revisar_tickets'),
    path('aprobar-ticket/<int:ticket_id>/', views.aprobar_ticket, name='aprobar_ticket'),
    path('rechazar-ticket/<int:ticket_id>/', views.rechazar_ticket, name='rechazar_ticket'),
    path('resultado-tarea-inicial/<str:task_id>/', views.get_initial_task_result, name='get_initial_task_result'),
    path('aprobar-todos-tickets/', views.aprobar_todos_tickets, name='aprobar_todos_tickets'),
    path('rechazar-todos-tickets/', views.rechazar_todos_tickets, name='rechazar_todos_tickets'),
    path('estado-grupo/<str:group_id>/', views.get_group_status, name='get_group_status'),
    path('revisar_tickets/', views.revisar_tickets, name='revisar_tickets'),
    path('inversiones/', views.lista_inversiones, name='lista_inversiones'),
    path('inversiones/crear/', views.crear_inversion, name='crear_inversion'),
    path('inversiones/<int:inversion_id>/editar/', views.editar_inversion, name='editar_inversion'),
    path('inversiones/<int:inversion_id>/eliminar/', views.eliminar_inversion, name='eliminar_inversion'),
    path('procesamiento-inversiones/', views.vista_procesamiento_inversiones, name='procesamiento_inversiones'),
    path('procesar-inversiones/', views.iniciar_procesamiento_inversiones, name='procesar_drive_inversiones'),
    path('revisar-inversiones/', views.revisar_inversiones, name='revisar_inversiones'),
    path('revisar-inversiones/', views.revisar_inversiones, name='revisar_inversiones'),
    path('aprobar-inversion/<int:inversion_id>/', views.aprobar_inversion, name='aprobar_inversion'),
    path('rechazar-inversion/<int:inversion_id>/', views.rechazar_inversion, name='rechazar_inversion'),
    path('aprobar-todas-inversiones/', views.aprobar_todas_inversiones, name='aprobar_todas_inversiones'),
    path('rechazar-todas-inversiones/', views.rechazar_todas_inversiones, name='rechazar_todas_inversiones'),
    path('suscripcion/', views.gestionar_suscripcion, name='gestionar_suscripcion'),
    path('suscripcion/exitosa/', views.suscripcion_exitosa, name='suscripcion_exitosa'),
    path('suscripcion/fallida/', views.suscripcion_fallida, name='suscripcion_fallida'),
    path('suscripcion/webhook/', views.mercadopago_webhook, name='mercadopago_webhook'),
    path('api/datos-ganancias-mensuales/', views.datos_ganancias_mensuales, name='api_ganancias_mensuales'),
    path('deudas/', views.lista_deudas, name='lista_deudas'),
    path('deudas/crear/', views.crear_deuda, name='crear_deuda'),
    path('deudas/<int:deuda_id>/', views.detalle_deuda, name='detalle_deuda'),
    path('deudas/<int:deuda_id>/editar/', views.editar_deuda, name='editar_deuda'),
    path('deudas/<int:deuda_id>/eliminar/', views.eliminar_deuda, name='eliminar_deuda'),
    path('mi_perfil/', views.mi_perfil, name='mi_perfil'),
    path('facturacion/', views.facturacion, name='facturacion'),
    # --- URLs para el procesamiento automático de deudas ---
    path('deudas/procesamiento/<int:deuda_id>/', views.vista_procesamiento_deudas, name='procesamiento_deudas'),
    path('deudas/procesar-drive/<int:deuda_id>/', views.iniciar_procesamiento_deudas, name='procesar_drive_deudas'),
    path('deudas/revisar-amortizaciones/<int:deuda_id>/', views.revisar_amortizaciones, name='revisar_amortizaciones'),
    path('deudas/aprobar-amortizacion/<int:pendiente_id>/', views.aprobar_amortizacion, name='aprobar_amortizacion'),
    path('deudas/rechazar-amortizacion/<int:pendiente_id>/', views.rechazar_amortizacion, name='rechazar_amortizacion'),
    path('risc-webhook/', views.risc_webhook, name='risc_webhook'),
    # --- Fin de las nuevas URLs ---
    path('privacy-policy/', views.politica_privacidad, name='privacy_policy'),
    path('terms-of-service/', views.terminos_servicio, name='terms_of_service'),
# 1. El endpoint que activa la tarea de Celery (lo que llama el botón)
    path('api/procesar-facturas/', views.iniciar_procesamiento_facturacion, name='procesamiento_facturas'),

    # 2. La página a la que te redirige al terminar (la tabla de revisión)
    path('facturacion/pendientes/', views.revisar_facturas_pendientes, name='revisar_facturas_pendientes'),
    path('procesamiento-facturacion/', views.vista_procesamiento_facturacion, name='procesamiento_facturacion'),
    # 3. La vista individual para revisar un ticket específico (ya la tenías, la mantenemos)
    path('facturacion/revisar/<int:ticket_id>/', views.revisar_factura_individual, name='revisar_factura'),
    path('facturacion/pendientes/<int:ticket_id>/', views.revisar_factura_detalle, name='revisar_factura'),
    # 4. Acción para marcar como ya facturado
    path('facturacion/marcar-listo/<int:factura_id>/', views.marcar_como_facturado, name='marcar_facturado'),
    path('facturacion/procesar-drive/', views.iniciar_procesamiento_facturacion, name='procesar_drive_facturacion'),
    
    # OPCIONAL: Si decides hacer el procesamiento de facturas por separado de los gastos normales
    # path('facturacion/procesar-ticket/', views.procesar_ticket_factura, name='procesar_ticket_factura'),
    path('facturacion/eliminar/<int:ticket_id>/', views.eliminar_factura_pendiente, name='eliminar_factura'),
    path('facturacion/marcar-facturado/<int:ticket_id>/', views.marcar_ticket_facturado, name='marcar_ticket_facturado'),
    # --- URLs para gestionar facturas guardadas ---
    path('facturacion/editar/<int:factura_id>/', views.editar_factura_registro, name='editar_factura_registro'),
    path('facturacion/eliminar-registro/<int:factura_id>/', views.eliminar_factura_registro, name='eliminar_factura_registro'),
    # ... tus otras urls ...
    path('api/guardar-config-tienda/', views.guardar_configuracion_tienda, name='guardar_config_tienda'),
    path('api/confirmar-factura/', views.confirmar_datos_factura, name='confirmar_factura'),
    path('api/agregar-campo-tienda/', views.agregar_campo_tienda, name='agregar_campo_tienda'),
    path('api/eliminar-campo-tienda/', views.eliminar_campo_tienda, name='eliminar_campo_tienda'),
]