# finanzas/tasks_documented.py
# Este archivo explica cómo funciona el procesamiento en segundo plano (Background Tasks) con Celery.

import time
import json
import logging
from PIL import Image  # Librería para manipulación de imágenes.
from io import BytesIO # Para manejar archivos en memoria RAM.
from decimal import Decimal, InvalidOperation # Tipos de datos precios.
from .utils import parse_date_safely

# --- IMPORTACIONES DE CELERY ---
from celery import shared_task, group
# 'shared_task': Decorador que convierte una función normal en una tarea asíncrona.
# 'group': Permite ejecutar muchas tareas en paralelo y monitorearlas como un conjunto.

from django.contrib.auth.models import User
from .services import (
    GoogleDriveService, StockPriceService, TransactionService, 
    InvestmentService, get_gemini_service, ExchangeRateService, 
    MistralOCRService, BillingService
)
from .models import (
    Deuda, AmortizacionPendiente, PagoAmortizacion, 
    TiendaFacturacion, Factura, TransaccionPendiente
)

logger = logging.getLogger(__name__)

# --- FUNCIÓN AUXILIAR DE IMAGEN ---
def load_and_optimize_image(file_content, max_width: int = 1024, quality: int = 80) -> bytes:
    """
    Toma una imagen gigante (ej. foto de 12MP del celular) y la reduce.
    
    ¿POR QUÉ?
    1. Las IAs (Gemini) cobran por tamaño o "tokens". Imagen más pequeña = más barato.
    2. Subir 5MB tarda mucho más que subir 200KB. Hacemos la app más rápida.
    """
    # Abrimos la imagen desde los bytes en memoria.
    image = Image.open(file_content).convert("RGB")
    
    # Si es muy ancha, la reducimos proporcionalmente.
    if image.width > max_width:
        ratio = max_width / float(image.width)
        new_height = int(image.height * ratio)
        image = image.resize((max_width, new_height))
    
    # Guardamos la imagen optimizada en un buffer de memoria (como un archivo virtual).
    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=quality) # Calidad 80% es suficiente para leer texto.
    
    # Devolvemos los bytes listos para enviar.
    return buffer.getvalue()


# --- TAREA 1: PROCESAR UN SOLO TICKET (El "Obrero") ---
# @shared_task: Indica que esta función puede ser enviada a la cola de trabajo (Redis/RabbitMQ).
# bind=True: Nos da acceso a 'self', permitiendo controlar el estado de la tarea (reintentar, fallar).
# max_retries=3: Si falla (ej. internet lento), Celery lo intentará 3 veces más.
@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def process_single_ticket(self, user_id: int, file_id: str, file_name: str, mime_type: str):
    """
    Esta tarea se ejecuta en segundo plano. Su único trabajo es procesar UN archivo.
    """
    try:
        # Recuperamos al usuario. No pasamos el objeto 'user' completo porque 
        # Celery tiene que "serializar" (convertir a texto) los argumentos. Pasar IDs es más seguro/rápido.
        user = User.objects.get(id=user_id)
        
        # Instanciamos los servicios necesarios.
        gdrive_service = GoogleDriveService(user)
        gemini_service = get_gemini_service()
        transaction_service = TransactionService()
        
        # 1. Descargamos el archivo de Drive.
        file_content = gdrive_service.get_file_content(file_id)

        # 2. Optimizamos la imagen (si es imagen).
        file_data = load_and_optimize_image(file_content) if 'image' in mime_type else file_content.getvalue()
        
        # 3. Enviamos a la IA psra extraer información.
        extracted_data = gemini_service.extract_data(
            prompt_name="tickets",
            file_data=file_data,
            mime_type=mime_type
        )
        
        # Si la IA devuelve error, terminamos reportando fallo.
        if extracted_data.get("error"):
             return {'status': 'FAILURE', 'file_name': file_name, 'error': extracted_data['raw_response']}

        # 4. Guardamos el resultado en la BD.
        transaction_service.create_pending_transaction(user, extracted_data)
        return {'status': 'SUCCESS', 'file_name': file_name}

    except Exception as e:
        # Si ocurre un error inesperado (ej. timeout), lo reintentamos automáticamente.
        # 'exc=e' guarda el error original para el log.
        self.retry(exc=e)
        return {'status': 'FAILURE', 'file_name': file_name, 'error': str(e)}


