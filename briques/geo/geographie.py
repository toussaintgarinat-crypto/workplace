"""Résolution de communes — nom (« Viviers-lès-Montagnes ») ou code postal (« 81290 »)
→ commune(s) INSEE {code, nom, bbox}, via l'API souveraine geo.api.gouv.fr (sans clé).

Un code postal peut couvrir PLUSIEURS villages : on les prend tous (c'est l'intention
« cibler ce coin-là »). La bbox vient du CONTOUR administratif de la commune (précis),
avec repli sur le centre ± 2 km si le contour manque. Honnête : une saisie qui ne
matche rien lève ValueError (message clair), jamais de commune devinée en silence."""
from __future__ import annotations

import os
import re

import httpx

import domaine

_GEO_URL = os.getenv("GEO_COMMUNES_URL", "https://geo.api.gouv.fr")


def resoudre_communes(saisies: list[str]) -> list[dict]:
    """Chaque saisie → commune(s) INSEE [{code, nom, bbox}], dédoublonnées par code.
    Lève ValueError (saisie introuvable) ou httpx.HTTPError (API injoignable)."""
    communes: dict[str, dict] = {}
    with httpx.Client(timeout=15) as client:
        for saisie in saisies or []:
            saisie = (saisie or "").strip()
            if not saisie:
                continue
            if re.fullmatch(r"\d{5}", saisie):
                params = {"codePostal": saisie, "fields": "code,nom,centre,contour"}
            else:
                params = {"nom": saisie, "fields": "code,nom,centre,contour",
                          "boost": "population", "limit": 1}
            r = client.get(f"{_GEO_URL}/communes", params=params)
            r.raise_for_status()
            trouvees = r.json()
            if not trouvees:
                raise ValueError(f"Commune introuvable : « {saisie} » (nom exact ou "
                                 "code postal à 5 chiffres attendu).")
            for c in trouvees:
                bbox = domaine.bbox_depuis_contour(c.get("contour"))
                if bbox is None and c.get("centre"):
                    lon, lat = c["centre"]["coordinates"]
                    bbox = domaine.bbox_depuis_rayon(lat, lon, 2.0)
                if bbox is None:
                    raise ValueError(f"Commune « {c.get('nom')} » sans géométrie.")
                communes.setdefault(c["code"], {"code": c["code"], "nom": c["nom"],
                                                "bbox": bbox})
    return list(communes.values())
