"""Fournisseurs de données géolocalisées — provider-agnostiques, mock honnête d'abord.

Contrat : `entreprises_recentes(zone, depuis)` renvoie des objets DÉJÀ NORMALISÉS au
modèle `geo_objects` (type, latitude, longitude, date_reference, ref_externe, source,
metadata) — l'ingestion (main.py) n'a plus qu'à upserter.

- `Mock` : entreprises SIMULÉES, déterministes par zone (seed = id de zone), dates
  étalées pour couvrir rouge/orange/bleu. Tout étiqueté `source="simule"` : sert la
  démo, les tests et le dev souverain sans un seul appel réseau.
- `RechercheEntreprises` : l'API publique recherche-entreprises.api.gouv.fr (données
  Sirene, SANS clé — d'où la bascule par env EXPLICITE `GEO_FOURNISSEUR=reel`, pas de
  détection par secret). Vérifié LIVE (2026-07-06) : `/near_point` apparie les
  ÉTABLISSEMENTS proches, l'API ne filtre PAS par date de création et plafonne à
  10 000 résultats → une zone n'est ÉNUMÉRABLE (donc la veille honnête : nouveaux
  SIRET = vraies découvertes) qu'avec un filtre d'activité NAF (`requiert_naf`)."""
from __future__ import annotations

import logging
import os
import random
import time
from datetime import datetime, timedelta, timezone

import httpx

import domaine

logger = logging.getLogger("geo.fournisseurs")

_API_URL = os.getenv("GEO_RECHERCHE_URL", "https://recherche-entreprises.api.gouv.fr")
# Politesse : l'API publique limite le débit (429 vu LIVE dès ~26 pages d'affilée).
_PAUSE_S = float(os.getenv("GEO_PAUSE_S", "0.25"))       # entre deux pages
_RETRIES_429 = int(os.getenv("GEO_RETRIES_429", "4"))    # tentatives sur 429


def _get_poliment(client: httpx.Client, url: str, params: dict) -> httpx.Response:
    """GET qui respecte le rythme de l'API : pause entre pages, et sur 429 on ATTEND
    (Retry-After s'il est fourni, sinon backoff progressif) puis on réessaie — la
    veille est nocturne, mieux vaut lent que refoulé."""
    for tentative in range(1, _RETRIES_429 + 1):
        r = client.get(url, params=params)
        if r.status_code != 429:
            r.raise_for_status()
            time.sleep(_PAUSE_S)
            return r
        attente = float(r.headers.get("Retry-After") or 2 * tentative)
        logger.warning("Geo : 429 sur %s (page %s) — attente %.1fs (tentative %s/%s)",
                       url, params.get("page"), attente, tentative, _RETRIES_429)
        time.sleep(attente)
    r.raise_for_status()   # toujours 429 après les tentatives → erreur honnête
    return r

_NOMS_SIMULES = ["Boulangerie du Pont", "Atelier Vélo Cité", "SARL Toit & Charpente",
                 "Café des Halles", "Menuiserie Lacaze", "Studio Photo Lumen",
                 "Garage de la Gare", "Épicerie Court-Circuit"]
_NAF_SIMULES = ["1071C", "4520A", "4332A", "5610A", "1623Z", "7420Z", "4520B", "4711B"]
_AGES_JOURS = [3, 15, 45, 70, 120, 200, 10, 60]   # couvre rouge / orange / bleu


class Mock:
    """Créations d'entreprises SIMULÉES dans la bbox de la zone. Déterministe (seed =
    id de zone) : deux ingestions produisent les MÊMES points → l'upsert dédoublonne
    et la 2e passe compte honnêtement 0 nouveau."""
    nom = "mock"

    def peut_traiter(self, zone: dict) -> str | None:
        return None   # le simulé traite tout

    def entreprises_recentes(self, zone: dict, depuis: str | None = None) -> list[dict]:
        alea = random.Random(zone["id"])
        maintenant = datetime.now(timezone.utc)
        objets = []
        for i, (nom, naf, age) in enumerate(zip(_NOMS_SIMULES, _NAF_SIMULES, _AGES_JOURS)):
            lat = alea.uniform(zone["lat_min"], zone["lat_max"])
            lon = alea.uniform(zone["lon_min"], zone["lon_max"])
            objets.append({
                "type": zone.get("type") or "entreprise", "latitude": lat, "longitude": lon,
                "date_reference": (maintenant - timedelta(days=age)).date().isoformat(),
                "ref_externe": f"simule-{zone['id'][:8]}-{i}",
                "source": "simule",
                "metadata": {"nom": nom, "naf": naf, "adresse": "adresse simulée"},
            })
        return objets


