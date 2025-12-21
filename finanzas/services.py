# finanzas/services.py
import os
import re
import json
import jwt
import base64
import requests
import logging
import mercadopago
from PIL import Image
from io import BytesIO
from decimal import Decimal
from twelvedata import TDClient
from jwt import PyJWKClient
from cachetools import TTLCache
from django.conf import settings
from django.conf import settings
import google.generativeai as genai
from mistralai import Mistral
import numpy as np
import cv2
from django.http import JsonResponse
from .utils import parse_date_safely
from allauth.socialaccount.models import SocialAccount
from .models import TiendaFacturacion
from django.contrib.sessions.models import Session
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
#from alpha_vantage.timeseries import TimeSeries
from google.oauth2.credentials import Credentials
from allauth.socialaccount.models import SocialApp, SocialToken
from .models import registro_transacciones, TransaccionPendiente, User, inversiones, PendingInvestment
import re
from difflib import get_close_matches


logger = logging.getLogger(__name__)

class GoogleDriveService:
    # ... (esta clase no cambia)
    """
    Servicio para interactuar con la API de Google Drive.
    Encapsula la creación del cliente y las operaciones con archivos/carpetas.
    """
    def __init__(self, user: User):
        try:
            app = SocialApp.objects.get(provider='google')
            google_token = SocialToken.objects.get(account__user=user, account__provider='google')
            
            creds = Credentials(
                token=google_token.token,
                refresh_token=google_token.token_secret,
                token_uri='https://oauth2.googleapis.com/token',
                client_id=app.client_id,
                client_secret=app.secret
            )
            self.service = build('drive', 'v3', credentials=creds)
        except (SocialToken.DoesNotExist, SocialApp.DoesNotExist) as e:
            raise ConnectionError("No se encontró una cuenta de Google vinculada o la configuración de la App Social.") from e

    def _get_folder_id(self, folder_name: str) -> str | None:
        try:
            query = f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
            response = self.service.files().list(q=query, spaces='drive', fields='files(id)').execute()
            return response.get('files', [])[0]['id'] if response.get('files') else None
        except HttpError as error:
            print(f"Ocurrió un error al buscar la carpeta '{folder_name}': {error}")
            return None

    def list_files_in_folder(self, folder_name: str, mimetypes: list[str]) -> list[dict]:
        folder_id = self._get_folder_id(folder_name)
        if not folder_id:
            return []
        
        mime_query = " or ".join([f"mimeType='{m}'" for m in mimetypes])
        query = f"'{folder_id}' in parents and ({mime_query}) and trashed=false"
        
        try:
            results = self.service.files().list(q=query, fields="files(id, name, mimeType)").execute()
            return results.get('files', [])
        except HttpError as error:
            print(f"Ocurrió un error al listar archivos: {error}")
            return []

    def get_file_content(self, file_id: str) -> BytesIO:
        request = self.service.files().get_media(fileId=file_id)
        return BytesIO(request.execute())

