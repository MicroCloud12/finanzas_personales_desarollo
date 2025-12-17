import time
import json
import logging
from PIL import Image
from io import BytesIO
from decimal import Decimal, InvalidOperation
from .utils import parse_date_safely
from celery import shared_task, group
from django.contrib.auth.models import User
from .services import GoogleDriveService, StockPriceService, TransactionService, InvestmentService, get_gemini_service, ExchangeRateService
from .models import Deuda, AmortizacionPendiente, PagoAmortizacion, TiendaFacturacion, Factura

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

@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def process_single_ticket(self, user_id: int, file_id: str, file_name: str, mime_type: str):
    """
    Procesa un único ticket: lo descarga, lo analiza con Gemini y lo guarda como pendiente.
    """
    try:
        user = User.objects.get(id=user_id)
        gdrive_service = GoogleDriveService(user)
        gemini_service = get_gemini_service() # Correcto, usando el singleton
        transaction_service = TransactionService()
        file_content = gdrive_service.get_file_content(file_id)

        
        
        # --- LÓGICA DE EXTRACCIÓN UNIFICADA ---
        file_data = load_and_optimize_image(file_content) if 'image' in mime_type else file_content.getvalue()
        
        extracted_data = gemini_service.extract_data(
            prompt_name="tickets", # Usamos la clave del prompt
            file_data=file_data,
            mime_type=mime_type
        )
        
        if extracted_data.get("error"):
             return {'status': 'FAILURE', 'file_name': file_name, 'error': extracted_data['raw_response']}

        transaction_service.create_pending_transaction(user, extracted_data)
        return {'status': 'SUCCESS', 'file_name': file_name}

    except Exception as e:
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
        current_price = StockPriceService()
        file_content = gdrive_service.get_file_content(file_id)

        # --- CORRECCIÓN 1: Unificar la preparación de datos y la llamada a Gemini ---
        file_data = load_and_optimize_image(file_content) if 'image' in mime_type else file_content.getvalue()

        extracted_data = gemini_service.extract_data(
            prompt_name="inversion", # Usamos la clave del prompt "inversion"
            file_data=file_data,
            mime_type=mime_type
        )
        
        if mime_type not in ('image/jpeg', 'image/png', 'application/pdf'):
            return {'status': 'UNSUPPORTED', 'file_name': file_name, 'error': 'Unsupported file type'}
        
        # (El resto de tu lógica para procesar los datos de inversión se mantiene igual)
        try:
            cantidad = Decimal(str(extracted_data.get("cantidad_titulos", 0)))
            precio_por_titulo_orig = Decimal(str(extracted_data.get("precio_por_titulo", 0)))
        except InvalidOperation:
            return {'status': 'FAILURE', 'file_name': file_name, 'error': 'Datos numéricos inválidos de Gemini'}
        
        # ... (resto de la lógica sin cambios)
        fecha = parse_date_safely(extracted_data.get("fecha_compra") or extracted_data.get("fecha"))
        rate_service = ExchangeRateService()
        rate = rate_service.get_usd_mxn_rate(fecha)

        precio_actual_usd = current_price.get_current_price(extracted_data['emisora_ticker'])
        if precio_actual_usd is None:
            precio_actual_usd = precio_por_titulo_orig if extracted_data.get("moneda") == "USD" else (precio_por_titulo_orig / rate if rate else None)
        
        if precio_actual_usd is None:
            return {'status': 'FAILURE', 'file_name': file_name, 'error': 'No se pudo obtener el precio actual ni el tipo de cambio'}
        
        # ... (más lógica sin cambios)
        precio_por_titulo_usd = precio_por_titulo_orig
        if extracted_data.get("moneda") == "MXN":
            if rate is None or rate == 0:
                return {'status': 'FAILURE', 'file_name': file_name, 'error': 'Tipo de cambio no disponible para conversión de MXN'}
            precio_por_titulo_usd = precio_por_titulo_orig / rate
        
        costo_total_adquisicion = cantidad * precio_por_titulo_usd
        valor_actual_mercado = cantidad * precio_actual_usd
        ganancia_perdida_no_realizada = valor_actual_mercado - costo_total_adquisicion

        extracted_data['tipo_cambio_usd'] = str(rate) if rate is not None else None
        
        valores = {
            'fecha_compra': extracted_data.get('fecha_compra'),
            'emisora_ticker': extracted_data.get('emisora_ticker'),
            'nombre_activo': extracted_data.get('nombre_activo'),
            'cantidad_titulos': str(cantidad),
            'precio_por_titulo': str(precio_por_titulo_usd),
            'costo_total_adquisicion': str(costo_total_adquisicion),
            'valor_actual_mercado': str(valor_actual_mercado),
            'ganancia_perdida_no_realizada': str(ganancia_perdida_no_realizada),
            'tipo_cambio': str(rate) if rate is not None else None,
            'moneda': "USD"
        }

        print(f"datos extraidos: {extracted_data}")
        investment_service.create_pending_investment(user, valores)

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

