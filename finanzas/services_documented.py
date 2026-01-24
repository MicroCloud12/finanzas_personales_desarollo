# finanzas/services_documented.py
# Este archivo es una copia de services.py con comentarios detallados línea por línea
# para que aprendas cómo funciona cada parte sin depender de una IA.

# --- IMPORTACIONES ---
# Librerías estándar de Python
import os  # Permite interactuar con el sistema operativo (ej. leer variables de entorno como contraseñas en .env).
import re  # 'Regular Expressions'. Herramienta muy potente para buscar patrones de texto (ej. encontrar un RFC en un texto largo).
import json  # Permite trabajar con datos en formato JSON (el formato estándar para enviar/recibir datos en la web).
import base64  # Permite convertir archivos binarios (como imágenes) en texto para poder enviarlos a través de internet.
from io import BytesIO  # Permite tratar datos en la memoria RAM como si fueran un archivo físico en el disco duro.
from decimal import Decimal  # Tipo de dato para números financieros exactos. 'float' tiene errores de redondeo, 'Decimal' no.
import logging  # Herramienta para escribir registros ("logs") de lo que pasa en el sistema (útil para encontrar errores).
from difflib import get_close_matches  # Función de Python para encontrar palabras que se escriben parecido (Búsqueda difusa).

# Librerías de terceros (tienes que instalarlas con pip)
import requests  # La librería más famosa para hacer peticiones HTTP (visitar páginas web o consultar APIs desde código).
import jwt  # JSON Web Tokens. Se usa para firmar y verificar tokens de seguridad.
import mercadopago  # SDK oficial de Mercado Pago para procesar pagos y suscripciones.
from PIL import Image  # 'Pillow'. Librería estándar para abrir, manipular y guardar imágenes.
from twelvedata import TDClient  # Cliente para conectar con la API de Twelve Data (precios de acciones).
from jwt import PyJWKClient  # Ayuda a descargar las claves públicas para verificar tokens JWT (usado en Login con Google).
from cachetools import TTLCache  # Permite guardar resultados en memoria RAM por un tiempo limitado para no repetir cálculos lentos.
import google.generativeai as genai  # Librería oficial de Google para usar Gemini (inteligencia artificial).
from mistralai import Mistral  # Cliente para la IA de Mistral.
import numpy as np  # Librería fundamental para matemáticas avanzadas y manejo de matrices (usada por OpenCV).
import cv2  # 'OpenCV'. La librería más potente del mundo para visión artificial.
from googleapiclient.discovery import build  # Función mágica de Google para crear clientes de sus servicios (Drive, Gmail, etc).
from googleapiclient.errors import HttpError  # Maneja los errores cuando Google falla (ej. archivo no encontrado).
from google.oauth2.credentials import Credentials  # Objeto que guarda tus "llaves" de acceso a Google.

# Librerías de Django (Framework Web)
from django.conf import settings  # Acceso a la configuración global de tu proyecto (settings.py).
from django.http import JsonResponse  # Respuesta especial que devuelve JSON en lugar de HTML.
from django.contrib.sessions.models import Session  # Modelo para controlar quién ha iniciado sesión en tu sitio.

# Librerías de tu propio Proyecto (Importaciones relativas)
from .utils import parse_date_safely  # Función auxiliar que creaste para convertir strings en fechas sin que explote el programa.
from allauth.socialaccount.models import SocialAccount, SocialApp, SocialToken  # Modelos de la librería que maneja el Social Login.
from .models import (  # Importamos tus modelos de base de datos.
    TiendaFacturacion, registro_transacciones, TransaccionPendiente, 
    User, inversiones, PendingInvestment
)

# Configuramos el 'logger' con el nombre de este archivo.
logger = logging.getLogger(__name__)

