# finanzas/utils.py
from datetime import datetime, date
import logging
from dateutil.parser import parse as dateutil_parse, ParserError

logger = logging.getLogger(__name__)

def parse_date_safely(date_str: str | None) -> date:
    if not date_str or not isinstance(date_str, str):
        return datetime.now().date()
    try:
        parsed_date = dateutil_parse(date_str, dayfirst=True).date()
    except (ParserError, ValueError, OverflowError):
        logger.warning(f"La cadena de fecha '{date_str}' no pudo ser procesada. Se usará la fecha actual.")
        return datetime.now().date()
    if (datetime.now().date() - parsed_date).days > 365:
        logger.warning(f"La fecha extraída '{parsed_date}' es muy antigua y fue descartada. Se usará la fecha actual.")
        return datetime.now().date()
    return parsed_date
