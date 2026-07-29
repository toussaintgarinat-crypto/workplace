"""Voies d'archétype (PvE personnel + groupe) — 10 archétypes, chacun une suite d'étapes
ordonnées non-rejouables. `ARCHETYPES_SIGNATURE` mirrore `personnages/synthese.py::_ARCHETYPES`
(donnée de référence : quelles 3 stats définissent chaque archétype — pas un recalcul)."""
from __future__ import annotations

import uuid

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


def seed_competences() -> None:
    with S._conn() as c:
        etapes = c.execute("SELECT * FROM zones_archetype").fetchall()
        for e in etapes:
            existe = c.execute(
                "SELECT 1 FROM competences WHERE archetype=? AND ordre_etape=?",
                (e["archetype"], e["ordre"])).fetchone()
            if existe:
                continue
            c.execute("""INSERT INTO competences (id, nom, texte, archetype, ordre_etape)
                         VALUES (?,?,?,?,?)""",
                      (uuid.uuid4().hex, f"Compétence — {e['nom']}",
                       f"Débloquée en achevant « {e['nom']} ». Effet à définir (spec combat).",
                       e["archetype"], e["ordre"]))


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
                        difficulte: int) -> dict:
    """Fonction PURE : `membres_stats` = [{"personnage_id", "stats": {...}}]."""
    total = sum(sum(int(m["stats"].get(s, 0)) for s in stats_cles) for m in membres_stats)
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


def lister_competences_debloquees(personnage_id: str) -> list[dict]:
    with S._conn() as c:
        rows = c.execute("""SELECT c.id, c.nom, c.texte, c.archetype, c.ordre_etape, cd.date
                            FROM competences_debloquees cd JOIN competences c ON c.id = cd.competence_id
                            WHERE cd.personnage_id=? ORDER BY cd.date""", (personnage_id,)).fetchall()
    return [{"id": r["id"], "nom": r["nom"], "texte": r["texte"], "archetype": r["archetype"],
             "ordre_etape": r["ordre_etape"], "date": r["date"]} for r in rows]
