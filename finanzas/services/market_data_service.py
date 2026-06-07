# finanzas/services/market_data_service.py
import os
import requests
from decimal import Decimal
from twelvedata import TDClient
from cachetools import TTLCache
import logging

logger = logging.getLogger(__name__)

class StockPriceService:
    """Service to fetch stock prices using TwelveData with caching mechanisms."""
    
    _price_cache = TTLCache(maxsize=100, ttl=300)   # 5 mins
    _series_cache = TTLCache(maxsize=50, ttl=86400) # 1 day

    def __init__(self):
        self.api_key = os.getenv("TWELVEDATA_API_KEY")
        if not self.api_key:
            logger.warning("TWELVEDATA_API_KEY missing.")
        self.client = TDClient(apikey=self.api_key) if self.api_key else None

    def get_current_price(self, ticker: str):
        if not self.client or not ticker: return None
        
        cache_key = ticker.upper()
        if cache_key in self._price_cache:
            return self._price_cache[cache_key]
        
        try:
            quote = self.client.quote(symbol=ticker)
            data = quote.as_json()
            if isinstance(data, list):
                data = data[0] if data else {}
                
            current_price = data.get("close") or data.get("price")
            if current_price is not None:
                price = Decimal(str(current_price))
                self._price_cache[cache_key] = price
                return price
            return None
        except Exception as e:
            logger.error(f"TwelveData API error for {ticker}: {e}")
            return None
        
    def _get_time_series(self, ticker: str, start_date, end_date, interval: str):
        if not self.client or not ticker: return []
        
        start_str = start_date.strftime("%Y-%m-%d")
        end_str = end_date.strftime("%Y-%m-%d")
        cache_key = f"{interval}:{ticker.upper()}:{start_str}:{end_str}"
        
        if cache_key in self._series_cache:
            return self._series_cache[cache_key]
            
        try:
            series = self.client.time_series(
                symbol=ticker,
                interval=interval,
                start_date=start_str,
                end_date=end_str,
            )
            raw = series.as_json()
            values = raw.get("values") if isinstance(raw, dict) else list(raw)
            values = values or []
            self._series_cache[cache_key] = values
            return values
        except Exception as e:
            logger.error(f"TwelveData TimeSeries error for {ticker}: {e}")
            return []

    def get_monthly_series(self, ticker: str, start_date, end_date):
        return self._get_time_series(ticker, start_date, end_date, "1month")

    def get_daily_series(self, ticker: str, start_date, end_date):
        return self._get_time_series(ticker, start_date, end_date, "1day")

    def get_closing_price_for_date(self, ticker: str, target_date):
        month_start = target_date.replace(day=1)
        series = self.get_monthly_series(ticker, month_start, target_date)
        return float(series[0]["close"]) if series else None


class ExchangeRateService:
    """Service to fetch USD/MXN historical exchange rates."""
    
    def get_usd_mxn_rate(self, date_obj):
        token = os.getenv("CURRENCYAPI_API_KEY")
        if not token:
            logger.warning("CURRENCYAPI_API_KEY missing.")
            return None
            
        url = f"https://api.currencyapi.com/v3/historical?apikey={token}&currencies=MXN&base_currency=USD&date={date_obj}"
        try:
            response = requests.get(url, timeout=5) # Added timeout
            response.raise_for_status()
            rate = response.json().get('data', {}).get('MXN', {}).get('value')
            return Decimal(str(rate)) if rate is not None else None
        except Exception as e:
            logger.error(f"Exchange Rate error: {e}")
            return None
