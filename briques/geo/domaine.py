"""Métier PUR de la brique geo — aucune I/O, aucune horloge implicite (l'instant est
toujours passé en paramètre) : tout est testable hors-ligne à la microseconde.

Porte : les règles de FRAÎCHEUR par type d'objet (la pastille de couleur de la carte),
les validations géométriques (bounding box, point, conversions rayon↔bbox) et la
normalisation des payloads fournisseurs vers le modèle `geo_objects`."""
from __future__ import annotations

import math
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


_KM_PAR_DEGRE = 111.0   # approximation sphérique, largement suffisante pour la veille


def bbox_depuis_rayon(latitude: float, longitude: float,
                      rayon_km: float) -> tuple[float, float, float, float]:
    """Bbox englobant un cercle centre+rayon (l'utilisateur dit « autour de Castres,
    20 km » ; la carte et le R*Tree parlent en boîtes). Bornée aux limites terrestres."""
    valider_point(latitude, longitude)
    if rayon_km <= 0:
        raise ValueError(f"Rayon invalide (km > 0 attendu) : {rayon_km}")
    d_lat = rayon_km / _KM_PAR_DEGRE
    d_lon = rayon_km / (_KM_PAR_DEGRE * max(math.cos(math.radians(latitude)), 0.01))
    return (max(latitude - d_lat, -90.0), max(longitude - d_lon, -180.0),
            min(latitude + d_lat, 90.0), min(longitude + d_lon, 180.0))


def centre_et_rayon(bbox: tuple[float, float, float, float]) -> tuple[float, float, float]:
    """L'inverse : centre + rayon (km) COUVRANT la bbox — pour les API qui cherchent
    par point+rayon (recherche-entreprises /near_point)."""
    lat_min, lon_min, lat_max, lon_max = bbox
    lat_c = (lat_min + lat_max) / 2
    lon_c = (lon_min + lon_max) / 2
    d_lat_km = (lat_max - lat_c) * _KM_PAR_DEGRE
    d_lon_km = (lon_max - lon_c) * _KM_PAR_DEGRE * max(math.cos(math.radians(lat_c)), 0.01)
    return (lat_c, lon_c, math.hypot(d_lat_km, d_lon_km))


def bbox_depuis_contour(contour: dict | None) -> tuple[float, float, float, float] | None:
    """Bbox englobant un contour GeoJSON de commune (Polygon ou MultiPolygon,
    coordonnées [lon, lat]). None si le contour est absent/illisible."""
    if not contour or not contour.get("coordinates"):
        return None
    anneaux = contour["coordinates"]
    if contour.get("type") == "Polygon":
        anneaux = [anneaux]
    points = [pt for poly in anneaux for anneau in poly for pt in anneau]
    if not points:
        return None
    lons = [p[0] for p in points]
    lats = [p[1] for p in points]
    return (min(lats), min(lons), max(lats), max(lons))


def bbox_union(boites: list[tuple[float, float, float, float]]) \
        -> tuple[float, float, float, float]:
    """La bbox englobant plusieurs bboxes (zone multi-villages)."""
    if not boites:
        raise ValueError("Aucune bbox à unir.")
    return (min(b[0] for b in boites), min(b[1] for b in boites),
            max(b[2] for b in boites), max(b[3] for b in boites))


def normaliser_entreprise(brute: dict) -> dict | None:
    """Payload brut recherche-entreprises.api.gouv.fr → objet `geo_objects`, ou None si
    inexploitable. PIÈGE vérifié LIVE : l'API apparie les ÉTABLISSEMENTS proches
    (`matching_etablissements`) — c'est LUI qu'on géolocalise et date, pas le siège
    (le bureau de poste de Castres appartient à un siège… parisien). On écarte les
    établissements FERMÉS (etat_administratif ≠ A). Coordonnées en CHAÎNES.
    L'identité d'upsert = SIRET de l'établissement (le SIREN en repli)."""
    etab = (brute.get("matching_etablissements") or [{}])[0]
    if not etab:
        etab = brute.get("siege") or {}
    if (etab.get("etat_administratif") or "A") != "A":
        return None
    try:
        latitude = float(etab.get("latitude"))
        longitude = float(etab.get("longitude"))
        valider_point(latitude, longitude)
    except (TypeError, ValueError):
        return None
    nom = (etab.get("nom_commercial") or brute.get("nom_complet")
           or brute.get("nom_raison_sociale") or "")
    return {
        "type": "entreprise",
        "latitude": latitude,
        "longitude": longitude,
        "date_reference": etab.get("date_creation") or brute.get("date_creation"),
        "ref_externe": etab.get("siret") or brute.get("siren"),
        "source": "recherche-entreprises",
        "metadata": {
            "nom": nom,
            "naf": etab.get("activite_principale") or brute.get("activite_principale") or "",
            "adresse": etab.get("adresse") or "",
            "commune": etab.get("libelle_commune") or "",
            "siren": brute.get("siren") or "",
        },
    }
