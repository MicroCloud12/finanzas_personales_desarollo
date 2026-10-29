"""Filtros para mostrar dinero: $1,234.56 / −$1,234.56 / +$1,234.56."""
from decimal import Decimal, InvalidOperation

from django import template

register = template.Library()


def _dec(valor):
    try:
        return Decimal(str(valor))
    except (InvalidOperation, TypeError, ValueError):
        return None


@register.filter
def dinero(valor):
    """$1,234.56 con el signo antes del símbolo: −$1,234.56."""
    d = _dec(valor)
    if d is None:
        return '—'
    return f"{'−' if d < 0 else ''}${abs(d):,.2f}"


@register.filter
def dinero_signo(valor):
    """Igual que dinero pero siempre con signo: +$1,234.56 / −$1,234.56 / $0.00."""
    d = _dec(valor)
    if d is None:
        return '—'
    signo = '+' if d > 0 else ('−' if d < 0 else '')
    return f"{signo}${abs(d):,.2f}"


@register.filter
def pct_signo(valor, decimales=1):
    d = _dec(valor)
    if d is None:
        return '—'
    signo = '+' if d > 0 else ('−' if d < 0 else '')
    return f"{signo}{abs(d):.{int(decimales)}f}%"
