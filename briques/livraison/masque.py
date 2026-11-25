"""Masquage des secrets dans les logs (copie autonome des regex de core/outils.py, durcie S246).

Ordre : du plus spécifique au plus général. Le masquage s'applique au texte COMPLET ; la
troncature éventuelle vient APRÈS (sinon un jeton coupé en deux laisse un fragment lisible).
"""
import re

_MOTS = r"(?:pass|pwd|secret|token|key|auth)"
_RE_URL_IDENTIFIANTS = re.compile(r"(\w[\w+.\-]*://[^\s:/@]+:)[^\s@/]+(@)")
_RE_QUERY_SECRET = re.compile(
    r"([?&](?:token|key|password|passwd|pwd|secret|sig|signature|auth|apikey|api_key|"
    r"access_token)=)[^&\s#'\"]+", re.IGNORECASE)
_RE_BEARER = re.compile(r"(\bBearer\s+)[^\s'\",;]+", re.IGNORECASE)
_RE_BASIC = re.compile(r"(\bBasic\s+)\S+")
# JSON : "password": "…" (le nom est conservé, la valeur masquée)
_RE_JSON_SECRET = re.compile(r'("[^"]*' + _MOTS + r'[^"]*"\s*:\s*")[^"]*(")', re.IGNORECASE)
# NOM=valeur / NOM: valeur (DB_PASSWORD=…, x-api-key: …, export GITHUB_TOKEN=…)
_RE_CLE_VALEUR = re.compile(r"(\b[\w-]*" + _MOTS + r"[\w-]*\s*[=:]\s*)\S+", re.IGNORECASE)
_RE_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_RE_JETON_OPAQUE = re.compile(r"[A-Za-z0-9+/=_-]{20,}")
_RE_SEGMENT_LONG = re.compile(r"[A-Za-z0-9_-]{20,}")


def _segment_aleatoire(seg: str) -> bool:
    """Majuscule + minuscule + chiffre mêlés : allure de jeton, pas de nom de dossier."""
    return (len(seg) >= 8 and any(ch.isupper() for ch in seg)
            and any(ch.islower() for ch in seg) and any(ch.isdigit() for ch in seg))


def _jeton(m: re.Match) -> str:
    """Un candidat qui a l'allure d'un CHEMIN (`/usr/local/lib/python3`) reste lisible :
    il contient `/`, ni `+` ni `=` (marqueurs base64), et chaque segment est court et
    non aléatoire. Sinon (jeton, base64…) il est masqué en entier."""
    t = m.group(0)
    if "/" in t and "+" not in t and "=" not in t:
        segments = t.split("/")
        if not any(_segment_aleatoire(s) for s in segments):
            return "/".join(_RE_SEGMENT_LONG.sub("***", s) for s in segments)
    return "***"


def masquer(texte: str) -> str:
    texte = _RE_URL_IDENTIFIANTS.sub(r"\1***\2", texte)
    texte = _RE_QUERY_SECRET.sub(r"\1***", texte)
    texte = _RE_BEARER.sub(r"\1***", texte)
    texte = _RE_BASIC.sub(r"\1***", texte)
    texte = _RE_JSON_SECRET.sub(r"\1***\2", texte)
    texte = _RE_CLE_VALEUR.sub(r"\1***", texte)
    texte = _RE_EMAIL.sub("***", texte)
    return _RE_JETON_OPAQUE.sub(_jeton, texte)
