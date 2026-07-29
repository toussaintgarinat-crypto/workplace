"""Voies d'archétype (PvE personnel + groupe) — 10 archétypes, chacun une suite d'étapes
ordonnées non-rejouables. `ARCHETYPES_SIGNATURE` mirrore `personnages/synthese.py::_ARCHETYPES`
(donnée de référence : quelles 3 stats définissent chaque archétype — pas un recalcul)."""
from __future__ import annotations

import os
import uuid
from datetime import datetime

import stockage as S

ARCHETYPES_SIGNATURE: dict[str, tuple[str, str, str]] = {
    "Le Stratège Solitaire": ("Discrétion", "Sagesse", "Combativité"),
    "Le Meneur Charismatique": ("Charisme", "Combativité", "Énergie"),
    "Le Sage Contemplatif": ("Sagesse", "Discrétion", "Stabilité"),
    "L'Artiste Visionnaire": ("Créativité", "Émotivité", "Charisme"),
    "Le Gardien Loyal": ("Stabilité", "Émotivité", "Sagesse"),
    "L'Aventurier Indomptable": ("Énergie", "Combativité", "Charisme"),
    "Le Diplomate Sensible": ("Charisme", "Émotivité", "Sagesse"),
    "Le Bâtisseur Méthodique": ("Stabilité", "Combativité", "Discrétion"),
    "L'Âme Empathique": ("Émotivité", "Sagesse", "Créativité"),
    "L'Électron Libre": ("Créativité", "Énergie", "Discrétion"),
}

# S216 — progression idle : bonus de points de voie d'archétype pendant l'absence.
# Plafonné à un cycle de tick (même variable d'env que `tick.TICK_INTERVAL_HOURS`, lue ici
# indépendamment pour éviter un import circulaire archetypes -> tick -> groupes -> archetypes).
TAUX_IDLE_PAR_HEURE = 2.0
PLAFOND_IDLE_HEURES = float(os.getenv("TICK_INTERVAL_HOURS", "24"))


def bonus_idle(derniere_presence: str | None, maintenant: datetime,
               taux_par_heure: float, plafond_heures: float) -> int:
    """Fonction PURE : points de progression accumulés depuis `derniere_presence`, plafonnés
    à `plafond_heures` d'absence. `derniere_presence=None` (jamais de heartbeat) -> 0."""
    if not derniere_presence:
        return 0
    depuis = datetime.fromisoformat(derniere_presence)
    heures_ecoulees = (maintenant - depuis).total_seconds() / 3600
    if heures_ecoulees <= 0:
        return 0
    return int(taux_par_heure * min(heures_ecoulees, plafond_heures))

# 3 étapes par voie pour la V1 — contenu narratif à enrichir plus tard (mécanique déjà complète).
_DIFFICULTES = (80, 140, 200)
_LORE_GENERIQUE = (
    "Un premier signe se manifeste — l'appel de la voie {archetype} se fait sentir.",
    "L'épreuve s'intensifie : {archetype} doit affronter le doute avant de continuer.",
    "Le dernier seuil : accomplir ce que {archetype} porte en lui depuis le début.",
)


def seed_zones_archetype() -> None:
    with S._conn() as c:
        for archetype in ARCHETYPES_SIGNATURE:
            existe = c.execute(
                "SELECT 1 FROM zones_archetype WHERE archetype=?", (archetype,)).fetchone()
            if existe:
                continue
            for ordre, (difficulte, lore) in enumerate(zip(_DIFFICULTES, _LORE_GENERIQUE), start=1):
                c.execute("""INSERT INTO zones_archetype
                             (id, archetype, ordre, nom, difficulte_pve, texte_lore)
                             VALUES (?,?,?,?,?,?)""",
                          (uuid.uuid4().hex, archetype, ordre,
                           f"{archetype} — étape {ordre}", difficulte,
                           lore.format(archetype=archetype)))


EFFETS_PAR_ETAPE: dict[int, dict] = {
    1: {"effet_type": "degats", "magnitude": 20, "portee": 120, "cooldown_s": 3.0},
    2: {"effet_type": "soin", "magnitude": 15, "portee": 100, "cooldown_s": 6.0},
    3: {"effet_type": "bouclier", "magnitude": 30, "portee": 80, "cooldown_s": 10.0},
}


def seed_competences() -> None:
    with S._conn() as c:
        etapes = c.execute("SELECT * FROM zones_archetype").fetchall()
        for e in etapes:
            effet = EFFETS_PAR_ETAPE.get(e["ordre"])
            if effet is None:
                continue
            existe = c.execute(
                "SELECT id, effet_type FROM competences WHERE archetype=? AND ordre_etape=?",
                (e["archetype"], e["ordre"])).fetchone()
            if existe:
                if existe["effet_type"] is None:
                    c.execute("""UPDATE competences
                                 SET effet_type=?, magnitude=?, portee=?, cooldown_s=?
                                 WHERE id=?""",
                              (effet["effet_type"], effet["magnitude"], effet["portee"],
                               effet["cooldown_s"], existe["id"]))
                continue
            c.execute("""INSERT INTO competences
                         (id, nom, texte, archetype, ordre_etape, effet_type, magnitude,
                          portee, cooldown_s)
                         VALUES (?,?,?,?,?,?,?,?,?)""",
                      (uuid.uuid4().hex, f"Compétence — {e['nom']}",
                       f"Débloquée en achevant « {e['nom']} ». "
                       f"Effet : {effet['effet_type']} ({effet['magnitude']}).",
                       e["archetype"], e["ordre"], effet["effet_type"], effet["magnitude"],
                       effet["portee"], effet["cooldown_s"]))