# --- SERVICIO DE GOOGLE DRIVE ---
class GoogleDriveService:
    """
    Esta clase agrupa todas las funciones necesarias para hablar con Google Drive.
    En lugar de repetir el código de conexión en todas partes, lo hacemos aquí una vez.
    """
    
    # __init__ es el CONSTRUCTOR. Se ejecuta automáticamente cada vez que creas una nueva instancia de la clase.
    # Recibe el 'user' (usuario) porque cada usuario tiene su propia cuenta de Google Drive.
    def __init__(self, user: User):
        try:
            # 1. Buscamos la configuración de la App 'google' en tu base de datos (Client ID y Secret).
            app = SocialApp.objects.get(provider='google')
            
            # 2. Buscamos el token de acceso específico de ESTE usuario.
            # Este token se guardó cuando el usuario hizo "Login con Google".
            google_token = SocialToken.objects.get(account__user=user, account__provider='google')
            
            # 3. Creamos el objeto 'Credentials' con toda la información necesaria.
            creds = Credentials(
                token=google_token.token,  # El pase VIP actual.
                refresh_token=google_token.token_secret,  # El pase para renovar el VIP cuando caduque.
                token_uri='https://oauth2.googleapis.com/token',  # URL de Google para renovar.
                client_id=app.client_id,
                client_secret=app.secret
            )
            
            # 4. Construimos el cliente final. 'drive' es el servicio, 'v3' es la versión.
            self.service = build('drive', 'v3', credentials=creds)
            
        except (SocialToken.DoesNotExist, SocialApp.DoesNotExist) as e:
            # Si algo falta, lanzamos un error claro.
            raise ConnectionError("No se encontró una cuenta de Google vinculada o la configuración de la App Social.") from e

    # Método privado (empieza con _) para buscar el ID de una carpeta dado su nombre.
    def _get_folder_id(self, folder_name: str) -> str | None:
        try:
            # Preparamos una consulta "estilo SQL" pero para Google Drive.
            # "name='X' AND mimeType='folder' AND trashed=false (no está en papelera)"
            query = f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
            
            # Ejecutamos la búsqueda pidiendo solo el ID de los archivos encontrados.
            response = self.service.files().list(q=query, spaces='drive', fields='files(id)').execute()
            
            # Si hay resultados, devolvemos el ID del primero. Si no, None.
            return response.get('files', [])[0]['id'] if response.get('files') else None
            
        except HttpError as error:
            print(f"Ocurrió un error al buscar la carpeta '{folder_name}': {error}")
            return None

    # Método para listar archivos dentro de una carpeta específica.
    def list_files_in_folder(self, folder_name: str, mimetypes: list[str]) -> list[dict]:
        # 1. Averiguamos el ID de la carpeta contenedora.
        folder_id = self._get_folder_id(folder_name)
        
        if not folder_id:
            return [] # Si no existe la carpeta, devolvemos lista vacía.
        
        # 2. Construimos el filtro de tipos de archivo (MIME types).
        # Ej: "mimeType='image/jpeg' or mimeType='application/pdf'"
        mime_query = " or ".join([f"mimeType='{m}'" for m in mimetypes])
        
        # Consulta completa: "padre es 'folder_id' Y (es imagen O pdf) Y no está borrado"
        query = f"'{folder_id}' in parents and ({mime_query}) and trashed=false"
        
        try:
            # Ejecutamos búsqueda pidiendo ID, nombre y tipo.
            results = self.service.files().list(q=query, fields="files(id, name, mimeType)").execute()
            return results.get('files', [])
        except HttpError as error:
            print(f"Ocurrió un error al listar archivos: {error}")
            return []

    # Método para descargar el contenido de un archivo.
    def get_file_content(self, file_id: str) -> BytesIO:
        # Pide a Google que descargue (get_media) el archivo.
        request = self.service.files().get_media(fileId=file_id)
        # request.execute() descarga los bytes crudos.
        # BytesIO los envuelve para que Python los pueda leer como si fueran un archivo abierto.
        return BytesIO(request.execute())


