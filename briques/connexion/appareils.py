"""Magasin des appareils push web (S178) : endpoint → {utilisateur, clés, ua}.

Un « appareil » est une cible Web Push (l'objet PushSubscription du navigateur :
endpoint + clés p256dh/auth). PAS un abonnement payant. Stocké en JSON simple comme
le reste de la brique (`stockage`). L'adaptateur `webpush` y résout les clés à l'envoi ;
la table de correspondance, elle, ne retient que le routage (reseau=webpush, id=endpoint)."""
from __future__ import annotations

import stockage

FICHIER = "appareils_webpush.json"


def _table() -> dict:
    t = stockage.lire_json(FICHIER, {})
    return t if isinstance(t, dict) else {}


def _sauver(t: dict) -> None:
    stockage.ecrire_json(FICHIER, t)


def enregistrer(utilisateur: str, appareil: dict) -> dict:
    """Upsert d'un appareil (clé = endpoint). Idempotent."""
    endpoint = appareil["endpoint"]
    t = _table()
    t[endpoint] = {
        "utilisateur": utilisateur,
        "endpoint": endpoint,
        "keys": appareil.get("keys") or {},
        "ua": appareil.get("ua"),
    }
    _sauver(t)
    return t[endpoint]


def retirer(endpoint: str) -> bool:
    t = _table()
    if endpoint in t:
        del t[endpoint]
        _sauver(t)
        return True
    return False


def par_endpoint(endpoint: str) -> dict | None:
    return _table().get(endpoint)


def endpoints_de(utilisateur: str) -> list[str]:
    return [e for e, v in _table().items() if v.get("utilisateur") == utilisateur]