@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def process_single_amortization(self, user_id: int, file_id: str, file_name: str, mime_type: str, deuda_id: int):
    """Procesa un único archivo de tabla de amortización."""
    try:
        user = User.objects.get(id=user_id)
        deuda = Deuda.objects.get(id=deuda_id, propietario=user)

        gdrive_service = GoogleDriveService(user)
        gemini_service = get_gemini_service()
        file_content = gdrive_service.get_file_content(file_id)
        
        # --- CORRECCIÓN 2: Unificar la preparación de datos y la llamada a Gemini ---
        file_data = load_and_optimize_image(file_content) if 'image' in mime_type else file_content.getvalue()
        
        extracted_data = gemini_service.extract_data(
            prompt_name="deudas", # Usamos la clave del prompt "deudas"
            file_data=file_data,
            mime_type=mime_type
        )

        if mime_type not in ('image/jpeg', 'image/png', 'application/pdf'):
            return {'status': 'UNSUPPORTED', 'file_name': file_name}

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

@shared_task
def process_drive_amortizations(user_id: int, deuda_id: int):
    """
    Busca tablas de amortización en Drive y lanza tareas para procesar solo
    los archivos cuyo nombre coincida con el de la deuda.
    """
    try:
        user = User.objects.get(id=user_id)
        
        # --- NUEVA LÓGICA (PASO 1: OBTENER NOMBRE DE LA DEUDA) ---
        try:
            deuda = Deuda.objects.get(id=deuda_id, propietario=user)
            # Normalizamos el nombre de la deuda para una comparación robusta
            # Ejemplo: "Préstamo Coche" -> "préstamo coche"
            nombre_deuda_normalizado = deuda.nombre.lower()
            print(f"Nombre de deuda normalizado: {nombre_deuda_normalizado}")
        except Deuda.DoesNotExist:
            return {'status': 'ERROR', 'message': 'La deuda especificada no fue encontrada.'}

        gdrive_service = GoogleDriveService(user)
        todos_los_archivos = gdrive_service.list_files_in_folder(
            folder_name="Tablas de Amortizacion",
            mimetypes=['image/jpeg', 'image/png', 'application/pdf']
        )

        if not todos_los_archivos:
            return {'status': 'NO_FILES', 'message': 'No se encontraron archivos en la carpeta.'}

        # --- NUEVA LÓGICA (PASO 2 y 3: FILTRAR ARCHIVOS) ---
        files_to_process = []
        for archivo in todos_los_archivos:
            # Normalizamos el nombre del archivo
            # Ejemplo: "Amortizacion - Préstamo Coche.pdf" -> "amortizacion - préstamo coche.pdf"
            nombre_archivo_normalizado = archivo['name'].lower()
            print(f"Nombre de archivo normalizado: {nombre_archivo_normalizado}")
            
            # Comprobamos si el nombre de la deuda está contenido en el nombre del archivo
            if nombre_deuda_normalizado in nombre_archivo_normalizado:
                files_to_process.append(archivo)
        
        # --- FIN DE LA NUEVA LÓGICA ---

        if not files_to_process:
            return {'status': 'NO_FILES', 'message': f"No se encontraron archivos que coincidan con el nombre '{deuda.nombre}'."}

        job = group(
            process_single_amortization.s(user.id, item['id'], item['name'], item['mimeType'], deuda_id)
            for item in files_to_process
        )
        result_group = job.apply_async()
        result_group.save()

        return {'status': 'STARTED', 'task_group_id': result_group.id, 'total_tasks': len(files_to_process)}

    except Exception as e:
        return {'status': 'ERROR', 'message': str(e)}
    


    # ... (código existente) ...

