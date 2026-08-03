"""Identité locale de `jeu-factions-public` (comptes email + mot de passe) — AUCUN secret
partagé avec le Cœur, contrairement à briques/jeu-factions/jeton.py (S217) : cette brique
émet et vérifie elle-même son jeton de session. Hachage de mot de passe (passlib+bcrypt,
mêmes versions que oria-stack/oria/backend/requirements.txt) + jeton HMAC (même mécanique
que jeu-factions, émission locale)."""
import hashlib
import hmac
import os
import time
from typing import Optional

from passlib.hash import bcrypt

COOKIE_NOM = "jeu_factions_public_utilisateur"
TTL_SESSION = 30 * 24 * 3600  # 30 jours — décision de cadrage produit public (spec § Identité)


def _secret() -> bytes:
    return (os.environ.get("JEU_FACTIONS_PUBLIC_SECRET") or "").encode()


def hacher_mot_de_passe(mot_de_passe: str) -> str:
    return bcrypt.hash(mot_de_passe)


def verifier_mot_de_passe(mot_de_passe: str, hash_: str) -> bool:
    try:
        return bcrypt.verify(mot_de_passe, hash_)
    except (ValueError, TypeError):
        return False


def emettre(compte_id: str, ttl: int = TTL_SESSION) -> str:
    expire = int(time.time()) + ttl
    message = f"{compte_id}:{expire}"
    signature = hmac.new(_secret(), message.encode(), hashlib.sha256).hexdigest()
    return f"{message}:{signature}"


def verifier(jeton: Optional[str]) -> Optional[str]:
    if not jeton or not _secret():
        return None
    try:
        compte_id, expire, signature = jeton.rsplit(":", 2)
        expire_i = int(expire)
    except ValueError:
        return None
    message = f"{compte_id}:{expire}"
    attendue = hmac.new(_secret(), message.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, attendue) or time.time() > expire_i:
        return None
    return compte_id


def emettre_reinitialisation(compte_id: str, ttl: int = 900) -> str:
    expire = int(time.time()) + ttl
    message = f"reset:{compte_id}:{expire}"
    signature = hmac.new(_secret(), message.encode(), hashlib.sha256).hexdigest()
    return f"{message}:{signature}"


def verifier_reinitialisation(jeton: Optional[str]) -> Optional[str]:
    if not jeton or not _secret():
        return None
    try:
        message, signature = jeton.rsplit(":", 1)
        prefixe, compte_id, expire = message.split(":", 2)
        expire_i = int(expire)
    except ValueError:
        return None
    if prefixe != "reset":
        return None
    attendue = hmac.new(_secret(), message.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, attendue) or time.time() > expire_i:
        return None
    return compte_id