# --- SERVICIO DE INTELIGENCIA ARTIFICIAL (GEMINI) ---
class GeminiService:
    """
    Este servicio es el puente entre nuestra base de datos y la IA de Google (Gemini).
    Se encarga de enviar preguntas (prompts) e imágenes, y recibir respuestas estructuradas.
    """
    def __init__(self):
        # Configuramos la librería con tu API KEY secreta.
        genai.configure(api_key=settings.GEMINI_API_KEY)
        
        # Inicializamos el modelo. 'gemini-2.0-flash' es la versión más rápida y barata optimizada para tareas simples.
        self.model = genai.GenerativeModel("gemini-2.0-flash")
        
        # --- PROMPTS (LAS INSTRUCCIONES) ---
        # Aquí definimos las "personalidades" de la IA.
        # Son textos largos que le dicen EXACTAMENTE qué hacer.
        self.prompts = { 
            "tickets": """
            Eres un asistente experto en contabilidad.
            Tu misión es leer el texto de un ticket de compra o transferencia y extraer datos.
            IMPORTANTE: Devuelve SOLO JSON válido. Nada de texto extra.

            FORMATO REQUERIDO:
            {
              "tipo_documento": "(TICKET_COMPRA|TRANSFERENCIA|OTRO)",
              "fecha": "YYYY-MM-DD",  <-- Formato ISO estándar
              "establecimiento": "Nombre de la tienda",
              "descripcion_corta": "Resumen breve (ej. Supermercado)",
              "total": 0.00, <-- Número decimal simple
              "confianza_extraccion": "(ALTA|MEDIA|BAJA)"
            }
            ... (Instrucciones detalladas omitidas para brevedad, ver archivo original) ...
            """,
            # El prompt para inversiones es similar, pero pide Ticker, Cantidad, Precio, etc.
            "inversion": """... (Instrucciones para inversiones) ...""",
            "deudas": """... (Instrucciones para tablas de amortización) ...""",
            # Facturación: Aquí usamos 'contexto dinámico' ({context_str}).
            # Significa que le inyectamos la lista de tiendas conocidas antes de enviar el prompt.
            "facturacion_from_text_with_context": """
            Eres un auditor fiscal.
            CONTEXTO CONOCIDO:
            {context_str}  <-- Aquí pegaremos la lista de tiendas que tu sistema ya conoce.

            Analiza el siguiente ticket:
            {text_content} <-- Aquí pegaremos el texto del OCR.
            
            Objetivo: Identificar si la tienda del ticket está en nuestra lista conocida.
            """
        }
        
        # Configuración técnica de la IA.
        self.generation_config = genai.types.GenerationConfig(
            temperature=0.1, # Temperatura baja = La IA es muy literal y poco creativa (bueno para datos).
            max_output_tokens=1024, # Límite de longitud de la respuesta.
        )

    def _prepare_content(self, file_data, mime_type: str):
        """
        Prepara el archivo para que la librería de Google lo entienda.
        Diferencia entre PDF e imágenes porque se envían distinto.
        """
        if mime_type == 'application/pdf':
            return {
                "mime_type": "application/pdf",
                "data": file_data 
            }
        else:
            return {
                "mime_type": mime_type, # ej. "image/jpeg"
                "data": file_data
            }

    def extract_data(self, prompt_name: str, file_data, mime_type: str, context: str = "") -> dict:
        """
        Función principal para extraer datos de un ARCHIVO (Imagen/PDF).
        """
        # 1. Verificamos que el prompt exista.
        if prompt_name not in self.prompts:
            raise ValueError(f"El prompt '{prompt_name}' no existe.")

        raw_prompt = self.prompts[prompt_name]
        
        # 2. Inyectamos el contexto (si el prompt lo usa).
        # .format() reemplaza {context_str} por el valor real.
        try:
            prompt = raw_prompt.format(context_str=context)
        except KeyError:
            prompt = raw_prompt

        # 3. Preparamos el archivo y llamamos a la función interna.
        prepared_content = self._prepare_content(file_data, mime_type)
        return self._generate_and_parse(prompt, prepared_content)

    def extract_from_text(self, prompt_name: str, text: str, context: str = "") -> dict:
        """
        Similar a la anterior, pero para extraer datos de TEXTO PURO (ya procesado por OCR Mistral).
        """
        if prompt_name not in self.prompts:
            raise ValueError(f"El prompt '{prompt_name}' no existe.")
            
        raw_prompt = self.prompts[prompt_name]
        
        # Inyectamos el texto y el contexto en el prompt.
        try:
            prompt = raw_prompt.format(text_content=text, context_str=context)
        except KeyError:
             # Fallback si el prompt no espera esos campos específicos
            prompt = raw_prompt + "\n\n" + text

        # Llamamos a generación solo con texto (sin imagen).
        response = self.model.generate_content(prompt)
        
        return self._clean_and_parse_json(response.text)

    def _generate_and_parse(self, prompt: str, content) -> dict:
        """Envía prompt + contenido a Gemini y parsea la respuesta."""
        response = self.model.generate_content([prompt, content])
        return self._clean_and_parse_json(response.text)

    def _clean_and_parse_json(self, raw_text: str) -> dict:
        """
        Método auxiliar para limpiar la respuesta de la IA.
        A veces la IA responde con ```json { ... } ``` y eso rompe el parser.
        Aquí quitamos esos bloques de código Markdown.
        """
        cleaned_response = raw_text.strip()
        if cleaned_response.startswith("```json"):
            cleaned_response = cleaned_response[7:] # Quitamos los primeros 7 caracteres
        if cleaned_response.startswith("```"):
            cleaned_response = cleaned_response[3:]
        if cleaned_response.endswith("```"):
            cleaned_response = cleaned_response[:-3] # Quitamos los últimos 3
        
        cleaned_response = cleaned_response.strip()
        
        try:
            # json.loads convierte el string limpio en un diccionario de Python.
            return json.loads(cleaned_response)
        except json.JSONDecodeError:
            logger.error(f"Error: La respuesta de Gemini no es un JSON válido: {cleaned_response}")
            return {"error": "Respuesta inválida de IA", "raw": cleaned_response}
    
