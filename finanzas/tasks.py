import time
import json
import logging
from PIL import Image
from io import BytesIO
from decimal import Decimal, InvalidOperation
from .utils import parse_date_safely
from celery import shared_task, group
from django.contrib.auth.models import User
from .services import GoogleDriveService, StockPriceService, TransactionService, InvestmentService, get_gemini_service, ExchangeRateService, MistralOCRService, BillingService
from .models import Deuda, AmortizacionPendiente, PagoAmortizacion, TiendaFacturacion, Factura, HistorialReciboServicio, Presupuesto

logger = logging.getLogger(__name__)

def load_and_optimize_image(file_content, max_width: int = 1024, quality: int = 80) -> bytes:
    """Reduce el tamaño y comprime la imagen para agilizar la llamada a la IA."""
    image = Image.open(file_content).convert("RGB")
    if image.width > max_width:
        ratio = max_width / float(image.width)
        new_height = int(image.height * ratio)
        image = image.resize((max_width, new_height))
    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=quality)
    return buffer.getvalue()

def _get_optimized_file_data(gdrive_service, file_id: str, mime_type: str) -> bytes:
    """Descarga y optimiza el archivo de Drive si es imagen."""
    file_content = gdrive_service.get_file_content(file_id)
    return load_and_optimize_image(file_content) if 'image' in mime_type else file_content.getvalue()

def _get_files_from_drive_folder(user, folder_name: str, mimetypes=None):
    """Obtiene la lista de archivos de una carpeta específica de Drive."""
    gdrive_service = GoogleDriveService(user)
    if mimetypes is None:
        mimetypes = ['image/jpeg', 'image/png', 'application/pdf']
    return gdrive_service.list_files_in_folder(folder_name=folder_name, mimetypes=mimetypes)

def _build_user_context(user) -> str:
    from .models import Cuenta, registro_transacciones
    cuentas = Cuenta.objects.filter(propietario=user)
    lista_cuentas_str = ", ".join([f"'{c.nombre}' (Terminación: {c.terminacion or 'N/A'})" for c in cuentas])
    categorias = list(registro_transacciones.objects.filter(propietario=user).values_list('categoria', flat=True).distinct()[:20])
    return f"Cuentas disponibles del usuario: [{lista_cuentas_str}]. Categorías conocidas del usuario: {categorias}."

@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def process_single_ticket(self, user_id: int, file_id: str, file_name: str, mime_type: str):
    """Procesa un único ticket: extrae datos con Gemini y lo guarda como pendiente."""
    try:
        user = User.objects.get(id=user_id)
        file_data = _get_optimized_file_data(GoogleDriveService(user), file_id, mime_type)
        contexto_usuario = _build_user_context(user)
        
        extracted_data = get_gemini_service().extract_data(
            prompt_name="tickets",
            file_data=file_data,
            mime_type=mime_type,
            context=contexto_usuario
        )
        
        if isinstance(extracted_data, list):
            extracted_data = extracted_data[0] if extracted_data else {}

        if extracted_data.get("error"):
             return {'status': 'FAILURE', 'file_name': file_name, 'error': extracted_data.get('raw_response', 'Error desconocido')}

        TransactionService().create_pending_transaction(user, extracted_data)
        return {'status': 'SUCCESS', 'file_name': file_name}
    except Exception as e:
        self.retry(exc=e)
        return {'status': 'FAILURE', 'file_name': file_name, 'error': str(e)}

@shared_task
def process_drive_tickets(user_id: int):
    """Busca tickets en Drive y lanza tareas paralelas."""
    try:
        user = User.objects.get(id=user_id)
        files_to_process = _get_files_from_drive_folder(user, "Tickets de Compra")

        if not files_to_process:
            return {'status': 'NO_FILES', 'message': 'No se encontraron nuevos tickets.'}

        job = group(process_single_ticket.s(user.id, item['id'], item['name'], item['mimeType']) for item in files_to_process)
        result_group = job.apply_async()
        result_group.save()

        return {'status': 'STARTED', 'task_group_id': result_group.id, 'total_tasks': len(files_to_process)}
    except Exception as e:
        return {'status': 'ERROR', 'message': str(e)}

