"""Chiffrement des paquets de données au repos (S248 3a) : AES-256-GCM, clé hors dépôt.

Format : b"WP1" + nonce (12 o) + chiffré||étiquette. Le `contexte` (la clé d'objet S3) est lié au
chiffrement (AAD) : un blob copié sous une autre clé est refusé. Changer la clé rend illisibles
les paquets déjà stockés (la rétention de 14 jours borne l'exposition ; vider avant rotation)."""
import base64
import binascii
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAGIE = b"WP1"
TAILLE_NONCE = 12


class CleAbsente(Exception):
    """LIVRAISON_CHIFFREMENT_CLE absente ou invalide : on refuse, jamais de repli en clair."""


class Illisible(Exception):
    """Blob altéré, mauvaise clé, mauvais contexte ou format inconnu."""


def _cle() -> bytes:
    brut = os.getenv("LIVRAISON_CHIFFREMENT_CLE", "").strip()
    try:
        cle = base64.b64decode(brut, validate=True)
    except (binascii.Error, ValueError):
        raise CleAbsente("clé de chiffrement invalide") from None
    if len(cle) != 32:
        raise CleAbsente("clé de chiffrement absente ou de mauvaise taille")
    return cle


def chiffrer(clair: bytes, contexte: str) -> bytes:
    nonce = os.urandom(TAILLE_NONCE)
    return MAGIE + nonce + AESGCM(_cle()).encrypt(nonce, clair, contexte.encode("utf-8"))


def dechiffrer(blob: bytes, contexte: str) -> bytes:
    if not blob.startswith(MAGIE) or len(blob) < len(MAGIE) + TAILLE_NONCE + 16:
        raise Illisible("format")
    nonce = blob[len(MAGIE):len(MAGIE) + TAILLE_NONCE]
    try:
        return AESGCM(_cle()).decrypt(nonce, blob[len(MAGIE) + TAILLE_NONCE:],
                                      contexte.encode("utf-8"))
    except InvalidTag:
        raise Illisible("authentification") from None
