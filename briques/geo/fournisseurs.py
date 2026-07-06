"""Fournisseurs de données géolocalisées — provider-agnostiques, mock honnête d'abord.

Contrat : `entreprises_recentes(zone, depuis)` renvoie des objets DÉJÀ NORMALISÉS au
modèle `geo_objects` (type, latitude, longitude, date_reference, ref_externe, source,
metadata) — l'ingestion (main.py) n'a plus qu'à upserter.

- `Mock` : entreprises SIMULÉES, déterministes par zone (seed = id de zone), dates
  étalées pour couvrir rouge/orange/bleu. Tout étiqueté `source="simule"` : sert la
  démo, les tests et le dev souverain sans un seul appel réseau.
- `RechercheEntreprises` : l'API publique recherche-entreprises.api.gouv.fr (données
  Sirene, SANS clé — d'où la bascule par env EXPLICITE `GEO_FOURNISSEUR=reel`, pas de
  détection par secret). Les payloads bruts passent par `domaine.normaliser_entreprise`
  (pur, testé hors-ligne sur payload figé)."""
from __future__ import annotations

import os
import random
from datetime import datetime, timedelta, timezone

import httpx

import domaine

_API_URL = os.getenv("GEO_RECHERCHE_URL", "https://recherche-entreprises.api.gouv.fr")
# Fenêtre de veille : au-delà, une entreprise n'est plus une « création récente ».
_FENETRE_JOURS = int(os.getenv("GEO_FENETRE_JOURS", "90"))

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

    def entreprises_recentes(self, zone: dict, depuis: str | None = None) -> list[dict]:
        alea = random.Random(zone["id"])
        maintenant = datetime.now(timezone.utc)
        objets = []
        for i, (nom, naf, age) in enumerate(zip(_NOMS_SIMULES, _NAF_SIMULES, _AGES_JOURS)):
            lat = alea.uniform(zone["lat_min"], zone["lat_max"])
            lon = alea.uniform(zone["lon_min"], zone["lon_max"])
            objets.append({
                "type": "entreprise", "latitude": lat, "longitude": lon,
                "date_reference": (maintenant - timedelta(days=age)).date().isoformat(),
                "ref_externe": f"simule-{zone['id'][:8]}-{i}",
                "source": "simule",
                "metadata": {"nom": nom, "naf": naf, "adresse": "adresse simulée"},
            })
        return objets


class RechercheEntreprises:
    """API publique recherche-entreprises.api.gouv.fr : recherche par point+rayon
    (`/near_point`), puis normalisation + filtre sur la fenêtre de veille."""
    nom = "recherche-entreprises"

    def entreprises_recentes(self, zone: dict, depuis: str | None = None) -> list[dict]:
        bbox = (zone["lat_min"], zone["lon_min"], zone["lat_max"], zone["lon_max"])
        lat, lon, rayon_km = domaine.centre_et_rayon(bbox)
        maintenant = datetime.now(timezone.utc)
        date_min = (maintenant - timedelta(days=_FENETRE_JOURS)).date().isoformat()
        objets: list[dict] = []
        with httpx.Client(timeout=30) as client:
            for page in range(1, 5):   # 4 pages × 25 = borne raisonnable par zone/nuit
                r = client.get(f"{_API_URL}/near_point",
                               params={"lat": lat, "long": lon,
                                       "radius": min(rayon_km, 50), "per_page": 25,
                                       "page": page})
                r.raise_for_status()
                resultats = r.json().get("results", [])
                for brute in resultats:
                    objet = domaine.normaliser_entreprise(brute)
                    if objet and (objet["date_reference"] or "") >= date_min:
                        objets.append(objet)
                if len(resultats) < 25:
                    break
        return objets


def etat_config() -> dict:
    """État honnête du fournisseur — l'API réelle étant sans clé, la bascule est un
    choix EXPLICITE (`GEO_FOURNISSEUR=reel`), jamais une détection silencieuse."""
    if os.getenv("GEO_FOURNISSEUR", "").strip().lower() == "reel":
        return {"configure": True, "fournisseur": RechercheEntreprises.nom,
                "message": "Données RÉELLES : recherche-entreprises.api.gouv.fr (Sirene)."}
    return {"configure": False, "fournisseur": Mock.nom,
            "message": "Données SIMULÉES (mock honnête) : posez GEO_FOURNISSEUR=reel "
                       "pour brancher l'API Sirene publique."}


def fournisseur() -> Mock | RechercheEntreprises:
    if etat_config()["configure"]:
        return RechercheEntreprises()
    return Mock()
