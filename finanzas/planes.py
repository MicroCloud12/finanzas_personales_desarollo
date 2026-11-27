"""Planes de la app y cuota mensual de documentos leídos con IA.

La métrica de valor es "documentos con IA al mes" (tickets, recibos, facturas, tablas de
amortización): es lo que el usuario siente como valor y lo único que cuesta de forma variable.
Todos los planes pueden usar la IA; cambia el tope. Facturar (CFDI) es solo del plan Pro.
"""
from django.db import transaction
from django.db.models import F
from django.utils import timezone

GRATIS, PERSONAL, PRO = 'gratis', 'personal', 'pro'

PLANES = {
    GRATIS:   {'nombre': 'Gratis',   'docs_mes': 10,  'mensual': 0,   'anual': 0,    'cfdi': False,
               'resumen': 'Libro mayor, CSV, presupuesto y reportes sin límite'},
    PERSONAL: {'nombre': 'Personal', 'docs_mes': 150, 'mensual': 99,  'anual': 948,  'cfdi': False,
               'resumen': 'Tickets, recibos y tablas de amortización leídos por IA'},
    PRO:      {'nombre': 'Pro',      'docs_mes': 600, 'mensual': 199, 'anual': 1908, 'cfdi': True,
               'resumen': 'Más documentos y facturación CFDI automática'},
}
PLANES_DE_PAGO = (PERSONAL, PRO)
PERIODOS = ('mensual', 'anual')
DIAS_POR_PERIODO = {'mensual': 31, 'anual': 366}


def plan_de(user) -> str:
    """Plan vigente: el de la suscripción si da acceso hoy; si no, Gratis."""
    suscripcion = getattr(user, 'suscripcion', None)
    if suscripcion is not None and suscripcion.is_active() and suscripcion.plan in PLANES_DE_PAGO:
        return suscripcion.plan
    return GRATIS


def tope_documentos(user) -> int:
    return PLANES[plan_de(user)]['docs_mes']


def documentos_usados(user, hoy=None) -> int:
    from .models import UsoIA
    hoy = hoy or timezone.localdate()
    uso = UsoIA.objects.filter(usuario=user, anio=hoy.year, mes=hoy.month).first()
    return uso.documentos if uso else 0


def documentos_restantes(user, hoy=None) -> int:
    return max(0, tope_documentos(user) - documentos_usados(user, hoy))


def registrar_documentos(user, n: int, hoy=None) -> None:
    """Suma ``n`` documentos al consumo del mes (se cuenta al mandarlos a la IA)."""
    from .models import UsoIA
    if n <= 0:
        return
    hoy = hoy or timezone.localdate()
    with transaction.atomic():
        uso, _ = UsoIA.objects.get_or_create(usuario=user, anio=hoy.year, mes=hoy.month)
        UsoIA.objects.filter(pk=uso.pk).update(documentos=F('documentos') + n)


def puede_procesar(user) -> bool:
    """¿Le quedan documentos con IA este mes?"""
    return documentos_restantes(user) > 0


def puede_facturar(user) -> bool:
    return PLANES[plan_de(user)]['cfdi']


def mensaje_sin_cuota(user) -> str:
    plan = plan_de(user)
    tope = PLANES[plan]['docs_mes']
    if plan == PRO:
        return f"Usaste los {tope} documentos con IA de este mes; el contador se reinicia el día 1."
    siguiente = PLANES[PERSONAL if plan == GRATIS else PRO]
    return (f"Usaste tus {tope} documentos con IA de este mes. Pasa al plan {siguiente['nombre']} "
            f"(${siguiente['mensual']} MXN/mes) para leer hasta {siguiente['docs_mes']} al mes.")


def resumen_cuota(user) -> dict:
    """Para mostrar 'X de Y documentos este mes · plan Z' en las pantallas de procesamiento."""
    plan = plan_de(user)
    usados = documentos_usados(user)
    tope = PLANES[plan]['docs_mes']
    return {'plan': plan, 'nombre_plan': PLANES[plan]['nombre'], 'usados': min(usados, tope),
            'tope': tope, 'restantes': max(0, tope - usados), 'agotado': usados >= tope}
