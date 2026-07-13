"""Client du RAIL de paiement — branche l'encaissement en ligne du restaurant sur la brique
« paiements » 6020 (Stripe Connect multi-tenant, S166). Le SPLIT/addition partagée reste ICI
(la brique restaurant tient le « qui doit quoi ») ; c'est le rail qui tient l'argent.

Repli HONNÊTE, principe cardinal : si le rail n'est pas configuré (URL + clé tenant) ou s'il
est injoignable/refuse, l'appelant retombe sur le paiement mock local — jamais de faux
encaissement présenté comme réel. Config par variables d'environnement :

  • PAIEMENTS_URL       : base de la brique paiements (ex. http://host.docker.internal:6020) ;
  • PAIEMENTS_API_KEY   : clé API du restaurant AUPRÈS du rail (son tenant, isolé des autres) ;
  • RESTAURANT_COMMISSION_BPS : commission plateforme des encaissements en ligne (défaut 0).
"""
from __future__ import annotations

import os

import httpx

_TIMEOUT = 10.0


def _base() -> str | None:
    url = os.getenv("PAIEMENTS_URL")
    return url.rstrip("/") if url else None


def _cle() -> str | None:
    return os.getenv("PAIEMENTS_API_KEY") or None


def configure() -> bool:
    """Le rail n'est utilisable que si son URL ET la clé tenant du restaurant sont présentes."""
    return bool(_base() and _cle())


def commission_bps() -> int:
    try:
        return max(0, int(os.getenv("RESTAURANT_COMMISSION_BPS", "0")))
    except ValueError:
        return 0


def _entetes() -> dict:
    return {"X-API-Key": _cle() or ""}


def creer_compte(nom: str) -> dict:
    """Crée un compte connecté vendeur dans le rail et son lien d'onboarding hébergé.
    Renvoie {compte_id, statut, onboarding_url}. Lève httpx.HTTPError si le rail échoue."""
    base = _base()
    with httpx.Client(timeout=_TIMEOUT) as cl:
        r = cl.post(f"{base}/comptes-connectes", headers=_entetes(), json={"nom": nom})
        r.raise_for_status()
        compte = r.json()
        lien = cl.post(f"{base}/comptes-connectes/{compte['id']}/onboarding", headers=_entetes())
        lien.raise_for_status()
    return {"compte_id": compte["id"], "statut": compte["statut"],
            "onboarding_url": lien.json().get("url")}


def statut_compte(compte_id: str) -> dict | None:
    """État d'un compte connecté (peut-il encaisser ?), ou None si rail injoignable/introuvable."""
    base = _base()
    try:
        with httpx.Client(timeout=_TIMEOUT) as cl:
            r = cl.get(f"{base}/comptes-connectes/{compte_id}", headers=_entetes())
        if r.status_code != 200:
            return None
        d = r.json()
        return {"statut": d.get("statut"), "peut_encaisser": bool(d.get("peut_encaisser"))}
    except httpx.HTTPError:
        return None


def encaisser(compte_id: str, montant_cents: int, description: str = "") -> dict:
    """Encaisse `montant_cents` en ligne via le rail, vers le compte connecté du restaurant,
    en prélevant la commission plateforme. Renvoie le paiement du rail. Lève ValueError
    (refus du rail) ou httpx.HTTPError (injoignable) → l'appelant fait le repli mock."""
    base = _base()
    with httpx.Client(timeout=_TIMEOUT) as cl:
        r = cl.post(f"{base}/paiements", headers=_entetes(), json={
            "compte_connecte_id": compte_id, "montant_cents": int(montant_cents),
            "commission_bps": commission_bps(), "description": description})
    if r.status_code >= 400:
        raise ValueError(f"rail a refusé l'encaissement ({r.status_code})")
    return r.json()
