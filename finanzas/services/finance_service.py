# finanzas/services/finance_service.py
import re
from decimal import Decimal
import logging
from ..utils import parse_date_safely
from .market_data_service import StockPriceService
from ..models import TransaccionPendiente, registro_transacciones, User, inversiones, PendingInvestment

logger = logging.getLogger(__name__)

class TransactionService:
    """Service for handling transaction business logic."""
    
    @staticmethod
    def create_pending_transaction(user: User, data: dict):
        if "error" in data:
            logger.warning(f"Failed pending transaction creation: {data['error']}")
            return None
        return TransaccionPendiente.objects.create(propietario=user, datos_json=data, estado='pendiente')

    @staticmethod
    def approve_pending_transaction(ticket_id: int, user: User, cuenta: str, categoria: str, tipo_transaccion: str, cuenta_destino: str):
        try:
            ticket = TransaccionPendiente.objects.get(id=ticket_id, propietario=user)
            datos = ticket.datos_json
            tipo_documento = datos.get("tipo_documento")
            
            descripcion_final = datos.get("descripcion_corta", "Sin descripción")
            
            if tipo_documento == 'TRANSFERENCIA':
                descripcion_final = re.sub(r'(?i)^transferencias?\s*(de|por)?\s*', '', descripcion_final).strip()
            
            if tipo_documento == 'TICKET_COMPRA':
                descripcion_final = datos.get("establecimiento", "Compra sin establecimiento")
            
            fecha_segura = parse_date_safely(datos.get("fecha") or datos.get("fecha_emision"))
            monto_str = str(datos.get("total") or datos.get("total_pagado") or 0.0)

            registro_transacciones.objects.create(
                propietario=user,
                fecha=fecha_segura,
                descripcion=descripcion_final.upper(), 
                categoria=categoria,
                monto=Decimal(monto_str),
                tipo=tipo_transaccion,
                cuenta_origen=cuenta,
                cuenta_destino=cuenta_destino,
                datos_extra=datos 
            )
            
            ticket.estado = 'aprobada'
            ticket.save()
            return ticket
        except TransaccionPendiente.DoesNotExist:
            return None


class InvestmentService:
    """Service for handling investment operations."""

    @staticmethod
    def create_investment(user: User, data: dict):
        if "error" in data:
            logger.warning(f"Failed investment creation: {data['error']}")
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
        if "error" in data:
            logger.warning(f"Failed pending investment creation: {data['error']}")
            return None
        
        return PendingInvestment.objects.create(
            propietario=user,
            datos_json=data,
            estado='pendiente'
        )
