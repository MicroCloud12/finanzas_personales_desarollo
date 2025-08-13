import logging
import time
from io import BytesIO
from PIL import Image
from celery import shared_task, group
from django.contrib.auth.models import User
from .services import GoogleDriveService, GeminiService, TransactionService, InvestmentService, get_gemini_service


logger = logging.getLogger(__name__)

def load_and_optimize_image(file_content, max_width: int = 1024, quality: int = 80) -> Image.Image:
    """Reduce el tamaño y comprime la imagen para agilizar la llamada a la IA."""
    image = Image.open(file_content).convert("RGB")
    if image.width > max_width:
        ratio = max_width / float(image.width)
        new_height = int(image.height * ratio)
        image = image.resize((max_width, new_height))
    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=quality)
    buffer.seek(0)
    return Image.open(buffer)

@shared_task(bind=True, max_retries=3, default_retry_delay=60)
#def process_single_ticket(self, user_id: int, file_id: str, file_name: str):
def process_single_ticket(self, user_id: int, file_id: str, file_name: str, mime_type: str):
    """
    Procesa un único ticket: lo descarga, lo analiza con Gemini y lo guarda como pendiente.
    Utiliza los servicios para abstraer la lógica.
    """
    try:
        user = User.objects.get(id=user_id)
        
        # 1. Usar servicios
        gdrive_service = GoogleDriveService(user)
        #gemini_service = GeminiService()
        gemini_service = get_gemini_service()
        transaction_service = TransactionService()

        # 2. Obtener contenido del archivo
        start_download = time.perf_counter()
        file_content = gdrive_service.get_file_content(file_id)
        #image = Image.open(file_content)
        download_time = time.perf_counter() - start_download
        logger.info("Download time for %s: %.2fs", file_name, download_time)
        #image = load_and_optimize_image(file_content)

        # 3. Extraer datos con Gemini
        #start_gemini = time.perf_counter()
        #extracted_data = gemini_service.extract_data_from_image(image)
        if mime_type in ('image/jpeg', 'image/png'):
            image = load_and_optimize_image(file_content)
            start_gemini = time.perf_counter()
            extracted_data = gemini_service.extract_data_from_image(image)
        elif mime_type == 'application/pdf':
            start_gemini = time.perf_counter()
            extracted_data = gemini_service.extract_data_from_pdf(file_content.getvalue())
        else:
            return {'status': 'UNSUPPORTED', 'file_name': file_name, 'error': 'Unsupported file type'}
        
        gemini_time = time.perf_counter() - start_gemini
        logger.info("Gemini processing time for %s: %.2fs", file_name, gemini_time)

        # 4. Crear transacción pendiente
        transaction_service.create_pending_transaction(user, extracted_data)

        # (Opcional) Aquí podrías añadir la lógica para mover el archivo a una carpeta "Procesados"
        # gdrive_service.move_file_to_processed(file_id, ...)
        
        return {'status': 'SUCCESS', 'file_name': file_name}

    except ConnectionError as e:
        # Error de conexión (ej. token no válido), no reintentar.
        self.update_state(state='FAILURE', meta=str(e))
        return {'status': 'FAILURE', 'file_name': file_name, 'error': 'ConnectionError'}
    except Exception as e:
        # Para otros errores, reintentar
        self.retry(exc=e)
        return {'status': 'FAILURE', 'file_name': file_name, 'error': str(e)}

@shared_task
def process_drive_tickets(user_id: int):
    """
    Tarea principal: Obtiene la lista de tickets y lanza tareas paralelas para procesarlos.
    """
    try:
        user = User.objects.get(id=user_id)
        gdrive_service = GoogleDriveService(user)
        files_to_process = gdrive_service.list_files_in_folder(
            folder_name="Tickets de Compra", 
            mimetypes=['image/jpeg', 'image/png', 'application/pdf']
        )

        if not files_to_process:
            return {'status': 'NO_FILES', 'message': 'No se encontraron nuevos tickets.'}

        job = group(
            process_single_ticket.s(user.id, item['id'], item['name'], item['mimeType'])
            for item in files_to_process
        )
        
        result_group = job.apply_async()
        result_group.save() # ¡Esto es clave! Guarda el estado del grupo en el backend de resultados.

        # --- CAMBIO IMPORTANTE ---
        # Devolvemos el ID del grupo para que el frontend pueda monitorearlo.
        return {'status': 'STARTED', 'task_group_id': result_group.id, 'total_tasks': len(files_to_process)}

    except Exception as e:
        # Manejo de errores
        return {'status': 'ERROR', 'message': str(e)}


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def process_single_inversion(self, user_id: int, file_id: str, file_name: str, mime_type: str):
    """Procesa una inversión (imagen o PDF) y crea el registro correspondiente."""
    try:
        user = User.objects.get(id=user_id)
        gdrive_service = GoogleDriveService(user)
        gemini_service = get_gemini_service()
        investment_service = InvestmentService()

        file_content = gdrive_service.get_file_content(file_id)
        if mime_type in ('image/jpeg', 'image/png'):
            image = Image.open(file_content)
            extracted_data = gemini_service.extract_data_from_inversion(image)
        elif mime_type == 'application/pdf':
            extracted_data = gemini_service.extract_inversion_from_pdf(file_content.getvalue())
        else:
            return {'status': 'UNSUPPORTED', 'file_name': file_name, 'error': 'Unsupported file type'}
        
        investment_service.create_pending_investment(user, extracted_data)

        return {'status': 'SUCCESS', 'file_name': file_name}
    except ConnectionError as e:
        self.update_state(state='FAILURE', meta=str(e))
        return {'status': 'FAILURE', 'file_name': file_name, 'error': 'ConnectionError'}
    except Exception as e:
        self.retry(exc=e)
        return {'status': 'FAILURE', 'file_name': file_name, 'error': str(e)}

@shared_task
def process_drive_investments(user_id):
    """
    Tarea para procesar TODOS los archivos de la carpeta 'Inversiones'.
    """
    try:
        user = User.objects.get(id=user_id)
        gdrive_service = GoogleDriveService(user)
        files_to_process = gdrive_service.list_files_in_folder(
            folder_name="Inversiones",
            mimetypes=['image/jpeg', 'image/png', 'application/pdf']
        )

        if not files_to_process:
            return {'status': 'NO_FILES', 'message': 'No se encontraron nuevos tickets.'}

        job = group(
            process_single_inversion.s(user.id, item['id'], item['name'], item['mimeType'])
            for item in files_to_process
        )
        
        result_group = job.apply_async()
        result_group.save() # ¡Esto es clave! Guarda el estado del grupo en el backend de resultados.

        # --- CAMBIO IMPORTANTE ---
        # Devolvemos el ID del grupo para que el frontend pueda monitorearlo.
        return {'status': 'STARTED', 'task_group_id': result_group.id, 'total_tasks': len(files_to_process)}

    except Exception as e:
        # Manejo de errores
        return {'status': 'ERROR', 'message': str(e)}