class GeminiService:
    """
    Servicio para interactuar con la API de Gemini de Google.
    """
    def __init__(self):
        genai.configure(api_key=settings.GEMINI_API_KEY)
        self.model = genai.GenerativeModel("gemini-2.5-pro")
        
        # --- CAMBIO EN EL PROMPT ---
        # Reforzamos la instrucción de la fecha.
        self.prompts = { 
            "tickets": """
            Eres un asistente experto en contabilidad para un sistema de finanzas personales.
            Tu tarea es analizar la imagen lo mas detallado posible de un documento y extraer la información clave con la máxima precisión.
            Devuelve SIEMPRE la respuesta en formato JSON, sin absolutamente ningún texto adicional.

            ### CONTEXTO:
            El usuario ha subido una imagen de un ticket de compra o un comprobante de transferencia.
            Necesito que identifiques el tipo de documento y extraigas los siguientes campos:

            ### FORMATO DE SALIDA ESTRICTO (JSON):
            {
              "tipo_documento": "(TICKET_COMPRA|TRANSFERENCIA|OTRO)",
              "fecha": "YYYY-MM-DD",
              "establecimiento": "Nombre del comercio o beneficiario",
              "descripcion_corta": "Un resumen breve del gasto (ej. 'Renta depto', 'Supermercado', 'Cena con amigos')",
              "total": 0.00,
              "confianza_extraccion": "(ALTA|MEDIA|BAJA)"
            }
            
            ### REGLAS DE EXTRACCIÓN:
            1.  **fecha**: Busca la fecha principal. Si no la encuentras, usa la fecha actual. Formato YYYY-MM-DD.
            2.  **establecimiento**: El nombre principal de la tienda (ej. "Walmart", "Starbucks", "CFE"). Si es una transferencia, el nombre del beneficiario.
            3.  **descripcion_corta**: Si es un ticket con muchos artículos, pon "Supermercado" o "Compra tienda". Si es una transferencia, usa el concepto.
            4.  **total**: El monto TOTAL final. Debe ser un número (float), sin el símbolo de moneda.
            5.  **confianza_extraccion**: Evalúa tu propia certeza.
                - **ALTA**: Si la imagen es clara y todos los campos son obvios.
                - **MEDIA**: Si la imagen es un poco borrosa o un campo es ambiguo.
                - **BAJA**: Si la imagen es muy difícil de leer o faltan datos clave.

            ### EJEMPLOS:
            - **Ejemplo 1 (Ticket claro):**
              { "tipo_documento": "TICKET_COMPRA", "fecha": "2025-07-03", "establecimiento": "La Comer", "descripcion_corta": "Supermercado", "total": 854.50, "confianza_extraccion": "ALTA" }
            - **Ejemplo 2 (Transferencia):**
              { "tipo_documento": "TRANSFERENCIA", "fecha": "2025-07-01", "establecimiento": "N/A", "descripcion_corta": "Digitt002", "total": 7500.00, "confianza_extraccion": "ALTA" }
            - **Ejemplo 3 (Ticket borroso):**
              { "tipo_documento": "TICKET_COMPRA", "fecha": "2025-06-28", "establecimiento": "Restaurante El Sol", "descripcion_corta": "Comida", "total": 450.00, "confianza_extraccion": "MEDIA" }

            ### Nota importante:
            - Quiero que revices bien si es ticket o transferencia, ya que la extracción de datos es diferente. y lo has estado haciendo mal.
            Por ejemplo, en las transferencias estas poniendo el nombre del usuario con el nombre del banco, y no es correcto.
            Lo correcto seria que pongas el concepto de la transferencia, que es lo que el usuario pone en la app de su banco. Y eso normalmente lo pone tal cual en la transferencia.
            - En caso de que el Establecimiento sea Express, sustituyelo por DIDI e igual en caso de que sea Tickets ponlos en mayusculas.

            Ahora, analiza la siguiente imagen:
        """,
        "inversion": """
            Eres un asistente experto en finanzas, especializado en extraer datos clave de comprobantes de inversión (compra de acciones o criptomonedas). 
            Tu tarea es analizar la imagen lo mas detallado posible de un documento y extraer la información clave con la máxima precisión.
            Devuelve SIEMPRE la respuesta en formato JSON, sin absolutamente ningún texto adicional.

            ### CONTEXTO:
            El usuario ha subido una imagen de una inversion que ha comprado.
            Necesito que identifiques el tipo de documento y extraigas los siguientes campos:

            ### FORMATO DE SALIDA (JSON):
            {
            "fecha_compra": "YYYY-MM-DD",
            "emisora_ticker": "Símbolo del activo (ej. NVDA, BTC/USD)",
            "nombre_activo": "Nombre completo del activo (ej. NVIDIA, Bitcoin)",
            "cantidad_titulos": 0.0,
            "precio_por_titulo": 0.0,
            "costo_total": 0.0,
            "moneda": "La moneda de la transacción (ej. USD, MXN)",
            "tipo_cambio_usd": null
            }

            ### REGLAS DE EXTRACCIÓN:
            1.  **fecha_compra**: Extrae la fecha principal de la operación en formato AÑO-MES-DÍA.
            2.  **emisora_ticker**: El símbolo de la acción o criptomoneda (ej. NVDA, AAPL, BTC/USD, ETH/USD).
            3.  **nombre_activo**: El nombre completo. Si la imagen solo muestra el ticker (ej. "NVDA"), infiere el nombre de la empresa (ej. "NVIDIA").
            4.  **cantidad_titulos**: El número de acciones o unidades de cripto. Debe ser un número decimal (float).
            5.  **precio_por_titulo**: El costo de cada título o unidad. Debe ser un número.
            6.  **costo_total**: El monto principal de la "Orden completada" o "Monto gastado". Debe ser un número.
            7.  **moneda**: Identifica la moneda de la transacción (USD, MXN, etc.).
            8.  **tipo_cambio_usd**: Solo si la imagen muestra explícitamente un tipo de cambio contra el dólar estadounidense (USD), de lo contrario, debe ser `null`.

            ### EJEMPLOS:

            **Ejemplo 1 (Compra de Acciones):**
            *IMAGEN DE ENTRADA: Comprobante de GBM para NVDA.*
            *SALIDA ESPERADA:*
            ```json
            {
            "fecha_compra": "2025-07-11",
            "emisora_ticker": "NVDA",
            "nombre_activo": "NVIDIA Corp.",
            "cantidad_titulos": 0.09438,
            "precio_por_titulo": 166.24,
            "costo_total": 15.72,
            "moneda": "USD",
            "tipo_cambio_usd": null
            }

            **Ejemplo 2 (Compra de Criptomonedas):**
            {
            "fecha_compra": "2025-07-14",
            "emisora_ticker": "ETH/USD",
            "nombre_activo": "Ethereum",
            "cantidad_titulos": 0.00396252,
            "precio_por_titulo": 57791.50,
            "costo_total": 229.00,
            "moneda": "MXN",
            "tipo_cambio_usd": null
            }

            *Aseguarte que aunque el ticker sea ETH/MXN en caso de Etherum, BTC/MXN en caso de Bitcoin cambialo ETH/USD y BTC/USD, ya que estoy convirtiendo todo en USD y no en MXN.
        """,
        "deudas": """
            Eres un asistente experto en finanzas, especializado en digitalizar tablas de amortización de préstamos.
            Tu tarea es analizar la imagen de un documento y extraer CADA UNA de las filas de la tabla de pagos con la máxima precisión.
            Devuelve SIEMPRE la respuesta como un array de objetos JSON, sin texto adicional.

            ### CONTEXTO:
            El usuario ha subido una imagen de una tabla de amortización. Necesito que extraigas los datos de cada cuota.

            ### FORMATO DE SALIDA ESTRICTO (Array de JSON):
            [
              {
                "fecha_vencimiento": "YYYY-MM-DD",
                "capital": 0.00,
                "interes": 0.00,
                "iva": 0.00,
                "saldo_insoluto": 0.00
              },
              {
                "fecha_vencimiento": "YYYY-MM-DD",
                "capital": 0.00,
                "interes": 0.00,
                "iva": 0.00,
                "saldo_insoluto": 0.00
              }
            ]
            
            ### REGLAS DE EXTRACCIÓN POR CAMPO:
            1.  **fecha_vencimiento**: La fecha exacta de pago de esa cuota. Formato AÑO-MES-DÍA.
            2.  **capital**: El monto destinado a la "Amortización de Capital". Debe ser un número (float).
            3.  **interes**: El monto de "Intereses". Debe ser un número (float).
            4.  **iva**: El monto del "IVA". Si la columna no existe, el valor debe ser 0.00.
            5.  **saldo_insoluto**: El "Saldo Insoluto" o saldo restante DESPUÉS de ese pago. Debe ser un número (float).

            ### NOTA IMPORTANTE:
            - Ignora el "Pago Total del Periodo", ya que lo calcularemos después.
            - Asegúrate de devolver un objeto JSON por CADA fila de la tabla de amortización.

            Ahora, analiza la siguiente imagen y extrae todas las filas de la tabla de amortización:
        """,
            "facturacion": """
            Eres un asistente obsesivo con la precisión para la FACTURACIÓN FISCAL en México (CFDI 4.0).
            Tu único propósito es extraer los datos EXACTOS que el usuario necesita para generar su factura en el portal del comercio.

            ### CONTEXTO DINÁMICO (TIENDAS CONOCIDAS):
            {context_str}

            ### INSTRUCCIONES:
            1.  Analiza la imagen e IDENTIFICA LA TIENDA.
            2.  **REVISA EL CONTEXTO DINÁMICO**:
                - Si la tienda está en la lista de "tiendas conocidas", **BUSCA SOLAMENTE LOS CAMPOS LISTADOS** en "campos_requeridos" para esa tienda.
                - Prioriza la extracción de esos campos específicos sobre cualquier otro.
            3.  Si la tienda NO está en la lista (o la lista está vacía):
                - Extrae TODOS los posibles datos de facturación estándar (Folio, Ticket ID, Transacción, Terminal, Código Web, Monto, RFC, Fecha, Código Postal).
            
            ### REGLAS DE ORO:
            - **Tienda**: Devuelve el nombre comercial limpio (ej. "WALMART", "OXXO", "STARBUCKS"). MAYÚSCULAS.
            - **Campos Específicos**: Si el contexto pide "Ticket ID", búscalo exhaustivamente aunque esté borroso.
            - **Valores**: Extrae los números tal cual aparecen (con guiones o sin ellos, según sea común en esa tienda, pero prefiere limpio).
            - **Distinción**: Diferencia entre "Ticket" y "Transferencia". Si es transferencia, márcalo.

            ### FORMATO DE SALIDA (JSON):
            {
            "tienda": "NOMBRE DE LA TIENDA",
            "fecha_emision": "YYYY-MM-DD",
            "total_pagado": 0.0,
            "tipo_documento": "TICKET_COMPRA | TRANSFERENCIA",
            # Campos flexibles extraídos (claves sugeridas: folio, ticket_id, sucursal, transaccion, codigo_facturacion, rfc_emisor, uso_cfdi, etc.)
            "folio": "...",
            "ticket_id": "...",
            "sucursal": "...",
            # ... otros campos encontrados ...
            }
            """,
            "facturacion_from_text": """
            Eres un experto en extracción de datos de facturación.
            Analiza el siguiente TEXTO CRUDO obtenido de un OCR (Mistral) de un ticket de compra.
            
            Tu objetivo es extraer:
            1. **tienda**: El nombre comercial del establecimiento. (Ej. "STARBUCKS", "COSTCO", "OXXO"). Importante: Si no es claro, infiérelo por el contexto del texto.
            2. **fecha**: Fecha de la compra en formato YYYY-MM-DD.
            3. **total**: El monto total pagado (numérico).
            
            Devuelve un JSON con esta estructura:
            {
                "tienda": "NOMBRE",
                "fecha": "YYYY-MM-DD",
                "total": 0.0
            }
            
            Texto OCR:
            {text_content}
            """,
            "facturacion_from_text_with_context": """
            Eres un experto en extracción de datos de facturación en México.
            Analiza el siguiente TEXTO CRUDO obtenido de un OCR (Mistral) de un ticket de compra.

            ### CONTEXTO DE TIENDAS CONOCIDAS:
            {context_str}

            ### INSTRUCCIONES:
            1.  **Identificar Tienda**: Busca el nombre del establecimiento en el texto.
            2.  **Verificar Requisitos**: Si el nombre de la tienda coincide (o es muy similar) a una de las "Tiendas Conocidas", **DEBES** buscar obligatoriamente los campos listados para esa tienda (ej. "Ticket ID", "Sucursal", etc.).
            3.  **Regla Especial 'Sucursal'**: 
                - Si se pide "Sucursal", busca el **NÚMERO** o **CÓDIGO** de la sucursal (ej. "Suc: 402", "Store# 3920").
                - EVITA devolver el nombre de la calle o colonia (ej. "Polanco", "Centro") salvo que no exista ningún número.
            4.  **Extracción General**:
                - **tienda**: Nombre comercial (MAYÚSCULAS).
                - **fecha**: Formato YYYY-MM-DD.
                - **total**: Monto total pagado (numérico).
                - **campos_adicionales**: Aquí DEBES poner todos los campos específicos encontrados (Folio, Sucursal, Ticket ID, etc.).

            Devuelve un JSON con esta estructura:
            {
                "tienda": "NOMBRE",
                "fecha": "YYYY-MM-DD",
                "total": 0.0,
                "campos_adicionales": {
                    "Sucursal": "3940",
                    "Ticket ID": "..."
                }
            }

            Texto OCR:
            {text_content}
            """
        }
        # Preconfiguramos configs opcionales de generación
        self.generation_config = genai.types.GenerationConfig(
            temperature=0.1, # Muy bajo para máxima precisión literal
            max_output_tokens=1024,
        )

    def _prepare_content(self, file_data, mime_type: str):
        """Prepara el contenido para enviarlo a Gemini (Imagen o PDF)."""
        if mime_type == 'application/pdf':
            return {
                "mime_type": "application/pdf",
                "data": file_data 
            }
        else:
            # Asumimos que es una imagen (bytes)
            return {
                "mime_type": mime_type, # ej. "image/jpeg"
                "data": file_data
            }

    def extract_data(self, prompt_name: str, file_data, mime_type: str, context: str = "") -> dict:
        """
        Extrae datos de una imagen o PDF utilizando un prompt específico.
        Permite inyectar contexto dinámico (como lista de tiendas conocidas) en el prompt.
        """
        if prompt_name not in self.prompts:
            raise ValueError(f"El prompt '{prompt_name}' no existe.")

        raw_prompt = self.prompts[prompt_name]
        
        # Inyectamos el contexto si el prompt tiene el placeholder {context_str}
        try:
            prompt = raw_prompt.format(context_str=context)
        except KeyError:
            # Si el prompt no tiene el placeholder, usamos el prompt tal cual (para compatibilidad)
            prompt = raw_prompt

        prepared_content = self._prepare_content(file_data, mime_type)
        
        return self._generate_and_parse(prompt, prepared_content)

    def extract_from_text(self, prompt_name: str, text: str, context: str = "") -> dict:
        """
        Extrae datos de un texto crudo utilizando un prompt específico.
        Permite contexto dinámico.
        """
        if prompt_name not in self.prompts:
            raise ValueError(f"El prompt '{prompt_name}' no existe.")
            
        raw_prompt = self.prompts[prompt_name]
        
        # Inyectamos el texto (y contexto si existe) en el prompt
        try:
            # Intentamos formatear con ambos
            prompt = raw_prompt.format(text_content=text, context_str=context)
        except KeyError:
             # Si falla (ej. el prompt viejo no tiene context_str), probamos solo con text_content
            try:
                prompt = raw_prompt.format(text_content=text)
            except KeyError:
                # Fallback final
                prompt = raw_prompt + "\n\n" + text

        # Para texto, enviamos solo el prompt string. Gemini lo maneja bien.
        
        response = self.model.generate_content(prompt)
        # Reutilizamos la lógica de limpieza de JSON
        cleaned_response = response.text.strip()
        if cleaned_response.startswith("```json"):
            cleaned_response = cleaned_response[7:]
        if cleaned_response.startswith("```"):
            cleaned_response = cleaned_response[3:]
        if cleaned_response.endswith("```"):
            cleaned_response = cleaned_response[:-3]
        cleaned_response = cleaned_response.strip()
        
        try:
            return json.loads(cleaned_response)
        except json.JSONDecodeError:
            logger.error(f"Error: La respuesta de Gemini no es un JSON válido: {cleaned_response}")
            return {}

    def _generate_and_parse(self, prompt: str, content) -> dict:
        """Genera la respuesta de Gemini y devuelve el JSON parseado."""
        response = self.model.generate_content([prompt, content])
        cleaned_response = response.text.strip()
        if cleaned_response.startswith("```json"):
            cleaned_response = cleaned_response[7:]
        if cleaned_response.startswith("```"):
            cleaned_response = cleaned_response[3:]
        if cleaned_response.endswith("```"):
            cleaned_response = cleaned_response[:-3]
        cleaned_response = cleaned_response.strip()
        
        try:
            return json.loads(cleaned_response)
        except json.JSONDecodeError:
            logger.error(f"Error: La respuesta de Gemini no es un JSON válido: {cleaned_response}")
            return {
                "error": "Respuesta no válida de la IA",
                "raw_response": cleaned_response
            }
    
