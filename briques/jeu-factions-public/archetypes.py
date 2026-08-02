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
# Plafond exprimé en heures d'absence maximum prises en compte (variable d'env historique
# `TICK_INTERVAL_HOURS`, conservée telle quelle — S218 a retiré la résolution passive par tick
# et le module `tick.py` qui la portait, mais le nom de la variable reste un réglage valide et
# déployé, sans lien de couplage avec un autre module désormais).
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

_DIFFICULTES = (80, 140, 200)

_CONTENU_VOIE: dict[str, tuple[tuple[str, str], tuple[str, str], tuple[str, str]]] = {
    "Le Stratège Solitaire": (
        ("L'ombre qui observe",
         "Loin des regards, il apprend à lire les intentions avant qu'elles ne se déclarent "
         "— le premier plan se dessine dans le silence."),
        ("Le piège du doute",
         "Un calcul mal posé, une alliance qui vacille : la solitude choisie devient un poids "
         "avant de redevenir une arme."),
        ("L'échiquier maîtrisé",
         "Toutes les pièces sont enfin à leur place — la victoire qu'il vient de remporter, "
         "personne d'autre n'aurait pu la voir venir."),
    ),
    "Le Meneur Charismatique": (
        ("Le premier cercle",
         "Sa voix rassemble avant même qu'il ait fini de parler — les premiers alliés se "
         "rangent derrière une promesse encore floue."),
        ("La foule qui doute",
         "Un discours qui tombe à plat, une loyauté qui vacille : mener, c'est aussi tenir "
         "quand plus personne n'écoute."),
        ("Le serment scellé",
         "Debout devant tous ceux qui l'ont suivi jusque-là, il transforme enfin la promesse "
         "du début en une cause commune."),
    ),
    "Le Sage Contemplatif": (
        ("Le silence qui enseigne",
         "Il apprend à ne pas répondre tout de suite — la première leçon de cette voie est "
         "de savoir attendre."),
        ("Le vertige des certitudes",
         "Une vérité qu'il croyait acquise se fissure ; la sagesse véritable commence là où "
         "les réponses faciles s'arrêtent."),
        ("L'équilibre retrouvé",
         "Ce qu'il cherchait n'était pas une réponse, mais une manière de tenir debout au "
         "milieu du doute — il l'a enfin trouvée."),
    ),
    "L'Artiste Visionnaire": (
        ("L'esquisse d'un monde",
         "Une image lui vient, encore imparfaite, mais assez forte pour qu'il refuse de la "
         "laisser filer — tout commence par ce premier trait."),
        ("La toile qui résiste",
         "L'œuvre ne ressemble plus à ce qu'il avait imaginé ; il doit apprendre à aimer ce "
         "qu'elle est devenue malgré lui."),
        ("L'œuvre achevée",
         "Ce qu'il a créé ne lui appartient plus tout à fait — et c'est précisément ce qui "
         "en fait une vraie œuvre."),
    ),
    "Le Gardien Loyal": (
        ("Le premier serment",
         "Il choisit ce qu'il protégera, sans savoir encore ce que ce choix lui coûtera — "
         "la garde commence par une promesse silencieuse."),
        ("La brèche dans le mur",
         "Ce qu'il devait protéger a failli lui échapper ; la loyauté se mesure au moment "
         "où tenir devient difficile."),
        ("Le rempart tenu",
         "Il est toujours là où il avait dit qu'il serait — et c'est cette constance, plus "
         "que la force, qui a fini par convaincre."),
    ),
    "L'Aventurier Indomptable": (
        ("Le départ sans retour",
         "Il part sans plan précis, porté par une énergie qu'il ne cherche pas encore à "
         "expliquer — la route se fera en marchant."),
        ("Le mur imprévu",
         "Un obstacle qu'aucune carte n'annonçait ; l'élan seul ne suffit plus, il faut "
         "apprendre à s'arrêter pour mieux repartir."),
        ("L'horizon conquis",
         "Ce qu'il cherchait n'était jamais une destination précise — c'est l'endurance de "
         "la quête elle-même qu'il vient de prouver."),
    ),
    "Le Diplomate Sensible": (
        ("Le premier accord",
         "Il sent avant de comprendre ce qui oppose les autres — et trouve, presque sans "
         "effort, le mot qui apaise."),
        ("La rupture évitée de justesse",
         "Un malentendu grandit plus vite que sa patience ; concilier deux camps qui ne "
         "veulent plus s'entendre, c'est une autre affaire."),
        ("La paix qui tient",
         "L'accord qu'il a bâti ne repose pas sur un compromis fragile — les deux camps y "
         "ont vraiment gagné quelque chose."),
    ),
    "Le Bâtisseur Méthodique": (
        ("La première pierre",
         "Rien ne presse : il pose une fondation avant même de savoir à quoi ressemblera "
         "l'édifice qu'elle portera."),
        ("La fissure imprévue",
         "Un plan pourtant solide se fend à l'endroit qu'il avait jugé le plus sûr — la "
         "méthode doit apprendre à douter d'elle-même."),
        ("L'édifice debout",
         "Ce qu'il a construit résistera longtemps après lui — patience et rigueur, pierre "
         "après pierre, ont fini par payer."),
    ),
    "L'Âme Empathique": (
        ("Le premier chagrin porté",
         "Elle ressent la peine d'un autre presque comme la sienne — et découvre, un peu "
         "inquiète, jusqu'où va cette porosité."),
        ("Le poids des autres",
         "Porter ce que ressentent tous ceux qu'elle croise a un prix ; apprendre à se "
         "protéger sans cesser d'écouter, c'est l'épreuve."),
        ("La présence qui apaise",
         "Elle n'a rien résolu à la place de personne — mais tous ceux qu'elle a accompagnés "
         "se sentent, enfin, moins seuls."),
    ),
    "L'Électron Libre": (
        ("Le premier écart",
         "Elle s'éloigne du chemin tracé sans bien savoir où l'autre mène — juste assez "
         "curieuse pour ne pas faire demi-tour."),
        ("La cage bien intentionnée",
         "Ceux qui l'aiment voudraient la voir se fixer ; refuser gentiment un cadre qui se "
         "referme, c'est là toute l'épreuve."),
        ("La liberté assumée",
         "Elle n'a suivi aucune route tracée par quelqu'un d'autre — et c'est exactement la "
         "vie qu'elle voulait construire."),
    ),
}


