# finanzas/services/finance_service.py
from decimal import Decimal
import logging
from datetime import datetime
from collections import defaultdict
from dateutil.relativedelta import relativedelta
from .market_data_service import StockPriceService
from ..models import TransaccionPendiente, registro_transacciones, User, inversiones, PendingInvestment, Deuda, PagoAmortizacion, Cuenta
from ..utils import parse_date_safely
from ..categorias import descripcion_final, cuenta_ahorro_para, monto_de_ticket, _a_decimal, CATEGORIA_POR_DEFECTO, SENTINELA_NUEVA_AHORRO
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
    def resolver_cuenta(user: User, nombre):
        """Convierte el nombre elegido en el formulario de tickets en una Cuenta (o None)."""
        nombre = (nombre or '').strip()
        if nombre.upper() in {'', 'N/A', 'OTRA CUENTA', 'SIN CUENTA'}:
            return None
        return Cuenta.objects.filter(propietario=user, nombre__iexact=nombre).first()

    @staticmethod
    def approve_pending_transaction(ticket_id: int, user: User, cuenta: str, categoria: str, tipo_transaccion: str, cuenta_destino: str, monto=None):
        """
        Convierte un ticket pendiente en un movimiento del libro mayor.
        Si no se eligió cuenta, se usa la cuenta principal del usuario para que la
        aprobación sea de un clic. Si no se eligió categoría, se usa 'Otro'.
        """
        try:
            ticket = TransaccionPendiente.objects.get(id=ticket_id, propietario=user)
            datos = ticket.datos_json
            fecha_segura = parse_date_safely(datos.get("fecha") or datos.get("fecha_emision"))
            # El monto lo puede corregir/escribir el usuario en la fila; si no, el que leyó la IA.
            monto_final = _a_decimal(monto) if monto not in (None, '') else None
            if monto_final is None:
                monto_final = monto_de_ticket(datos)
            if monto_final <= 0:
                return None   # sin monto no hay movimiento que registrar
            tipo_transaccion = (tipo_transaccion or 'GASTO').upper()
            categoria = (categoria or '').strip() or CATEGORIA_POR_DEFECTO
            descripcion_mov = descripcion_final(datos, tipo_transaccion, categoria)

            # En el formulario de tickets "cuenta" es la cuenta protagonista del
            # movimiento: para un INGRESO es a la que ENTRA, para lo demás de la que SALE.
            cuenta_obj = TransactionService.resolver_cuenta(user, cuenta)
            if (cuenta_destino or '').strip() == SENTINELA_NUEVA_AHORRO:
                destino_obj = cuenta_ahorro_para(user, crear=True)
            else:
                destino_obj = TransactionService.resolver_cuenta(user, cuenta_destino)
            principal = (Cuenta.objects.filter(propietario=user).order_by('-es_principal', 'id').first())

            # Un ahorro nunca es gasto: es una transferencia a la cuenta de ahorro
            # (se crea "Cuenta Ahorro" si el usuario aún no tiene una).
            if tipo_transaccion in ('GASTO', 'TRANSFERENCIA') and categoria.lower() == 'ahorro':
                tipo_transaccion = 'TRANSFERENCIA'
                if destino_obj is None or destino_obj.tipo != 'AHORRO':
                    destino_obj = cuenta_ahorro_para(user, crear=True)

            if tipo_transaccion == 'INGRESO':
                origen, destino = None, (destino_obj or cuenta_obj or principal)
            elif tipo_transaccion == 'GASTO':
                origen, destino = (cuenta_obj or principal), None
            else:
                origen, destino = (cuenta_obj or principal), destino_obj

            registro_transacciones.objects.create(
                propietario=user,
                fecha=fecha_segura,
                descripcion=descripcion_mov,
                categoria=categoria,
                monto=monto_final,
                tipo=tipo_transaccion,
                origen=origen,
                destino=destino,
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
                precio_actual_ticker = None
                
                for inv in lista_inv:
                    if inv.fecha_compra <= fecha_iter:
                        cantidad_acumulada_ticker += inv.cantidad_titulos
                        costo_acumulado_ticker += inv.costo_total_adquisicion
                        precio_actual_ticker = inv.precio_actual_titulo
                
                if cantidad_acumulada_ticker > 0:
                    capital_invertido_dia += costo_acumulado_ticker
                    
                    if fecha_iter == hoy and precio_actual_ticker:
                        precio_cierre = precio_actual_ticker
                    else:
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