_gemini_singleton = None
def get_gemini_service() -> GeminiService:
    """Obtiene una instancia única de :class:`GeminiService` por proceso."""
    global _gemini_singleton
    if _gemini_singleton is None:
        _gemini_singleton = GeminiService()
    return _gemini_singleton

class TransactionService:
    """
    Servicio para manejar la lógica de negocio de las transacciones.
    """
    @staticmethod
    def create_pending_transaction(user: User, data: dict):
        if "error" in data:
            print(f"No se creará transacción pendiente debido a un error previo: {data['error']}")
            return None
        
        return TransaccionPendiente.objects.create(
            propietario=user,
            datos_json=data,
            estado='pendiente'
        )

    @staticmethod
    def approve_pending_transaction(ticket_id: int, user: User, cuenta: str, categoria: str, tipo_transaccion: str, cuenta_destino: str):
        try:
            ticket = TransaccionPendiente.objects.get(id=ticket_id, propietario=user)
            datos = ticket.datos_json
            print(f"Aprobando ticket: {ticket_id} con datos: {datos}")
            tipo_documento = datos.get("tipo_documento")
            
            # Por defecto, usamos la descripción corta
            descripcion_final = datos.get("descripcion_corta", "Sin descripción")
            
            # Si es un ticket de compra, sobrescribimos con el nombre del establecimiento
            if tipo_documento == 'TICKET_COMPRA':
                descripcion_final = datos.get("establecimiento", "Compra sin establecimiento")
            
            # --- FIN DE LA LÓGICA ---
            # Usamos nuestra función segura para procesar la fecha.
            # Ya no hay riesgo de que el programa se rompa por un formato incorrecto.
            fecha_segura = parse_date_safely(datos.get("fecha") or datos.get("fecha_emision"))

            # Validamos el monto (puede venir como 'total' o 'total_pagado')
            monto_str = str(datos.get("total") or datos.get("total_pagado") or 0.0)

            registro_transacciones.objects.create(
                propietario=user,
                fecha=fecha_segura, # Usamos la fecha limpia y validada
                #descripcion=datos.get("descripcion_corta", datos.get("establecimiento", "Sin descripción")),
                descripcion=descripcion_final.upper(),
                categoria=categoria,
                monto=Decimal(monto_str), # Convertir a string primero para mayor precisión con Decimal
                tipo=tipo_transaccion,
                cuenta_origen=cuenta,
                cuenta_destino=cuenta_destino,
                datos_extra=datos  # Guardamos TODOS los datos originales (RFC, Folio, etc.)
            )
            
            ticket.estado = 'aprobada'
            ticket.save()
            return ticket
        except TransaccionPendiente.DoesNotExist:
            return None
        
