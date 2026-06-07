# finanzas/utils.py
from datetime import datetime, date
import logging

logger = logging.getLogger(__name__)

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
                break
            except (ValueError, TypeError):
                continue

    if parsed_date:
        # Validación: si la fecha extraída es muy antigua (> 1 año), usar la actual
        if (datetime.now().date() - parsed_date).days > 365:
            logger.warning(f"La fecha extraída '{parsed_date}' es muy antigua y fue descartada. Se usará la fecha actual.")
            return datetime.now().date()
        else:
            return parsed_date

    # Fallback final si no se pudo parsear
    if date_str:
        logger.warning(f"La cadena de fecha '{date_str}' no pudo ser procesada. Se usará la fecha actual.")
    return datetime.now().date()