def seed_zones_archetype() -> None:
    """Idempotent ET self-healing : la vérification d'existence porte sur (archetype, ordre)
    — la vraie clé d'unicité de la table — pas sur l'archetype seul. Une ligne déjà présente
    est mise à jour (nom/lore/difficulté) plutôt que sautée, pour que du contenu narratif
    révisé (S219) atteigne aussi une DB déjà seedée par une version antérieure de ce fichier."""
    with S._conn() as c:
        for archetype in ARCHETYPES_SIGNATURE:
            contenu = _CONTENU_VOIE[archetype]
            for ordre, difficulte in enumerate(_DIFFICULTES, start=1):
                nom, lore = contenu[ordre - 1]
                existe = c.execute(
                    "SELECT id FROM zones_archetype WHERE archetype=? AND ordre=?",
                    (archetype, ordre)).fetchone()
                if existe:
                    c.execute("""UPDATE zones_archetype
                                 SET nom=?, texte_lore=?, difficulte_pve=? WHERE id=?""",
                              (nom, lore, difficulte, existe["id"]))
                    continue
                c.execute("""INSERT INTO zones_archetype
                             (id, archetype, ordre, nom, difficulte_pve, texte_lore)
                             VALUES (?,?,?,?,?,?)""",
                          (uuid.uuid4().hex, archetype, ordre, nom, difficulte, lore))


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
