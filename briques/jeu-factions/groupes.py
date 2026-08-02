"""Groupes ouverts sur une voie d'archétype — n'importe qui peut rejoindre pour aider
(« carry »), mais seuls les membres pour qui l'étape ciblée est EXACTEMENT leur propre
prochaine étape voient leur progression avancer (pas de saut, pas de re-completion)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import archetypes as A
import stockage as S


def _maintenant() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ligne_groupe(c, groupe_id: str) -> dict:
    g = c.execute("SELECT * FROM groupes WHERE id=?", (groupe_id,)).fetchone()
    membres = [r["personnage_id"] for r in
              c.execute("SELECT personnage_id FROM membres_groupe WHERE groupe_id=?",
                       (groupe_id,)).fetchall()]
    return {"id": g["id"], "personnage_cible_id": g["personnage_cible_id"],
            "zone_archetype_id": g["zone_archetype_id"], "etat": g["etat"],
            "cree_le": g["cree_le"], "membres": membres}


def creer_groupe(personnage_cible_id: str, zone_archetype_id: str) -> dict:
    etape = A.lire_etape(zone_archetype_id)
    if not etape:
        raise ValueError("Étape d'archétype introuvable.")
    attendu = A.prochaine_etape(personnage_cible_id, etape["archetype"])
    if attendu != zone_archetype_id:
        raise ValueError("Cette étape n'est pas la prochaine de ce personnage sur cette voie.")
    gid = uuid.uuid4().hex
    cree_le = _maintenant()
    with S._conn() as c:
        c.execute("""INSERT INTO groupes (id, personnage_cible_id, zone_archetype_id, etat, cree_le)
                     VALUES (?,?,?, 'actif', ?)""",
                  (gid, personnage_cible_id, zone_archetype_id, cree_le))
        c.execute("INSERT INTO membres_groupe (groupe_id, personnage_id) VALUES (?,?)",
                 (gid, personnage_cible_id))
        return _ligne_groupe(c, gid)


def rejoindre_groupe(groupe_id: str, personnage_id: str) -> dict:
    with S._conn() as c:
        g = c.execute("SELECT etat FROM groupes WHERE id=?", (groupe_id,)).fetchone()
        if not g:
            raise ValueError("Groupe introuvable.")
        if g["etat"] != "actif":
            raise ValueError("Ce groupe n'est plus actif (déjà résolu ou dissous).")
        c.execute("INSERT OR IGNORE INTO membres_groupe (groupe_id, personnage_id) VALUES (?,?)",
                 (groupe_id, personnage_id))
        return _ligne_groupe(c, groupe_id)


def lire_groupe(groupe_id: str) -> dict | None:
    with S._conn() as c:
        existe = c.execute("SELECT 1 FROM groupes WHERE id=?", (groupe_id,)).fetchone()
        if not existe:
            return None
        return _ligne_groupe(c, groupe_id)


def dissoudre_groupes_de_letape(zone_archetype_id: str, personnages_progresses: list[str]) -> None:
    """Appelée par `combat.persister_evenements` (contexte archétype) à la mort du boss d'une
    étape : dissout uniquement les groupes dont la cible fait partie de `personnages_progresses`
    (ceux dont c'était réellement leur propre prochaine étape, cf. la règle carry appliquée
    par l'appelant) — les groupes d'autres personnes visant la même étape, mais qui n'ont pas
    elles-mêmes progressé, restent actifs (cloisonnement par propriétaire, cf. README)."""
    if not personnages_progresses:
        return
    with S._conn() as c:
        marks = ",".join("?" for _ in personnages_progresses)
        c.execute(f"""UPDATE groupes SET etat='dissous'
                      WHERE zone_archetype_id=? AND etat='actif'
                      AND personnage_cible_id IN ({marks})""",
                  (zone_archetype_id, *personnages_progresses))
