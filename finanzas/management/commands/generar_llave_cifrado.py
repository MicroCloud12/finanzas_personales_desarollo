"""
Genera una llave maestra Fernet para `DATA_ENCRYPTION_KEY` o rota la llave maestra existente
re-envolviendo todas las llaves por usuario (`LlaveUsuario`) sin re-escribir las tablas de datos.

Uso:
    python manage.py generar_llave_cifrado
    python manage.py generar_llave_cifrado --rotar
"""
from cryptography.fernet import Fernet
from django.core.management.base import BaseCommand
from django.db import transaction

from finanzas.crypto import clear_key_cache, get_master_fernet
from finanzas.models import LlaveUsuario


class Command(BaseCommand):
    help = "Genera una nueva llave DATA_ENCRYPTION_KEY o re-envuelve las llaves de usuario tras rotarla."

    def add_arguments(self, parser):
        parser.add_argument(
            "--rotar",
            action="store_true",
            help="Re-encripta todas las LlaveUsuario usando la primera llave de DATA_ENCRYPTION_KEY "
                 "(después de poner DATA_ENCRYPTION_KEY=LLAVE_NUEVA,LLAVE_ANTERIOR en .env).",
        )

    def handle(self, *args, **opts):
        if opts["rotar"]:
            master = get_master_fernet()
            actualizadas = 0
            with transaction.atomic():
                for ll in LlaveUsuario.objects.select_for_update():
                    ll.dek_cifrada = master.rotate(ll.dek_cifrada.encode("ascii")).decode("ascii")
                    ll.save(update_fields=["dek_cifrada"])
                    actualizadas += 1
            clear_key_cache()
            self.stdout.write(self.style.SUCCESS(
                f"Rotación completada: {actualizadas} llaves de usuario re-envueltas con la nueva llave primaria. "
                "Ya puedes retirar la llave anterior de DATA_ENCRYPTION_KEY."
            ))
            return

        nueva = Fernet.generate_key().decode("ascii")
        self.stdout.write(self.style.SUCCESS("Agrega esta línea a tu archivo .env (y guárdala en tu gestor de contraseñas):"))
        self.stdout.write(f"\nDATA_ENCRYPTION_KEY={nueva}\n")