def lister_toutes_competences_avec_effet() -> dict[str, dict]:
    with S._conn() as c:
        rows = c.execute(
            "SELECT id, effet_type, magnitude, portee, cooldown_s FROM competences "
            "WHERE effet_type IS NOT NULL").fetchall()
    return {r["id"]: {"effet_type": r["effet_type"], "magnitude": r["magnitude"],
                      "portee": r["portee"], "cooldown_s": r["cooldown_s"]} for r in rows}


def _ligne_etape(r) -> dict:
    return {"id": r["id"], "archetype": r["archetype"], "ordre": r["ordre"], "nom": r["nom"],
            "difficulte_pve": r["difficulte_pve"], "texte_lore": r["texte_lore"]}


def lister_etapes(archetype: str) -> list[dict]:
    with S._conn() as c:
        rows = c.execute(
            "SELECT * FROM zones_archetype WHERE archetype=? ORDER BY ordre", (archetype,)).fetchall()
    return [_ligne_etape(r) for r in rows]


def lire_etape(zone_archetype_id: str) -> dict | None:
    with S._conn() as c:
        r = c.execute("SELECT * FROM zones_archetype WHERE id=?", (zone_archetype_id,)).fetchone()
    return _ligne_etape(r) if r else None


def prochaine_etape(personnage_id: str, archetype: str) -> str | None:
    """La première étape (ordre croissant) de cette voie qui n'est pas encore `vaincue`
    pour ce personnage. Une étape sans ligne de progression compte comme non-vaincue."""
    with S._conn() as c:
        etapes = c.execute(
            "SELECT id FROM zones_archetype WHERE archetype=? ORDER BY ordre", (archetype,)).fetchall()
        for e in etapes:
            row = c.execute(
                "SELECT etat FROM progression_archetype WHERE personnage_id=? AND zone_archetype_id=?",
                (personnage_id, e["id"])).fetchone()
            if row is None or row["etat"] != "vaincue":
                return e["id"]
    return None


def calculer_resolution(membres_stats: list[dict], stats_cles: tuple[str, str, str],
                        difficulte: int, bonus_par_membre: dict[str, int] | None = None) -> dict:
    """Fonction PURE : `membres_stats` = [{"personnage_id", "stats": {...}}].
    `bonus_par_membre` (S216 idle) ajoute des points à la contribution d'un membre précis
    avant sommation — absent de `membres_stats` -> ignoré silencieusement."""
    bonus_par_membre = bonus_par_membre or {}
    total = sum(sum(int(m["stats"].get(s, 0)) for s in stats_cles) +
               bonus_par_membre.get(m["personnage_id"], 0)
               for m in membres_stats)
    return {"total": total, "vaincue": total >= difficulte}


def marquer_etape_vaincue(personnage_id: str, zone_archetype_id: str) -> None:
    with S._conn() as c:
        c.execute("""INSERT INTO progression_archetype
                     (personnage_id, zone_archetype_id, etat, date_completion)
                     VALUES (?,?, 'vaincue', datetime('now'))
                     ON CONFLICT(personnage_id, zone_archetype_id) DO UPDATE SET
                     etat='vaincue', date_completion=datetime('now')""",
                  (personnage_id, zone_archetype_id))


def debloquer_competence_si_existe(personnage_id: str, zone_archetype_id: str) -> None:
    with S._conn() as c:
        etape = c.execute("SELECT archetype, ordre FROM zones_archetype WHERE id=?",
                          (zone_archetype_id,)).fetchone()
        if not etape:
            return
        comp = c.execute("SELECT id FROM competences WHERE archetype=? AND ordre_etape=?",
                         (etape["archetype"], etape["ordre"])).fetchone()
        if not comp:
            return
        c.execute("""INSERT OR IGNORE INTO competences_debloquees
                     (personnage_id, competence_id, date) VALUES (?,?, datetime('now'))""",
                  (personnage_id, comp["id"]))


def lister_progressions_personnage(personnage_id: str) -> list[dict]:
    """Toute la progression connue d'un personnage, toutes voies d'archétype confondues."""
    with S._conn() as c:
        rows = c.execute(
            "SELECT p.zone_archetype_id, p.etat, p.date_completion, z.archetype, z.ordre, z.nom "
            "FROM progression_archetype p JOIN zones_archetype z ON z.id = p.zone_archetype_id "
            "WHERE p.personnage_id=? ORDER BY z.archetype, z.ordre", (personnage_id,)).fetchall()
    return [{"archetype": r["archetype"], "ordre": r["ordre"], "nom": r["nom"],
             "etat": r["etat"], "date_completion": r["date_completion"]} for r in rows]


def lister_competences_debloquees(personnage_id: str) -> list[dict]:
    with S._conn() as c:
        rows = c.execute("""SELECT c.id, c.nom, c.texte, c.archetype, c.ordre_etape, cd.date
                            FROM competences_debloquees cd JOIN competences c ON c.id = cd.competence_id
                            WHERE cd.personnage_id=? ORDER BY cd.date""", (personnage_id,)).fetchall()
    return [{"id": r["id"], "nom": r["nom"], "texte": r["texte"], "archetype": r["archetype"],
             "ordre_etape": r["ordre_etape"], "date": r["date"]} for r in rows]