# --- PATRÓN SINGLETON ---
# Esto asegura que solo exista UNA instancia de GeminiService en memoria.
# Ahorra recursos al no reconectar con la API cada vez.
_gemini_singleton = None
def get_gemini_service() -> GeminiService:
    global _gemini_singleton
    if _gemini_singleton is None:
        _gemini_singleton = GeminiService()
    return _gemini_singleton


# --- SERVICIO DE TRANSACCIONES (GASTOS/INGRESOS) ---
class TransactionService:
    """
    Maneja la lógica de validación y creación de transacciones.
    Separa la lógica "sucia" de la Base de Datos de las Vistas.
    """
    
    # @staticmethod: Método que no necesita acceso a 'self' (la instancia).
    # Es como una función normal pero agrupada dentro de la clase por orden.
    @staticmethod
    def create_pending_transaction(user: User, data: dict):
        # Si hubo error previo, abortamos.
        if "error" in data:
            print(f"Error previo, no se guarda transacción: {data['error']}")
            return None
        
        # Creamos el registro en estado 'pendiente' para que el usuario revise.
        return TransaccionPendiente.objects.create(
            propietario=user,
            datos_json=data,
            estado='pendiente'
        )

    @staticmethod
    def approve_pending_transaction(ticket_id: int, user: User, cuenta: str, categoria: str, tipo_transaccion: str, cuenta_destino: str):
        try:
            # 1. Buscamos el ticket y verificamos que sea del usuario (¡Seguridad!).
            ticket = TransaccionPendiente.objects.get(id=ticket_id, propietario=user)
            datos = ticket.datos_json
            
            tipo_documento = datos.get("tipo_documento")
            descripcion_final = datos.get("descripcion_corta", "Sin descripción")
            
            if tipo_documento == 'TICKET_COMPRA':
                descripcion_final = datos.get("establecimiento", "Compra")
            
            # 2. Limpieza de datos (Data Cleaning)
            # Usamos nuestra utilidad para fechas (evita errores si el formato es raro).
            fecha_segura = parse_date_safely(datos.get("fecha") or datos.get("fecha_emision"))

            # Convertimos el monto a string y luego a Decimal para máxima precisión financiera.
            monto_str = str(datos.get("total") or datos.get("total_pagado") or 0.0)

            # 3. Guardado final en la base de datos real.
            registro_transacciones.objects.create(
                propietario=user,
                fecha=fecha_segura,
                descripcion=descripcion_final.upper(), # Guardamos en mayúsculas para consistencia visual.
                categoria=categoria,
                monto=Decimal(monto_str),
                tipo=tipo_transaccion, # E.g. 'GASTO', 'INGRESO'
                cuenta_origen=cuenta,
                cuenta_destino=cuenta_destino,
                datos_extra=datos  # Guardamos el JSON original porsiaca (Auditoría).
            )
            
            # 4. Marcamos el ticket como aprobado para que ya no salga en "Pendientes".
            ticket.estado = 'aprobada'
            ticket.save()
            return ticket
            
        except TransaccionPendiente.DoesNotExist:
            return None


