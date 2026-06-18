"""Composition de la brique sœur « personnages » (5900) — adaptateur client (S52).

Le Studio COMPOSE les briques autonomes, il ne les ABSORBE pas (cf. plan brique studio).
Deux services rendus par la brique personnages :
  • distribution     → proposer une distribution cohérente (Directeur de Casting) ;
  • casting vocal    → affecter des voix de façon STABLE par personnage (le différenciateur).

Chaque adaptateur a un REPLI HONNÊTE : si la brique est absente/injoignable/illisible, on
renvoie None → l'appelant retombe sur la logique INTERNALISÉE au socle S51 (studio._caster /
Directeur de Casting interne) et signale la `source` réellement utilisée. On ne casse jamais
une production parce qu'une brique sœur est éteinte.

(La brique images, elle, est composée depuis `studio._appeler_images` — même esprit.)
"""
import os
from typing import Optional

import httpx

# Brique « personnages » (5900) : distribution + casting vocal stable, agnostique au TTS.
PERSONNAGES_URL = os.getenv("PERSONNAGES_URL", "http://host.docker.internal:5900")
# Clé API si la brique personnages tourne en mode authentifié (sinon mode ouvert).
PERSONNAGES_KEY = os.getenv("PERSONNAGES_KEY", "")


def _headers() -> dict:
    return {"X-API-Key": PERSONNAGES_KEY} if PERSONNAGES_KEY else {}


async def personnages_joignable() -> bool:
    """Vrai si la brique personnages répond et s'annonce bien comme telle (sans réseau lourd)."""
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.get(f"{PERSONNAGES_URL}/sante", headers=_headers())
            return r.status_code == 200 and r.json().get("service") == "personnages"
    except Exception:  # noqa: BLE001
        return False


async def caster(personnages: list, langue: str, intervenants: list,
                 pool: list) -> Optional[tuple]:
    """Casting vocal STABLE via la brique personnages (POST /casting).

    Retourne (casting {NOM→voix}, personnages_enrichis) — la distribution voix figées —
    ou None si la brique est injoignable (→ repli interne côté appelant). Le casting de
    la brique est stateless : c'est à nous de re-persister les voix figées (fusionner_voix).
    """
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(f"{PERSONNAGES_URL}/casting", headers=_headers(), json={
                "personnages": personnages,
                "repliques":   [{"perso": n} for n in intervenants],
                "langue":      langue,
                "pool_voix":   pool,
            })
            r.raise_for_status()
            data = r.json()
            casting = data.get("casting")
            if not isinstance(casting, dict):
                return None
            return casting, data.get("personnages") or personnages
    except Exception:  # noqa: BLE001
        return None


async def proposer_distribution(premisse: str, langue: str, combien: int,
                                deja: str = "") -> Optional[list]:
    """Distribution proposée par la brique personnages (POST /distribution/proposer).

    Retourne une liste [{nom, role, description}] normalisée, ou None si injoignable/illisible
    (→ repli sur le Directeur de Casting internalisé côté appelant)."""
    try:
        async with httpx.AsyncClient(timeout=120) as c:
            r = await c.post(f"{PERSONNAGES_URL}/distribution/proposer",
                             headers=_headers(), json={
                                 "premisse": premisse, "langue": langue,
                                 "combien":  combien,  "deja":   deja})
            r.raise_for_status()
            persos = r.json().get("personnages") or []
    except Exception:  # noqa: BLE001
        return None
    return [{"nom":         str(p.get("nom") or "").strip(),
             "role":        str(p.get("role") or "").strip(),
             "description": str(p.get("description") or "").strip()}
            for p in persos if isinstance(p, dict) and (p.get("nom") or "").strip()]


async def lister_fiches_holistiques() -> Optional[list]:
    """Personnages ENREGISTRÉS dans l'atelier holistique (GET /fiches de la brique 5900).

    Permet au Studio de proposer « mes personnages créés » à la sélection. Retourne
    [{id, nom, nom_naissance, archetype, cree_le}] ou None si la brique est injoignable
    (→ le Studio affiche un repli honnête, on ne casse pas la vue Distribution)."""
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"{PERSONNAGES_URL}/fiches", headers=_headers())
            r.raise_for_status()
            fiches = r.json()
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(fiches, list):
        return None
    return [{"id": f.get("id"), "nom": f.get("nom") or "Personnage",
             "nom_naissance": f.get("nom_naissance") or f.get("nom") or "",
             "archetype": f.get("archetype") or "", "cree_le": f.get("cree_le") or ""}
            for f in fiches if isinstance(f, dict) and f.get("id")]


async def lire_fiche_holistique(fiche_id: str) -> Optional[dict]:
    """Lit une fiche enregistrée complète (GET /fiches/{id}) pour l'importer comme rôle.

    Retourne le dict de la brique (nom, nom_naissance, archetype, donnees…) ou None si
    injoignable/introuvable."""
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"{PERSONNAGES_URL}/fiches/{fiche_id}", headers=_headers())
            if r.status_code == 404:
                return None
            r.raise_for_status()
            f = r.json()
    except Exception:  # noqa: BLE001
        return None
    return f if isinstance(f, dict) and f.get("id") else None


def fusionner_voix(serie: dict, personnages_enrichis: list) -> bool:
    """Recopie dans la série les voix figées renvoyées par la brique (stabilité inter-épisodes).

    Apparie par `id` puis par nom normalisé, n'écrase pas une voix déjà posée par une vide.
    Retourne True si la série a été modifiée."""
    par_id = {p.get("id"): p for p in (personnages_enrichis or []) if p.get("id")}
    par_nom = {_cle(p.get("nom")): p for p in (personnages_enrichis or []) if p.get("nom")}
    modifie = False
    for p in serie.get("personnages") or []:
        src = par_id.get(p.get("id")) or par_nom.get(_cle(p.get("nom")))
        if not (src and isinstance(src.get("voix"), dict)):
            continue
        voix = p.setdefault("voix", {})
        for langue, vid in src["voix"].items():
            if vid and voix.get(langue) != vid:
                voix[langue] = vid
                modifie = True
    return modifie


def _cle(nom) -> str:
    import re
    return re.sub(r"\s+", " ", (nom or "").strip()).upper()