# --- TAREA 2: COORDINADOR DE TICKETS (El "Jefe") ---
@shared_task
def process_drive_tickets(user_id: int):
    """
    Esta tarea no procesa archivos. Su trabajo es BUSCAR archivos y asignar trabajo.
    Patrón: Fan-out (Uno a Muchos).
    """
    try:
        user = User.objects.get(id=user_id)
        gdrive_service = GoogleDriveService(user)
        
        # Busca todos los tickets en la carpeta.
        files_to_process = gdrive_service.list_files_in_folder(
            folder_name="Tickets de Compra", 
            mimetypes=['image/jpeg', 'image/png', 'application/pdf']
        )

        if not files_to_process:
            return {'status': 'NO_FILES', 'message': 'No se encontraron nuevos tickets.'}

        # --- PARALELISMO (La Magia) ---
        # Creamos un 'group' de tareas.
        # Esto le dice a Celery: "Lanza 50 workers, uno para cada archivo, al mismo tiempo".
        job = group(
            process_single_ticket.s(user.id, item['id'], item['name'], item['mimeType'])
            for item in files_to_process
        )
        
        # apply_async(): Envía el grupo a la cola de ejecución.
        result_group = job.apply_async()
        
        # save(): Importante para poder consultar el progreso (Barra de carga) después.
        result_group.save() 

        # Devolvemos el ID del grupo ("Task ID") al Frontend.
        # Con este ID, el Javascript preguntará cada 2 segundos: "¿Ya terminaron todas las tareas del grupo X?"
        return {'status': 'STARTED', 'task_group_id': result_group.id, 'total_tasks': len(files_to_process)}

    except Exception as e:
        return {'status': 'ERROR', 'message': str(e)}


# --- TAREAS DE INVERSIONES (Misma lógica Maestro-Esclavo) ---

@shared_task(bind=True, max_retries=3)
def process_single_inversion(self, user_id: int, file_id: str, file_name: str, mime_type: str):
    try:
        user = User.objects.get(id=user_id)
        # Servicios
        gdrive_service = GoogleDriveService(user)
        gemini_service = get_gemini_service()
        investment_service = InvestmentService()
        current_price = StockPriceService()
        
        # Descarga y optimiza
        file_content = gdrive_service.get_file_content(file_id)
        file_data = load_and_optimize_image(file_content) if 'image' in mime_type else file_content.getvalue()
        
        # Extrae datos
        extracted_data = gemini_service.extract_data(prompt_name="inversion", file_data=file_data, mime_type=mime_type)
        
        # --- LÓGICA FINANCIERA EN SEGUNDO PLANO ---
        # Aquí hacemos cálculos pesados para no bloquear al usuario.
        
        # 1. Obtenemos cantidades seguras.
        try:
            cantidad = Decimal(str(extracted_data.get("cantidad_titulos", 0)))
            precio_por_titulo_orig = Decimal(str(extracted_data.get("precio_por_titulo", 0)))
        except InvalidOperation:
            return {'status': 'FAILURE', 'file_name': file_name, 'error': 'Datos numéricos inválidos'}

        # 2. Obtenemos tipo de cambio histórico para la fecha de compra.
        fecha = parse_date_safely(extracted_data.get("fecha_compra") or extracted_data.get("fecha"))
        rate_service = ExchangeRateService()
        rate = rate_service.get_usd_mxn_rate(fecha) # Llamada a API externa 1
        
        # 3. Obtenemos precio actual de la acción (Tiempo real o delay de 15min)
        ticker = extracted_data.get('emisora_ticker')
        precio_actual_usd = current_price.get_current_price(ticker) # Llamada a API externa 2
        
        # Fallback complejo: Si no hay precio actual, intentamos calcularlo con lo que tenemos.
        if precio_actual_usd is None:
             if extracted_data.get("moneda") == "USD":
                 precio_actual_usd = precio_por_titulo_orig
             elif rate:
                 precio_actual_usd = precio_por_titulo_orig / rate
        
        # 4. Guardamos todo calculado.
        valores = {
            'fecha_compra': extracted_data.get('fecha_compra'),
            'emisora_ticker': ticker,
            'nombre_activo': extracted_data.get('nombre_activo'),
            'cantidad_titulos': str(cantidad),
            'precio_por_titulo': str(precio_por_titulo_orig),
             # Guardamos también el tipo de cambio usado para referencia futura
            'tipo_cambio': str(rate) if rate else None,
            # ... (más campos)
        }
        
        investment_service.create_pending_investment(user, valores)
        return {'status': 'SUCCESS', 'file_name': file_name}
        
    except Exception as e:
        self.retry(exc=e)
        return {'status': 'FAILURE', 'error': str(e)}

