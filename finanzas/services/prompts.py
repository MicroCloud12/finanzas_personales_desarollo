# finanzas/services/prompts.py
# Optimized for Gemini API (Minimal tokens, direct constraints)

PROMPTS = {
    "tickets": """
### CONTEXTO DEL USUARIO
{context_str}

### INSTRUCCIONES
Extrae datos del recibo/ticket y mapealos al esquema JSON.
- `fecha`: YYYY-MM-DD.
- `establecimiento`: Comercio principal (ignorar bancos de terminales como BBVA/CLIP). Si es Express -> DIDI.
- `total`: Monto final (float).
- `tipo_movimiento`: GASTO, INGRESO o TRANSFERENCIA.
- `categoria_sugerida`: Elige estrictamente una del CONTEXTO.
- `cuenta_origen_sugerida`: Busca terminación de tarjeta en recibo (ej. VISA 1234) y cruza con 'Cuentas disponibles' del CONTEXTO. Coincidencia exacta -> nombre de cuenta. Efectivo -> nombre de cuenta efectivo. Sin cruce -> "".
- `cuenta_destino_sugerida`: "N/A" para compras.
- `descripcion_corta`: Concepto central. Omite "Transferencia de", "Pago de".
- `confianza_extraccion`: ALTA|MEDIA|BAJA
""",
    "inversion": """
### INSTRUCCIONES
Extrae datos del comprobante de inversión al esquema JSON.
- `fecha_compra`: YYYY-MM-DD.
- `emisora_ticker`: Símbolo (ej. NVDA, BTC/USD). Si dice BTC/MXN, asume BTC/USD (se normaliza todo a USD).
- `nombre_activo`: Nombre completo (ej. NVIDIA).
- `cantidad_titulos`: float.
- `precio_por_titulo`: float.
- `costo_total`: float.
- `moneda`: ej. USD, MXN.
- `tipo_cambio_usd`: Si se indica explícitamente, float; si no, null.
""",
    "deudas": """
### INSTRUCCIONES
Extrae CADA fila de la tabla de amortización como un array JSON de objetos. Ignora totales.
- `fecha_vencimiento`: YYYY-MM-DD.
- `capital`: Amortización de Capital (float).
- `interes`: Intereses (float).
- `iva`: IVA (float, 0.0 si no hay).
- `saldo_insoluto`: Saldo DESPUÉS de pago (float).
""",
    "facturacion": """
### CONTEXTO DE TIENDAS
{context_str}

### INSTRUCCIONES
Extrae datos para facturación CFDI 4.0.
1. Si la tienda está en el CONTEXTO, extrae SOLO los `campos_requeridos`.
2. Si no, extrae: Folio, Ticket ID, Transacción, Terminal, Monto, RFC, Fecha, CP.
- `tienda`: Nombre limpio (ej. WALMART).
- `fecha_emision`: YYYY-MM-DD.
- `total_pagado`: float.
- `tipo_documento`: TICKET_COMPRA | TRANSFERENCIA.
- Resto de campos descubiertos en el JSON raíz.
""",
    "facturacion_from_text": """
### INSTRUCCIONES
Extrae datos básicos de este OCR.
- `tienda`: Nombre comercial.
- `fecha`: YYYY-MM-DD.
- `total`: float.

OCR:
{text_content}
""",
    "facturacion_from_text_with_context": """
### TIENDAS CONOCIDAS
{context_str}

### INSTRUCCIONES
Auditor CFDI 4.0. Extrae datos del OCR con precisión 100%.
1. Si parece transferencia/pago servicios (CFE/SPEI), `es_transferencia` = true. Parar.
2. Si coincide con TIENDAS CONOCIDAS, extrae SOLO sus campos.
3. Si no, extrae Folio, Ticket ID, Sucursal, Caja, Transaccion, RFC.
- `tienda`: Normalizado o inferido.
- `es_conocida`: bool.
- `campos_adicionales`: JSON Object con campos extraídos (ej. McDonalds usa Sucursal=numero).
- `_razonamiento`: Breve justificación. NO confundir Puntos con Ticket. NO confundir Total con Subtotal.

OCR:
{text_content}
""",
    "recibo_servicio": """
### INSTRUCCIONES
Extrae datos del recibo de servicio.
- `fecha_emision`: YYYY-MM-DD.
- `monto_total`: float.
- `periodo_facturado`: string (ej. Enero 2025).
- `consumo`: string (ej. 150 kWh).
""",
    "recibo_servicio_from_text": """
### INSTRUCCIONES
Extrae datos del OCR del recibo.
- `fecha_emision`: YYYY-MM-DD.
- `monto_total`: float.
- `periodo_facturado`: string (ej. Enero 2025).
- `consumo`: string (ej. 150 kWh).

OCR:
{text_content}
""",
    "prediccion_servicio": """
### HISTÓRICO
{context_str}

### INSTRUCCIONES
Calcula matemáticamente una estimación del próximo recibo basándote en tendencias o promedios.
- `monto_predicho`: float.
- `fecha_predicha`: YYYY-MM-DD.
- `razonamiento`: string.
"""
}
