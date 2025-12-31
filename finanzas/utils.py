# finanzas/utils.py
from decimal import Decimal
from datetime import datetime, date
from collections import defaultdict
from dateutil.relativedelta import relativedelta
from .models import inversiones, Deuda, PagoAmortizacion
import time

def parse_date_safely(date_str: str | None) -> date:
    """
    Convierte y valida de forma segura una cadena de texto a un objeto de fecha.
    Si la fecha parseada es de hace más de un año, la considera inválida.
    Si falla, devuelve la fecha actual.
    """
    parsed_date = None
    
    if date_str and isinstance(date_str, str):
        formats_to_try = [
            "%Y-%m-%d",  # Formato ideal (ISO)
            "%d/%m/%Y",
            "%d-%m-%Y",
            "%Y/%m/%d",
            "%d/%m/%y",
        ]
        for fmt in formats_to_try:
            try:
                parsed_date = datetime.strptime(date_str, fmt).date()
                break  # Si tiene éxito, salimos del bucle
            except (ValueError, TypeError):
                continue

    # --- LÓGICA DE VALIDACIÓN MEJORADA ---
    if parsed_date:
        # Si la fecha extraída es de hace más de 365 días, es muy probable que
        # sea un error de la IA. Es más seguro usar la fecha actual.
        if (datetime.now().date() - parsed_date).days > 365:
            print(f"ADVERTENCIA: La fecha extraída '{parsed_date}' es muy antigua y fue descartada. Se usará la fecha actual.")
            return datetime.now().date()
        else:
            # La fecha es razonable y se devuelve
            return parsed_date

    # Fallback final si no se pudo parsear o la cadena era inválida
    if date_str:
        print(f"ADVERTENCIA: La cadena de fecha '{date_str}' no pudo ser procesada. Se usará la fecha actual.")
    return datetime.now().date()

def calculate_monthly_profit(user, price_service=None):
    from .services import StockPriceService
    """Calcula la ganancia mensual no realizada de las inversiones de un usuario."""
    servicio_precios = price_service or StockPriceService()
    #servicio_precios = StockPriceService()
    ganancias_mensuales = defaultdict(Decimal)
    
    # Obtenemos todas las inversiones del usuario de una vez
    inversiones_usuario = inversiones.objects.filter(propietario=user)
    
    if not inversiones_usuario:
        return {}

    # Obtenemos el mes y año actual para saber hasta dónde calcular
    hoy = datetime.now().date()
    
    # Creamos un diccionario para cachear los precios que ya consultamos y evitar llamadas duplicadas
    #cache_precios = {}

    inversiones_por_ticker = defaultdict(list)
    inicio_por_ticker = {}

    # Iteramos por cada una de las inversiones del usuario
    for inv in inversiones_usuario:

        inversiones_por_ticker[inv.emisora_ticker].append(inv)
        inicio = inv.fecha_compra.replace(day=1)

    
        if inv.emisora_ticker not in inicio_por_ticker or inicio < inicio_por_ticker[inv.emisora_ticker]:
            inicio_por_ticker[inv.emisora_ticker] = inicio
        # Consultamos la serie mensual solo una vez por ticker
    series_cache = {}
    for ticker, inicio in inicio_por_ticker.items():
        series = servicio_precios.get_monthly_series(ticker, inicio, hoy)
        series_cache[ticker] = {p["datetime"][:7]: Decimal(str(p["close"])) for p in series}
        # Esperamos 12 segundos entre llamadas para respetar el límite de 5 llamadas por minuto (aprox)
        # o el límite de 8 llamadas/minuto del que se queja el usuario.
        time.sleep(12)

    # Calculamos las ganancias iterando sobre cada inversión pero reutilizando el caché
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
    # Ordenamos por fecha para devolver un diccionario coherente
    return dict(sorted(ganancias_mensuales.items()))

