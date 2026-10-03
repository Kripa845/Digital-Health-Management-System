"""Checks on the uploaded file itself: real content type, hash and a safe display name."""
import hashlib
import re

from django.conf import settings

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
ALLOWED_TYPES = {'.pdf': 'application/pdf', '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg'}
_SIGNATURES = (
    (b'%PDF-', 'application/pdf'),
    (b'\x89PNG\r\n\x1a\n', 'image/png'),
    (b'\xff\xd8\xff', 'image/jpeg'),
)


def detect_type(raw: bytes) -> str | None:
    """MIME type from the file's content, not its name.

    Uses python-magic when LAB_USE_LIBMAGIC is on (it needs the libmagic system
    library; on Windows without it, importing python-magic hangs). Otherwise the
    file signature is checked directly, which covers the three accepted types.
    """
    if getattr(settings, 'LAB_USE_LIBMAGIC', False):
        import magic  # imported only when enabled
        return magic.from_buffer(raw[:4096], mime=True)
    for signature, mime in _SIGNATURES:
        if raw.startswith(signature):
            return mime
    return None


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def safe_display_name(name: str, fallback: str = 'Lab report') -> str:
    """A report name safe to store and show: no path, control or reserved characters."""
    base = re.split(r'[\\/]', name or '')[-1]
    base = re.sub(r'[\x00-\x1f\x7f<>:"|?*]', '', base)
    base = re.sub(r'\s+', ' ', base).strip(' .')
    return base[:255] or fallback