def _calculate_investment_metrics(extracted_data: dict) -> dict:
    try:
        cantidad = Decimal(str(extracted_data.get("cantidad_titulos", 0)))
        precio_orig = Decimal(str(extracted_data.get("precio_por_titulo", 0)))
    except InvalidOperation:
        raise ValueError('Datos numéricos inválidos de Gemini')

    fecha = parse_date_safely(extracted_data.get("fecha_compra") or extracted_data.get("fecha"))
    rate = ExchangeRateService().get_usd_mxn_rate(fecha)
    precio_actual_usd = StockPriceService().get_current_price(extracted_data.get('emisora_ticker', ''))
    
    if precio_actual_usd is None:
        precio_actual_usd = precio_orig if extracted_data.get("moneda") == "USD" else (precio_orig / rate if rate else None)

    if precio_actual_usd is None:
        raise ValueError('No se pudo obtener el precio actual ni el tipo de cambio')

    precio_usd = precio_orig
    if extracted_data.get("moneda") == "MXN":
        if not rate:
            raise ValueError('Tipo de cambio no disponible para conversión de MXN')
        precio_usd = precio_orig / rate

    costo_total = cantidad * precio_usd
    valor_actual = cantidad * precio_actual_usd
    
    return {
        'fecha_compra': extracted_data.get('fecha_compra'),
        'emisora_ticker': extracted_data.get('emisora_ticker'),
        'nombre_activo': extracted_data.get('nombre_activo'),
        'cantidad_titulos': str(cantidad),
        'precio_por_titulo': str(precio_usd),
        'costo_total_adquisicion': str(costo_total),
        'valor_actual_mercado': str(valor_actual),
        'ganancia_perdida_no_realizada': str(valor_actual - costo_total),
        'tipo_cambio': str(rate) if rate is not None else None,
        'moneda': "USD"
    }

@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def process_single_inversion(self, user_id: int, file_id: str, file_name: str, mime_type: str):
    """Procesa una inversión y crea el registro correspondiente."""
    try:
        if mime_type not in ('image/jpeg', 'image/png', 'application/pdf'):
            return {'status': 'UNSUPPORTED', 'file_name': file_name, 'error': 'Unsupported file type'}
            
        user = User.objects.get(id=user_id)
        file_data = _get_optimized_file_data(GoogleDriveService(user), file_id, mime_type)

        extracted_data = get_gemini_service().extract_data(
            prompt_name="inversion",
            file_data=file_data,
            mime_type=mime_type
        )
        
        if isinstance(extracted_data, list):
            extracted_data = extracted_data[0] if extracted_data else {}
            
        valores = _calculate_investment_metrics(extracted_data)
        InvestmentService().create_pending_investment(user, valores)

        return {'status': 'SUCCESS', 'file_name': file_name}

    except ConnectionError as e:
        self.update_state(state='FAILURE', meta=str(e))
        return {'status': 'FAILURE', 'file_name': file_name, 'error': 'ConnectionError'}
    except Exception as e:
        self.retry(exc=e)
        return {'status': 'FAILURE', 'file_name': file_name, 'error': str(e)}

@shared_task
def process_drive_investments(user_id):
    """Tarea para procesar TODOS los archivos de la carpeta 'Inversiones'."""
    try:
        user = User.objects.get(id=user_id)
        files_to_process = _get_files_from_drive_folder(user, "Inversiones")

        if not files_to_process:
            return {'status': 'NO_FILES', 'message': 'No se encontraron nuevos tickets.'}

        job = group(process_single_inversion.s(user.id, item['id'], item['name'], item['mimeType']) for item in files_to_process)
        result_group = job.apply_async()
        result_group.save()

        return {'status': 'STARTED', 'task_group_id': result_group.id, 'total_tasks': len(files_to_process)}
    except Exception as e:
        return {'status': 'ERROR', 'message': str(e)}