class MercadoPagoService:
    """
    Servicio para manejar la lógica de negocio con Mercado Pago.
    """
    def __init__(self):
        self.sdk = mercadopago.SDK(os.getenv('MERCADOPAGO_ACCESS_TOKEN'))
        self.plan_id = os.getenv('MERCADOPAGO_PLAN_ID')
        if not self.sdk or not self.plan_id:
            raise ValueError("Las credenciales o el Plan ID de Mercado Pago no están configurados en .env")
    
    def crear_link_suscripcion(self, user, back_url: str):
        """
        Construye el link de checkout para la suscripción.
        No requiere una llamada a la API.
        """
        # La URL base para el checkout de suscripciones
        base_url = "https://www.mercadopago.com.mx/subscriptions/checkout"
        
        # Construimos la URL final con el ID de nuestro plan
        checkout_url = f"{base_url}?preapproval_plan_id={self.plan_id}"
        
        # La back_url y el email del usuario se gestionan en la configuración
        # del plan en el panel de Mercado Pago y cuando el usuario inicia sesión allí.
        
        return checkout_url

class StockPriceService:
    """
    Servicio para obtener precios de acciones de Alpha Vantage.
    """
    # Caches para limitar las consultas a la API
    _price_cache: TTLCache = TTLCache(maxsize=100, ttl=300)   # 5 minutos
    _series_cache: TTLCache = TTLCache(maxsize=50, ttl=86400) # 1 día

    def __init__(self):
        self.api_key = os.getenv("TWELVEDATA_API_KEY")
        if not self.api_key:
            raise ValueError("No se encontró la clave de API de Twelve Data en .env")
        self.client = TDClient(apikey=self.api_key)

    def get_current_price(self, ticker: str):
        """
        Obtiene el precio más reciente para un ticker.
        Ejemplo: 'AAPL' para Apple, 'BIMBOA.MX' para Bimbo en la BMV.
        """
        cache_key = ticker.upper()
        if cache_key in self._price_cache:
            return self._price_cache[cache_key]
        
        try:
            quote = self.client.quote(symbol=ticker)
            data = quote.as_json()
            # El endpoint devuelve una lista o un dict según el modo.
            if isinstance(data, list):
                data = data[0] if data else {}
            current_price = data.get("close") or data.get("price")
            if current_price is not None:
                # Convertimos a Decimal de forma segura antes de retornar
                price = Decimal(str(current_price))
                self._price_cache[cache_key] = price
                return price
            return None
        except Exception as e:
            print(f"Error al llamar a la API de Twelve Data para {ticker}: {e}")
            return None
        
    def get_monthly_series(self, ticker: str, start_date, end_date):
            """Devuelve la serie de precios mensuales para un rango de fechas."""
            start_str = start_date.strftime("%Y-%m-%d")
            end_str = end_date.strftime("%Y-%m-%d")
            cache_key = f"{ticker.upper()}:{start_str}:{end_str}"
            if cache_key in self._series_cache:
                return self._series_cache[cache_key]
            try:
                series = self.client.time_series(
                    symbol=ticker,
                    interval="1month",
                    start_date=start_str,
                    end_date=end_str,
                )
                raw = series.as_json()
                values = raw.get("values") if isinstance(raw, dict) else list(raw)
                values = values or []
                self._series_cache[cache_key] = values
                return values
            except Exception as e:
                print(f"Error al obtener datos mensuales de {ticker}: {e}")
                print(f"Error al obtener la serie mensual de {ticker}: {e}")
                return []

    def get_closing_price_for_date(self, ticker: str, target_date):
        """Obtiene el precio de cierre aproximado de un ticker para una fecha."""
        month_start = target_date.replace(day=1)
        series = self.get_monthly_series(ticker, month_start, target_date)
        if series:
            return float(series[0]["close"])
        return None

