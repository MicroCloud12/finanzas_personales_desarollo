# finanzas/services/prompts.py
# Optimized using prompt-engineer skill frameworks (RTF + Chain of Thought)

PROMPTS = {
    "tickets": """
Role: Eres un experto analista contable especializado en extracción de datos financieros a partir de recibos y comprobantes.

Task: Extrae la información del recibo o ticket y mapea los valores exactamente a la estructura JSON requerida.

Approach step-by-step:
1. Analiza el nombre del establecimiento comercial principal. ESTANDARIZA el nombre eliminando razones sociales (ej. "S.A. de C.V."). Ignora bancos de terminales como BBVA/CLIP. Si el ticket es de un cajero automático y dice "RETIRO DE EFECTIVO" o "DISPOSICION", el establecimiento debe ser "Cajero [Nombre del Banco]" (ej. "Cajero Banorte"). Si es una captura de transferencia bancaria, IGNORA el título de la app (ej. "Santander Universidades"); el establecimiento debe ser el nombre del destinatario, o en su defecto, dejarlo vacío.
2. Identifica el monto total final pagado (o retirado). Si el monto aparece con signo negativo, extrae el valor absoluto positivo.
3. Clasifica el movimiento como GASTO, INGRESO o TRANSFERENCIA. Un retiro en cajero suele ser una TRANSFERENCIA a cuenta de efectivo, o GASTO.
4. Identifica la cuenta de origen. Busca los últimos 4 dígitos de la tarjeta o banco emisor. Crúzalo con las 'Cuentas disponibles' del CONTEXTO y devuelve ÚNICAMENTE el 'nombre'. Si es un retiro de efectivo de un banco, la cuenta origen es el banco.
5. Selecciona la categoría más adecuada basándote estrictamente en las opciones del CONTEXTO.
6. Identifica el CONCEPTO de la operación para usarlo como descripción corta. Si es un ticket de cajero automático (ej. "RETIRO DE EFECTIVO"), la descripción DEBE SER obligatoriamente "Retiro en efectivo" y NUNCA el nombre del banco. Para transferencias o comprobantes SPEI, busca 'concepto', 'motivo' o 'mensaje'. Si no aparecen, la descripción ES la frase descriptiva que aparece resaltada debajo del monto o la fecha (ej. "PAGO GAS JUNIO", "Ahorro"). NUNCA uses "N/A" si hay una frase así. NUNCA uses el nombre del banco o de la app (ej. "Santander") como descripción. Si es una compra, resume el giro del ticket.

Contexto del usuario:
{context_str}

Format: Devuelve ÚNICAMENTE un objeto JSON válido con la siguiente estructura:
{{
    "_razonamiento": "string - Explica paso a paso cómo identificaste el total, la cuenta origen y por qué elegiste el establecimiento y concepto.",
    "fecha": "YYYY-MM-DD",
    "establecimiento": "string - Comercio o destinatario. Si es una app bancaria, déjalo vacío. PROHIBIDO usar 'Universidades' o el nombre del banco.",
    "total": float,
    "tipo_movimiento": "GASTO|INGRESO|TRANSFERENCIA",
    "categoria_sugerida": "string",
    "cuenta_origen_sugerida": "string",
    "cuenta_destino_sugerida": "string o N/A",
    "descripcion_corta": "string - Concepto o motivo. En transferencias, DEBES extraer la frase debajo del monto/fecha (ej. 'PAGO GAS JUNIO'). PROHIBIDO usar 'N/A' a menos que realmente no haya ningún texto descriptivo.",
    "confianza_extraccion": "ALTA|MEDIA|BAJA"
}}
""",
    "inversion": """
Role: Eres un analista de inversiones y corredor de bolsa.

Task: Extrae los datos del comprobante de inversión y mapealos a la estructura JSON requerida.

Approach step-by-step:
1. Identifica la fecha de la transacción de compra o venta.
2. Identifica el símbolo ticker de la emisora (ej. NVDA, AAPL). Si indica BTC/MXN, asume BTC/USD.
3. Identifica el nombre completo del activo.
4. Calcula o extrae la cantidad de títulos exactos comprados.
5. Identifica el precio pagado por título y el costo total de la operación.
6. Identifica la moneda de la transacción y el tipo de cambio si es aplicable.

Format: Devuelve ÚNICAMENTE un objeto JSON válido con la siguiente estructura:
{{
  "_razonamiento": "string - Explica brevemente de dónde tomaste los valores de precio, cantidad y costo total.",
  "fecha_compra": "YYYY-MM-DD",
  "emisora_ticker": "string",
  "nombre_activo": "string",
  "cantidad_titulos": float,
  "precio_por_titulo": float,
  "costo_total": float,
  "moneda": "string",
  "tipo_cambio_usd": float o null
}}
""",
    "deudas": """
Role: Eres un actuario y analista de crédito.

Task: Extrae cada fila de la tabla de amortización proporcionada, ignorando los totales generales, y estructúralo como un array JSON de objetos.

Approach step-by-step:
1. Identifica las columnas de la tabla de amortización (Fecha, Capital, Interés, IVA, Saldo).
2. Ignora las filas de resumen o totales.
3. Procesa cada cuota o fila extrayendo los valores monetarios exactos sin símbolos de moneda.
4. Asegúrate de que el saldo insoluto sea el saldo restante DESPUÉS de aplicar el pago.

Format: Devuelve ÚNICAMENTE un JSON válido que sea un ARRAY de objetos `[]` con la siguiente estructura por objeto:
{{
  "_razonamiento": "string - Opcional por fila para explicar ajustes si hubo comisiones extra.",
  "fecha_vencimiento": "YYYY-MM-DD",
  "capital": float,
  "interes": float,
  "iva": float,
  "saldo_insoluto": float
}}
""",
    "facturacion": """
Role: Eres un auditor fiscal especialista en CFDI 4.0.

Objective: Extraer con precisión absoluta los datos para facturación, garantizando capturar el MONTO TOTAL real pagado, sin confundirlo con subtotales o cambio (que suele ser cero).

Approach step-by-step:
1. Analiza si el establecimiento pertenece a las TIENDAS CONOCIDAS del CONTEXTO. ESTANDARIZA el nombre de la tienda eliminando razones sociales.
2. Extrae los `campos_requeridos` indicados si es tienda conocida, o los genéricos (Folio, Ticket, etc.) si no lo es.
3. Busca el monto total a pagar. Identifica explícitamente palabras como "TOTAL", "IMPORTE" o "PAGO".
4. EVITA extraer líneas que digan "CAMBIO", "VUELTO" o "SUBTOTAL". Si tu extracción inicial del total resulta en 0.0, vuelve a evaluar el texto buscando el verdadero importe cobrado.
5. Clasifica el tipo de documento.

Contexto de Tiendas:
{context_str}

Format: Devuelve ÚNICAMENTE un objeto JSON válido con la siguiente estructura:
{{
  "_razonamiento": "string - Explica paso a paso cómo identificaste el total exacto para evitar extraer un cero.",
  "tienda": "string",
  "fecha": "YYYY-MM-DD",
  "total": float,
  "tipo_documento": "TICKET_COMPRA|TRANSFERENCIA",
  "campos_adicionales": {{}}
}}
""",
    "facturacion_from_text": """
Role: Eres un sistema OCR de extracción estructurada avanzado.

Objective: Extraer los datos básicos de facturación a partir de texto OCR, garantizando que el MONTO TOTAL sea el importe final pagado y nunca un valor de cero por error.

Approach step-by-step:
1. Identifica el nombre comercial de la tienda y ESTANDARIZA el nombre eliminando sufijos legales.
2. Localiza la fecha de la compra o emisión.
3. Extrae el monto TOTAL final pagado. Discrimina estrictamente entre el total real y otros números como el "Cambio" o "Vuelto" (que suelen ser $0.00). NO los confundas.
4. Sense Check: Verifica que el total no sea 0.0 (a menos que el OCR explícitamente indique un descuento del 100%).

Texto OCR:
{text_content}

Format: Devuelve ÚNICAMENTE un objeto JSON válido con la siguiente estructura:
{{
  "_razonamiento": "string - Indica brevemente la lógica para extraer el total real confirmando que no se tomó el 'cambio'.",
  "tienda": "string",
  "fecha": "YYYY-MM-DD",
  "total": float
}}
""",
    "facturacion_from_text_with_context": """
Role: Eres un Auditor Fiscal CFDI 4.0 automatizado y minucioso.

Objective: Analizar texto OCR de comprobantes para extraer datos con 100% de precisión, prestando especial cuidado a que el MONTO TOTAL sea correcto y no termine siendo extraído como cero.

Approach step-by-step:
1. Analiza el texto. Si es transferencia bancaria o pago de servicios, establece `es_transferencia` a true.
2. Verifica coincidencias con TIENDAS CONOCIDAS, estandariza el nombre, y extrae campos requeridos o estándar.
3. Extrae exhaustivamente el TOTAL FINAL. Es CRÍTICO ignorar líneas como 'Cambio: $0.00' o 'Su cambio $0'. El total debe ser el valor cobrado. 
4. Si inicialmente detectas un total de 0, revisa líneas anteriores buscando las palabras 'Total', 'Venta' o el monto de mayor denominación que corresponda a la suma.

Tiendas Conocidas:
{context_str}

Texto OCR:
{text_content}

Format: Devuelve ÚNICAMENTE un objeto JSON válido con la siguiente estructura:
{{
  "_razonamiento": "string - Justifica cómo aislaste el total final para evitar extraer un cero por error, además de los campos extraídos.",
  "tienda": "string",
  "fecha": "YYYY-MM-DD",
  "total": float,
  "es_conocida": bool,
  "es_transferencia": bool,
  "campos_adicionales": {{}}
}}
""",
    "recibo_servicio": """
Role: Eres un analista de servicios domiciliarios y facturación.

Task: Extrae los datos clave del recibo de servicio público o privado.

Approach step-by-step:
1. Identifica la fecha exacta de emisión del documento.
2. Localiza el monto total a pagar.
3. Extrae el periodo facturado textualmente.
4. Identifica el nivel de consumo y su unidad de medida.

Format: Devuelve ÚNICAMENTE un objeto JSON válido con la siguiente estructura:
{{
  "_razonamiento": "string - Explica de dónde sacaste el monto y el periodo.",
  "fecha_emision": "YYYY-MM-DD",
  "monto_total": float,
  "periodo_facturado": "string",
  "consumo": "string"
}}
""",
    "recibo_servicio_from_text": """
Role: Eres un analista de servicios domiciliarios operando sobre texto OCR.

Task: Extrae los datos clave del recibo basándote únicamente en el texto OCR proporcionado.

Approach step-by-step:
1. Lee el documento de arriba hacia abajo para encontrar la fecha de emisión.
2. Identifica el total a pagar definitivo.
3. Localiza el mes o rango de meses del periodo de facturación.
4. Extrae la métrica de consumo.

Texto OCR:
{text_content}

Format: Devuelve ÚNICAMENTE un objeto JSON válido con la siguiente estructura:
{{
  "_razonamiento": "string - Explica brevemente la extracción.",
  "fecha_emision": "YYYY-MM-DD",
  "monto_total": float,
  "periodo_facturado": "string",
  "consumo": "string"
}}
""",
    "prediccion_servicio": """
Role: Eres un Analista Financiero Predictivo Senior experto en series de tiempo.

Objective: Estimar el monto a pagar y la fecha exacta de emisión del próximo recibo de servicio (luz, agua, gas).

Details:
- Se te proporcionará un JSON con la 'fecha_actual_sistema' y el 'historial_recibos'.
- Regla para la 'fecha_predicha': Toma la fecha del último recibo y calcula matemáticamente la próxima fecha que sea ESTRICTAMENTE POSTERIOR al mes de 'fecha_actual_sistema'.
- IMPORTANTE: NO iterar paso a paso escribiendo cada ciclo si la fecha es antigua. Utiliza una suma matemática directa para encontrar el mes futuro correspondiente que preserve el día original.
- Ejemplos: Si hoy es Junio y el cálculo base te da Julio, DETENTE, esa es la fecha correcta. Si el último recibo fue hace un año, calcula directamente el salto de meses hacia el futuro actual (Julio o Agosto del presente año) conservando el día y la frecuencia (mensual/bimestral).

Approach:
1. Determina la frecuencia (1 mes o 2 meses) basándote en la distancia entre los últimos recibos.
2. Identifica el mes y año de la 'fecha_actual_sistema'.
3. Calcula matemáticamente el próximo ciclo de facturación que caiga en un mes ESTRICTAMENTE MAYOR al mes de la 'fecha_actual_sistema'.
4. Calcula el monto predicho promediando o detectando tendencias en los últimos recibos.

Contexto (Fecha actual y sumario histórico):
{context_str}

Format: Devuelve ÚNICAMENTE un objeto JSON válido con la siguiente estructura:
{{
  "_razonamiento": "string - Muestra brevemente la frecuencia detectada y el salto matemático directo a la fecha futura, sin iteraciones largas.",
  "monto_predicho": float,
  "fecha_predicha": "YYYY-MM-DD"
}}
"""
}