# --- SERVICIO DE MERCADO PAGO ---
class MercadoPagoService:
    """
    Encapsula la lógica de cobros.
    """
    def __init__(self):
        # Iniciamos el SDK con el token secreto.
        self.sdk = mercadopago.SDK(os.getenv('MERCADOPAGO_ACCESS_TOKEN'))
        self.plan_id = os.getenv('MERCADOPAGO_PLAN_ID')
        
    def crear_link_suscripcion(self, user, back_url: str):
        """Genera la URL a la que redirigimos al usuario para pagar."""
        base_url = "https://www.mercadopago.com.mx/subscriptions/checkout"
        # Simplemente pegamos el ID del plan. Mercado Pago hace el resto.
        return f"{base_url}?preapproval_plan_id={self.plan_id}"


# --- SERVICIO DE PRECIOS DE ACCIONES (Twelve Data) ---
class StockPriceService:
    """
    Obtiene precios de acciones/criptos en tiempo real.
    """
    # CACHÉ EN MEMORIA RAM (Optimizaciones):
    # Guardamos los precios por 5 minutos (300s) para no saturar la API ni alentizar la app.
    _price_cache: TTLCache = TTLCache(maxsize=100, ttl=300)

    def __init__(self):
        self.api_key = os.getenv("TWELVEDATA_API_KEY")
        self.client = TDClient(apikey=self.api_key)

    def get_current_price(self, ticker: str):
        """
        Obtiene el precio actual. Primero mira en caché, si no está, llama a la API.
        """
        cache_key = ticker.upper()
        
        # 1. ¿Está en memoria? ¡Retorno inmediato!
        if cache_key in self._price_cache:
            return self._price_cache[cache_key]
        
        # 2. Si no, consultamos la API externa (Lento, ~1-2 segundos).
        try:
            quote = self.client.quote(symbol=ticker)
            data = quote.as_json()
            
            # A veces devuelve lista, a veces dict. Normalizamos.
            if isinstance(data, list):
                data = data[0] if data else {}
            
            val = data.get("close") or data.get("price")
            if val is not None:
                price = Decimal(str(val))
                # Guardamos en caché para la próxima vez.
                self._price_cache[cache_key] = price
                return price
            return None
        except Exception as e:
            print(f"Error API Stock: {e}")
            return None

    # (Métodos get_monthly_series, etc. omitidos por brevedad, lógica similar)


# --- SERVICIO DE INVERSIONES ---
class InvestmentService:
    """Gestiona la creación de registros de inversión."""

    @staticmethod
    def create_investment(user: User, data: dict):
        # Extraemos datos del JSON de la IA.
        ticker = (data.get("emisora_ticker") or "").upper()
        nombre = data.get("nombre_activo") or ticker
        
        # Conversiones seguras a Decimal (dinero/cantidad).
        cantidad = Decimal(str(data.get("cantidad_titulos") or 0))
        precio_compra = Decimal(str(data.get("precio_por_titulo") or 0))
        fecha = parse_date_safely(data.get("fecha_compra"))

        # Intentamos obtener precio actual para calcular ganancia/pérdida inicial.
        price_service = StockPriceService()
        try:
            precio_actual_float = price_service.get_current_price(ticker) if ticker else None
        except Exception:
            precio_actual_float = None
        
        precio_actual = Decimal(str(precio_actual_float)) if precio_actual_float is not None else precio_compra

        # Creamos el registro final.
        return inversiones.objects.create(
            propietario=user,
            tipo_inversion=data.get("tipo_inversion", "ACCION"),
            emisora_ticker=ticker,
            nombre_activo=nombre,
            cantidad_titulos=cantidad,
            fecha_compra=fecha,
            precio_compra_titulo=precio_compra,
            precio_actual_titulo=precio_actual,
            # ... otros campos
        )


# --- SERVICIO DE TIPO DE CAMBIO ---
class ExchangeRateService:
    """Consigue el valor histórico del dólar (USD -> MXN)."""
    def get_usd_mxn_rate(self, date_obj):
        try:
            token = os.getenv("CURRENCYAPI_API_KEY")
            # Consulta a API externa (currencyapi.com).
            BASE_URL = f"https://api.currencyapi.com/v3/historical?apikey={token}&currencies=MXN&base_currency=USD&date={date_obj}"
            
            response = requests.get(BASE_URL)
            response.raise_for_status()
            
            data = response.json()
            rate = data['data']['MXN']['value']
            
            return Decimal(str(rate)) if rate is not None else None
        except Exception as e:
            print(f"Error Exchange Rate: {e}")
            return None