def generar_tabla_amortizacion(deuda: Deuda):
    '''
    Calcula y guarda la tabla de amortización para un préstamo.
    Utiliza el sistema de amortización francés (cuotas fijas).
    '''
    # Solo se ejecuta para préstamos, no para tarjetas de crédito
    if deuda.tipo_deuda != 'PRESTAMO' or deuda.plazo_meses == 0:
        return

    # --- 1. Preparación de Variables ---
    tasa_interes_mensual = (deuda.tasa_interes / Decimal(100)) / Decimal(12)
    plazo = deuda.plazo_meses
    monto_prestamo = deuda.monto_total
    saldo_pendiente = monto_prestamo
    
    # --- 2. Cálculo de la Cuota Mensual Fija ---
    # Fórmula del sistema francés
    if tasa_interes_mensual > 0:
        factor = (tasa_interes_mensual * (1 + tasa_interes_mensual) ** plazo) / (((1 + tasa_interes_mensual) ** plazo) - 1)
        cuota_mensual = monto_prestamo * factor
    else:
        # Si no hay interés, la cuota es simplemente el total dividido por el plazo
        cuota_mensual = monto_prestamo / plazo

    # --- 3. Generación de cada Fila de la Tabla ---
    fecha_pago = deuda.fecha_adquisicion

    for i in range(1, plazo + 1):
        # Avanzamos la fecha al siguiente mes para cada cuota
        fecha_pago += relativedelta(months=1)
        
        intereses_cuota = saldo_pendiente * tasa_interes_mensual
        capital_cuota = cuota_mensual - intereses_cuota
        saldo_pendiente -= capital_cuota

        # El último pago puede tener un pequeño ajuste para que el saldo sea exactamente cero
        if i == plazo:
            capital_cuota += saldo_pendiente
            saldo_pendiente = Decimal(0)

        PagoAmortizacion.objects.create(
            deuda=deuda,
            numero_cuota=i,
            fecha_vencimiento=fecha_pago,
            capital=capital_cuota.quantize(Decimal('0.01')),
            interes=intereses_cuota.quantize(Decimal('0.01')),
            # Aquí asumimos un IVA del 16% sobre los intereses, como es común en México.
            # Podrías hacerlo un campo configurable en el futuro.
            iva=(intereses_cuota * Decimal('0.16')).quantize(Decimal('0.01')),
            saldo_insoluto=saldo_pendiente.quantize(Decimal('0.01'))
        )

def calculate_daily_portfolio_history(user, price_service=None):
    from .services import StockPriceService
    """
    Calcula el historial diario del valor del portafolio.
    Devuelve una lista de diccionarios con: fecha, valor_total, capital_invertido, ganancia_no_realizada.
    """
    servicio_precios = price_service or StockPriceService()
    
    inversiones_usuario = inversiones.objects.filter(propietario=user).order_by('fecha_compra')
    if not inversiones_usuario:
        return []

    # Fecha inicio: la primera compra
    fecha_inicio = inversiones_usuario.first().fecha_compra
    hoy = datetime.now().date()
    
    # Agrupamos inversiones por ticker
    inversiones_por_ticker = defaultdict(list)
    tickers = set()
    for inv in inversiones_usuario:
        inversiones_por_ticker[inv.emisora_ticker].append(inv)
        tickers.add(inv.emisora_ticker)

    # Obtenemos series de precios DIARIOS
    precios_diarios_cache = {}
    for ticker in tickers:
        # Obtenemos datos desde el inicio de la PRIMERA compra de este ticker
        inicio_ticker = inversiones_por_ticker[ticker][0].fecha_compra
        series = servicio_precios.get_daily_series(ticker, inicio_ticker, hoy)
        
        # Mapa: 'YYYY-MM-DD' -> Decimal(Precio)
        precios_diarios_cache[ticker] = {
            p["datetime"]: Decimal(str(p["close"])) for p in series
        }
        # Respetamos el límite de la API
        time.sleep(12)

    historial = []
    fecha_iter = fecha_inicio

    while fecha_iter <= hoy:
        valor_total_dia = Decimal('0.0')
        capital_invertido_dia = Decimal('0.0')

        # Para cada activo, vemos si ya lo teníamos comprado en esta fecha
        for ticker, lista_inv in inversiones_por_ticker.items():
            cantidad_acumulada_ticker = Decimal('0.0')
            costo_acumulado_ticker = Decimal('0.0')
            
            # Sumamos las 'sub-inversiones' (lotes) que ya existían en fecha_iter
            for inv in lista_inv:
                if inv.fecha_compra <= fecha_iter:
                    cantidad_acumulada_ticker += inv.cantidad_titulos
                    costo_acumulado_ticker += inv.costo_total_adquisicion
            
            if cantidad_acumulada_ticker > 0:
                capital_invertido_dia += costo_acumulado_ticker
                
                # Buscamos precio de cierre de este día
                fecha_str = fecha_iter.strftime("%Y-%m-%d")
                precio_cierre = precios_diarios_cache.get(ticker, {}).get(fecha_str)
                
                # Si no hay precio (fin de semana/festivo), buscamos el último disponible
                # (Lógica simplificada: si es None, usamos el último conocido o coste como fallback malo, 
                #  para hacerlo robusto deberíamos llenar huecos, pero por ahora esto sirve)
                if precio_cierre is None:
                    # Intento simple de backfill de 1 a 5 días
                    for i in range(1, 6):
                        d_back = fecha_iter - relativedelta(days=i)
                        p_back = precios_diarios_cache.get(ticker, {}).get(d_back.strftime("%Y-%m-%d"))
                        if p_back:
                            precio_cierre = p_back
                            break
                            
                if precio_cierre:
                     valor_total_dia += cantidad_acumulada_ticker * precio_cierre
                else:
                    # Fallback final: si no encontramos precio, asumimos que vale lo que costó
                    # para no quebrar la gráfica
                    valor_total_dia += costo_acumulado_ticker

        historial.append({
            'fecha': fecha_iter,
            'valor_total': valor_total_dia,
            'capital_invertido': capital_invertido_dia,
            'ganancia_no_realizada': valor_total_dia - capital_invertido_dia
        })
        
        fecha_iter += relativedelta(days=1)

    return historial
