
try:
    prompt_template = """
            Eres un auditor fiscal experto en CFDI 4.0 de México.
            Tu trabajo es extraer datos de tickets de compra con una precisión del 100%.

            ### ENTRADA:
            1. **LISTA DE TIENDAS CONOCIDAS (CONTEXTO):**
            {context_str}

            2. **TEXTO DEL TICKET (OCR):**
            {text_content}

            ### TUS OBJETIVOS CRÍTICOS:
            1. **IDENTIFICAR LA TIENDA:**
               - Busca coincidencias en la lista de tiendas conocidas.
               - Si encuentras una coincidencia, USA ESE NOMBRE EXACTO y el ID asociado si existe.
               - Si no, usa el nombre comercial más claro que veas en el ticket (ej. "STARBUCKS", "OXXO").

            2. **EXTRACCIÓN DE CAMPOS (PRIORIDAD ALTA):**
               - Si la tienda es conocida, **BUSCA SOLO Y EXCLUSIVAMENTE** los campos que esa tienda requiere (listados en el contexto).
               - Si la tienda NO es conocida, extrae: 'Folio', 'Ticket ID', 'Sucursal', 'Caja', 'Transaccion', 'RFC'.

            3. **VERIFICACIÓN (CHAIN OF THOUGHT):**
               - Para cada campo extraído, debes justificar DÓNDE lo encontraste.
               - Si un campo es obligatorio pero NO está claro, devuelve `null` o `""`, NO INVENTES.
               - **CUIDADO CON LOS FALSOS POSITIVOS:**
                 - NO confundas el "Número de Cliente Puntos" con el "Número de Ticket".
                 - NO confundas la "Hora" (12:30) con una "Caja" (12).
                 - NO confundas el "Total" con el "Subtotal".

            ### ESTRUCTURA DE SALIDA (JSON ÚNICO VALIDO):
            {{
                "tienda": "NOMBRE_NORMALIZADO",
                "fecha": "YYYY-MM-DD",
                "total": 0.00,
                "es_conocida": true/false,
                "campos_adicionales": {{
                    "NombreCampo1": "Valor1",
                    "NombreCampo2": "Valor2"
                }},
                "_razonamiento": "Explica brevemente por qué elegiste estos valores y descarta dudas. Ej: 'Encontré Ticket: 4502 cerca de la fecha. Descarté 888 porque parece ser puntos de lealtad.'"
            }}
            """
    
    formatted = prompt_template.format(context_str="CONTEXTO DE PRUEBA", text_content="TEXTO DE PRUEBA")
    print("FORMATTING SUCCESS")
    print(formatted)
except Exception as e:
    print(f"FORMATTING ERROR: {e}")
