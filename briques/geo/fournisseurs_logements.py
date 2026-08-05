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

import os
import random
from datetime import datetime, timedelta, timezone

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
