"""Éphéméride géocentrique — longitudes écliptiques tropicales de la date.

Stdlib only. Soleil/Lune réutilisent traditions (Meeus/ELP abrégé).
Mercure→Neptune via éléments osculateurs + Kepler (Meeus ch.32-36, ~0.5-2°).
Pluton/Chiron/Lilith/Nœud Nord via formules approchées Meeus (task 3).

Référentiel : longitude géocentrique écliptique tropicale de la date (vraie
équinoxe), en degrés. UT1→TT via ΔT (Espenak-Meeus) pour les planètes.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

import traditions as T


CORPS = ["Soleil", "Lune", "Mercure", "Vénus", "Mars", "Jupiter",
         "Saturne", "Uranus", "Neptune", "Pluton", "Chiron", "Lilith",
         "Nœud Nord"]

_PLANETES_KEPLER = {"Mercure", "Vénus", "Mars", "Jupiter", "Saturne",
                    "Uranus", "Neptune", "Pluton", "Chiron"}

# ── Éléments osculateurs J2000 + variations séculaires (Meeus ch.32-36) ──
# Format : (a, e, i, Ω, ϖ, L0, Δa, Δe, Δi, ΔΩ, Δϖ, ΔL0)
# Angles en degrés, a en AU, taux par siècle julien.
_ELEMENTS = {
    "Mercure": (0.387099, 0.205646, 7.005, 48.331, 77.456, 252.251,
                0.0, 0.0000213, -0.006, -0.1254, 0.1606, 149472.674),
    "Vénus":   (0.723332, 0.006773, 3.395, 76.680, 131.564, 181.980,
                0.0, -0.0000495, 0.001, -0.2784, 0.0523, 58517.815),
    "Terre":   (1.000001, 0.016709, 0.0, 0.0, 102.937, 100.466,
                0.0, -0.0000420, 0.0, 0.0, 0.3232, 35999.373),
    "Mars":    (1.523688, 0.093405, 1.850, 49.558, 336.041, 355.433,
                0.0, 0.0000910, -0.0072, -0.2933, 0.4441, 19140.299),
    "Jupiter": (5.202561, 0.048495, 1.303, 100.464, 14.331, 34.351,
                -0.0000248, 0.0001633, -0.0065, 0.1767, 0.2156, 3034.906),
    "Saturne": (9.554747, 0.055546, 2.489, 113.665, 93.057, 50.078,
                0.0, -0.0003467, 0.0039, -0.2567, 0.5636, 1222.114),
    "Uranus":  (19.21814, 0.046381, 0.773, 74.006, 173.005, 314.055,
                0.0, 0.0000270, -0.0024, 0.0462, 0.0324, 428.466),
    "Neptune": (30.10957, 0.009456, 1.770, 131.784, 48.123, 304.349,
                0.0, 0.0000058, 0.0006, -0.0105, -0.0189, 218.466),
    # Pluton : éléments osculateurs J2000 (précision ~1-2°, orbite perturbée)
    "Pluton":  (39.482, 0.2488, 17.16, 110.303, 224.066, 238.93,
                0.0, 0.000051, -0.003, -0.009, -0.015, 145.08),
    # Chiron : éléments osculateurs approximatifs J2000 (précision ~1-3°)
    "Chiron":  (17.0, 0.38, 6.95, 207.0, 22.0, 212.0,
                0.0, 0.0, 0.0, 0.0, 0.0, 7.42),
}


@dataclass
class _Contexte:
    jj: float
    t: float
    heure_ut: float
    delta_t: float


def _delta_t(annee: int) -> float:
    """ΔT (TT - UT1) en secondes — Espenak-Meeus par siècle."""
    if 2000 <= annee < 2100:
        u = annee - 2000
        return 62.92 + 0.32217 * u + 0.005589 * u * u
    elif 1900 <= annee < 2000:
        t = (annee - 1900) / 100.0
        return -2.79 + 1.494119 * t + 0.0006205 * t * t
    elif 2100 <= annee < 2200:
        t = (annee - 2100) / 100.0
        return 111.19 + 4.06246 * t + 0.000118 * t * t
    else:
        return 69.0


def _contexte(dt: datetime, utc_offset_h: float) -> _Contexte:
    heure_ut = dt.hour + dt.minute / 60.0 - utc_offset_h
    jj = T._jour_julien(dt.year, dt.month, dt.day, heure_ut)
    t = (jj - 2451545.0) / 36525.0
    return _Contexte(jj=jj, t=t, heure_ut=heure_ut, delta_t=_delta_t(dt.year))


def _vitesse_et_retro(corps: str, dt: datetime, utc_offset_h: float,
                      lon_a_t: float) -> tuple[float, bool]:
    """Dérivée finie sur 1h → vitesse (deg/jour) + rétrogradation."""
    dt_plus = dt + timedelta(hours=1)
    lon_plus = _longitude_brute(corps, dt_plus, utc_offset_h)
    delta = (lon_plus - lon_a_t + 180) % 360 - 180
    vitesse = delta * 24.0
    return vitesse, vitesse < 0


# ── Mercure→Neptune : éléments osculateurs + Kepler (Meeus) ────────
def _elements_a_t(corps: str, t: float) -> tuple:
    """Éléments osculateurs au temps t (siècles juliens TT depuis J2000)."""
    a0, e0, i0, O0, w0, L0, da, de, di, dO, dw, dL = _ELEMENTS[corps]
    return (a0 + da * t, e0 + de * t, i0 + di * t,
            O0 + dO * t, w0 + dw * t, L0 + dL * t)


def _kepler(M: float, e: float, iterations: int = 12) -> float:
    """Résout E - e*sin(E) = M (équation de Kepler). M, E en radians."""
    E = M if e < 0.8 else math.pi
    for _ in range(iterations):
        dE = (E - e * math.sin(E) - M) / (1 - e * math.cos(E))
        E -= dE
        if abs(dE) < 1e-10:
            break
    return E


def _position_heliocentrique(corps: str, t_tt: float) -> tuple[float, float, float]:
    """Position héliocentrique (x, y, z) en AU dans l'écliptique de la date."""
    a, e, i, O, w, L = _elements_a_t(corps, t_tt)
    M = math.radians(L - w) % (2 * math.pi)
    E = _kepler(M, e)
    # Anomalie vraie
    nu = 2 * math.atan2(math.sqrt(1 + e) * math.sin(E / 2),
                        math.sqrt(1 - e) * math.cos(E / 2))
    r = a * (1 - e * math.cos(E))
    # Position dans le plan orbital
    x_orb = r * math.cos(nu)
    y_orb = r * math.sin(nu)
    # Rotation vers écliptique : argument du périhélie depuis le nœud
    w_rel = math.radians(w - O)
    O_r = math.radians(O)
    i_r = math.radians(i)
    x1 = math.cos(w_rel) * x_orb - math.sin(w_rel) * y_orb
    y1 = math.sin(w_rel) * x_orb + math.cos(w_rel) * y_orb
    x = math.cos(O_r) * x1 - math.sin(O_r) * math.cos(i_r) * y1
    y = math.sin(O_r) * x1 + math.cos(O_r) * math.cos(i_r) * y1
    z = math.sin(i_r) * y1
    return x, y, z


