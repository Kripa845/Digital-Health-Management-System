"""Encryption at rest for uploaded lab report files.

Files are encrypted with Fernet (AES-128-CBC + HMAC-SHA256) before they reach
storage, so a copied media folder or leaked storage bucket does not expose
reports. The key comes from LAB_REPORT_ENCRYPTION_KEY; without it a key is
derived from SECRET_KEY, so changing SECRET_KEY makes existing files unreadable.
"""
import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings


def _fernet() -> Fernet:
    key = getattr(settings, 'LAB_REPORT_ENCRYPTION_KEY', '') or ''
    if not key:
        digest = hashlib.sha256(f'lab-reports:{settings.SECRET_KEY}'.encode()).digest()
        key = base64.urlsafe_b64encode(digest).decode()
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt(data: bytes) -> bytes:
    return _fernet().encrypt(data)


def decrypt(token: bytes) -> bytes:
    try:
        return _fernet().decrypt(token)
    except InvalidToken as exc:
        raise RuntimeError(
            'The stored report could not be decrypted. The encryption key may have changed.'
        ) from exc