class InvestmentService:
    """Servicio para manejar la creación de inversiones."""

    @staticmethod
    def create_investment(user: User, data: dict):
        if "error" in data:
            print(f"No se creará inversión debido a un error previo: {data['error']}")
            return None

        ticker = (data.get("emisora_ticker") or data.get("ticker") or "").upper()
        nombre = data.get("nombre_activo") or ticker
        tipo_inversion = data.get("tipo_inversion", "ACCION")
        cantidad = Decimal(str(data.get("cantidad_titulos") or data.get("cantidad") or 0))
        precio_compra = Decimal(str(data.get("precio_por_titulo") or data.get("precio") or 0))
        fecha = parse_date_safely(data.get("fecha_compra") or data.get("fecha"))
        tipo_cambio = data.get("tipo_cambio_usd")
        tipo_cambio = Decimal(str(tipo_cambio)) if tipo_cambio is not None else None

        price_service = StockPriceService()
        try:
            precio_actual_float = price_service.get_current_price(ticker) if ticker else None
        except Exception:
            precio_actual_float = None
        precio_actual = Decimal(str(precio_actual_float)) if precio_actual_float is not None else precio_compra

        return inversiones.objects.create(
            propietario=user,
            tipo_inversion=tipo_inversion,
            emisora_ticker=ticker or None,
            nombre_activo=nombre,
            cantidad_titulos=cantidad,
            fecha_compra=fecha,
            precio_compra_titulo=precio_compra,
            precio_actual_titulo=precio_actual,
            tipo_cambio_compra=tipo_cambio,
        )
    
    @staticmethod
    def create_pending_investment(user: User, data: dict):
        """
        Crea un registro de inversión pendiente a partir de los datos extraídos por la IA.
        """
        if "error" in data:
            print(f"No se creará inversión pendiente debido a un error previo: {data['error']}")
            return None
        
        # Simplemente guardamos los datos crudos para revisarlos después.
        return PendingInvestment.objects.create(
            propietario=user,
            datos_json=data,
            estado='pendiente'
        )
    
