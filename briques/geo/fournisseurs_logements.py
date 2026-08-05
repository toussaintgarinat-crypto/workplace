"""Fournisseurs de LOGEMENTS — famille séparée de `fournisseurs.py` (entreprises) :
fichier distinct pour que le pipeline Sirene existant ne coure aucun risque de
régression. Contrat identique en esprit (mock déterministe d'abord, fournisseur réel
derrière une bascule env explicite), mais une méthode différente
(`logements_recents`, pas `entreprises_recentes`) — un logement n'a ni SIRET ni site
officiel, ce n'est pas la même forme d'objet.

`MockLogements` : logements SIMULÉS, déterministes par zone (seed = id de zone).
JAMAIS de nom de personne dans les metadata — seulement adresse et caractéristiques
du bien, cohérent avec la contrainte légale (fichiers fonciers inaccessibles)."""
from __future__ import annotations

import httpx
import os
import random
from datetime import datetime, timedelta, timezone

import domaine

_DPE_API_URL = os.getenv("GEO_DPE_URL",
                         "https://data.ademe.fr/data-fair/api/v1/datasets/dpe03existant")
_CHAMPS_DPE = ("numero_dpe,etiquette_dpe,adresse_ban,nom_commune_ban,code_postal_ban,"
              "coordonnee_cartographique_x_ban,coordonnee_cartographique_y_ban,"
              "date_etablissement_dpe,periode_construction,surface_habitable_logement")

_ADRESSES_SIMULEES = ["12 Rue des Lilas", "4 Impasse du Moulin", "7 Chemin de la Combe",
                      "21 Rue Basse", "3 Place du Marché", "9 Rue Haute",
                      "15 Allée des Tilleuls", "2 Rue de la Fontaine"]
_GRADES_SIMULES = ["F", "G", "E", "F", "E", "G", "F", "E"]
_AGES_JOURS = [3, 15, 45, 70, 120, 200, 10, 60]   # couvre rouge / orange / bleu


class MockLogements:
    """Déterministe (seed = id de zone) : deux appels produisent les MÊMES points."""
    nom = "mock-logements"

    def peut_traiter(self, zone: dict) -> str | None:
        return None   # le simulé traite toute zone

    def logements_recents(self, zone: dict, depuis: str | None = None) -> list[dict]:
        alea = random.Random(zone["id"])
        maintenant = datetime.now(timezone.utc)
        commune = (zone.get("communes") or [{"nom": zone.get("nom", "")}])[0]["nom"]
        grades_demandes = (zone.get("parametres") or {}).get("grades_dpe") or ["E", "F", "G"]
        objets = []
        for i, (adresse, age) in enumerate(zip(_ADRESSES_SIMULEES, _AGES_JOURS)):
            lat = alea.uniform(zone["lat_min"], zone["lat_max"])
            lon = alea.uniform(zone["lon_min"], zone["lon_max"])
            grade = _GRADES_SIMULES[i % len(_GRADES_SIMULES)]
            if grade not in grades_demandes:
                grade = grades_demandes[i % len(grades_demandes)]
            objets.append({
                "type": "logement", "latitude": lat, "longitude": lon,
                "date_reference": (maintenant - timedelta(days=age)).date().isoformat(),
                "ref_externe": f"simule-logement-{zone['id'][:8]}-{i}",
                "source": "simule-logement",
                "metadata": {"adresse": f"{adresse}, {commune}", "commune": commune,
                             "code_postal": "", "grade_dpe": grade,
                             "surface_m2": 70.0 + i * 5, "periode_construction": "avant 1948"},
            })
        return objets


class DpeAdeme:
    """API ouverte ADEME (Observatoire DPE, dataset `dpe03existant`), SANS clé, bascule
    explicite `GEO_FOURNISSEUR_LOGEMENTS=reel`. Filtre par communes (code INSEE) × grade
    DPE — nécessite des communes (pas de recherche par rayon sur cette API, contrairement
    à Sirene `/near_point`). Ne cible que les MAISONS (`type_batiment_eq=maison`) : le
    cas d'usage (convaincre un propriétaire individuel) ne s'applique pas à un logement
    en copropriété. Pagination par CURSEUR (le champ `next` de la réponse est l'URL
    complète de la page suivante), pas par numéro de page."""
    nom = "dpe-ademe"

    def peut_traiter(self, zone: dict) -> str | None:
        if not zone.get("communes"):
            return (f"zone « {zone['nom']} » ignorée : le fournisseur {self.nom} "
                    "nécessite des communes (code INSEE) — pas de recherche par rayon "
                    "sur l'API ADEME.")
        return None

    def logements_recents(self, zone: dict, depuis: str | None = None) -> list[dict]:
        codes = ",".join(c["code"] for c in zone["communes"])
        grades = (zone.get("parametres") or {}).get("grades_dpe") or ["E", "F", "G"]
        params = {"code_insee_ban_in": codes, "etiquette_dpe_in": ",".join(grades),
                  "type_batiment_eq": "maison", "size": 100, "select": _CHAMPS_DPE}
        pages_max = int(os.getenv("GEO_PAGES_MAX_LOGEMENTS", "10"))
        objets: list[dict] = []
        url, params_actuels = f"{_DPE_API_URL}/lines", params
        with httpx.Client(timeout=30) as client:
            for _ in range(pages_max):
                r = client.get(url, params=params_actuels)
                r.raise_for_status()
                d = r.json()
                for brute in d.get("results", []):
                    objet = domaine.normaliser_logement(brute)
                    if objet:
                        objets.append(objet)
                url = d.get("next")
                if not url:
                    break
                params_actuels = None   # `next` embarque déjà tous les paramètres
        return objets


def etat_config_logements() -> dict:
    if os.getenv("GEO_FOURNISSEUR_LOGEMENTS", "").strip().lower() == "reel":
        return {"configure": True, "fournisseur": DpeAdeme.nom,
                "message": "Données RÉELLES : ADEME Observatoire DPE (data.ademe.fr). "
                           "Veille par zone à communes × grade DPE (maisons individuelles)."}
    return {"configure": False, "fournisseur": MockLogements.nom,
            "message": "Données SIMULÉES (mock honnête) : posez "
                       "GEO_FOURNISSEUR_LOGEMENTS=reel pour brancher l'API ADEME."}


def fournisseur_logements() -> "MockLogements | DpeAdeme":
    if etat_config_logements()["configure"]:
        return DpeAdeme()
    return MockLogements()