class RechercheEntreprises:
    """API publique recherche-entreprises.api.gouv.fr, `/near_point` (point + rayon).

    Stratégie ÉNUMÉRATION (pas de filtre par date côté API) : on liste tous les
    établissements ACTIFS de la zone (pages bornées par GEO_PAGES_MAX), et l'upsert
    par SIRET fait le tri — la 1re passe SÈME la carte, les passes suivantes ne
    comptent « nouveau » que ce qui vient d'apparaître au répertoire. Deux modes :
    zone à COMMUNES → `/search?code_commune=…` (ciblage exact au village, NAF
    facultatif, filtre associations disponible) ; sinon → `/near_point`
    (point+rayon, NAF requis, pas de filtre associations — vérifié LIVE)."""
    nom = "recherche-entreprises"

    def peut_traiter(self, zone: dict) -> str | None:
        """None si la zone est traitable ; sinon le message d'avertissement HONNÊTE
        (la zone sera ignorée par l'ingestion plutôt que mal servie)."""
        if zone.get("communes"):
            return None   # /search : énumérable, tous filtres disponibles
        if (zone.get("type") or "entreprise") == "association":
            return (f"zone « {zone['nom']} » ignorée : les ASSOCIATIONS ne se filtrent "
                    "que par communes (le filtre n'existe pas sur point+rayon).")
        if not zone.get("naf"):
            return (f"zone « {zone['nom']} » ignorée : le fournisseur {self.nom} requiert "
                    "un filtre NAF ou des communes (sinon la zone n'est pas énumérable).")
        return None

    def entreprises_recentes(self, zone: dict, depuis: str | None = None) -> list[dict]:
        type_ = zone.get("type") or "entreprise"
        codes = ",".join(c["code"] for c in (zone.get("communes") or []))
        if codes:
            chemin = "/search"
            params = {"code_commune": codes}
            if type_ == "association":
                params["est_association"] = "true"
        else:
            bbox = (zone["lat_min"], zone["lon_min"], zone["lat_max"], zone["lon_max"])
            lat, lon, rayon_km = domaine.centre_et_rayon(bbox)
            chemin = "/near_point"
            params = {"lat": lat, "long": lon, "radius": min(rayon_km, 50),
                      "sort_by_size": "false"}
        if zone.get("naf"):
            params["activite_principale"] = zone["naf"]
        pages_max = int(os.getenv("GEO_PAGES_MAX", "40"))   # 40 × 25 = 1 000 étabs/zone/nuit
        objets: list[dict] = []
        with httpx.Client(timeout=30) as client:
            for page in range(1, pages_max + 1):
                r = _get_poliment(client, f"{_API_URL}{chemin}",
                                  {**params, "per_page": 25, "page": page})
                d = r.json()
                for brute in d.get("results", []):
                    objet = domaine.normaliser_entreprise(brute, type_=type_)
                    if objet:
                        objets.append(objet)
                total_pages = d.get("total_pages", 1)
                if page >= total_pages:
                    break
            else:
                logger.warning("Geo zone « %s » : %s pages > borne %s — énumération "
                               "TRONQUÉE, resserrer la zone ou le NAF.",
                               zone.get("nom"), total_pages, pages_max)
        return objets


def etat_config() -> dict:
    """État honnête du fournisseur — l'API réelle étant sans clé, la bascule est un
    choix EXPLICITE (`GEO_FOURNISSEUR=reel`), jamais une détection silencieuse."""
    if os.getenv("GEO_FOURNISSEUR", "").strip().lower() == "reel":
        return {"configure": True, "fournisseur": RechercheEntreprises.nom,
                "message": "Données RÉELLES : recherche-entreprises.api.gouv.fr (Sirene). "
                           "Veille par zone×NAF (filtre d'activité requis)."}
    return {"configure": False, "fournisseur": Mock.nom,
            "message": "Données SIMULÉES (mock honnête) : posez GEO_FOURNISSEUR=reel "
                       "pour brancher l'API Sirene publique."}


def fournisseur() -> Mock | RechercheEntreprises:
    if etat_config()["configure"]:
        return RechercheEntreprises()
    return Mock()
