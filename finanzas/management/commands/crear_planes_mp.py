"""Crea en Mercado Pago los planes de suscripción de la app y muestra las líneas para el .env.

Uso en el servidor:
    docker compose exec web python manage.py crear_planes_mp --dominio prismavault.mx

Crea un "plan de suscripción" (preapproval_plan) por cada combinación plan/periodo de
finanzas/planes.py. Si ya existe uno activo con el mismo nombre, lo reutiliza en vez de duplicarlo.
Usa MERCADOPAGO_ACCESS_TOKEN del .env; con un token de pruebas (TEST-...) los planes quedan en el
modo de pruebas de Mercado Pago y no sirven para cobrar de verdad.
"""
import os

import mercadopago
from django.core.management.base import BaseCommand, CommandError

from finanzas import planes

VARIABLES = {
    ('personal', 'mensual'): 'MERCADOPAGO_PLAN_PERSONAL_MENSUAL',
    ('personal', 'anual'): 'MERCADOPAGO_PLAN_PERSONAL_ANUAL',
    ('pro', 'mensual'): 'MERCADOPAGO_PLAN_PRO_MENSUAL',
    ('pro', 'anual'): 'MERCADOPAGO_PLAN_PRO_ANUAL',
}
NOMBRE_APP = 'Prisma Vault'


def cuerpo_del_plan(plan: str, periodo: str, dominio: str) -> dict:
    datos = planes.PLANES[plan]
    return {
        "reason": f"{NOMBRE_APP} {datos['nombre']} ({periodo})",
        "auto_recurring": {
            "frequency": 1 if periodo == 'mensual' else 12,
            "frequency_type": "months",
            "transaction_amount": datos[periodo],
            "currency_id": "MXN",
        },
        "back_url": f"https://{dominio}/suscripcion/exitosa/",
        "status": "active",
    }


class Command(BaseCommand):
    help = 'Crea (o reutiliza) los planes de suscripción en Mercado Pago y muestra las líneas para el .env'

    def add_arguments(self, parser):
        parser.add_argument('--dominio', required=True, help='Dominio de la app, p. ej. prismavault.mx')
        parser.add_argument('--solo-mostrar', action='store_true', help='No crea nada: muestra lo que mandaría')

    def handle(self, *args, **opciones):
        dominio = opciones['dominio'].strip().rstrip('/')
        token = os.getenv('MERCADOPAGO_ACCESS_TOKEN')
        if not token:
            raise CommandError('Falta MERCADOPAGO_ACCESS_TOKEN en el .env')
        if token.startswith('TEST-'):
            self.stdout.write(self.style.WARNING(
                'Aviso: el token es de PRUEBAS (TEST-...). Los planes se crearán en el modo de pruebas de '
                'Mercado Pago; para cobrar de verdad hay que usar el token de producción (APP_USR-...).'))

        if opciones['solo_mostrar']:
            for (plan, periodo), variable in VARIABLES.items():
                c = cuerpo_del_plan(plan, periodo, dominio)
                self.stdout.write(f"{variable}: {c['reason']} · ${c['auto_recurring']['transaction_amount']} MXN "
                                  f"cada {c['auto_recurring']['frequency']} mes(es) · vuelve a {c['back_url']}")
            return

        sdk = mercadopago.SDK(token)
        existentes = {}
        try:
            r = sdk.plan().search({"status": "active"})
            if r.get('status') == 200:
                for p in r.get('response', {}).get('results', []) or []:
                    existentes[p.get('reason')] = p.get('id')
        except Exception as e:  # sin búsqueda se crean de todos modos
            self.stdout.write(self.style.WARNING(f'No pude consultar los planes existentes ({e}); se crearán nuevos.'))

        lineas = []
        for (plan, periodo), variable in VARIABLES.items():
            cuerpo = cuerpo_del_plan(plan, periodo, dominio)
            razon = cuerpo['reason']
            if razon in existentes:
                plan_id = existentes[razon]
                self.stdout.write(f"{razon}: ya existía ({plan_id})")
            else:
                r = sdk.plan().create(cuerpo)
                if r.get('status') not in (200, 201):
                    raise CommandError(f"Mercado Pago respondió {r.get('status')} al crear '{razon}': {r.get('response')}")
                plan_id = r['response']['id']
                self.stdout.write(self.style.SUCCESS(f"{razon}: creado ({plan_id})"))
            lineas.append(f"{variable}={plan_id}")

        self.stdout.write('\nCopia estas líneas en el .env del servidor y luego corre `docker compose up -d`:\n')
        for linea in lineas:
            self.stdout.write(linea)
        self.stdout.write(f"\nFalta el webhook (se configura en el panel de Mercado Pago, en tu aplicación → Webhooks):\n"
                          f"  URL: https://{dominio}/suscripcion/webhook/   Evento: Suscripciones (subscription_preapproval)")