def _longitude_planete(corps: str, ctx: _Contexte) -> float:
    """Longitude géocentrique écliptique d'une planète (deg) via Meeus simplifié."""
    t_tt = (ctx.jj + ctx.delta_t / 86400.0 - 2451545.0) / 36525.0
    # Position héliocentrique de la planète
    px, py, _ = _position_heliocentrique(corps, t_tt)
    # Position héliocentrique de la Terre
    ex, ey, _ = _position_heliocentrique("Terre", t_tt)
    # Géocentrique = planète - Terre
    gx = px - ex
    gy = py - ey
    return math.degrees(math.atan2(gy, gx)) % 360


# ── Lilith (apogée lunaire moyen) + Nœud Nord (nœud lunaire moyen) ─
def _omega_mean_lune(ctx: _Contexte) -> float:
    """Longitude du nœud ascendant moyen de la Lune (deg) — Meeus ch.47."""
    t = ctx.t
    return (125.04452 - 1934.136261 * t + 0.0020708 * t * t
            + t ** 3 / 467411.0 - t ** 4 / 60616000.0) % 360


def _lilith_longitude(ctx: _Contexte) -> float:
    """Lilith = apogée lunaire moyen = Ω_mean + 180° (convention astrologique)."""
    return (_omega_mean_lune(ctx) + 180.0) % 360


def _noeud_nord_longitude(ctx: _Contexte) -> float:
    """Nœud Nord lunaire moyen = Ω_mean (Meeus ch.47)."""
    return _omega_mean_lune(ctx)


def _longitude_brute(corps: str, dt: datetime, utc_offset_h: float) -> float:
    """Longitude écliptique brute (deg) — dispatch interne."""
    if corps == "Soleil":
        return T.soleil_longitude(dt, utc_offset_h)
    if corps == "Lune":
        return T.lune_longitude(dt, utc_offset_h)
    ctx = _contexte(dt, utc_offset_h)
    if corps in _PLANETES_KEPLER:
        return _longitude_planete(corps, ctx)
    if corps == "Lilith":
        return _lilith_longitude(ctx)
    if corps == "Nœud Nord":
        return _noeud_nord_longitude(ctx)
    raise NotImplementedError(f"Corps {corps!r} non implémenté")


def longitude(corps: str, dt: datetime, utc_offset_h: float,
              latitude: float, longitude_geo: float) -> dict:
    """Retourne {corps, longitude, latitude, distance_au, vitesse_deg_j,
    retrograde, methode}."""
    if corps not in CORPS:
        raise ValueError(f"Corps inconnu : {corps!r}")
    lon = _longitude_brute(corps, dt, utc_offset_h)
    vitesse, retro = _vitesse_et_retro(corps, dt, utc_offset_h, lon)
    methodes = {"Soleil": "meeus_soleil", "Lune": "elp_abrege",
                "Mercure": "meeus_kepler", "Vénus": "meeus_kepler",
                "Mars": "meeus_kepler", "Jupiter": "meeus_kepler",
                "Saturne": "meeus_kepler", "Uranus": "meeus_kepler",
                "Neptune": "meeus_kepler", "Pluton": "meeus_kepler",
                "Chiron": "meeus_kepler", "Lilith": "lilith_moyenne",
                "Nœud Nord": "noeud_lunaire_moyen"}
    return {
        "corps": corps,
        "longitude": round(lon % 360, 6),
        "latitude": 0.0,
        "distance_au": 0.0,
        "vitesse_deg_j": round(vitesse, 4),
        "retrograde": retro,
        "methode": methodes.get(corps, "inconnu"),
    }


def positions(dt: datetime, utc_offset_h: float,
              latitude: float, longitude_geo: float) -> dict[str, dict]:
    """Tous les CORPS d'un coup (réutilise le contexte calculé une fois)."""
    return {corps: longitude(corps, dt, utc_offset_h, latitude, longitude_geo)
            for corps in CORPS}