class ExchangeRateService:
    """Servicio para obtener el tipo de cambio histórico USD/MXN."""

    def get_usd_mxn_rate(self, date_obj):
        """Obtiene el tipo de cambio USD->MXN para una fecha dada."""
        try:
            token = os.getenv("CURRENCYAPI_API_KEY")
            BASE_URL = f"https://api.currencyapi.com/v3/historical?apikey={token}&currencies=MXN&base_currency=USD&date={date_obj}"
            response = requests.get(BASE_URL)
            response.raise_for_status()
            data = response.json()
            fecha = data['meta']['last_updated_at']
            rate = data['data']['MXN']['value']
            return Decimal(str(rate)) if rate is not None else None
        except Exception as e:
            print(f"Error al obtener el tipo de cambio USD/MXN: {e}")
            return None
        
class RISCService:
    """
    Servicio para manejar y validar eventos de seguridad de Google RISC.
    """
    # URL del endpoint de configuración de RISC de Google
    GOOGLE_RISC_CONFIG_URL = "https://accounts.google.com/.well-known/risc-configuration"
    
    # Caché para las claves públicas de Google para no tener que pedirlas en cada request
    _jwk_client = None

    def __init__(self):
        # Obtenemos el "audience", que es tu Client ID de Google.
        # ¡Asegúrate de añadir GOOGLE_CLIENT_ID a tu archivo .env!
        self.audience = os.getenv("GOOGLE_CLIENT_ID")
        if not self.audience:
            raise ValueError("El GOOGLE_CLIENT_ID no está configurado en el archivo .env")

    def _get_jwk_client(self):
        """
        Obtiene y cachea el cliente JWK para verificar la firma de los tokens.
        """
        if self._jwk_client is None:
            config = requests.get(self.GOOGLE_RISC_CONFIG_URL).json()
            jwks_uri = config.get("jwks_uri")
            self._jwk_client = PyJWKClient(jwks_uri)
        return self._jwk_client

    def validate_token(self, token: str) -> dict:
        """
        Valida un token de seguridad (SET) de Google y procesa los eventos.
        Devuelve el payload decodificado si es válido, de lo contrario lanza una excepción.
        """
        jwk_client = self._get_jwk_client()

        try:
            signing_key = jwk_client.get_signing_key_from_jwt(token)
        except jwt.exceptions.PyJWKClientError as e:
            raise ValueError(f"No se pudo encontrar la clave de firma: {e}")

        try:
            payload = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                audience=self.audience,
                issuer="https://accounts.google.com",
            )

            # --- LÓGICA DE PROCESAMIENTO QUE YA TENÍAS ---
            events = payload.get('events', {})
            for event_type, event_data in events.items():
                if event_type == "https://schemas.openid.net/secevent/risc/event-type/verification":
                    state = event_data.get('state')
                    # ¡CAMBIO CLAVE! Usamos el logger para un registro robusto.
                    logger.info(f"✅ Evento de verificación RISC recibido. Estado: {state}")

            return payload
        except jwt.PyJWTError as e:
            raise ValueError(f"Token inválido: {e}")
    
    def process_security_event(self, payload: dict):
        """
        Procesa los eventos de seguridad dentro de un token validado.
        """
        events = payload.get("events", {})
        for event_type, event_details in events.items():
            subject = event_details.get("subject", {})
            user_google_id = subject.get("sub")

            if not user_google_id:
                continue

            # Busca al usuario en tu base de datos a través de su ID de Google
            try:
                social_account = SocialAccount.objects.get(provider='google', uid=user_google_id)
                user = social_account.user
                
                # --- ¡AQUÍ TOMAS ACCIÓN! ---
                # Dependiendo del tipo de evento, decides qué hacer.
                
                if event_type == "https://schemas.openid.net/secevent/risc/event-type/account-disabled":
                    # Si la cuenta de Google fue deshabilitada, desactivamos al usuario localmente.
                    user.is_active = False
                    user.save()
                    # Borramos todas sus sesiones para forzar un logout.
                    Session.objects.filter(session_key__in=user.session_set.values_list('session_key', flat=True)).delete()
                    logger.warning(f"Usuario {user.username} desactivado debido a evento RISC: Cuenta de Google deshabilitada.")

                elif event_type == "https://schemas.openid.net/secevent/risc/event-type/sessions-revoked":
                    # Si Google revocó las sesiones, hacemos lo mismo.
                    Session.objects.filter(session_key__in=user.session_set.values_list('session_key', flat=True)).delete()
                    logger.warning(f"Sesiones del usuario {user.username} revocadas debido a evento RISC.")
                
                # Puedes añadir más `elif` para otros tipos de eventos que quieras manejar.

            except SocialAccount.DoesNotExist:
                logger.warning(f"Se recibió un evento RISC para un usuario de Google con ID {user_google_id} que no existe en el sistema.")

