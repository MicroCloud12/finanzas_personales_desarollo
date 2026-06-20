# finanzas/services/finance_service.py
import re
from decimal import Decimal
import logging
from datetime import datetime, date
from collections import defaultdict
from dateutil.relativedelta import relativedelta
from .market_data_service import StockPriceService
from ..models import TransaccionPendiente, registro_transacciones, User, inversiones, PendingInvestment, Deuda, PagoAmortizacion
from ..utils import parse_date_safely
import time

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
            tipo_movimiento = datos.get("tipo_movimiento")
            
            descripcion_final = datos.get("descripcion_corta", "Sin descripción")
            
            if tipo_documento == 'TRANSFERENCIA' or tipo_movimiento == 'TRANSFERENCIA':
                descripcion_final = re.sub(r'(?i)^transferencias?\s*(de|por)?\s*', '', descripcion_final).strip()
            elif tipo_documento == 'TICKET_COMPRA' or tipo_movimiento == 'GASTO':
                descripcion_final = datos.get("establecimiento", descripcion_final)
            
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

    @staticmethod
    def calculate_monthly_profit(user, price_service=None):
        """Calcula la ganancia mensual no realizada de las inversiones de un usuario."""
        servicio_precios = price_service or StockPriceService()
        ganancias_mensuales = defaultdict(Decimal)
        
        inversiones_usuario = inversiones.objects.filter(propietario=user)
        if not inversiones_usuario:
            return {}

        hoy = datetime.now().date()
        inversiones_por_ticker = defaultdict(list)
        inicio_por_ticker = {}

        for inv in inversiones_usuario:
            inversiones_por_ticker[inv.emisora_ticker].append(inv)
            inicio = inv.fecha_compra.replace(day=1)
            if inv.emisora_ticker not in inicio_por_ticker or inicio < inicio_por_ticker[inv.emisora_ticker]:
                inicio_por_ticker[inv.emisora_ticker] = inicio

        series_cache = {}
        for ticker, inicio in inicio_por_ticker.items():
            series = servicio_precios.get_monthly_series(ticker, inicio, hoy)
            series_cache[ticker] = {p["datetime"][:7]: Decimal(str(p["close"])) for p in series}
            time.sleep(12)

        for ticker, inversiones_list in inversiones_por_ticker.items():
            precios_por_mes = series_cache.get(ticker, {})
            for inv in inversiones_list:
                fecha_iter = inv.fecha_compra.replace(day=1)
                while fecha_iter <= hoy:
                    mes_str = fecha_iter.strftime("%Y-%m")
                    precio_cierre = precios_por_mes.get(mes_str)
                    if precio_cierre is not None:
                        costo_total_adquisicion = inv.cantidad_titulos * inv.precio_compra_titulo
                        valor_actual_mercado = inv.cantidad_titulos * precio_cierre
                        ganancia_perdida_no_realizada = valor_actual_mercado - costo_total_adquisicion
                        ganancias_mensuales[mes_str] += ganancia_perdida_no_realizada
                        
                    if fecha_iter.month == 12:
                        fecha_iter = date(fecha_iter.year + 1, 1, 1)
                    else:
                        fecha_iter = date(fecha_iter.year, fecha_iter.month + 1, 1)
        return dict(sorted(ganancias_mensuales.items()))

    @staticmethod
    def calculate_daily_portfolio_history(user, price_service=None):
        """
        Calcula el historial diario del valor del portafolio.
        Devuelve una lista de diccionarios con: fecha, valor_total, capital_invertido, ganancia_no_realizada.
        """
        servicio_precios = price_service or StockPriceService()
        
        inversiones_usuario = inversiones.objects.filter(propietario=user).order_by('fecha_compra')
        if not inversiones_usuario:
            return []

        fecha_inicio = inversiones_usuario.first().fecha_compra
        hoy = datetime.now().date()
        
        inversiones_por_ticker = defaultdict(list)
        tickers = set()
        for inv in inversiones_usuario:
            inversiones_por_ticker[inv.emisora_ticker].append(inv)
            tickers.add(inv.emisora_ticker)

        precios_diarios_cache = {}
        for ticker in tickers:
            inicio_ticker = inversiones_por_ticker[ticker][0].fecha_compra
            series = servicio_precios.get_daily_series(ticker, inicio_ticker, hoy)
            
            precios_diarios_cache[ticker] = {
                p["datetime"]: Decimal(str(p["close"])) for p in series
            }
            time.sleep(12)

        historial = []
        fecha_iter = fecha_inicio

        while fecha_iter <= hoy:
            valor_total_dia = Decimal('0.0')
            capital_invertido_dia = Decimal('0.0')

            for ticker, lista_inv in inversiones_por_ticker.items():
                cantidad_acumulada_ticker = Decimal('0.0')
                costo_acumulado_ticker = Decimal('0.0')
                
                for inv in lista_inv:
                    if inv.fecha_compra <= fecha_iter:
                        cantidad_acumulada_ticker += inv.cantidad_titulos
                        costo_acumulado_ticker += inv.costo_total_adquisicion
                
                if cantidad_acumulada_ticker > 0:
                    capital_invertido_dia += costo_acumulado_ticker
                    
                    fecha_str = fecha_iter.strftime("%Y-%m-%d")
                    precio_cierre = precios_diarios_cache.get(ticker, {}).get(fecha_str)
                    
                    if precio_cierre is None:
                        for i in range(1, 6):
                            d_back = fecha_iter - relativedelta(days=i)
                            p_back = precios_diarios_cache.get(ticker, {}).get(d_back.strftime("%Y-%m-%d"))
                            if p_back:
                                precio_cierre = p_back
                                break
                                
                    if precio_cierre:
                         valor_total_dia += cantidad_acumulada_ticker * precio_cierre
                    else:
                        valor_total_dia += costo_acumulado_ticker

            historial.append({
                'fecha': fecha_iter,
                'valor_total': valor_total_dia,
                'capital_invertido': capital_invertido_dia,
                'ganancia_no_realizada': valor_total_dia - capital_invertido_dia
            })
            
            fecha_iter += relativedelta(days=1)

        return historial

