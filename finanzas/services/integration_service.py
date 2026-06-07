# finanzas/services/integration_service.py
import os
import requests
import jwt
from io import BytesIO
import logging
from jwt import PyJWKClient
import mercadopago
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.oauth2.credentials import Credentials
from allauth.socialaccount.models import SocialApp, SocialToken, SocialAccount
from django.contrib.sessions.models import Session
from ..models import User

logger = logging.getLogger(__name__)

class GoogleDriveService:
    """Service to interact with Google Drive API."""
    def __init__(self, user: User):
        try:
            app = SocialApp.objects.get(provider='google')
            google_token = SocialToken.objects.get(account__user=user, account__provider='google')
            creds = Credentials(
                token=google_token.token,
                refresh_token=google_token.token_secret,
                token_uri='https://oauth2.googleapis.com/token',
                client_id=app.client_id,
                client_secret=app.secret
            )
            self.service = build('drive', 'v3', credentials=creds)
        except (SocialToken.DoesNotExist, SocialApp.DoesNotExist) as e:
            raise ConnectionError("Google account link or Social App config missing.") from e

    def _get_folder_id(self, folder_name: str) -> str | None:
        try:
            query = f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
            response = self.service.files().list(q=query, spaces='drive', fields='files(id)').execute()
            return response.get('files', [])[0]['id'] if response.get('files') else None
        except HttpError as error:
            logger.error(f"Google Drive folder search error for '{folder_name}': {error}")
            return None

    def list_files_in_folder(self, folder_name: str, mimetypes: list[str]) -> list[dict]:
        folder_id = self._get_folder_id(folder_name)
        if not folder_id: return []
        
        mime_query = " or ".join([f"mimeType='{m}'" for m in mimetypes])
        query = f"'{folder_id}' in parents and ({mime_query}) and trashed=false"
        
        try:
            results = self.service.files().list(q=query, fields="files(id, name, mimeType)").execute()
            return results.get('files', [])
        except HttpError as error:
            logger.error(f"Google Drive list files error: {error}")
            return []

    def get_file_content(self, file_id: str) -> BytesIO:
        request = self.service.files().get_media(fileId=file_id)
        return BytesIO(request.execute())


class MercadoPagoService:
    """Service for Mercado Pago business logic."""
    def __init__(self):
        self.sdk = mercadopago.SDK(os.getenv('MERCADOPAGO_ACCESS_TOKEN'))
        self.plan_id = os.getenv('MERCADOPAGO_PLAN_ID')
        if not self.sdk or not self.plan_id:
            logger.warning("Mercado Pago credentials/Plan ID missing in .env")
    
    def crear_link_suscripcion(self, user, back_url: str):
        base_url = "https://www.mercadopago.com.mx/subscriptions/checkout"
        return f"{base_url}?preapproval_plan_id={self.plan_id}"


class RISCService:
    """Service to handle Google RISC security events."""
    GOOGLE_RISC_CONFIG_URL = "https://accounts.google.com/.well-known/risc-configuration"
    _jwk_client = None

    def __init__(self):
        self.audience = os.getenv("GOOGLE_CLIENT_ID")
        if not self.audience:
            logger.warning("GOOGLE_CLIENT_ID missing in .env")

    def _get_jwk_client(self):
        if self._jwk_client is None:
            config = requests.get(self.GOOGLE_RISC_CONFIG_URL, timeout=5).json()
            self._jwk_client = PyJWKClient(config.get("jwks_uri"))
        return self._jwk_client

    def validate_token(self, token: str) -> dict:
        jwk_client = self._get_jwk_client()
        try:
            signing_key = jwk_client.get_signing_key_from_jwt(token)
            payload = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                audience=self.audience,
                issuer="https://accounts.google.com",
            )
            
            for event_type, event_data in payload.get('events', {}).items():
                if event_type == "https://schemas.openid.net/secevent/risc/event-type/verification":
                    logger.info(f"✅ RISC Verification Event. State: {event_data.get('state')}")
            return payload
        except jwt.exceptions.PyJWKClientError as e:
            raise ValueError(f"Signing key error: {e}")
        except jwt.PyJWTError as e:
            raise ValueError(f"Invalid Token: {e}")
    
    def process_security_event(self, payload: dict):
        for event_type, event_details in payload.get("events", {}).items():
            user_google_id = event_details.get("subject", {}).get("sub")
            if not user_google_id: continue

            try:
                user = SocialAccount.objects.get(provider='google', uid=user_google_id).user
                
                if event_type == "https://schemas.openid.net/secevent/risc/event-type/account-disabled":
                    user.is_active = False
                    user.save()
                    Session.objects.filter(session_key__in=user.session_set.values_list('session_key', flat=True)).delete()
                    logger.warning(f"User {user.username} deactivated (Google account disabled via RISC).")

                elif event_type == "https://schemas.openid.net/secevent/risc/event-type/sessions-revoked":
                    Session.objects.filter(session_key__in=user.session_set.values_list('session_key', flat=True)).delete()
                    logger.warning(f"User {user.username} sessions revoked via RISC.")
            except SocialAccount.DoesNotExist:
                logger.warning(f"RISC event for unknown Google ID {user_google_id}.")