@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def process_single_amortization(self, user_id: int, file_id: str, file_name: str, mime_type: str, deuda_id: int):
    """Procesa un único archivo de tabla de amortización."""
    try:
        if mime_type not in ('image/jpeg', 'image/png', 'application/pdf'):
            return {'status': 'UNSUPPORTED', 'file_name': file_name}
            
        user = User.objects.get(id=user_id)
        deuda = Deuda.objects.get(id=deuda_id, propietario=user)
        file_data = _get_optimized_file_data(GoogleDriveService(user), file_id, mime_type)
        
        extracted_data = get_gemini_service().extract_data(
            prompt_name="deudas",
            file_data=file_data,
            mime_type=mime_type
        )

        AmortizacionPendiente.objects.create(
            propietario=user,
            deuda=deuda,
            datos_json=extracted_data,
            nombre_archivo=file_name,
            estado='pendiente'
        )

        return {'status': 'SUCCESS', 'file_name': file_name}

    except Deuda.DoesNotExist:
        return {'status': 'FAILURE', 'file_name': file_name, 'error': f'No se encontró la deuda con ID {deuda_id}'}
    except Exception as e:
        self.retry(exc=e)
        return {'status': 'FAILURE', 'file_name': file_name, 'error': str(e)}

def _filter_files_by_name(files, target_name: str) -> list:
    """Filtra archivos cuyo nombre contenga el texto objetivo (case-insensitive)."""
    target = target_name.lower()
    return [f for f in files if target in f['name'].lower()]

@shared_task
def process_drive_amortizations(user_id: int, deuda_id: int):
    """Busca tablas de amortización en Drive que coincidan con la deuda."""
    try:
        user = User.objects.get(id=user_id)
        try:
            deuda = Deuda.objects.get(id=deuda_id, propietario=user)
        except Deuda.DoesNotExist:
            return {'status': 'ERROR', 'message': 'La deuda especificada no fue encontrada.'}

        todos_los_archivos = _get_files_from_drive_folder(user, "Tablas de Amortizacion")
        
        if not todos_los_archivos:
            return {'status': 'NO_FILES', 'message': 'No se encontraron archivos en la carpeta.'}

        files_to_process = _filter_files_by_name(todos_los_archivos, deuda.nombre)

        if not files_to_process:
            return {'status': 'NO_FILES', 'message': f"No se encontraron archivos que coincidan con el nombre '{deuda.nombre}'."}

        job = group(process_single_amortization.s(user.id, item['id'], item['name'], item['mimeType'], deuda_id) for item in files_to_process)
        result_group = job.apply_async()
        result_group.save()

        return {'status': 'STARTED', 'task_group_id': result_group.id, 'total_tasks': len(files_to_process)}
    except Exception as e:
        return {'status': 'ERROR', 'message': str(e)}

def _is_bank_transfer(text: str) -> bool:
    """Valida rápidamente si el texto corresponde a una transferencia bancaria."""
    text_upper = text.upper()
    bank_words = ["TRANSFERENCIA", "SPEI", "CLAVE DE RASTREO", "CUENTA ORIGEN", "CUENTA DESTINO", "FOLIO DE AUTORIZACIÓN", "REFERENCIA NUMÉRICA", "REFERENCIA NUMERICA"]
    return any(word in text_upper for word in bank_words) and "TICKET" not in text_upper and "FACTURA" not in text_upper

def _normalize_store_name(datos_extraidos: dict) -> str:
    """Obtiene y normaliza el nombre de la tienda."""
    nombre_ia = (datos_extraidos.get("tienda") or datos_extraidos.get("establecimiento") or "DESCONOCIDO").upper().strip()
    
    if datos_extraidos.get("es_conocida", False):
        logger.info(f"Tienda reconocida por IA: {nombre_ia}")
        return nombre_ia
        
    tienda_obj = BillingService.buscar_tienda_fuzzy(nombre_ia)
    if tienda_obj:
        logger.info(f"Tienda normalizada por Fuzzy: {nombre_ia} -> {tienda_obj.tienda}")
        return tienda_obj.tienda
        
    logger.info(f"Tienda nueva detectada: {nombre_ia}")
    return nombre_ia

from google.api_core.exceptions import ResourceExhausted