class DebtService:
    """Service for handling debt operations like amortizations."""

    @staticmethod
    def generar_tabla_amortizacion(deuda: Deuda):
        '''
        Calcula y guarda la tabla de amortización para un préstamo usando el sistema de amortización francés.
        '''
        if deuda.tipo_deuda != 'PRESTAMO' or deuda.plazo_meses == 0:
            return

        tasa_interes_mensual = (deuda.tasa_interes / Decimal(100)) / Decimal(12)
        plazo = deuda.plazo_meses
        monto_prestamo = deuda.monto_total
        saldo_pendiente = monto_prestamo
        
        if tasa_interes_mensual > 0:
            factor = (tasa_interes_mensual * (1 + tasa_interes_mensual) ** plazo) / (((1 + tasa_interes_mensual) ** plazo) - 1)
            cuota_mensual = monto_prestamo * factor
        else:
            cuota_mensual = monto_prestamo / plazo

        fecha_pago = deuda.fecha_adquisicion

        for i in range(1, plazo + 1):
            fecha_pago += relativedelta(months=1)
            
            intereses_cuota = saldo_pendiente * tasa_interes_mensual
            capital_cuota = cuota_mensual - intereses_cuota
            saldo_pendiente -= capital_cuota

            if i == plazo:
                capital_cuota += saldo_pendiente
                saldo_pendiente = Decimal(0)

            PagoAmortizacion.objects.create(
                deuda=deuda,
                numero_cuota=i,
                fecha_vencimiento=fecha_pago,
                capital=capital_cuota.quantize(Decimal('0.01')),
                interes=intereses_cuota.quantize(Decimal('0.01')),
                iva=(intereses_cuota * Decimal('0.16')).quantize(Decimal('0.01')),
                saldo_insoluto=saldo_pendiente.quantize(Decimal('0.01'))
            )
