# S218+S219 — Quêtes jouées + contenu narratif (jeu-factions) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Faire de chaque étape de voie d'archétype un vrai combat joué (réutilisant
`combat_moteur.py`/`combat.py`, comme pour les zones de signe) au lieu d'une comparaison de
stats côté groupe, ET remplacer le lore générique par 30 textes narratifs réels.

**Architecture:** Une nouvelle table `mobs_zone_archetype` fournit des gabarits de mobs
dédiés par étape (30 lignes, une par archétype×ordre). `combat_moteur.py` gagne un paramètre
`cle_contribution` (défaut = `signe`) qui permet de bucketer les dégâts par `personnage_id`
plutôt que par guilde/signe — zéro changement de comportement pour les zones (défaut inchangé),
et bucketing par personnage pour les voies. `combat.py` gagne un `contexte` ("zone" ou
"archetype") sur chaque instance, qui détermine quelle logique de persistance
`persister_evenements` applique (score de zone vs. progression de voie + dissolution de
groupe). Une nouvelle route WebSocket `/groupes/{groupe_id}/combat` ouvre l'instance ; le
bonus idle (S216) s'y applique en dégâts immédiats au boss à l'entrée, au lieu d'être calculé
dans l'ancien `groupes.resoudre_groupes_actifs()` (retiré, comme `zones.resoudre_toutes_zones`
l'a été avant lui). `tick.py` devient sans objet et est supprimé.

**Tech Stack:** Python 3.11+, FastAPI, SQLite (stdlib `sqlite3`), pytest (+ `pytest-asyncio`
en mode auto — voir `test_combat.py` existant, aucun marqueur explicite).

## Global Constraints

- Toutes les fonctions DB utilisent des connexions courtes (`with S._conn() as c:`) — jamais
  une connexion tenue ouverte pendant un appel imbriqué vers un autre module (verrouillage
  SQLite, cf. docstring `groupes.py`).
- `combat_moteur.py` reste PUR : zéro I/O, zéro horloge système lue directement.
- Comportement des zones de signe (contexte `"zone"`) doit rester bit-à-bit identique après
  ce plan — tous les tests `test_combat.py`/`test_combat_moteur.py` existants passent SANS
  modification.
- Noms de fonctions/variables en français, style déjà établi (voir fichiers existants).
- Un test par comportement, jamais de `# TODO`.

---

### Task 1: Contenu narratif réel (S219) — `archetypes.py`

**Files:**
- Modify: `briques/jeu-factions/archetypes.py:44-66`
- Test: `briques/jeu-factions/test_archetypes.py`

**Interfaces:**
- Consumes: rien de nouveau.
- Produces: `archetypes._CONTENU_VOIE: dict[str, tuple[tuple[str,str], tuple[str,str], tuple[str,str]]]`
  (archétype -> 3× (nom, texte_lore)) — consommé par `mobs_archetype.py` (Task 3) pour nommer
  les boss par étape.

- [ ] **Step 1: Écrire le test qui échoue**

Ajouter à la fin de `test_archetypes.py` :

```python
def test_seed_zones_archetype_a_un_contenu_narratif_distinct_par_archetype():
    A.seed_zones_archetype()
    noms = set()
    for archetype in A.ARCHETYPES_SIGNATURE:
        for e in A.lister_etapes(archetype):
            assert "étape" not in e["nom"].lower()
            noms.add(e["nom"])
    assert len(noms) == 30  # aucun texte dupliqué entre archétypes/étapes
```

- [ ] **Step 2: Vérifier l'échec**

Run: `cd briques/jeu-factions && python -m pytest test_archetypes.py::test_seed_zones_archetype_a_un_contenu_narratif_distinct_par_archetype -v`
Expected: FAIL (le nom contient toujours "étape N").

- [ ] **Step 3: Remplacer `_LORE_GENERIQUE` par le contenu réel**

Remplacer dans `archetypes.py` les lignes 44-66 (de `_DIFFICULTES = ...` à la fin de
`seed_zones_archetype`) par :

```python
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
    with S._conn() as c:
        for archetype in ARCHETYPES_SIGNATURE:
            existe = c.execute(
                "SELECT 1 FROM zones_archetype WHERE archetype=?", (archetype,)).fetchone()
            if existe:
                continue
            contenu = _CONTENU_VOIE[archetype]
            for ordre, difficulte in enumerate(_DIFFICULTES, start=1):
                nom, lore = contenu[ordre - 1]
                c.execute("""INSERT INTO zones_archetype
                             (id, archetype, ordre, nom, difficulte_pve, texte_lore)
                             VALUES (?,?,?,?,?,?)""",
                          (uuid.uuid4().hex, archetype, ordre, nom, difficulte, lore))
```

Le commentaire `# 3 étapes par voie pour la V1 — contenu narratif à enrichir plus tard` doit
être retiré (dette soldée).

- [ ] **Step 4: Vérifier que le test passe, puis tout le fichier**

Run: `cd briques/jeu-factions && python -m pytest test_archetypes.py -v`
Expected: tous les tests PASS (30 lignes, 30 noms distincts, `test_seed_est_idempotent`
toujours vert).

- [ ] **Step 5: Commit**

```bash
git add briques/jeu-factions/archetypes.py briques/jeu-factions/test_archetypes.py
git commit -m "feat(jeu-factions): S219 — 30 textes de lore réels remplacent _LORE_GENERIQUE"
```

---

### Task 2: Table `mobs_zone_archetype` — `stockage.py`

**Files:**
- Modify: `briques/jeu-factions/stockage.py:52-56`

**Interfaces:**
- Produces: table SQLite `mobs_zone_archetype(id, zone_archetype_id, nom, role, pv_max,
  degats_attaque, cooldown_attaque_s, portee_aggro, portee_attaque)` — consommée par
  `mobs_archetype.py` (Task 3).

- [ ] **Step 1: Ajouter la table**

Dans `stockage.py`, juste après le bloc `CREATE TABLE IF NOT EXISTS mobs_zone` (ligne 56),
ajouter :