@shared_task(bind=True, max_retries=2, default_retry_delay=10)
def process_single_invoice(self, user_id: int, file_id: str, file_name: str, mime_type: str):
    """Procesa un ticket para FACTURACIÓN."""
    try:
        user = User.objects.get(id=user_id)
        file_bytes = GoogleDriveService(user).get_file_content(file_id).getvalue()

        ocr_result = MistralOCRService().get_text_from_image(file_bytes, mime_type)
        if "error" in ocr_result:
            return {'status': 'FAILURE', 'file_name': file_name, 'error': f"Mistral: {ocr_result['error']}"}
            
        texto_ticket = ocr_result['text_content']

        if _is_bank_transfer(texto_ticket):
            return {'status': 'SKIPPED', 'file_name': file_name, 'reason': 'Parece transferencia bancaria, ignorado en facturación.'}

        contexto_str = BillingService.preparar_contexto_para_gemini(texto_ticket)
        
        try:
            datos_extraidos = get_gemini_service().extract_from_text(
                prompt_name="facturacion_from_text_with_context", 
                text=texto_ticket, 
                context=contexto_str
            )
        except ResourceExhausted:
            logger.warning(f"Rate Limit en Gemini para {file_name}. Pausando...")
            return {'status': 'THROTTLED', 'file_name': file_name, 'error': 'Cuota de Gemini excedida (15 RPM).'}
        except Exception as e:
             return {'status': 'FAILURE', 'file_name': file_name, 'error': f"Gemini Error: {str(e)}"}

        if not datos_extraidos:
             return {'status': 'FAILURE', 'file_name': file_name, 'error': 'JSON vacío de Gemini'}

        if isinstance(datos_extraidos, list):
            datos_extraidos = datos_extraidos[0] if datos_extraidos else {}

        if datos_extraidos.get("es_transferencia", False):
             return {'status': 'SKIPPED', 'file_name': file_name, 'reason': 'Gemini detectó que es una transferencia o pago de servicios.'}

        tienda_final = _normalize_store_name(datos_extraidos)

        payload_facturacion = datos_extraidos.get("campos_adicionales", {})
        payload_facturacion['tienda'] = tienda_final
        payload_facturacion['es_conocida'] = True 

        Factura.objects.create(
            propietario=user,
            tienda=tienda_final,
            fecha_emision=parse_date_safely(datos_extraidos.get("fecha")),
            total=Decimal(str(datos_extraidos.get("total", 0))),
            datos_facturacion=payload_facturacion,
            archivo_drive_id=file_id,
            estado='pendiente' 
        )

        return {'status': 'SUCCESS', 'file_name': file_name, 'tienda': tienda_final, 'es_conocida': True, 'mensaje': f"Tienda vinculada: {tienda_final}"}

    except Exception as e:
        logger.error(f"Error fatal procesando {file_name}: {e}")
        return {'status': 'FAILURE', 'file_name': file_name, 'error': str(e)}

@shared_task
def process_drive_for_invoices(user_id: int):
    """Tarea Maestra: Busca archivos y lanza los workers."""
    try:
        user = User.objects.get(id=user_id)
        files_to_process = _get_files_from_drive_folder(user, "Tickets de Compra")

        if not files_to_process:
            return {'status': 'NO_FILES', 'message': 'No se encontraron nuevos tickets.'}

        job = group(process_single_invoice.s(user.id, item['id'], item['name'], item['mimeType']) for item in files_to_process)
        result_group = job.apply_async()
        result_group.save()

        return {'status': 'STARTED', 'task_group_id': result_group.id, 'total_tasks': len(files_to_process)}

    except Exception as e:
        return {'status': 'ERROR', 'message': str(e)}

def _parse_utility_bill_data(datos: dict) -> tuple:
    from datetime import datetime
    fecha_emision = datos.get('fecha_emision')
    fecha_obj = None
    if fecha_emision:
        try:
            fecha_obj = datetime.strptime(fecha_emision, '%Y-%m-%d').date()
        except ValueError:
            pass

    try:
        monto = float(datos.get('monto_total', 0))
    except (ValueError, TypeError):
        monto = 0.0

    return fecha_obj, monto

