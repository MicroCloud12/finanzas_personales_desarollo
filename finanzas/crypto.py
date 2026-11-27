"""
Motor criptográfico de Nivel 2 (Envelope Encryption por usuario + Índices Ciegos HMAC-SHA256).

* Llave maestra (`DATA_ENCRYPTION_KEY`): vive únicamente en variables de entorno (.env), nunca en MySQL.
  Acepta varias llaves Fernet separadas por coma (`MultiFernet`) para rotación sin tiempo fuera.
* Llave por usuario (`LlaveUsuario`): cada usuario tiene su propia llave aleatoria (DEK) envuelta con
  la llave maestra. Así dos usuarios con el mismo monto o comercio producen textos cifrados y hashes
  completamente distintos.
* Formato en columna SQL: `enc:v1:<uid>:<token_fernet>`.
"""
import base64
import hashlib
import hmac
from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

ENC_PREFIX = "enc:v1:"

# Caché en memoria por proceso: {(fingerprint_maestra, uid): bytes_dek_fernet_urlsafe_b64}
_DEK_BYTES_CACHE: dict[tuple[str, int], bytes] = {}
_FERNET_CACHE: dict[tuple[str, int], Fernet] = {}


def _raw_master_keys() -> list[bytes]:
    raw = getattr(settings, "DATA_ENCRYPTION_KEY", "") or ""
    partes = [k.strip().encode("ascii") for k in raw.split(",") if k.strip()]
    if not partes:
        raise ImproperlyConfigured(
            "DATA_ENCRYPTION_KEY no está configurada. Genera una con: "
            "python manage.py generar_llave_cifrado"
        )
    return partes


def _master_fingerprint() -> str:
    partes = _raw_master_keys()
    return hashlib.sha256(b"|".join(partes)).hexdigest()[:16]


def get_master_fernet() -> MultiFernet:
    return MultiFernet([Fernet(k) for k in _raw_master_keys()])


def _system_dek_bytes() -> bytes:
    """DEK determinista derivada de la llave maestra primaria para filas sin usuario directo (uid=0)."""
    primaria = _raw_master_keys()[0]
    digest = hashlib.sha256(b"finanzas:system-dek:v1:" + primaria).digest()
    return base64.urlsafe_b64encode(digest)


def _global_hmac_key() -> bytes:
    """Llave HMAC determinista para índices únicos globales (ej. IDs de archivos de Google Drive)."""
    primaria = _raw_master_keys()[0]
    return hashlib.sha256(b"finanzas:global-blind-index:v1:" + primaria).digest()


def clear_key_cache(user_id: int | None = None) -> None:
    if user_id is None:
        _DEK_BYTES_CACHE.clear()
        _FERNET_CACHE.clear()
        return
    uid = int(user_id)
    for cache in (_DEK_BYTES_CACHE, _FERNET_CACHE):
        for k in [key for key in cache if key[1] == uid]:
            cache.pop(k, None)


def register_user_dek_in_cache(user_id: int, dek_b64: bytes) -> None:
    fp = _master_fingerprint()
    uid = int(user_id)
    _DEK_BYTES_CACHE[(fp, uid)] = dek_b64
    _FERNET_CACHE[(fp, uid)] = Fernet(dek_b64)


def ensure_user_dek_bytes(user_id: int | None, llave_model=None) -> bytes:
    """Devuelve la DEK (bytes base64 urlsafe para Fernet) del usuario; la crea en BD si no existe."""
    uid = int(user_id or 0)
    fp = _master_fingerprint()
    cached = _DEK_BYTES_CACHE.get((fp, uid))
    if cached is not None:
        return cached

    if uid == 0:
        dek_b64 = _system_dek_bytes()
        register_user_dek_in_cache(0, dek_b64)
        return dek_b64

    if llave_model is None:
        from django.apps import apps
        llave_model = apps.get_model("finanzas", "LlaveUsuario")

    master = get_master_fernet()
    registro = llave_model.objects.filter(usuario_id=uid).first()
    if registro is None:
        nueva_dek = Fernet.generate_key()
        dek_cifrada = master.encrypt(nueva_dek).decode("ascii")
        registro, created = llave_model.objects.get_or_create(
            usuario_id=uid,
            defaults={"dek_cifrada": dek_cifrada},
        )
        dek_b64 = nueva_dek if created else master.decrypt(registro.dek_cifrada.encode("ascii"))
    else:
        dek_b64 = master.decrypt(registro.dek_cifrada.encode("ascii"))

    register_user_dek_in_cache(uid, dek_b64)
    return dek_b64


def get_user_fernet(user_id: int | None, llave_model=None) -> Fernet:
    uid = int(user_id or 0)
    fp = _master_fingerprint()
    fernet = _FERNET_CACHE.get((fp, uid))
    if fernet is not None:
        return fernet
    ensure_user_dek_bytes(uid, llave_model=llave_model)
    return _FERNET_CACHE[(fp, uid)]


def is_encrypted(value) -> bool:
    return isinstance(value, str) and value.startswith(ENC_PREFIX)


def encrypt_str(plaintext: str, user_id: int | None, llave_model=None) -> str:
    if is_encrypted(plaintext):
        return plaintext
    uid = int(user_id or 0)
    fernet = get_user_fernet(uid, llave_model=llave_model)
    token = fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")
    return f"{ENC_PREFIX}{uid}:{token}"


def decrypt_str(value: str, llave_model=None) -> str:
    if not is_encrypted(value):
        return value
    try:
        _, _, uid_str, token = value.split(":", 3)
        uid = int(uid_str)
    except ValueError as exc:
        raise InvalidToken("Formato de texto cifrado inválido.") from exc
    fernet = get_user_fernet(uid, llave_model=llave_model)
    return fernet.decrypt(token.encode("ascii")).decode("utf-8")


def blind_index(user_id: int | None, value: str | None, llave_model=None) -> str:
    """HMAC-SHA256 por usuario sobre texto normalizado (trim + minúsculas) para búsquedas exactas y unique_together."""
    norm = (value or "").strip().lower().encode("utf-8")
    dek_raw = base64.urlsafe_b64decode(ensure_user_dek_bytes(user_id, llave_model=llave_model))
    return hmac.new(dek_raw, b"blind-index:v1:" + norm, hashlib.sha256).hexdigest()


def global_blind_index(value: str | None) -> str:
    """HMAC-SHA256 global sobre valor exacto (trim) para IDs externos únicos como archivo_drive_id."""
    if value is None or str(value).strip() == "":
        return ""
    norm = str(value).strip().encode("utf-8")
    return hmac.new(_global_hmac_key(), norm, hashlib.sha256).hexdigest()
