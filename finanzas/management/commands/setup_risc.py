import os
import json
import time
import jwt
import requests
from django.core.management.base import BaseCommand, CommandError
from django.conf import settings

# --- ¡IMPORTANTE! ---
# Coloca la ruta a tu archivo de credenciales JSON aquí.
# Puede ser una ruta absoluta o relativa a la raíz de tu proyecto.
CREDENTIALS_FILE_PATH = '/opt/app/mis-finanzas-personales.json'

class Command(BaseCommand):
    help = 'Registra y prueba el endpoint del webhook de Google RISC.'

    def _validate_credentials(self, credentials):
        """Verifica que las claves necesarias estén en el archivo de credenciales."""
        required_keys = ['client_email', 'private_key_id', 'private_key']
        missing_keys = [key for key in required_keys if key not in credentials]
        if missing_keys:
            raise CommandError(
                f"El archivo de credenciales es inválido o no es un archivo de Cuenta de Servicio. "
                f"Faltan las siguientes claves: {', '.join(missing_keys)}"
            )

    def _make_bearer_token(self):
        """Genera un token de autorización a partir del archivo de credenciales."""
        self.stdout.write("🔑 Generando token de autorización...")
        try:
            with open(CREDENTIALS_FILE_PATH) as f:
                service_account = json.load(f)
        except FileNotFoundError:
            raise CommandError(f"Error: No se encontró el archivo de credenciales en '{CREDENTIALS_FILE_PATH}'. "
                               "Por favor, actualiza la ruta en este script.")

        self._validate_credentials(service_account) # Nueva validación

        payload = {
            'iss': service_account['client_email'],
            'sub': service_account['client_email'],
            'aud': 'https://risc.googleapis.com/google.identity.risc.v1beta.RiscManagementService',
            'iat': int(time.time()),
            'exp': int(time.time()) + 3600,
        }

        token = jwt.encode(payload, service_account['private_key'], algorithm='RS256', 
                           headers={'kid': service_account['private_key_id']})
        self.stdout.write(self.style.SUCCESS("   Token generado con éxito."))
        return token

    def handle(self, *args, **kwargs):
        auth_token = self._make_bearer_token()

        # --- 1. REGISTRAR EL ENDPOINT ---
        self.stdout.write("\n📡 Registrando el endpoint del webhook con Google...")

        # ¡IMPORTANTE! Cambia esta URL por la URL real de tu servidor en producción
        # Para pruebas locales, puedes usar un servicio como ngrok para exponer tu localhost.
        receiver_endpoint = "https://www.prismavault.mx/risc-webhook/"

        events_requested = [
            "https://schemas.openid.net/secevent/risc/event-type/account-disabled",
            "https://schemas.openid.net/secevent/risc/event-type/sessions-revoked",
            "https://schemas.openid.net/secevent/risc/event-type/verification" # ¡Importante para la prueba!
        ]

        stream_cfg = {
            'delivery': {
                'delivery_method': 'https://schemas.openid.net/secevent/risc/delivery-method/push',
                'url': receiver_endpoint
            },
            'events_requested': events_requested
        }

        try:
            response = requests.post(
                'https://risc.googleapis.com/v1beta/stream:update',
                json=stream_cfg,
                headers={'Authorization': f'Bearer {auth_token}'}
            )
            response.raise_for_status()
            self.stdout.write(self.style.SUCCESS(f"   Endpoint '{receiver_endpoint}' registrado correctamente."))
        except requests.exceptions.HTTPError as e:
            raise CommandError(f"Error al registrar el endpoint: {e.response.text}")

        # --- 2. PROBAR EL ENDPOINT ---
        self.stdout.write("\n🚀 Solicitando un token de prueba a Google...")
        try:
            test_message = f"Verificación de Finanzas Personales a las {time.ctime()}"
            response = requests.post(
                'https://risc.googleapis.com/v1beta/stream:verify',
                json={'state': test_message},
                headers={'Authorization': f'Bearer {auth_token}'}
            )
            response.raise_for_status()
            self.stdout.write(self.style.SUCCESS("   ¡Solicitud de prueba enviada!"))
            self.stdout.write(self.style.WARNING("   Revisa los logs de tu servidor para confirmar la recepción del token."))
        except requests.exceptions.HTTPError as e:
            raise CommandError(f"Error al solicitar la prueba: {e.response.text}")

        self.stdout.write(self.style.SUCCESS("\n✅ ¡Proceso completado!"))