@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def process_single_utility_bill(self, user_id: int, presupuesto_id: int, file_id: str, file_name: str, mime_type: str):
    """Procesa un recibo de servicio usando Mistral y Gemini."""
    try:
        user = User.objects.get(id=user_id)
        presupuesto = Presupuesto.objects.get(id=presupuesto_id, propietario=user)
        file_data = _get_optimized_file_data(GoogleDriveService(user), file_id, mime_type)
        
        datos = get_gemini_service().extract_data(
            prompt_name="recibo_servicio",
            file_data=file_data,
            mime_type="application/pdf" if mime_type == "application/pdf" else "image/jpeg"
        )
        
        if isinstance(datos, list):
            datos = datos[0] if datos else {}
            
        if datos.get("error"):
            return {'status': 'FAILURE', 'file_name': file_name, 'error': datos.get('error')}
            
        fecha_obj, monto = _parse_utility_bill_data(datos)
            
        HistorialReciboServicio.objects.create(
            propietario=user,
            presupuesto=presupuesto,
            fecha_emision=fecha_obj,
            monto_total=monto,
            datos_json=datos,
            archivo_drive_id=file_id
        )
        
        return {'status': 'SUCCESS', 'file_name': file_name}
    except Exception as e:
        self.retry(exc=e)
        return {'status': 'FAILURE', 'file_name': file_name, 'error': str(e)}

def _get_utility_bill_folder_files(drive_service, categoria_lower: str) -> list:
    query_recibos = "mimeType='application/vnd.google-apps.folder' and trashed=false and (name='recibos' or name='Recibos' or name='RECIBOS')"
    carpetas = drive_service.service.files().list(q=query_recibos, spaces='drive', fields='files(id)').execute().get('files', [])
    if not carpetas:
        raise ValueError('Carpeta Recibos no encontrada.')
        
    carpeta_id = carpetas[0]['id']
    cat_upper, cat_title = categoria_lower.upper(), categoria_lower.capitalize()
    query_sub = f"mimeType='application/vnd.google-apps.folder' and '{carpeta_id}' in parents and trashed=false and (name='{categoria_lower}' or name='{cat_title}' or name='{cat_upper}')"
    
    subcarpetas = drive_service.service.files().list(q=query_sub, spaces='drive', fields='files(id)').execute().get('files', [])
    if not subcarpetas:
        raise ValueError(f'Subcarpeta {categoria_lower} no encontrada.')
        
    return drive_service.service.files().list(
        q=f"'{subcarpetas[0]['id']}' in parents and trashed=false",
        fields="files(id, name, mimeType)"
    ).execute().get('files', [])

@shared_task
def process_drive_utility_bills(user_id: int, presupuesto_id: int, categoria_lower: str):
    """Busca y procesa recibos de servicio en Drive."""
    try:
        user = User.objects.get(id=user_id)
        drive_service = GoogleDriveService(user)
        
        try:
            archivos = _get_utility_bill_folder_files(drive_service, categoria_lower)
        except ValueError as ve:
            return {'status': 'NO_FILES', 'message': str(ve)}
            
        if not archivos:
            return {'status': 'NO_FILES', 'message': 'No hay archivos para analizar en la carpeta.'}
            
        files_to_process = [
            a for a in archivos 
            if (a['mimeType'].startswith('image/') or a['mimeType'] == 'application/pdf') 
            and not HistorialReciboServicio.objects.filter(archivo_drive_id=a['id']).exists()
        ]
                
        if not files_to_process:
            return {'status': 'NO_FILES', 'message': 'No hay recibos nuevos por procesar.'}
            
        job = group(process_single_utility_bill.s(user.id, presupuesto_id, item['id'], item['name'], item['mimeType']) for item in files_to_process)
        result_group = job.apply_async()
        result_group.save()
        
        return {'status': 'STARTED', 'task_group_id': result_group.id, 'total_tasks': len(files_to_process)}
        
    except Exception as e:
        return {'status': 'ERROR', 'message': str(e)}