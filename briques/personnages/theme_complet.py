"""Theme complet — orchestrateur de la carte astrologique.

Assemble les 6 zones (fondations, 10 corps, points évolutifs, maisons, aspects,
dominantes) à partir d'une fiche. Repli honnête : chaque sous-section absente si
données manquantes, jamais d'erreur.
"""
from __future__ import annotations

from datetime import date, datetime

import aspects as A
import dominantes as D
import ephemeride as E
import maisons as M
import traditions as T

_CAVEATS = [
    "Pluton/Chiron : formule approchée stdlib (~0,1-1°) — suffisant pour signe/maison, limite pour aspects serrés.",
    "Nœud lunaire moyen (par défaut) — diffère du nœud vrai de ~0,1°.",
]


def _parse_naissance(fiche: dict) -> tuple[date | None, datetime | None, float, float, float, bool]:
    """Extrait date, datetime, utc_offset, latitude, longitude, heure_valide de la fiche."""
    dn = (fiche.get("date_naissance") or "").strip()
    naissance = None
    if dn:
        try:
            naissance = date.fromisoformat(dn)
        except ValueError:
            naissance = None
    he = (fiche.get("heure_naissance") or "").strip()
    dt = None
    heure_valide = False
    if naissance and he:
        try:
            hh, mm = (int(x) for x in he.split(":")[:2])
            dt = datetime(naissance.year, naissance.month, naissance.day, hh, mm)
            heure_valide = True
        except (ValueError, TypeError):
            pass
    off = float(fiche.get("utc_offset") or 0)
    lat = fiche.get("latitude")
    lon = fiche.get("longitude")
    return naissance, dt, off, lat, lon, heure_valide


def _maison_de(longitude: float, maisons: list[dict]) -> int | None:
    """Trouve la maison contenant la longitude."""
    if not maisons:
        return None
    for i, m in enumerate(maisons):
        cuspe = m["cuspe"]
        next_cuspe = maisons[(i + 1) % 12]["cuspe"]
        if cuspe <= next_cuspe:
            if cuspe <= longitude < next_cuspe:
                return m["maison"]
        else:  # chevauche 0°
            if longitude >= cuspe or longitude < next_cuspe:
                return m["maison"]
    return maisons[0]["maison"]