class MistralOCRService:
    def __init__(self):
        self.api_key = os.getenv("MISTRAL_API_KEY") 
        self.client = Mistral(api_key=self.api_key) if self.api_key else None

    def optimize_image(self, image_bytes, max_size=1024):
        """
        Redimensiona y comprime la imagen en memoria usando PIL.
        Pasa de 5MB -> 150KB en milisegundos.
        """
        try:
            img = Image.open(BytesIO(image_bytes))
            
            # Convertir a RGB si es PNG/RGBA
            if img.mode in ('RGBA', 'P'):
                img = img.convert('RGB')

            # Redimensionar si es muy grande (Cuello de botella de red)
            if max(img.size) > max_size:
                img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)

            # Guardar en buffer optimizado
            buffer = BytesIO()
            img.save(buffer, format="JPEG", quality=85, optimize=True)
            return base64.b64encode(buffer.getvalue()).decode('utf-8')
        except Exception as e:
            logger.error(f"Error optimizando imagen: {e}")
            # Fallback: devolver original si falla PIL
            return base64.b64encode(image_bytes).decode('utf-8')

    def get_text_from_image(self, file_content_bytes, mime_type="image/jpeg"):
        if not self.client:
            return {"error": "Mistral API Key missing"}

        # 1. Optimización (Clave para velocidad)
        if 'pdf' in mime_type:
             # Los PDFs no se redimensionan igual, se mandan directo
             base64_image = base64.b64encode(file_content_bytes).decode('utf-8')
        else:
             base64_image = self.optimize_image(file_content_bytes)

        try:
            # 2. Llamada a Mistral
            # Mistral OCR es rápido, el cuello de botella suele ser la subida de la imagen
            ocr_response = self.client.ocr.process(
                model="mistral-ocr-latest",
                document={
                    "type": "image_url",
                    "image_url": f"data:image/jpeg;base64,{base64_image}" 
                },
                include_image_base64=False
            )
            
            json_data = json.loads(ocr_response.model_dump_json())
            
            full_markdown = ""
            if "pages" in json_data:
                for page in json_data["pages"]:
                    if "markdown" in page:
                        # Limpieza ultra-rápida
                        text = page["markdown"]
                        # Solo correcciones críticas
                        if "0XX0" in text or "0xx0" in text:
                            text = text.replace("0XX0", "OXXO").replace("0xx0", "OXXO")
                        full_markdown += text + "\n"

            return {"text_content": full_markdown, "raw_json": json_data}

        except Exception as e:
            logger.error(f"Error Mistral API: {e}")
            return {"error": str(e)}

