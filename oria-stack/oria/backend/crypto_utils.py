"""
Chiffrement Fernet (AES-128-CBC + HMAC-SHA256) pour les clés API LLM stockées en DB.
Si LLM_ENCRYPTION_KEY est absent, les valeurs sont stockées en clair (rétrocompat).
Génération de la clé : python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""
import os
from cryptography.fernet import Fernet, InvalidToken

_raw_key = os.getenv("LLM_ENCRYPTION_KEY", "")
_fernet: Fernet | None = None

if _raw_key:
    try:
        _fernet = Fernet(_raw_key.encode())
    except Exception:
        pass  # Clé invalide → dégradation gracieuse


def encrypt_api_key(value: str) -> str:
    """Chiffre value si la clé est configurée, sinon retourne value tel quel."""
    if not _fernet or not value:
        return value
    return _fernet.encrypt(value.encode()).decode()


def decrypt_api_key(value: str) -> str:
    """Déchiffre value. Si InvalidToken (valeur non chiffrée / migration), retourne value tel quel."""
    if not _fernet or not value:
        return value
    try:
        return _fernet.decrypt(value.encode()).decode()
    except (InvalidToken, Exception):
        return value
