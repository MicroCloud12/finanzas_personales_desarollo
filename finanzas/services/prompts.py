# finanzas/services/prompts.py
# Optimized using prompt-engineer skill frameworks (RTF + Chain of Thought)

PROMPTS = {
    "tickets": """
Role: Eres un experto analista contable especializado en extracción de datos financieros a partir de recibos y comprobantes.

Task: Extrae la información del recibo o ticket y mapea los valores exactamente a la estructura JSON requerida.

Approach step-by-step:
0. PRIMERO determina el tipo de documento:
   - TICKET_COMPRA: ticket o recibo de una compra o pago.
   - TRANSFERENCIA: comprobante de transferencia, SPEI, pago de servicio o retiro de cajero.
   - CAPTURA_BANCO: captura de pantalla de la app del banco que muestra un depósito recibido o el saldo
     de una cuenta (ej. "Cuentas en pesos", "Saldo disponible", pantalla de inicio del banco). Trátala como
     un INGRESO: tipo_movimiento = "INGRESO", total = el monto del depósito si aparece y, si no, el saldo
     que muestra la pantalla (NUNCA 0 si hay una cifra visible). Si es un abono de nómina (texto como NOMINA,
     SUELDO, PAGO DE NOMINA, o el depósito viene de una empresa) descripcion_corta = "Nómina" y
     categoria_sugerida = "Nomina"; si no, descripcion_corta = el concepto visible o "Depósito".
     cuenta_origen_sugerida = la cuenta del CONTEXTO
     que corresponda al banco o a los últimos 4 dígitos visibles (es la cuenta a la que ENTRA el dinero).
   - NO_FINANCIERO: la imagen no contiene información financiera. Devuelve total = 0 y tipo_movimiento = "NINGUNO".
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
    "tipo_documento": "TICKET_COMPRA|TRANSFERENCIA|CAPTURA_BANCO|NO_FINANCIERO",
    "fecha": "YYYY-MM-DD",
    "establecimiento": "string - Comercio o destinatario. Si es una app bancaria, déjalo vacío. PROHIBIDO usar 'Universidades' o el nombre del banco.",
    "total": float,
    "tipo_movimiento": "GASTO|INGRESO|TRANSFERENCIA|NINGUNO",
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
3. Localiza la fecha límite de pago ("límite de pago", "pagar antes de", "vencimiento"); si no aparece, null.
4. Extrae el periodo facturado textualmente.
5. Identifica el nivel de consumo y su unidad de medida.

Format: Devuelve ÚNICAMENTE un objeto JSON válido con la siguiente estructura:
{{
  "_razonamiento": "string - Explica de dónde sacaste el monto, el periodo y la fecha límite.",
  "fecha_emision": "YYYY-MM-DD",
  "fecha_limite_pago": "YYYY-MM-DD o null",
  "monto_total": float,
  "periodo_facturado": "string",
  "consumo": "string"
}}
""",
    "prediccion_servicio": """
Role: Eres un Analista Financiero y de Servicios Residenciales en México experto en pronóstico de consumo estacional (agua, luz CFE, gas, internet y servicios del hogar).

Task: Pronostica cuánto pagará el usuario en su PRÓXIMO recibo (posterior al último registrado) y su fecha estimada de emisión, sin importar cuántos días falten para que llegue.

Approach step-by-step:
1. Frecuencia real del servicio: Revisa `periodo_facturado` y las fechas del historial. Si el periodo facturado cubre ~1 mes (ej. "08 OCT - 07 NOV"), el servicio es MENSUAL (~30 días) aunque falten recibos intermedios en el historial; si cubre ~2 meses (ej. "SEP - NOV"), es BIMESTRAL (~60 días). Calcula `fecha_predicha` estrictamente posterior a `fecha_actual` y al último recibo.
2. Consumo físico y recibos atípicos: Analiza `consumo` (m³, kWh, litros) junto con `monto_total` para identificar el consumo habitual y el costo implícito por unidad. NO copies ni extrapoles linealmente el último recibo si presenta un pico inusual, recargo o salto aislado respecto al historial; pondera el comportamiento normal del hogar.
3. Estacionalidad climática según los meses que cubrirá el próximo recibo:
   - Invierno (noviembre, diciembre, enero, febrero):
     * Agua: menor calor, riego y uso de agua fría -> el consumo suele bajar (típicamente 10%-25% respecto a meses cálidos o picos previos).
     * Luz (CFE): sin aire acondicionado ni ventiladores -> el consumo baja notablemente frente a verano/otoño (salvo evidencia clara de calefacción eléctrica en invierno previo).
     * Gas: el agua fría de red exige más gas en el boiler/calentador -> el consumo suele subir moderadamente (10%-25%).
   - Primavera / Verano (abril a septiembre): sube el consumo de Agua y Luz por calor/aire acondicionado; baja el de Gas.
   - Internet / Telefonía: monto estable salvo cambio de tarifa visible en los últimos recibos.
   - Si hay recibos de la misma época del año anterior, úsalos como referencia principal.
4. Estima el consumo esperado para la temporada entrante y conviértelo en `monto_predicho` con base en la tarifa implícita reciente.

Datos del servicio e historial:
{context_str}
{text_content}

Format: Devuelve ÚNICAMENTE un objeto JSON válido con la siguiente estructura:
{{
  "razonamiento": "string - Explicación clara y concisa en español (1-2 oraciones) indicando cómo influyeron el consumo histórico y la época del año (ej. invierno en diciembre/enero).",
  "consumo_estimado": "string - Consumo físico esperado con su unidad (ej. '18 m3', '240 kWh' o 'N/A')",
  "frecuencia_dias": int,
  "fecha_predicha": "YYYY-MM-DD",
  "monto_predicho": float
}}
""",
}