def _construire(naissance, dt, off, lat, lon, heure_valide,
                systeme_maisons, methode_dominantes, trad=None) -> dict:
    """Construction partagée entre theme_complet et theme_complet_depuis_traditions."""
    out: dict = {}
    meta: dict = {"caveats": list(_CAVEATS)}
    if not naissance:
        out["meta"] = meta
        return out

    # Soleil (toujours calculable avec juste la date)
    soleil_lon = T.soleil_longitude(dt or datetime(naissance.year, naissance.month, naissance.day, 12, 0), off)
    fondations = {"soleil": {**T._signe_depuis_longitude(soleil_lon),
                             "longitude": round(soleil_lon % 360, 4)}}

    # Lune (besoin de l'heure, mais on peut approximer à midi si pas d'heure)
    if dt is not None or heure_valide:
        lune_lon = T.lune_longitude(dt, off)
        fondations["lune"] = {**T._signe_depuis_longitude(lune_lon),
                              "longitude": round(lune_lon % 360, 4)}
    elif naissance is not None:
        # Approximation à midi
        dt_midi = datetime(naissance.year, naissance.month, naissance.day, 12, 0)
        lune_lon = T.lune_longitude(dt_midi, off)
        fondations["lune"] = {**T._signe_depuis_longitude(lune_lon),
                              "longitude": round(lune_lon % 360, 4)}

    # Asc/MC (besoin de l'heure + lieu)
    asc = mc = None
    if heure_valide and isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
        ta = trad or T.theme_astral(dt, off, float(lat), float(lon))
        asc = ta["ascendant"]["longitude"]
        mc = ta["milieu_du_ciel"]["longitude"]
        fondations["ascendant"] = {**T._signe_depuis_longitude(asc), "longitude": round(asc % 360, 4)}
        fondations["descendant"] = {**T._signe_depuis_longitude((asc + 180) % 360),
                                    "longitude": round((asc + 180) % 360, 4)}
        fondations["milieu_du_ciel"] = {**T._signe_depuis_longitude(mc), "longitude": round(mc % 360, 4)}
        fondations["fond_du_ciel"] = {**T._signe_depuis_longitude((mc + 180) % 360),
                                      "longitude": round((mc + 180) % 360, 4)}

    out["fondations"] = fondations

    # 10 corps + points évolutifs (besoin de l'heure)
    points_positions = {}
    if heure_valide:
        try:
            pos = E.positions(dt, off, float(lat or 0), float(lon or 0))
            # 10 corps
            dix_corps = {}
            for corps in ["Soleil", "Lune", "Mercure", "Vénus", "Mars",
                          "Jupiter", "Saturne", "Uranus", "Neptune", "Pluton"]:
                if corps in pos:
                    p = pos[corps]
                    s = T._signe_depuis_longitude(p["longitude"])
                    dix_corps[corps] = {**s, **p, "corps": corps}
            out["dix_corps"] = dix_corps
            # Points évolutifs
            pe = {}
            if "Nœud Nord" in pos:
                nn = pos["Nœud Nord"]
                pe["noeud_nord"] = {**T._signe_depuis_longitude(nn["longitude"]), **nn}
                ns_lon = (nn["longitude"] + 180) % 360
                pe["noeud_sud"] = {**T._signe_depuis_longitude(ns_lon),
                                   "longitude": round(ns_lon, 4), "corps": "Nœud Sud"}
            if "Chiron" in pos:
                pe["chiron"] = {**T._signe_depuis_longitude(pos["Chiron"]["longitude"]), **pos["Chiron"]}
            if "Lilith" in pos:
                pe["lilith"] = {**T._signe_depuis_longitude(pos["Lilith"]["longitude"]), **pos["Lilith"]}
            out["points_evolutifs"] = pe

            # Construire le dict points pour aspects + dominantes
            points_positions = {**dix_corps, **pe}
            if asc is not None:
                points_positions["Ascendant"] = {"longitude": asc, "signe": fondations["ascendant"]["signe"]}
                points_positions["Descendant"] = {"longitude": (asc + 180) % 360}
                points_positions["Milieu du Ciel"] = {"longitude": mc}
                points_positions["Fond du Ciel"] = {"longitude": (mc + 180) % 360}
        except (NotImplementedError, ValueError, TypeError):
            pass

    # Maisons
    maisons_list = []
    if asc is not None and mc is not None and isinstance(lat, (int, float)):
        try:
            maisons_list = M.maisons(asc, mc, float(lat), systeme_maisons)
            out["maisons"] = maisons_list
            meta["systeme_maisons_effectif"] = maisons_list[0]["systeme"]
            # Assigner la maison à chaque point
            for nom, p in points_positions.items():
                p["maison"] = _maison_de(p["longitude"], maisons_list)
        except Exception:
            meta["systeme_maisons_effectif"] = systeme_maisons
    meta["systeme_maisons_demande"] = systeme_maisons
    meta["methode_dominantes_demande"] = methode_dominantes

    # Aspects
    if len(points_positions) >= 2:
        try:
            out["aspects"] = A.aspects(points_positions)
        except Exception:
            pass

    # Dominantes
    if points_positions and maisons_list:
        try:
            out["dominantes"] = D.dominantes(points_positions, maisons_list,
                                             out.get("aspects", []), methode_dominantes)
            meta["methode_dominantes_effectif"] = out["dominantes"]["methode"]
        except NotImplementedError:
            meta["methode_dominantes_effectif"] = "non_calcule"

    out["meta"] = meta
    return out


def theme_complet(fiche: dict) -> dict:
    """Carte astrologique complète depuis une fiche."""
    naissance, dt, off, lat, lon, heure_valide = _parse_naissance(fiche)
    systeme = fiche.get("systeme_maisons", "whole_sign")
    methode = fiche.get("methode_dominantes", "comptage_dignite")
    return _construire(naissance, dt, off, lat, lon, heure_valide, systeme, methode)


def theme_complet_depuis_traditions(trad: dict, fiche: dict) -> dict:
    """Variante réutilisant un calcul traditions déjà fait."""
    naissance, dt, off, lat, lon, heure_valide = _parse_naissance(fiche)
    systeme = fiche.get("systeme_maisons", "whole_sign")
    methode = fiche.get("methode_dominantes", "comptage_dignite")
    return _construire(naissance, dt, off, lat, lon, heure_valide, systeme, methode,
                       trad=trad.get("theme_astral"))
