# finanzas/services/billing_service.py
from difflib import get_close_matches
from ..models import TiendaFacturacion
import json

class BillingService:
    @staticmethod
    def guardar_configuracion_tienda(nombre_tienda: str, campos_seleccionados: list):
        if not nombre_tienda: return None
        obj, _ = TiendaFacturacion.objects.update_or_create(
            tienda=nombre_tienda.upper().strip(),
            defaults={'campos_requeridos': campos_seleccionados}
        )
        return obj

    @staticmethod
    def buscar_tienda_fuzzy(nombre_detectado: str):
        if not nombre_detectado: return None
            
        nombre_detectado = nombre_detectado.strip().upper()
        
        try:
            return TiendaFacturacion.objects.get(tienda=nombre_detectado)
        except TiendaFacturacion.DoesNotExist:
            pass
            
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
                return TiendaFacturacion.objects.get(tienda=nombre_corregido)
            except TiendaFacturacion.DoesNotExist:
                nombre_detectado = nombre_corregido
                
        palabras_ruido = ["FARMACIAS", "TIENDA", "SUPERMERCADO", "RESTAURANTE", "S.A. DE C.V.", "SA DE CV", "SUCURSAL"]
        nombre_limpio = nombre_detectado
        for p in palabras_ruido:
            nombre_limpio = nombre_limpio.replace(p, "").strip()
            
        inicial = nombre_limpio[0] if nombre_limpio else ""
        if inicial:
            candidatos_qs = TiendaFacturacion.objects.filter(tienda__istartswith=inicial)
            if candidatos_qs.count() < 5:
                primera_palabra = nombre_limpio.split()[0]
                candidatos_qs = TiendaFacturacion.objects.filter(tienda__icontains=primera_palabra)
            nombres_tiendas = list(candidatos_qs.values_list('tienda', flat=True))
        else:
            nombres_tiendas = []
        
        if nombres_tiendas:
            coincidencias = get_close_matches(nombre_detectado, nombres_tiendas, n=1, cutoff=0.8)
            if coincidencias: return TiendaFacturacion.objects.get(tienda=coincidencias[0])
                
            if nombre_limpio and nombre_limpio != nombre_detectado:
                coincidencias_limpias = get_close_matches(nombre_limpio, nombres_tiendas, n=1, cutoff=0.8)
                if coincidencias_limpias: return TiendaFacturacion.objects.get(tienda=coincidencias_limpias[0])
            
        return None

    @staticmethod
    def procesar_datos_facturacion(datos_json: dict) -> dict:
        tienda_detectada = (datos_json.get('tienda') or datos_json.get('establecimiento') or 'DESCONOCIDO').upper().strip()
        ya_validada_por_ia = datos_json.get('es_conocida') is True

        config_tienda = None
        if ya_validada_por_ia:
            try:
                config_tienda = TiendaFacturacion.objects.get(tienda=tienda_detectada)
            except TiendaFacturacion.DoesNotExist:
                config_tienda = BillingService.buscar_tienda_fuzzy(tienda_detectada)
        else:
            config_tienda = BillingService.buscar_tienda_fuzzy(tienda_detectada)
        
        es_conocida = getattr(config_tienda, 'configuracion_finalizada', False) if config_tienda else False
        tienda_nombre = config_tienda.tienda if config_tienda else tienda_detectada
        campos_requeridos = config_tienda.campos_requeridos if config_tienda else []
        url_portal = config_tienda.url_portal if config_tienda else None

        campos_encontrados = datos_json.get('campos_adicionales') or datos_json 
        datos_para_cliente = {}
        campos_faltantes = []
        
        if campos_requeridos:
            for campo in campos_requeridos:
                valor = (campos_encontrados.get(campo) or 
                         campos_encontrados.get(campo.lower()) or 
                         campos_encontrados.get(campo.replace(' ', '_').lower()) or
                         campos_encontrados.get(campo.upper()))
                if valor: datos_para_cliente[campo] = valor
                else: campos_faltantes.append(campo)
        else:
            claves_ignorar = ['tienda', 'fecha', 'total', 'es_conocida', 'tipo_documento', 'confianza_extraccion', 'fecha_emision', 'total_pagado', 'establecimiento', 'texto_ocr_preview', 'archivo_drive_id', 'nombre_archivo', 'campos_adicionales', '_razonamiento']
            for k, v in campos_encontrados.items():
                if k not in claves_ignorar and isinstance(v, (str, int, float)) and v:
                     datos_para_cliente[k] = v

        claves_ignorar = ['tienda', 'fecha', 'total', 'es_conocida', 'campos_adicionales', 'tipo_documento', 'confianza_extraccion', 'fecha_emision', 'total_pagado', 'establecimiento', 'texto_ocr_preview', 'archivo_drive_id', 'nombre_archivo', '_razonamiento']
        campos_en_config = set(datos_para_cliente.keys()) | set(campos_faltantes)
        campos_extra_detectados = {}
        for k, v in campos_encontrados.items():
            if k not in claves_ignorar and k not in campos_en_config and isinstance(v, (str, int, float)) and v:
                 campos_extra_detectados[k] = v

        return {
            'tienda': tienda_nombre,
            'tienda_original': tienda_detectada if tienda_detectada != tienda_nombre else None,
            'es_conocida': es_conocida,
            'url_portal': url_portal,
            'datos_para_cliente': datos_para_cliente,
            'campos_faltantes': campos_faltantes,
            'campos_extra_detectados': campos_extra_detectados,
            'raw_json': datos_json
        }

    @staticmethod
    def preparar_contexto_para_gemini(texto_ticket: str) -> str:
        tiendas = TiendaFacturacion.objects.all()
        if not tiendas.exists():
            return "No hay tiendas conocidas configuradas. Extrae los datos estándar."

        contexto_str = "### BASE DE DATOS DE TIENDAS CONOCIDAS (USAR ESTOS NOMBRES EXACTOS):\n"
        for t in tiendas:
            campos_json = json.dumps(t.campos_requeridos, ensure_ascii=False)
            contexto_str += f"- ID: '{t.tienda}' | REQUIERE EXTRACCIÓN DE: {campos_json}\n"
            
        return contexto_str
