"""
Migración de datos existentes a cifrado Nivel 2 (usada por 0035_cifrar_datos_existentes).

Es idempotente:
1. Garantiza que cada `User` tenga su registro en `LlaveUsuario`.
2. Recorre cada una de las 14 tablas financieras; gracias a que los campos `Encrypted*Field`
   aceptan texto plano legado al leer (`from_db_value`) y escriben `enc:v1:<uid>:<token>` al
   guardar (`pre_save` + `get_db_prep_save`), re-guardar cada fila cifra en sitio los datos
   anteriores y calcula los índices ciegos (`*_hash`).
"""
from finanzas.crypto import blind_index, ensure_user_dek_bytes, global_blind_index


def cifrar_datos_existentes(apps, schema_editor=None):
    User = apps.get_model("auth", "User")
    LlaveUsuario = apps.get_model("finanzas", "LlaveUsuario")

    for uid in User.objects.values_list("id", flat=True):
        ensure_user_dek_bytes(uid, llave_model=LlaveUsuario)

    # 1. Modelos con índice ciego por usuario o global
    Cuenta = apps.get_model("finanzas", "Cuenta")
    for obj in Cuenta.objects.all().iterator(chunk_size=500):
        obj.nombre_hash = blind_index(obj.propietario_id, obj.nombre, llave_model=LlaveUsuario)
        obj.save()

    Deuda = apps.get_model("finanzas", "Deuda")
    for obj in Deuda.objects.all().iterator(chunk_size=500):
        obj.nombre_hash = blind_index(obj.propietario_id, obj.nombre, llave_model=LlaveUsuario)
        obj.save()

    Presupuesto = apps.get_model("finanzas", "Presupuesto")
    for obj in Presupuesto.objects.all().iterator(chunk_size=500):
        obj.categoria_hash = blind_index(obj.propietario_id, obj.categoria, llave_model=LlaveUsuario)
        obj.save()

    AliasComercio = apps.get_model("finanzas", "AliasComercio")
    for obj in AliasComercio.objects.all().iterator(chunk_size=500):
        obj.texto_banco_hash = blind_index(obj.propietario_id, obj.texto_banco, llave_model=LlaveUsuario)
        obj.save()

    Factura = apps.get_model("finanzas", "Factura")
    for obj in Factura.objects.all().iterator(chunk_size=500):
        obj.archivo_drive_hash = (
            None if obj.archivo_drive_id is None else global_blind_index(obj.archivo_drive_id)
        )
        obj.save()

    HistorialReciboServicio = apps.get_model("finanzas", "HistorialReciboServicio")
    for obj in HistorialReciboServicio.objects.all().iterator(chunk_size=500):
        obj.archivo_drive_hash = global_blind_index(obj.archivo_drive_id)
        obj.save()

    # 2. Modelos sin columnas *_hash propias (solo re-guardar cifra todos sus campos)
    modelos_simples = (
        "SaldoEstadoCuenta",
        "registro_transacciones",
        "TransaccionPendiente",
        "inversiones",
        "PendingInvestment",
        "PagoAmortizacion",
        "AmortizacionPendiente",
        "PortfolioHistory",
    )
    for nombre_modelo in modelos_simples:
        Modelo = apps.get_model("finanzas", nombre_modelo)
        for obj in Modelo.objects.all().iterator(chunk_size=500):
            obj.save()
