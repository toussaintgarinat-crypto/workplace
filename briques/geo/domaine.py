"""Métier PUR de la brique geo — aucune I/O, aucune horloge implicite (l'instant est
toujours passé en paramètre) : tout est testable hors-ligne à la microseconde.

Porte : les règles de FRAÎCHEUR par type d'objet (la pastille de couleur de la carte),
les validations géométriques (bounding box, point), et — à partir de S157 — la
normalisation des payloads fournisseurs vers le modèle `geo_objects`."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

PASTILLE_DEFAUT = "bleu"
PASTILLES = ("rouge", "orange", "bleu")

# Règles par TYPE d'objet : liste (age_max_jours, pastille), évaluée dans l'ordre ;
# au-delà de la dernière borne → bleu (établi). Étendre = ajouter une entrée, zéro
# migration (ex. "immobilier": [(2, "rouge"), (14, "orange")]).
REGLES_FRAICHEUR: dict[str, list[tuple[int, str]]] = {
    "entreprise": [(30, "rouge"), (90, "orange")],
    "_defaut": [(30, "rouge"), (90, "orange")],
}


def _en_utc(date_iso: str) -> datetime:
    d = datetime.fromisoformat(date_iso)
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d


def pastille_fraicheur(type_: str, date_reference: str | None, maintenant: datetime) -> str:
    """Couleur de pastille d'un objet selon l'âge de sa date de RÉFÉRENCE métier (ex.
    création d'entreprise). Sans date (ou date illisible) : bleu — on ne prétend pas
    qu'un objet est « nouveau » sans preuve. Une date future compte comme âge zéro."""
    if not date_reference:
        return PASTILLE_DEFAUT
    try:
        ref = _en_utc(date_reference)
    except ValueError:
        return PASTILLE_DEFAUT
    age_jours = max((maintenant - ref).days, 0)
    for age_max, pastille in REGLES_FRAICHEUR.get(type_, REGLES_FRAICHEUR["_defaut"]):
        if age_jours < age_max:
            return pastille
    return PASTILLE_DEFAUT


def date_min_pour_fraicheur(type_: str, pastille: str, maintenant: datetime) -> str | None:
    """Borne de date pour le filtre `?fraicheur=` : « au moins aussi frais que » la
    pastille demandée (rouge = les plus récents ; orange inclut donc les rouges ;
    bleu = tout → None, pas de filtre). Lève ValueError si la pastille est inconnue."""
    if pastille not in PASTILLES:
        raise ValueError(f"Fraîcheur inconnue « {pastille} » (attendues : rouge, orange, bleu).")
    if pastille == "bleu":
        return None
    regles = REGLES_FRAICHEUR.get(type_, REGLES_FRAICHEUR["_defaut"])
    for age_max, p in regles:
        if p == pastille:
            return (maintenant - timedelta(days=age_max)).isoformat()
    return None


def valider_point(latitude: float, longitude: float) -> None:
    """Lève ValueError si le point sort des bornes terrestres (±90 / ±180)."""
    if not (-90.0 <= latitude <= 90.0):
        raise ValueError(f"Latitude hors bornes (±90) : {latitude}")
    if not (-180.0 <= longitude <= 180.0):
        raise ValueError(f"Longitude hors bornes (±180) : {longitude}")


def valider_bbox(brut: str) -> tuple[float, float, float, float]:
    """Parse et valide « lat_min,lon_min,lat_max,lon_max » (l'ordre Leaflet/spec).
    Lève ValueError (message honnête) si malformée, hors bornes ou inversée."""
    morceaux = [m.strip() for m in (brut or "").split(",")]
    if len(morceaux) != 4:
        raise ValueError("bbox attendue : « lat_min,lon_min,lat_max,lon_max » (4 nombres).")
    try:
        lat_min, lon_min, lat_max, lon_max = (float(m) for m in morceaux)
    except ValueError:
        raise ValueError(f"bbox illisible (nombres attendus) : « {brut} »")
    valider_point(lat_min, lon_min)
    valider_point(lat_max, lon_max)
    if lat_min >= lat_max or lon_min >= lon_max:
        raise ValueError("bbox inversée : min doit être strictement inférieur à max.")
    return (lat_min, lon_min, lat_max, lon_max)