class BillingService:
    @staticmethod
    def guardar_configuracion_tienda(nombre_tienda, campos_seleccionados):
        """
        Guarda o actualiza la configuración de campos requeridos para una tienda.
        """
        if not nombre_tienda:
            return

        nombre_tienda = nombre_tienda.upper().strip()
        
        obj, created = TiendaFacturacion.objects.update_or_create(
            tienda=nombre_tienda,
            defaults={'campos_requeridos': campos_seleccionados}
        )
        return obj

    @staticmethod
    def buscar_tienda_fuzzy(nombre_detectado):
        """
        Busca una tienda en la base de datos que coincida similitud con el nombre detectado.
        Retorna el objeto TiendaFacturacion o None.
        """
        if not nombre_detectado:
            return None
            
        nombre_detectado = nombre_detectado.strip().upper()
        
        # 1. Intento exacto rápido
        try:
            return TiendaFacturacion.objects.get(tienda=nombre_detectado)
        except TiendaFacturacion.DoesNotExist:
            pass
            
        # 2. Diccionario de correcciones manuales conocidas (Hardcoded fixes)
        # Esto soluciona errores OCR comunes y recurrentes que el fuzzy no capta o confunde
        correcciones = {
            "SIMITLA": "FARMACIAS SIMILARES",
            "SIMILARES": "FARMACIAS SIMILARES",
            "FARMACIAS SIMITLA": "FARMACIAS SIMILARES",
            "MCDONALDS": "MCDONALD'S",
            "MCDONALD´S": "MCDONALD'S",
            "0XX0": "OXXO",
            "WAL MART": "WALMART",
            "WAL-MART": "WALMART",
            "STARBUCKS COFFEE": "STARBUCKS",
        }
        
        if nombre_detectado in correcciones:
            nombre_corregido = correcciones[nombre_detectado]
            try:
                # Intentamos buscar el nombre corregido
                return TiendaFacturacion.objects.get(tienda=nombre_corregido)
            except TiendaFacturacion.DoesNotExist:
                # Si no existe la tienda "oficial" corregida, intentamos buscarla fuzzy con el nombre corregido
                nombre_detectado = nombre_corregido
                
        # 3. Limpieza de ruido para mejorar el Match
        # Quitamos palabras genéricas que ensucian la comparación
        palabras_ruido = ["FARMACIAS", "TIENDA", "SUPERMERCADO", "RESTAURANTE", "S.A. DE C.V.", "SA DE CV", "SUCURSAL"]
        nombre_limpio = nombre_detectado
        for p in palabras_ruido:
            nombre_limpio = nombre_limpio.replace(p, "").strip()
            
        todas_las_tiendas_objs = list(TiendaFacturacion.objects.all())
        nombres_tiendas = [t.tienda for t in todas_las_tiendas_objs]
        
        # 4. Intento difuso con umbral más permisivo (0.6)
        coincidencias = get_close_matches(nombre_detectado, nombres_tiendas, n=1, cutoff=0.6)
        
        if coincidencias:
            return TiendaFacturacion.objects.get(tienda=coincidencias[0])
            
        # 5. Intento difuso con nombre LIMPIO (si falló el completo)
        if nombre_limpio and nombre_limpio != nombre_detectado:
            coincidencias_limpias = get_close_matches(nombre_limpio, nombres_tiendas, n=1, cutoff=0.6)
            if coincidencias_limpias:
                 return TiendaFacturacion.objects.get(tienda=coincidencias_limpias[0])
            
        return None

    @staticmethod
    def procesar_datos_facturacion(datos_json: dict) -> dict:
        """
        Analiza los datos extraídos por la IA y los cruza con la configuración de la tienda.
        Devuelve un contexto listo para el template.
        """
        tienda_detectada = datos_json.get('tienda') or datos_json.get('establecimiento') or 'DESCONOCIDO'
        tienda_detectada = tienda_detectada.upper()
        
        # Usamos la búsqueda inteligente
        config_tienda = BillingService.buscar_tienda_fuzzy(tienda_detectada)
        
        if config_tienda:
            es_conocida = True
            tienda_nombre = config_tienda.tienda # Usamos el nombre OFICIAL de la DB
            campos_requeridos = config_tienda.campos_requeridos
            url_portal = config_tienda.url_portal
        else:
            es_conocida = False
            tienda_nombre = tienda_detectada # Usamos lo que encontró la IA
            campos_requeridos = []
            url_portal = None

        # 2. Preparamos los datos base
        # El modelo Factura guarda los datos específicos en 'datos_facturacion'
        # Pero a veces vienen mezclados en el root del JSON si es un objeto antiguo.
        # Asumimos que datos_json ES el 'datos_facturacion' completo.
        
        # Extraemos campos comunes
        campos_encontrados = datos_json.get('campos_adicionales') or datos_json 
        # (Si campos_adicionales no existe, usamos el propio dict, asumiendo estructura plana)
        
        # Datos para mostrar al usuario final (limpios)
        datos_para_cliente = {}
        
        # 3. Lógica de coincidencias
        campos_faltantes = []
        
        if es_conocida and campos_requeridos:
            # Si sabemos qué buscar, filtramos y validamos
            for campo in campos_requeridos:
                # Buscamos el campo con varias estrategias (exacto, lowercase, espacios->guiones)
                valor = (campos_encontrados.get(campo) or 
                         campos_encontrados.get(campo.lower()) or 
                         campos_encontrados.get(campo.replace(' ', '_').lower()) or
                         campos_encontrados.get(campo.upper()))
                
                if valor:
                    datos_para_cliente[campo] = valor
                else:
                    campos_faltantes.append(campo)
        else:
            # Si NO es conocida, mostramos TODO lo que parezca útil (excluyendo basura)
            claves_ignorar = ['tienda', 'fecha', 'total', 'tipo_documento', 'confianza_extraccion', 'fecha_emision', 'total_pagado', 'establecimiento', 'texto_ocr_preview', 'archivo_drive_id', 'nombre_archivo', 'campos_adicionales']
            
            for k, v in campos_encontrados.items():
                if k not in claves_ignorar and isinstance(v, (str, int, float)) and v:
                     datos_para_cliente[k] = v

        # 4. Sugerencia de campos (para el modo aprendizaje)
        # Si no es conocida, enviamos todas las llaves encontradas como sugerencia
        claves_sugeridas = [k for k in campos_encontrados.keys() if k not in ['tienda', 'fecha', 'total', 'tipo_documento', 'confianza_extraccion', 'fecha_emision', 'total_pagado', 'establecimiento', 'campos_adicionales']]

        return {
            'tienda': tienda_nombre, # Nombre normalizado si se encontró, o el original
            'tienda_original': tienda_detectada if tienda_detectada != tienda_nombre else None, # Para avisar al usuario si hubo corrección
            'es_conocida': es_conocida,
            'url_portal': url_portal,
            'datos_para_cliente': datos_para_cliente, # Lo que se guardará en la Factura final
            'campos_faltantes': campos_faltantes,
            'claves_sugeridas': claves_sugeridas,
            'raw_json': datos_json # Para debug o fallback
        }

    @staticmethod
    def preparar_contexto_para_gemini(texto_ticket: str) -> str:
        """
        Genera el string {context_str} que necesita tu prompt 'facturacion_from_text_with_context'.
        Filtra solo las tiendas relevantes o devuelve todas si no está seguro.
        """
        # 1. Intentamos identificar la tienda primero para no enviar TODA la base de datos
        #    (Esto ahorra tokens y confusión a Gemini)
        texto_upper = texto_ticket.upper()
        tiendas = TiendaFacturacion.objects.all()
        
        tiendas_relevantes = []
        for t in tiendas:
            # Si el nombre de la tienda aparece en el ticket, es relevante
            if t.tienda in texto_upper:
                tiendas_relevantes.append(t)
        
        # Si no encontramos ninguna exacta, mandamos todas por si acaso (o las más comunes)
        lista_final = tiendas_relevantes if tiendas_relevantes else tiendas

        contexto_str = "LISTA DE TIENDAS Y CAMPOS REQUERIDOS:\n"
        if not lista_final:
            return "No hay tiendas conocidas configuradas."

        for t in lista_final:
            lista_campos = ", ".join(t.campos_requeridos) if t.campos_requeridos else "Estándar"
            # Formato que tu prompt ya entiende:
            contexto_str += f"- {t.tienda}: [{lista_campos}]\n"
            
        return contexto_str