```python
    c.execute("""CREATE TABLE IF NOT EXISTS mobs_zone_archetype (
        id TEXT PRIMARY KEY, zone_archetype_id TEXT NOT NULL, nom TEXT NOT NULL,
        role TEXT NOT NULL, pv_max INTEGER NOT NULL, degats_attaque INTEGER NOT NULL,
        cooldown_attaque_s REAL NOT NULL, portee_aggro INTEGER NOT NULL,
        portee_attaque INTEGER NOT NULL)""")
```

- [ ] **Step 2: Vérifier que rien ne casse**

Run: `cd briques/jeu-factions && python -m pytest test_archetypes.py test_zones.py test_mobs.py -v`
Expected: tous PASS (la nouvelle table est `CREATE TABLE IF NOT EXISTS`, sans effet sur
l'existant).

- [ ] **Step 3: Commit**

```bash
git add briques/jeu-factions/stockage.py
git commit -m "feat(jeu-factions): table mobs_zone_archetype pour les gabarits de mobs par étape (S218)"
```

---

### Task 3: `mobs_archetype.py` — gabarits de mobs dédiés par étape

**Files:**
- Create: `briques/jeu-factions/mobs_archetype.py`
- Test: `briques/jeu-factions/test_mobs_archetype.py`

**Interfaces:**
- Consumes: `archetypes.seed_zones_archetype()`/`archetypes.lister_etapes()` (Task 1),
  table `mobs_zone_archetype` (Task 2).
- Produces: `mobs_archetype.seed_mobs_archetype() -> None`,
  `mobs_archetype.lister_mobs_etape(zone_archetype_id: str) -> list[dict]` (même forme de
  dict que `mobs.lister_mobs_zone`, avec `zone_archetype_id` au lieu de `zone_id`) —
  consommé par la route WebSocket de Task 8.

- [ ] **Step 1: Écrire le test qui échoue**

Créer `briques/jeu-factions/test_mobs_archetype.py` :

```python
import archetypes
import mobs_archetype as MA


def _etape_fixture():
    archetypes.seed_zones_archetype()
    return archetypes.lister_etapes("Le Meneur Charismatique")[0]


def test_seed_mobs_archetype_cree_un_boss_et_deux_mobs_par_etape():
    etape = _etape_fixture()
    MA.seed_mobs_archetype()
    gabarits = MA.lister_mobs_etape(etape["id"])
    assert len(gabarits) == 3
    assert sum(1 for g in gabarits if g["role"] == "boss") == 1
    assert sum(1 for g in gabarits if g["role"] == "mob") == 2


def test_seed_mobs_archetype_est_idempotent():
    etape = _etape_fixture()
    MA.seed_mobs_archetype()
    MA.seed_mobs_archetype()
    assert len(MA.lister_mobs_etape(etape["id"])) == 3


def test_seed_mobs_archetype_couvre_les_30_etapes():
    archetypes.seed_zones_archetype()
    MA.seed_mobs_archetype()
    total = 0
    for arch in archetypes.ARCHETYPES_SIGNATURE:
        for e in archetypes.lister_etapes(arch):
            total += len(MA.lister_mobs_etape(e["id"]))
    assert total == 30 * 3


def test_boss_plus_difficile_a_plus_de_pv_que_letape_precedente():
    archetypes.seed_zones_archetype()
    MA.seed_mobs_archetype()
    etapes = archetypes.lister_etapes("Le Meneur Charismatique")
    pv = []
    for e in etapes:
        boss = next(g for g in MA.lister_mobs_etape(e["id"]) if g["role"] == "boss")
        pv.append(boss["pv_max"])
    assert pv[0] < pv[1] < pv[2]


def test_lister_mobs_etape_inconnue_est_vide():
    assert MA.lister_mobs_etape("inconnue") == []


def test_nom_du_boss_reprend_le_titre_de_letape():
    etape = _etape_fixture()
    MA.seed_mobs_archetype()
    boss = next(g for g in MA.lister_mobs_etape(etape["id"]) if g["role"] == "boss")
    assert etape["nom"] in boss["nom"]
```

- [ ] **Step 2: Vérifier l'échec**

Run: `cd briques/jeu-factions && python -m pytest test_mobs_archetype.py -v`
Expected: FAIL avec `ModuleNotFoundError: No module named 'mobs_archetype'`.

- [ ] **Step 3: Écrire l'implémentation**

Créer `briques/jeu-factions/mobs_archetype.py` :

```python
"""Mobs/boss de combat par étape de voie d'archétype — même motif que mobs.py, mais une
ligne dédiée par étape (zone_archetype_id) plutôt que par zone_id (S218). Les stats sont
dérivées de difficulte_pve (seule variable réelle entre étapes d'un même archétype) ; le nom
du boss reprend le titre de l'étape (cf. archetypes.py, contenu narratif S219)."""
from __future__ import annotations

import uuid

import stockage as S


def _gabarit_boss_etape(difficulte: int, nom_etape: str) -> tuple:
    return ("boss", f"{nom_etape} — Gardien", difficulte * 3, max(8, difficulte // 8),
            1.5, difficulte + 140, 30)


def _gabarits_mobs_etape(difficulte: int) -> list[tuple]:
    pv = max(30, difficulte // 3)
    degats = max(4, difficulte // 20)
    return [("mob", "Disciple de la voie", pv, degats, 1.0, difficulte + 70, 25),
            ("mob", "Disciple de la voie", pv, degats, 1.0, difficulte + 70, 25)]


def seed_mobs_archetype() -> None:
    with S._conn() as c:
        etapes = c.execute("SELECT id, nom, difficulte_pve FROM zones_archetype").fetchall()
        for e in etapes:
            existe = c.execute(
                "SELECT 1 FROM mobs_zone_archetype WHERE zone_archetype_id=?",
                (e["id"],)).fetchone()
            if existe:
                continue
            gabarits = [_gabarit_boss_etape(e["difficulte_pve"], e["nom"]),
                        *_gabarits_mobs_etape(e["difficulte_pve"])]
            for role, nom, pv_max, degats, cooldown, aggro, portee in gabarits:
                c.execute("""INSERT INTO mobs_zone_archetype
                             (id, zone_archetype_id, nom, role, pv_max, degats_attaque,
                              cooldown_attaque_s, portee_aggro, portee_attaque)
                             VALUES (?,?,?,?,?,?,?,?,?)""",
                          (uuid.uuid4().hex, e["id"], nom, role, pv_max, degats,
                           cooldown, aggro, portee))


def _ligne_mob(r) -> dict:
    return {"id": r["id"], "zone_archetype_id": r["zone_archetype_id"], "nom": r["nom"],
            "role": r["role"], "pv_max": r["pv_max"], "degats_attaque": r["degats_attaque"],
            "cooldown_attaque_s": r["cooldown_attaque_s"], "portee_aggro": r["portee_aggro"],
            "portee_attaque": r["portee_attaque"]}


def lister_mobs_etape(zone_archetype_id: str) -> list[dict]:
    with S._conn() as c:
        rows = c.execute(
            "SELECT * FROM mobs_zone_archetype WHERE zone_archetype_id=? ORDER BY role DESC",
            (zone_archetype_id,)).fetchall()
    return [_ligne_mob(r) for r in rows]
```

- [ ] **Step 4: Vérifier que les tests passent**

Run: `cd briques/jeu-factions && python -m pytest test_mobs_archetype.py -v`
Expected: 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add briques/jeu-factions/mobs_archetype.py briques/jeu-factions/test_mobs_archetype.py
git commit -m "feat(jeu-factions): mobs_archetype — gabarits de mobs dédiés par étape de voie (S218)"
```

---

### Task 4: `combat_moteur.py` — bucketing par `cle_contribution` + bonus idle

**Files:**
- Modify: `briques/jeu-factions/combat_moteur.py:46-53` (`ajouter_joueur`), `:141-157`
  (bucketing dégâts/DOT), ajout d'une fonction après `_infliger_degats` (ligne 84).
- Test: `briques/jeu-factions/test_combat_moteur.py`

**Interfaces:**
- Consumes: rien de nouveau.
- Produces: `combat_moteur.ajouter_joueur(etat, personnage_id, element, signe,
  cle_contribution: str | None = None) -> dict` (rétro-compatible, défaut = `signe`) ;
  `combat_moteur.appliquer_bonus_degats(etat, degats: float, cle_contribution: str) -> dict`
  — consommés par `combat.py` (Task 6).

- [ ] **Step 1: Écrire les tests qui échouent**

Ajouter à la fin de `test_combat_moteur.py` :

```python
def test_ajouter_joueur_cle_contribution_par_defaut_est_le_signe():
    etat = _etat_avec_joueur()
    assert etat["joueurs"]["p1"]["cle_contribution"] == "Bélier"


def test_ajouter_joueur_cle_contribution_explicite_bucket_par_cle():
    etat = CM.nouvel_etat_instance("zone-1", 800, MOB_ZONE)
    etat = CM.ajouter_joueur(etat, "p1", "Archétype", "p1", cle_contribution="perso-1")
    mob_id = next(iter(etat["mobs"]))
    etat = _joueur_colle_au_mob(etat, mob_id)
    actions = [{"type": "sort", "personnage_id": "p1", "competence_id": "sort-degats",
               "cible_id": mob_id}]
    etat, _ = CM.avancer_tick(etat, actions, dt=0.1, competences=COMPETENCE_DEGATS,
                              horodatage=0.0, respawn_delai_s=60.0)
    assert etat["mobs"][mob_id]["degats_recus_par_guilde"] == {"perso-1": 30}


def test_appliquer_bonus_degats_reduit_les_pv_du_boss():
    etat = _etat_avec_joueur()
    mob_id = next(iter(etat["mobs"]))
    etat = CM.appliquer_bonus_degats(etat, 20, "perso-1")
    assert etat["mobs"][mob_id]["pv"] == 30
    assert etat["mobs"][mob_id]["degats_recus_par_guilde"] == {"perso-1": 20}


def test_appliquer_bonus_degats_zero_est_un_noop():
    etat = _etat_avec_joueur()
    mob_id = next(iter(etat["mobs"]))
    etat = CM.appliquer_bonus_degats(etat, 0, "perso-1")
    assert etat["mobs"][mob_id]["pv"] == 50
    assert etat["mobs"][mob_id]["degats_recus_par_guilde"] == {}
```

- [ ] **Step 2: Vérifier l'échec**

Run: `cd briques/jeu-factions && python -m pytest test_combat_moteur.py -v -k "cle_contribution or bonus_degats"`
Expected: FAIL (`TypeError: ajouter_joueur() got an unexpected keyword argument
'cle_contribution'` / `AttributeError: module 'combat_moteur' has no attribute
'appliquer_bonus_degats'`).

- [ ] **Step 3: Implémenter**

Remplacer `ajouter_joueur` (lignes 46-53) par :

```python
def ajouter_joueur(etat: dict, personnage_id: str, element: str, signe: str,
                   cle_contribution: str | None = None) -> dict:
    bord = etat["arene_taille"] * 0.05
    etat["joueurs"][personnage_id] = {
        "x": bord, "y": bord, "pv": PV_MAX_JOUEUR, "pv_max": PV_MAX_JOUEUR,
        "element": element, "signe": signe, "cle_contribution": cle_contribution or signe,
        "etat": "actif", "cooldowns": {}, "bouclier": 0, "dots": [],
    }
    return etat
```

Juste après `_infliger_degats` (après la ligne 84), ajouter :

```python
def appliquer_bonus_degats(etat: dict, degats: float, cle_contribution: str) -> dict:
    """Dégâts immédiats appliqués au boss actif de l'instance (S216 idle bonus : progression
    accumulée pendant l'absence, convertie en dégâts au moment où le personnage rejoint le
    combat — jamais un tick serveur, cf. archetypes.bonus_idle)."""
    boss = next((m for m in etat["mobs"].values() if m["role"] == "boss"), None)
    if boss is None or degats <= 0:
        return etat
    reels = _infliger_degats(boss, degats)
    boss["degats_recus_par_guilde"][cle_contribution] = \
        boss["degats_recus_par_guilde"].get(cle_contribution, 0) + reels
    return etat
```

Dans la section 3 (Sorts), remplacer le bloc `if effet == "degats":` (lignes 141-145) par :

```python
        if effet == "degats":
            reels = _infliger_degats(cible, comp["magnitude"])
            cible["degats_recus_par_guilde"][j["cle_contribution"]] = \
                cible["degats_recus_par_guilde"].get(j["cle_contribution"], 0) + reels
            evenements.append({"type": "mob_touche", "mob_id": a.get("cible_id"), "degats": reels})
```

Et le bloc `elif effet == "dot":` (lignes 154-157) par :

```python
        elif effet == "dot":
            cible.setdefault("dots", []).append(
                {"degats_par_seconde": comp["magnitude"], "expire_a": horodatage + DUREE_DOT_S,
                 "cle_contribution": j["cle_contribution"]})
```

Dans la section 4 (DOT), remplacer le corps de la boucle (lignes 163-170) par :

```python
            for d in e.get("dots", []):
                if horodatage >= d["expire_a"]:
                    continue
                reels = _infliger_degats(e, d["degats_par_seconde"] * dt)
                if "degats_recus_par_guilde" in e:
                    e["degats_recus_par_guilde"][d["cle_contribution"]] = \
                        e["degats_recus_par_guilde"].get(d["cle_contribution"], 0) + reels
                actifs.append(d)
```

- [ ] **Step 4: Vérifier que tout passe**

Run: `cd briques/jeu-factions && python -m pytest test_combat_moteur.py -v`
Expected: tous PASS, y compris les tests DOT/dégâts existants (le défaut
`cle_contribution = signe` préserve exactement le comportement `degats_recus_par_guilde`
actuel pour les zones).

- [ ] **Step 5: Commit**

```bash
git add briques/jeu-factions/combat_moteur.py briques/jeu-factions/test_combat_moteur.py
git commit -m "feat(jeu-factions): combat_moteur — cle_contribution paramétrable + bonus idle en dégâts (S218/S216)"
```

---

### Task 5: `groupes.py` — retirer la résolution par stats, ajouter les primitives combat

**Files:**
- Modify: `briques/jeu-factions/groupes.py:58-109` (retirer `resoudre_groupes_actifs`),
  ajouter `lire_groupe`/`dissoudre_groupes_de_letape`.
- Modify: `briques/jeu-factions/test_groupes.py` (retirer/réécrire les tests de résolution).

**Interfaces:**
- Consumes: rien de nouveau.
- Produces: `groupes.lire_groupe(groupe_id: str) -> dict | None`,
  `groupes.dissoudre_groupes_de_letape(zone_archetype_id: str) -> None` — consommés par
  `combat.py` (Task 6) et `main.py` (Task 8).
- Removes: `groupes.resoudre_groupes_actifs` (plus aucun appelant après ce plan).

- [ ] **Step 1: Retirer `resoudre_groupes_actifs`, ajouter les nouvelles fonctions**

Remplacer les lignes 58-109 de `groupes.py` (toute la fonction `resoudre_groupes_actifs`) par :

```python
def lire_groupe(groupe_id: str) -> dict | None:
    with S._conn() as c:
        existe = c.execute("SELECT 1 FROM groupes WHERE id=?", (groupe_id,)).fetchone()
        if not existe:
            return None
        return _ligne_groupe(c, groupe_id)


def dissoudre_groupes_de_letape(zone_archetype_id: str) -> None:
    """Appelée par `combat.persister_evenements` (contexte archétype) à la mort du boss d'une
    étape : tous les groupes encore actifs sur CETTE étape sont clos — la voie est franchie,
    même précédent que l'ancien `resoudre_groupes_actifs` qui dissolvait le groupe au seuil
    atteint (mais désormais côté combat joué, pas côté comparaison de stats)."""
    with S._conn() as c:
        c.execute("UPDATE groupes SET etat='dissous' WHERE zone_archetype_id=? AND etat='actif'",
                  (zone_archetype_id,))
```

Retirer aussi les imports devenus inutiles dans `groupes.py` si `json`/`datetime` ne sont
plus utilisés que par `_maintenant()` (garder `_maintenant`, il sert à `creer_groupe`) — ne
retirer que ce qui devient réellement mort après le remplacement (`json` était utilisé
uniquement dans `resoudre_groupes_actifs` pour lire `snapshot_holistique` : à retirer de
l'import si plus rien d'autre dans le fichier ne l'utilise).

- [ ] **Step 2: Réécrire `test_groupes.py`**

Retirer entièrement ces 5 tests (la mécanique qu'ils testent — comparaison de stats,
bonus idle appliqué dans `resoudre_groupes_actifs` — n'existe plus ; leurs garanties de
carry/idle sont réécrites contre le combat joué dans `test_combat_archetype.py`, Task 7) :
`test_resoudre_groupes_actifs_avance_la_cible_et_debloque_competence`,
`test_resoudre_groupes_actifs_carry_naide_pas_la_progression_de_laide`,
`test_resoudre_groupes_actifs_pas_vaincu_reste_actif`,
`test_resoudre_groupes_actifs_bonus_idle_comble_lecart`,
`test_resoudre_groupes_actifs_bonus_idle_du_carry_ne_beneficie_pas_a_la_cible`.

Remplacer `test_rejoindre_groupe_dissous_leve_valueerror` (qui dissolvait le groupe via
`G.resoudre_groupes_actifs()`) par :

```python
def test_rejoindre_groupe_dissous_leve_valueerror():
    A.seed_zones_archetype()
    p = _personnage("cleG4", "Cible3", {"Charisme": 200, "Combativité": 200, "Énergie": 200})
    etapes = A.lister_etapes("Le Meneur Charismatique")
    g = G.creer_groupe(p["id"], etapes[0]["id"])
    G.dissoudre_groupes_de_letape(etapes[0]["id"])
    try:
        G.rejoindre_groupe(g["id"], p["id"])
        assert False, "aurait dû lever ValueError"
    except ValueError:
        pass
```

Ajouter :

```python
def test_lire_groupe_inconnu_est_none():
    assert G.lire_groupe("inconnu") is None


def test_lire_groupe_connu():
    A.seed_zones_archetype()
    p = _personnage("cleG11", "Solo", {"Charisme": 10, "Combativité": 10, "Énergie": 10})
    etapes = A.lister_etapes("Le Meneur Charismatique")
    g = G.creer_groupe(p["id"], etapes[0]["id"])
    assert G.lire_groupe(g["id"])["id"] == g["id"]


def test_dissoudre_groupes_de_letape_ne_touche_pas_les_autres_etapes():
    A.seed_zones_archetype()
    p = _personnage("cleG12", "Autre", {"Charisme": 10, "Combativité": 10, "Énergie": 10})
    etapes = A.lister_etapes("Le Meneur Charismatique")
    g1 = G.creer_groupe(p["id"], etapes[0]["id"])
    G.dissoudre_groupes_de_letape("etape-qui-nexiste-pas")
    assert G.lire_groupe(g1["id"])["etat"] == "actif"
```

- [ ] **Step 3: Vérifier que tout passe**

Run: `cd briques/jeu-factions && python -m pytest test_groupes.py -v`
Expected: tous PASS.

- [ ] **Step 4: Commit**

```bash
git add briques/jeu-factions/groupes.py briques/jeu-factions/test_groupes.py
git commit -m "refactor(jeu-factions): groupes — retire resoudre_groupes_actifs, ajoute lire_groupe/dissoudre_groupes_de_letape (S218)"
```

---

### Task 6: `combat.py` — instances par contexte (`zone` | `archetype`)

**Files:**
- Modify: `briques/jeu-factions/combat.py` (dataclass, `_instance_disponible`,
  `_creer_instance`, `rejoindre`, `fermer_instance`, `persister_evenements`, `un_tick`),
  ajout de `appliquer_bonus_idle`.

**Interfaces:**
- Consumes: `combat_moteur.ajouter_joueur(..., cle_contribution=...)`,
  `combat_moteur.appliquer_bonus_degats` (Task 4), `groupes.dissoudre_groupes_de_letape`
  (Task 5), `archetypes.lire_etape`/`prochaine_etape`/`marquer_etape_vaincue`/
  `debloquer_competence_si_existe`.
- Produces: `combat.rejoindre(cle: str, personnage_id, element, signe, mobs_zone,
  contexte: str = "zone", cle_contribution: str | None = None) -> InstanceCombat` (rétro-
  compatible : appel positionnel à 5 arguments inchangé) ; `combat.appliquer_bonus_idle(inst,
  degats: float, cle_contribution: str) -> None` — consommés par `main.py` (Task 8) et
  `test_combat_archetype.py` (Task 7).

- [ ] **Step 1: Vérifier que les tests existants passent AVANT modification (baseline)**

Run: `cd briques/jeu-factions && python -m pytest test_combat.py -v`
Expected: tous PASS (baseline avant refactor).

- [ ] **Step 2: Généraliser `combat.py`**

Ajouter `import archetypes` et `import groupes` en haut du fichier (après `import zones`).

Remplacer le dataclass `InstanceCombat` (lignes 37-45) par :

```python
@dataclass
class InstanceCombat:
    id: str
    zone_id: str
    etat: dict
    contexte: str = "zone"                              # "zone" | "archetype"
    connexions: dict = field(default_factory=dict)     # personnage_id -> WebSocket
    file_actions: list = field(default_factory=list)   # actions en attente du prochain tick
    derniere_activite: float | None = None              # horodatage depuis lequel vide
    tache: asyncio.Task | None = None
```

Remplacer `_instance_disponible`/`_creer_instance` (lignes 51-63) par :

```python
def _cle_partition(cle: str, contexte: str) -> str:
    return cle if contexte == "zone" else f"{contexte}:{cle}"


def _instance_disponible(cle: str, contexte: str) -> InstanceCombat | None:
    for inst in _INSTANCES.get(_cle_partition(cle, contexte), []):
        if len(inst.connexions) < capacite():
            return inst
    return None


def _creer_instance(zone_id: str, mobs_zone: list[dict], contexte: str) -> InstanceCombat:
    import uuid
    etat = CM.nouvel_etat_instance(zone_id, arene_taille(), mobs_zone)
    inst = InstanceCombat(id=uuid.uuid4().hex, zone_id=zone_id, etat=etat, contexte=contexte)
    _INSTANCES.setdefault(_cle_partition(zone_id, contexte), []).append(inst)
    return inst
```

Remplacer `rejoindre` (lignes 66-71) par :

```python
async def rejoindre(zone_id: str, personnage_id: str, element: str, signe: str,
                    mobs_zone: list[dict], contexte: str = "zone",
                    cle_contribution: str | None = None) -> InstanceCombat:
    inst = _instance_disponible(zone_id, contexte) or _creer_instance(zone_id, mobs_zone, contexte)
    inst.etat = CM.ajouter_joueur(inst.etat, personnage_id, element, signe, cle_contribution)
    inst.derniere_activite = None
    return inst
```

Remplacer `fermer_instance` (lignes 101-106) par :

```python
def fermer_instance(inst: InstanceCombat) -> None:
    if inst.tache:
        inst.tache.cancel()
    liste = _INSTANCES.get(_cle_partition(inst.zone_id, inst.contexte), [])
    if inst in liste:
        liste.remove(inst)
```

Remplacer `persister_evenements` (lignes 109-116) par :

```python
def persister_evenements(inst: InstanceCombat, evenements: list[dict]) -> None:
    for ev in evenements:
        if ev["type"] not in ("mob_tue", "boss_tue"):
            continue
        contributions = ev.get("contributions", {})
        if inst.contexte == "zone":
            for guilde, points in contributions.items():
                zones.ajouter_score(inst.zone_id, guilde, points)
            stockage.log_resolution(inst.zone_id, None, contributions, ev["type"])
            if ev["type"] == "boss_tue":
                zones.marquer_vaincue_si_premiere_fois(inst.zone_id)
        else:
            stockage.log_resolution(None, inst.zone_id, contributions, ev["type"])
            if ev["type"] == "boss_tue":
                etape = archetypes.lire_etape(inst.zone_id)
                if etape:
                    for personnage_id in contributions:
                        if archetypes.prochaine_etape(personnage_id, etape["archetype"]) == inst.zone_id:
                            archetypes.marquer_etape_vaincue(personnage_id, inst.zone_id)
                            archetypes.debloquer_competence_si_existe(personnage_id, inst.zone_id)
                groupes.dissoudre_groupes_de_letape(inst.zone_id)
```

Remplacer `un_tick` (lignes 119-124) par :

```python
async def un_tick(inst: InstanceCombat, actions: list[dict], dt: float,
                  competences: dict[str, dict], horodatage: float) -> list[dict]:
    inst.etat, evenements = CM.avancer_tick(inst.etat, actions, dt, competences, horodatage,
                                            respawn_delai_s())
    persister_evenements(inst, evenements)
    return evenements
```

Ajouter, juste après `un_tick` :

```python
def appliquer_bonus_idle(inst: InstanceCombat, degats: float, cle_contribution: str) -> None:
    inst.etat = CM.appliquer_bonus_degats(inst.etat, degats, cle_contribution)
```

- [ ] **Step 3: Vérifier que les tests EXISTANTS passent toujours sans modification**

Run: `cd briques/jeu-factions && python -m pytest test_combat.py -v`
Expected: tous PASS — `contexte` par défaut `"zone"` et `_cle_partition` renvoie la clé brute
dans ce cas, donc `combat._INSTANCES[zone_id]` (utilisé directement par
`test_fermer_instance_la_retire_du_registre`) continue de fonctionner à l'identique.

- [ ] **Step 4: Commit**

```bash
git add briques/jeu-factions/combat.py
git commit -m "feat(jeu-factions): combat — instances par contexte zone/archetype, persistance de voie (S218)"
```

---

### Task 7: Tests d'intégration — résolution de voie par combat joué

**Files:**
- Create: `briques/jeu-factions/test_combat_archetype.py`

**Interfaces:**
- Consumes: `combat.rejoindre(..., contexte="archetype", cle_contribution=...)`,
  `combat.un_tick`, `combat.appliquer_bonus_idle` (Task 6), `mobs_archetype.seed_mobs_archetype`/
  `lister_mobs_etape` (Task 3), `groupes.creer_groupe`/`lire_groupe` (Task 5).

- [ ] **Step 1: Écrire les tests (ils doivent déjà passer, Tasks 4-6 sont faites)**

Créer `briques/jeu-factions/test_combat_archetype.py` :

```python
"""Tests de la résolution de voie d'archétype par combat joué (S218) — remplace l'ancienne
résolution par comparaison de stats (`groupes.resoudre_groupes_actifs`, retirée)."""
import archetypes as A
import combat
import groupes as G
import mobs_archetype as MA
import stockage as S


def _personnage(cle, nom):
    S.assurer_joueur(cle, nom)
    return S.creer_personnage(cle, nom, {"date_naissance": "1990-01-01"},
                              {"traditions": {"signe_solaire": {"nom": "Lion"}},
                               "portrait": {"stats": {}}})


def _etape_fixture(archetype="Le Meneur Charismatique", ordre=1):
    A.seed_zones_archetype()
    MA.seed_mobs_archetype()
    return A.lister_etapes(archetype)[ordre - 1]


async def _rejoindre_et_tuer_le_boss(etape, personnage_id):
    gabarits = MA.lister_mobs_etape(etape["id"])
    inst = await combat.rejoindre(etape["id"], personnage_id, etape["archetype"], personnage_id,
                                  gabarits, contexte="archetype", cle_contribution=personnage_id)
    boss_id = next(mid for mid, m in inst.etat["mobs"].items() if m["role"] == "boss")
    inst.etat["mobs"][boss_id]["pv"] = 0
    inst.etat["mobs"][boss_id]["degats_recus_par_guilde"] = {personnage_id: 999}
    evenements = await combat.un_tick(inst, [], dt=0.1, competences={}, horodatage=0.0)
    return inst, evenements


async def test_boss_tue_avance_la_cible_et_debloque_competence():
    etape = _etape_fixture()
    A.seed_competences()
    p = _personnage("cleCA1", "Cible")
    G.creer_groupe(p["id"], etape["id"])
    _, evenements = await _rejoindre_et_tuer_le_boss(etape, p["id"])
    assert any(e["type"] == "boss_tue" for e in evenements)
    assert A.prochaine_etape(p["id"], etape["archetype"]) == A.lister_etapes(etape["archetype"])[1]["id"]
    assert len(A.lister_competences_debloquees(p["id"])) == 1


async def test_boss_tue_dissout_les_groupes_actifs_de_letape():
    etape = _etape_fixture()
    p = _personnage("cleCA2", "Cible2")
    g = G.creer_groupe(p["id"], etape["id"])
    await _rejoindre_et_tuer_le_boss(etape, p["id"])
    assert G.lire_groupe(g["id"])["etat"] == "dissous"


async def test_boss_tue_ne_fait_pas_progresser_un_carry_sans_sa_propre_etape():
    """Même garantie qu'avant S218 (ancien test_groupes.py::
    test_resoudre_groupes_actifs_carry_naide_pas_la_progression_de_laide) : un aide qui
    contribue au combat de l'étape 2 d'un autre, sans avoir complété sa propre étape 1, ne
    voit pas sa progression avancer."""
    etape1 = _etape_fixture()
    A.seed_competences()
    p = _personnage("cleCA3", "Cible3")
    aide = _personnage("cleCA3b", "Copain")
    await _rejoindre_et_tuer_le_boss(etape1, p["id"])
    etape2 = A.lister_etapes(etape1["archetype"])[1]
    G.creer_groupe(p["id"], etape2["id"])
    gabarits = MA.lister_mobs_etape(etape2["id"])
    inst = await combat.rejoindre(etape2["id"], p["id"], etape2["archetype"], p["id"], gabarits,
                                  contexte="archetype", cle_contribution=p["id"])
    inst = await combat.rejoindre(etape2["id"], aide["id"], etape2["archetype"], aide["id"],
                                  gabarits, contexte="archetype", cle_contribution=aide["id"])
    boss_id = next(mid for mid, m in inst.etat["mobs"].items() if m["role"] == "boss")
    inst.etat["mobs"][boss_id]["pv"] = 0
    inst.etat["mobs"][boss_id]["degats_recus_par_guilde"] = {p["id"]: 500, aide["id"]: 500}
    await combat.un_tick(inst, [], dt=0.1, competences={}, horodatage=0.0)
    assert A.prochaine_etape(p["id"], etape1["archetype"]) == A.lister_etapes(etape1["archetype"])[2]["id"]
    assert A.prochaine_etape(aide["id"], etape1["archetype"]) == etape1["id"]


async def test_idle_bonus_applique_a_lentree_reduit_les_pv_du_boss():
    etape = _etape_fixture()
    p = _personnage("cleCA4", "Fatigue")
    gabarits = MA.lister_mobs_etape(etape["id"])
    inst = await combat.rejoindre(etape["id"], p["id"], etape["archetype"], p["id"], gabarits,
                                  contexte="archetype", cle_contribution=p["id"])
    boss_id = next(mid for mid, m in inst.etat["mobs"].items() if m["role"] == "boss")
    pv_avant = inst.etat["mobs"][boss_id]["pv"]
    combat.appliquer_bonus_idle(inst, 20, p["id"])
    assert inst.etat["mobs"][boss_id]["pv"] == pv_avant - 20
```

- [ ] **Step 2: Lancer les tests**

Run: `cd briques/jeu-factions && python -m pytest test_combat_archetype.py -v`
Expected: 4 tests PASS (aucune implémentation nouvelle requise — ce fichier vérifie
l'intégration des Tasks 3-6).

- [ ] **Step 3: Commit**

```bash
git add briques/jeu-factions/test_combat_archetype.py
git commit -m "test(jeu-factions): intégration combat joué pour les voies d'archétype (S218)"
```

---

### Task 8: Route WebSocket `/groupes/{groupe_id}/combat` + branchement startup — `main.py`

**Files:**
- Modify: `briques/jeu-factions/main.py` (imports, `_seed_donnees_globales`, nouvelle route).
- Test: `briques/jeu-factions/test_api.py`

**Interfaces:**
- Consumes: `groupes.lire_groupe`, `archetypes.lire_etape`/`prochaine_etape`/`bonus_idle`/
  `TAUX_IDLE_PAR_HEURE`/`PLAFOND_IDLE_HEURES`, `mobs_archetype.lister_mobs_etape`,
  `combat.rejoindre`/`appliquer_bonus_idle`/`demarrer_boucle_si_necessaire`/
  `enregistrer_connexion`/`etat_public`/`empiler_action`/`quitter`.

- [ ] **Step 1: Écrire les tests qui échouent**

Ajouter à la fin de `test_api.py` :

```python
def test_combat_voie_ws_rejette_une_session_absente():
    with client.websocket_connect("/groupes/inconnu/combat?personnage_id=x") as ws:
        message = ws.receive()
        assert message["type"] == "websocket.close"
        assert message["code"] == 4401


def test_combat_voie_ws_groupe_ou_membre_inconnu_est_rejete():
    with client.websocket_connect("/groupes/inconnu/combat?personnage_id=inconnu",
                                  cookies=_cookies("voie-tenant-1")) as ws:
        message = ws.receive()
        assert message["type"] == "websocket.close"
        assert message["code"] == 4404


def test_combat_voie_ws_connexion_valide_recoit_un_etat_initial(monkeypatch):
    _patch_moteur(monkeypatch, portrait_reponse={
        "portrait": {"archetype": "Le Meneur Charismatique",
                    "stats": {"Charisme": 10, "Combativité": 10, "Énergie": 10}},
        "traditions": {"signe_solaire": {"nom": "Lion"}}, "empreinte": []})
    archetypes.seed_zones_archetype()
    import mobs_archetype
    mobs_archetype.seed_mobs_archetype()
    ck = _cookies("voie-tenant-2")
    p = client.post("/personnages", json={"nom": "Voie", "date_naissance": "1990-01-01"},
                    cookies=ck).json()
    etape = client.get("/archetypes/Le Meneur Charismatique/etapes", cookies=ck).json()[0]
    g = client.post("/groupes", json={"personnage_cible_id": p["id"], "zone_archetype_id": etape["id"]},
                    cookies=ck).json()
    with client.websocket_connect(f"/groupes/{g['id']}/combat?personnage_id={p['id']}",
                                  cookies=ck) as ws:
        message = ws.receive_json()
        assert message["type"] == "etat"
        assert p["id"] in message["joueurs"]


def test_combat_voie_ws_non_membre_du_groupe_est_rejete(monkeypatch):
    _patch_moteur(monkeypatch, portrait_reponse={
        "portrait": {"archetype": "Le Sage Contemplatif", "stats": {}},
        "traditions": {"signe_solaire": {"nom": "Vierge"}}, "empreinte": []})
    archetypes.seed_zones_archetype()
    import mobs_archetype
    mobs_archetype.seed_mobs_archetype()
    ck = _cookies("voie-tenant-3")
    p = client.post("/personnages", json={"nom": "Cible", "date_naissance": "1990-01-01"},
                    cookies=ck).json()
    autre = client.post("/personnages", json={"nom": "PasMembre", "date_naissance": "1990-01-01"},
                        cookies=ck).json()
    etape = client.get("/archetypes/Le Sage Contemplatif/etapes", cookies=ck).json()[0]
    g = client.post("/groupes", json={"personnage_cible_id": p["id"], "zone_archetype_id": etape["id"]},
                    cookies=ck).json()
    with client.websocket_connect(f"/groupes/{g['id']}/combat?personnage_id={autre['id']}",
                                  cookies=ck) as ws:
        message = ws.receive()
        assert message["type"] == "websocket.close"
        assert message["code"] == 4404
```

- [ ] **Step 2: Vérifier l'échec**

Run: `cd briques/jeu-factions && python -m pytest test_api.py -v -k combat_voie`
Expected: FAIL (route `/groupes/{groupe_id}/combat` inexistante -> 404/erreur de connexion
WebSocket).

- [ ] **Step 3: Implémenter**

Dans `main.py`, ajouter `import mobs_archetype` après `import mobs` (ligne 24), et retirer
`import tick` (ligne 27) — plus aucun appelant après ce plan (Task 9 supprime `tick.py`).

Remplacer `_seed_donnees_globales` (lignes 46-53) par :

```python
@app.on_event("startup")
async def _seed_donnees_globales():
    zones.seed_zones()
    archetypes.seed_zones_archetype()
    archetypes.seed_competences()
    mobs.seed_mobs()
    mobs_archetype.seed_mobs_archetype()
```

Ajouter, juste après la route `combat_ws` existante (après la ligne 233) :

```python
@app.websocket("/groupes/{groupe_id}/combat")
async def combat_voie_ws(websocket: WebSocket, groupe_id: str, personnage_id: str = Query(...)):
    await websocket.accept()
    identite = jeton.verifier(websocket.cookies.get(jeton.COOKIE_NOM))
    if identite is None:
        await websocket.close(code=4401)
        return
    perso = stockage.lire_personnage(identite, personnage_id)
    gr = groupes.lire_groupe(groupe_id)
    if not perso or not gr or gr["etat"] != "actif" or personnage_id not in gr["membres"]:
        await websocket.close(code=4404)
        return
    etape = archetypes.lire_etape(gr["zone_archetype_id"])
    if not etape:
        await websocket.close(code=4404)
        return
    gabarits = mobs_archetype.lister_mobs_etape(gr["zone_archetype_id"])
    inst = await combat.rejoindre(gr["zone_archetype_id"], personnage_id, etape["archetype"],
                                  personnage_id, gabarits, contexte="archetype",
                                  cle_contribution=personnage_id)
    if archetypes.prochaine_etape(personnage_id, etape["archetype"]) == gr["zone_archetype_id"]:
        derniere_presence = stockage.lire_derniere_presence_personnage(personnage_id)
        bonus = archetypes.bonus_idle(derniere_presence, datetime.now(timezone.utc),
                                      archetypes.TAUX_IDLE_PAR_HEURE, archetypes.PLAFOND_IDLE_HEURES)
        if bonus:
            combat.appliquer_bonus_idle(inst, bonus, personnage_id)
    competences = archetypes.lister_toutes_competences_avec_effet()
    combat.demarrer_boucle_si_necessaire(inst, competences)
    try:
        combat.enregistrer_connexion(inst, personnage_id, websocket)
        await websocket.send_json({"type": "etat", **combat.etat_public(inst), "evenements": []})
        while True:
            message = await websocket.receive_json()
            combat.empiler_action(inst, personnage_id, message)
    except WebSocketDisconnect:
        pass
    finally:
        combat.quitter(inst, personnage_id, time.monotonic())
```

- [ ] **Step 4: Vérifier que tout passe**

Run: `cd briques/jeu-factions && python -m pytest test_api.py -v`
Expected: tous PASS.

- [ ] **Step 5: Commit**

```bash
git add briques/jeu-factions/main.py briques/jeu-factions/test_api.py
git commit -m "feat(jeu-factions): route WS /groupes/{id}/combat — étapes de voie jouées (S218)"
```

---

### Task 9: Supprimer `tick.py` (devenu sans objet)

**Files:**
- Delete: `briques/jeu-factions/tick.py`, `briques/jeu-factions/test_tick.py`
- Modify: `briques/jeu-factions/conftest.py:11` (retirer la variable d'env devenue morte)

**Interfaces:** aucune — nettoyage pur, zéro appelant restant après Task 8.

- [ ] **Step 1: Confirmer qu'il n'y a plus d'appelant**

Run: `cd briques/jeu-factions && grep -rn "import tick\|tick\." --include="*.py" . | grep -v test_tick.py`
Expected: aucune sortie (plus aucune référence à `tick.py` en dehors de lui-même).

- [ ] **Step 2: Supprimer les fichiers**

```bash
git rm briques/jeu-factions/tick.py briques/jeu-factions/test_tick.py
```

Dans `conftest.py`, retirer la ligne :
```python
os.environ["JEU_FACTIONS_TICK_AUTOSTART"] = "0"      # jamais de boucle asyncio réelle en test
```

- [ ] **Step 3: Vérifier que toute la suite passe**

Run: `cd briques/jeu-factions && python -m pytest -v`
Expected: tous PASS, aucun test ne référence plus `tick`/`TICK_INTERVAL_HOURS`/
`JEU_FACTIONS_TICK_AUTOSTART`.

- [ ] **Step 4: Commit**

```bash
git add briques/jeu-factions/conftest.py
git commit -m "refactor(jeu-factions): supprime tick.py — plus aucune résolution passive après S218"
```

---

### Task 10: Front — jouer une étape de voie depuis `front_combat.html`

**Files:**
- Modify: `briques/jeu-factions/front_combat.html:31-33,83-85`

**Interfaces:** aucune nouvelle interface serveur — câblage front pur sur la route de
Task 8.

- [ ] **Step 1: Généraliser le paramètre d'URL et l'URL du WebSocket**

Remplacer les lignes 31-33 :
```javascript
const params = new URLSearchParams(location.search);
const zoneId = params.get("zone");
```
par :
```javascript
const params = new URLSearchParams(location.search);
const zoneId = params.get("zone");
const groupeId = params.get("groupe");
```

Remplacer la fonction `connecter` (lignes 83-85) par :
```javascript
function connecter() {
  const protocole = location.protocol === "https:" ? "wss:" : "ws:";
  const route = groupeId ? `/groupes/${groupeId}/combat` : `/zones/${zoneId}/combat`;
  ws = new WebSocket(`${protocole}//${location.host}${route}?personnage_id=${personnageId}`);
```
(la ligne `ws.onmessage = ...` qui suit reste inchangée).

- [ ] **Step 2: Vérifier manuellement**

Run: `cd briques/jeu-factions && python -m pytest test_front_combat.py -v`
Expected: PASS (smoke test de service du fichier statique, inchangé).

Vérification manuelle (pas de test automatisé pour du JS inline) : ouvrir
`/front_combat.html?groupe=<id>` après avoir créé un groupe via `POST /groupes` doit ouvrir
la connexion sur `/groupes/<id>/combat` au lieu de `/zones/<id>/combat`.

- [ ] **Step 3: Commit**

```bash
git add briques/jeu-factions/front_combat.html
git commit -m "feat(jeu-factions): front combat — support des étapes de voie via ?groupe= (S218)"
```

---

### Task 11: Suite complète + revue finale

- [ ] **Step 1: Lancer toute la suite de la brique**

Run: `cd briques/jeu-factions && python -m pytest -v`
Expected: 100% PASS, aucun test ignoré/xfail.

- [ ] **Step 2: Vérifier qu'aucune référence morte ne subsiste**

Run: `cd briques/jeu-factions && grep -rn "_LORE_GENERIQUE\|resoudre_groupes_actifs\|resoudre_toutes_zones" --include="*.py" .`
Expected: aucune sortie.

- [ ] **Step 3: Commit final si des ajustements ont eu lieu pendant la revue**

```bash
git add -A
git commit -m "chore(jeu-factions): revue finale S218/S219"
```
