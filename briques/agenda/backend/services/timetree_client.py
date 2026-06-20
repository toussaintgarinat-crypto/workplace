"""Client TimeTree NON OFFICIEL — la seule partie fragile du pont.

TimeTree a fermé son API publique le 22/12/2023. On lit l'agenda partagé via son API
WEB INTERNE rétro-conçue, telle qu'exposée par la bibliothèque communautaire
`timetree-exporter` (login email/mot de passe → cookie de session, puis lecture seule
des événements).

⚠️ NON OFFICIEL : peut casser sans préavis. Tout l'aléa (réseau, login, format) est
CONFINÉ dans ce module, derrière une interface stable (`list_calendars`, `fetch_events`)
consommée par `services/timetree_calendar.py`. Si TimeTree change, on ne remplace QUE ce
fichier. On ne fait que LIRE — jamais d'écriture vers TimeTree.

Les appels sous-jacents sont synchrones (`requests`) : les appelants async les lancent
dans un thread (`asyncio.to_thread`) pour ne pas bloquer la boucle.
"""

from __future__ import annotations

import logging

from timetree_exporter.api.auth import (
    AuthenticationError,
    InvalidCredentialsError,
    RateLimitAuthenticationError,
)
from timetree_exporter.api.auth import login as _login
from timetree_exporter.api.calendar import TimeTreeCalendar

logger = logging.getLogger(__name__)


class TimeTreeError(RuntimeError):
    """Échec d'un appel TimeTree (réseau, format, indisponibilité)."""


class TimeTreeAuthError(TimeTreeError):
    """Identifiants refusés ou session non obtenue."""


def _session(email: str, password: str) -> str:
    """Login → identifiant de session. Traduit les erreurs en messages clairs (FR)."""
    try:
        sid = _login(email, password)
    except InvalidCredentialsError as exc:
        raise TimeTreeAuthError("Email ou mot de passe TimeTree invalide") from exc
    except RateLimitAuthenticationError as exc:
        raise TimeTreeAuthError("TimeTree limite les tentatives — réessaie plus tard") from exc
    except AuthenticationError as exc:
        raise TimeTreeAuthError("Connexion TimeTree refusée") from exc
    except Exception as exc:  # noqa: BLE001 — réseau / format inattendu de l'API non officielle
        raise TimeTreeError(f"Connexion TimeTree échouée : {exc}") from exc
    if not sid:
        raise TimeTreeAuthError("TimeTree n'a pas renvoyé de session")
    return sid


def list_calendars(email: str, password: str) -> list[dict]:
    """Calendriers accessibles : [{'id', 'name'}]. Sert à choisir le calendrier partagé."""
    sid = _session(email, password)
    try:
        cals = TimeTreeCalendar(sid, capture_raw_responses=False).get_metadata()
    except Exception as exc:  # noqa: BLE001
        raise TimeTreeError(f"Lecture des calendriers TimeTree échouée : {exc}") from exc
    return [{"id": str(c.get("id")), "name": c.get("name") or "(sans nom)"} for c in cals]


def fetch(email: str, password: str, calendar_id: str) -> dict:
    """Événements bruts + étiquettes (couleurs) du calendrier, en UNE seule session.

    Renvoie {'events': [...], 'labels': {label_id: {'name', 'color'}}}. Les étiquettes
    portent la couleur de chaque événement (dans TimeTree, la couleur vient du label).
    L'échec de lecture des labels est toléré (couleurs absentes ⇒ repli sur la couleur
    du calendrier côté affichage)."""
    sid = _session(email, password)
    cid = int(calendar_id)
    api = TimeTreeCalendar(sid, capture_raw_responses=False)
    try:
        events = api.get_events(cid)
    except Exception as exc:  # noqa: BLE001
        raise TimeTreeError(f"Lecture des événements TimeTree échouée : {exc}") from exc
    try:
        labels = api.get_labels(cid)
    except Exception as exc:  # noqa: BLE001 — couleurs facultatives, on n'échoue pas pour ça
        logger.warning("Lecture des étiquettes TimeTree échouée (couleurs ignorées) : %s", exc)
        labels = {}
    return {"events": events, "labels": labels}
