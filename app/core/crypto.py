"""Maydonlarni shifrlash (Fernet / MultiFernet).

Kalit konteyner tashqarisida (env/secret) saqlanadi: FIELD_ENCRYPTION_KEYS.
Birinchi kalit bilan shifrlanadi, qolganlari faqat eski yozuvlarni ochish uchun.
"""
from functools import lru_cache

import numpy as np
from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

EMBEDDING_DIM = 128


@lru_cache(maxsize=1)
def _fernet() -> MultiFernet:
    keys = settings.FIELD_ENCRYPTION_KEYS
    if not keys:
        raise ImproperlyConfigured("FIELD_ENCRYPTION_KEYS berilmagan (shifrlash kaliti)")
    return MultiFernet([Fernet(k.encode() if isinstance(k, str) else k) for k in keys])


def reset_cache():
    _fernet.cache_clear()


def encrypt_bytes(data: bytes) -> bytes:
    return _fernet().encrypt(data)


def decrypt_bytes(token: bytes) -> bytes:
    return _fernet().decrypt(bytes(token))


def encrypt_str(value: str) -> str:
    return encrypt_bytes(value.encode("utf-8")).decode("ascii")


def decrypt_str(token: str) -> str:
    if not token:
        return ""
    return decrypt_bytes(token.encode("ascii")).decode("utf-8")


def encrypt_embedding(vec: np.ndarray) -> bytes:
    arr = np.asarray(vec, dtype="<f4").reshape(-1)
    if arr.shape[0] != EMBEDDING_DIM:
        raise ValueError("andoza o'lchami noto'g'ri")
    return encrypt_bytes(arr.tobytes())


def decrypt_embedding(token: bytes) -> np.ndarray:
    raw = decrypt_bytes(token)
    return np.frombuffer(raw, dtype="<f4").astype(np.float32)


def rotate(token: bytes) -> bytes:
    """Eski kalit bilan shifrlangan tokenni joriy kalitga o'tkazadi."""
    return _fernet().rotate(bytes(token))


__all__ = [
    "InvalidToken",
    "encrypt_bytes",
    "decrypt_bytes",
    "encrypt_str",
    "decrypt_str",
    "encrypt_embedding",
    "decrypt_embedding",
    "rotate",
    "reset_cache",
]