# --- SERVICIO DE SEGURIDAD (RISC) ---
class RISCService:
    """
    Maneja alertas de seguridad de Google (Cross-Account Protection).
    Si le roban la cuenta de Google al usuario, Google nos avisa aquí.
    """
    GOOGLE_RISC_CONFIG_URL = "https://accounts.google.com/.well-known/risc-configuration"
    _jwk_client = None

    def __init__(self):
        self.audience = os.getenv("GOOGLE_CLIENT_ID") 

    def validate_token(self, token: str) -> dict:
        """Verifica que la alerta venga realmente de Google (Firma Digital)."""
        # (Lógica de verificación JWT omitida por brevedad, es técnica criptográfica estándar)
        return {} # Placeholder para este ejemplo educativo

    def process_security_event(self, payload: dict):
        """Toma medidas drásticas si el evento es crítico."""
        # ... lógica de bloqueo de cuenta ...
        pass


# --- SERVICIO DE OCR ALTERNATIVO (MISTRAL) ---
class MistralOCRService:
    """
    Usa la IA 'Mistral' específicamente para leer texto de imágenes (OCR).
    A veces es mejor/más barato que Gemini para puro texto.
    """
    def __init__(self):
        self.api_key = os.getenv("MISTRAL_API_KEY")
        self.client = Mistral(api_key=self.api_key) if self.api_key else None

    # (Métodos de preprocesamiento de imagen con OpenCV omitidos, son complejos matemáticamente)
    # Su objetivo es limpiar la imagen (quitar sombras, corregir perspectiva)
    # para que la IA lea mejor.


# --- SERVICIO DE FACTURACIÓN (OPTIMIZADO) ---
class BillingService:
    """
    Gestiona la configuración para saber qué datos pide cada tienda para facturar.
    """
    
    @staticmethod
    def buscar_tienda_fuzzy(nombre_detectado):
        """
        Busca una tienda en la BD aunque el nombre no sea exacto (ej. 'WAL-MART' vs 'WALMART').
        
        OPTIMIZACIÓN DE ESCALABILIDAD:
        Antes cargábamos TODAS las tiendas en memoria. Eso era lento si hay miles.
        Ahora filtramos primero por la base de datos.
        """
        if not nombre_detectado:
            return None
            
        nombre_detectado = nombre_detectado.strip().upper()
        
        # 1. Limpieza: Quitamos "S.A. DE C.V.", "TIENDA", etc.
        palabras_ruido = ["FARMACIAS", "TIENDA", "SUPERMERCADO", "RESTAURANTE", "S.A. DE C.V."]
        nombre_limpio = nombre_detectado
        for p in palabras_ruido:
            nombre_limpio = nombre_limpio.replace(p, "").strip()
            
        # 2. FILTRO INTELIGENTE (DB): 
        # Solo traemos de la base de datos las tiendas que empiezan igual.
        # Esto reduce la lista de 10,000 a 5 o 10. ¡Mucho más rápido!
        inicial = nombre_limpio[0] if nombre_limpio else ""
        if inicial:
            # SQL: SELECT * FROM tiendas WHERE tienda LIKE 'W%'
            candidatos_qs = TiendaFacturacion.objects.filter(tienda__istartswith=inicial)
            nombres_tiendas = list(candidatos_qs.values_list('tienda', flat=True))
        else:
            nombres_tiendas = []
        
        # 3. COMPARACIÓN DIFUSA (RAM):
        # Ahora que tenemos una lista pequeña, usamos 'difflib' para encontrar el más parecido matemáticamente.
        if nombres_tiendas:
            coincidencias = get_close_matches(nombre_detectado, nombres_tiendas, n=1, cutoff=0.8)
            if coincidencias:
                return TiendaFacturacion.objects.get(tienda=coincidencias[0])
            
        return None

    @staticmethod
    def procesar_datos_facturacion(datos_json: dict) -> dict:
        """
        Prepara los datos finales para mostrar en la web.
        Cruza lo que encontró la IA con lo que sabemos que pide la tienda.
        """
        # ... lógica de cruce de datos ...
        return {} # Placeholder



