"""Masquage des secrets dans les logs (copie autonome des regex de core/outils.py)."""
import re

_RE_URL_IDENTIFIANTS = re.compile(r"(\w[\w+.\-]*://[^\s:/@]+:)[^\s@/]+(@)")
_RE_JETON_OPAQUE = re.compile(r"[A-Za-z0-9_\-]{32,}")
_RE_QUERY_SECRET = re.compile(
    r"([?&](?:token|key|password|passwd|pwd|secret|sig|signature|auth|apikey|api_key|"
    r"access_token)=)[^&\s#'\"]+", re.IGNORECASE)
_RE_BEARER = re.compile(r"(\bBearer\s+)[^\s'\",;]+", re.IGNORECASE)
_RE_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def masquer(texte: str) -> str:
    texte = _RE_URL_IDENTIFIANTS.sub(r"\1***\2", texte)
    texte = _RE_QUERY_SECRET.sub(r"\1***", texte)
    texte = _RE_BEARER.sub(r"\1***", texte)
    texte = _RE_EMAIL.sub("***", texte)
    return _RE_JETON_OPAQUE.sub("***", texte)