@shared_task
def process_drive_investments(user_id):
    # (Idéntico a process_drive_tickets pero busca en carpeta "Inversiones")
    # ... código omitido por repetitivo ...
    return {'status': 'STARTED'} 


# --- TAREAS DE AMORTIZACIÓN (Préstamos) ---
@shared_task(bind=True, max_retries=3)
def process_single_amortization(self, user_id, file_id, file_name, mime_type, deuda_id):
    # ... lógica similar para procesar tablas de pagos ...
    pass 

@shared_task
def process_drive_amortizations(user_id, deuda_id):
    # Este tiene una particularidad: FILTRA los archivos.
    # Solo procesa archivos cuyo nombre coincida con el nombre de la deuda.
    # Ej. Deuda "Coche" -> Busca archivo "Tabla Coche.pdf"
    pass


# --- TAREA DE FACTURACIÓN (La más compleja) ---
@shared_task(bind=True, max_retries=2)
def process_single_invoice(self, user_id, file_id, file_name, mime_type):
    """
    Procesa un ticket buscando datos FISCALES para facturar.
    Usa múltiples inteligencias: Mistral para OCR + Gemini para Entendimiento.
    """
    try:
        user = User.objects.get(id=user_id)
        gdrive = GoogleDriveService(user)
        
        # 1. Obtenemos el archivo
        file_bytes = gdrive.get_file_content(file_id).getvalue()

        # 2. Paso 1: OCR (Lectura de Texto) con Mistral
        # ¿Por qué Mistral? A veces es más barato/rápido para puro texto que Gemini multimodal.
        mistral_service = MistralOCRService()
        ocr_result = mistral_service.get_text_from_image(file_bytes, mime_type)
        texto_ticket = ocr_result.get('text_content', '')

        # 3. Paso 2: Análisis Semántico con Gemini
        # Le enviamos el texto a Gemini y le pedimos que extraiga la tienda, total, etc.
        # Además, le damos "Contexto": La lista de tiendas que ya conocemos para que normalice el nombre.
        contexto = BillingService.preparar_contexto_para_gemini(texto_ticket)
        gemini = get_gemini_service()
        
        try:
            datos = gemini.extract_from_text(
                prompt_name="facturacion_from_text_with_context", 
                text=texto_ticket, 
                context=contexto
            )
        except Exception as e:
            # MANEJO DE RATE LIMIT (Importante para escalar)
            # Si Gemini dice "ResourceExhausted" (Error 429), significa que nos pasamos de peticiones por minuto.
            # En ese caso, detenemos ESTA tarea específica pero no la marcamos como fallida definitiva,
            # devolvemos un estado 'THROTTLED' para intentar luego.
            if "429" in str(e) or "ResourceExhausted" in str(e):
                return {'status': 'THROTTLED', 'error': 'Cuota de IA excedida, reintentar más tarde'}
            raise e

        # 4. Lógica de Normalización de Tienda (Fuzzy Search)
        # Si la IA no está segura, el sistema busca en la BD el nombre más parecido.
        # (Ver services_documented.py -> BillingService para el detalle del algoritmo).
        nombre_ia = datos.get("tienda", "DESCONOCIDO")
        
        if datos.get("es_conocida"):
            tienda_final = nombre_ia
        else:
            obj = BillingService.buscar_tienda_fuzzy(nombre_ia)
            tienda_final = obj.tienda if obj else nombre_ia

        # 5. Guardamos la Factura
        Factura.objects.create(
            tienda=tienda_final,
            # ... resto de campos ...
        )
        
        return {'status': 'SUCCESS', 'tienda': tienda_final}

    except Exception as e:
        return {'status': 'FAILURE', 'error': str(e)}

@shared_task
def process_drive_for_invoices(user_id):
    # (Idéntico a los otros coordinadores)
    pass