@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def process_single_invoice(self, user_id: int, file_id: str, file_name: str, mime_type: str):
    """
    Procesa un ticket para fines de FACTURACIÓN.
    1. Obtiene tiendas conocidas (Tabla 1).
    2. Envía a Gemini con ese contexto.
    3. Guarda en el modelo Factura (Tabla 2).
    """
    try:
        user = User.objects.get(id=user_id)
        gdrive_service = GoogleDriveService(user)
        gemini_service = get_gemini_service()
        
        # Obtenemos el contenido del archivo
        file_content = gdrive_service.get_file_content(file_id)
        
        # Preparamos los datos (usando la función corregida que devuelve bytes)
        file_data = load_and_optimize_image(file_content) if 'image' in mime_type else file_content.getvalue()

        # --- PASO 1: Contexto de Tiendas Conocidas (Tabla 1) ---
        # Consultamos qué tiendas ya tenemos configuradas para decirle a Gemini qué buscar.
        try:
            tiendas_conocidas = TiendaFacturacion.objects.all().values('tienda', 'campos_requeridos')
            lista_tiendas = list(tiendas_conocidas)
            contexto_str = json.dumps(lista_tiendas, ensure_ascii=False) if lista_tiendas else ""
        except Exception:
            contexto_str = "" 

        # --- PASO 2: Extracción con Gemini ---
        extracted_data = gemini_service.extract_data(
            prompt_name="facturacion",
            file_data=file_data,
            mime_type=mime_type,
            context=contexto_str
        )

        if extracted_data.get("error"):
            return {'status': 'FAILURE', 'file_name': file_name, 'error': extracted_data['raw_response']}

        # Validamos que sea un ticket y no una transferencia
        tipo_documento = extracted_data.get("tipo_documento", "").upper()
        if tipo_documento == "TRANSFERENCIA":
            return {'status': 'SKIPPED', 'file_name': file_name, 'reason': 'Es una transferencia, no aplica para facturación'}

        # --- PASO 3: Guardar en Tabla de Resultados (Tabla 2: Factura) ---
        
        # Intentamos vincular con la configuración existente
        nombre_tienda = extracted_data.get("tienda", "DESCONOCIDO").upper()
        config_tienda = TiendaFacturacion.objects.filter(tienda=nombre_tienda).first()

        # Limpiamos y convertimos datos básicos
        fecha_str = extracted_data.get("fecha_emision") or extracted_data.get("fecha")
        fecha_obj = parse_date_safely(fecha_str)
        
        total_str = str(extracted_data.get("total_pagado") or extracted_data.get("total") or 0)
        
        # Creamos el registro de Factura
        Factura.objects.create(
            propietario=user,
            tienda=nombre_tienda,
            fecha_emision=fecha_obj,
            total=Decimal(total_str),
            
            # Aquí guardamos TODO el JSON que nos dio Gemini.
            # Esto permite que si Gemini encontró "Folio" y "RFC", se guarden aquí
            # para mostrarlos luego en el frontend.
            datos_facturacion=extracted_data, 
            
            # Guardamos el ID de Drive para que el usuario pueda ver la imagen original
            archivo_drive_id=file_id,
            
            # Vinculamos la configuración si la encontramos (para saber la URL del portal, etc.)
            configuracion_tienda=config_tienda,
            
            estado='pendiente'
        )

        return {'status': 'SUCCESS', 'file_name': file_name, 'tienda': nombre_tienda}

    except Exception as e:
        self.retry(exc=e)
        return {'status': 'FAILURE', 'file_name': file_name, 'error': str(e)}

@shared_task
def process_drive_for_invoices(user_id: int):
    """Busca tickets en Drive y los procesa con el prompt de facturación."""
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
            process_single_invoice.s(user.id, item['id'], item['name'], item['mimeType'])
            for item in files_to_process
        )

        result_group = job.apply_async()
        result_group.save()

        return {'status': 'STARTED', 'task_group_id': result_group.id, 'total_tasks': len(files_to_process)}

    except Exception as e:
        return {'status': 'ERROR', 'message': str(e)}
