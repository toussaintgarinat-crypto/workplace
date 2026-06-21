"""Atelier de SKILLS (S91) : la brique `dev` fabrique des skills « façon Claude Code » et y
accroche des MCP, puis les expose à la **porte** du Cœur (S90) — découvrables + chargeables à
la demande, sans une ligne de code en dur.

Une **skill** = un dossier `<racine>/<nom>/SKILL.md` avec un frontmatter YAML minimal (les
clés canoniques de Claude Code, pour qu'un agent Claude Code puisse aussi la consommer) :

    ---
    name: revue-securite
    description: Audite un diff à la recherche de secrets et d'injections.
    allowed-tools: Read, Grep, Bash
    mcp: github, playwright
    ---
    # corps : les INSTRUCTIONS du workflow (ce que l'agent doit faire, pas à pas)

Deux usages, comme prévu au design : un **workflow réutilisable** (ex. « revue sécurité ») ou
une **persona BMAD** (Analyst/Architect/Dev/QA) fabriquée UNE fois et servie à la demande.

Pont vers la porte S90 : `capacite_pour(skill)` rend une **capacité de niveau 1** au format du
catalogue (`core/catalogue.py`). Niveau 1 = DIFFÉRÉE derrière `competence_charger` : son
nom+description restent listés (bon marché), et son corps (les instructions + les MCP
accrochés) n'est chargé que quand l'agent en a besoin — exactement la divulgation progressive.

Pur autant que possible : la validation, la composition/lecture du SKILL.md et la conversion en
capacité sont sans I/O (testables hors-ligne) ; seules `creer`/`lister`/`lire`/`supprimer`
touchent le disque.
"""
from __future__ import annotations

import os
import re

import domaine  # réutilise domaine.slug (slug sûr, déjà éprouvé)

# Racine des skills (souveraine, locale). Vit DANS la brique par défaut → versionnable.
RACINE = os.environ.get("DEV_SKILLS_DIR",
                        os.path.join(os.path.dirname(__file__), "skills"))

_CLES_LISTE = ("allowed-tools", "mcp")     # frontmatter : valeurs en liste (CSV toléré)
_MAX_DESC = 280


# ── Domaine pur : validation + (dé)composition du SKILL.md ─────────────────────

def valider(meta: dict) -> list[str]:
    """Liste des erreurs d'un descripteur de skill (vide = valide). Ne lève jamais.

    Règles minimales et honnêtes : un nom slug non vide, une description courte non vide,
    `allowed-tools`/`mcp` en listes de chaînes. Tout le reste est toléré (un workflow peut
    n'accrocher aucun MCP)."""
    err: list[str] = []
    nom = (meta.get("name") or "").strip()
    if not nom:
        err.append("name requis")
    elif domaine.slug(nom) != nom:
        err.append("name doit être un slug (a-z0-9 et tirets, ex. revue-securite)")
    desc = (meta.get("description") or "").strip()
    if not desc:
        err.append("description requise")
    elif len(desc) > _MAX_DESC:
        err.append(f"description trop longue (> {_MAX_DESC} caractères)")
    for cle in _CLES_LISTE:
        v = meta.get(cle)
        if v is not None and not (isinstance(v, list) and all(isinstance(x, str) for x in v)):
            err.append(f"{cle} doit être une liste de chaînes")
    return err


def _liste(v) -> list[str]:
    """Normalise une valeur frontmatter en liste de chaînes (accepte une CSV ou une liste)."""
    if v is None:
        return []
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    return [p.strip() for p in str(v).split(",") if p.strip()]


def normaliser(meta: dict) -> dict:
    """Descripteur propre et canonique (name/description + listes outils_autorises/mcp)."""
    return {
        "name": (meta.get("name") or "").strip(),
        "description": (meta.get("description") or "").strip(),
        "allowed-tools": _liste(meta.get("allowed-tools") or meta.get("outils_autorises")),
        "mcp": _liste(meta.get("mcp")),
    }


def composer_skill_md(meta: dict, corps: str) -> str:
    """Rend le texte d'un SKILL.md : frontmatter YAML (clés Claude Code) + corps d'instructions."""
    m = normaliser(meta)
    lignes = ["---", f"name: {m['name']}", f"description: {m['description']}"]
    if m["allowed-tools"]:
        lignes.append("allowed-tools: " + ", ".join(m["allowed-tools"]))
    if m["mcp"]:
        lignes.append("mcp: " + ", ".join(m["mcp"]))
    lignes.append("---")
    return "\n".join(lignes) + "\n\n" + (corps or "").strip() + "\n"


def parser_skill_md(texte: str) -> dict:
    """Relit un SKILL.md → ``{name, description, allowed-tools[], mcp[], corps}``.

    Parseur YAML-frontmatter minimal (clés `cle: valeur` à plat) — pas de dépendance PyYAML,
    dépendances minces obligent. Tolérant : un fichier sans frontmatter rend un corps brut."""
    meta: dict = {}
    corps = texte or ""
    m = re.match(r"^\s*---\s*\n(.*?)\n---\s*\n?(.*)$", texte or "", re.DOTALL)
    if m:
        bloc, corps = m.group(1), m.group(2)
        for ligne in bloc.splitlines():
            if ":" in ligne and not ligne.lstrip().startswith("#"):
                cle, val = ligne.split(":", 1)
                meta[cle.strip()] = val.strip()
    skill = normaliser(meta)
    skill["corps"] = corps.strip()
    return skill


# ── Pont vers la porte (S90) ───────────────────────────────────────────────────

def nom_capacite(nom_skill: str) -> str:
    """Nom de la capacité-porte d'une skill (préfixe `skill_`, slug en underscores)."""
    return "skill_" + domaine.slug(nom_skill).replace("-", "_")


def capacite_pour(skill: dict, *, base_chemin: str = "/skills", niveau: int = 1) -> dict:
    """Convertit une skill en **capacité du catalogue** (format `core/catalogue.py`), de
    niveau 1 par défaut → DIFFÉRÉE derrière `competence_charger` (S90).

    Le chemin pointe vers `GET /skills/{name}/corps` : appeler la capacité (après l'avoir
    chargée) renvoie les instructions + les MCP accrochés. Lecture seule (un workflow ne fait
    rien tout seul)."""
    nom = (skill or {}).get("name") or ""
    return {
        "nom": nom_capacite(nom),
        "description": (skill.get("description") or "").strip(),
        "methode": "GET",
        "chemin": f"{base_chemin}/{nom}/corps",
        "params": {},
        "action": False,
        "niveau": niveau,
    }


# ── Personas BMAD prêtes à fabriquer (un atout concret de S91) ──────────────────
# Une skill peut être une persona spécialisée (cf. S88) fabriquée une fois et rappelée.
_PERSONAS = {
    "analyst": ("Analyst", "Cadre le besoin : transforme une intention floue en exigences "
                "claires et critères de succès, sans solutionner.",
                "Tu es l'Analyst. Reformule le besoin, liste les exigences et les critères de "
                "succès mesurables. Pose les questions manquantes. Ne propose AUCUNE solution "
                "technique : tu cadres le QUOI et le POURQUOI."),
    "architect": ("Architect", "Conçoit le plan (mini-PRD + stories + domaine DDD) AVANT le "
                  "code, fidèle à l'archi noyau+briques.",
                  "Tu es l'Architect. Produis un plan court : Mini-PRD, Stories livrables, "
                  "Domaine (DDD) à modéliser dans un `domaine.py` PUR avant toute technique. "
                  "Reste fidèle à l'intention, ne code pas."),
    "dev": ("Dev", "Implémente une story dans une brique en respectant le DDD et les tests "
            "hors-ligne.",
            "Tu es le Dev. Implémente la story dans la brique cible : domaine pur d'abord, "
            "puis la technique, puis des tests hors-ligne verts. Petits diffs, doc à jour."),
    "qa": ("QA", "Vérifie qu'un incrément tient ses promesses (tests, garde-fous, honnêteté).",
           "Tu es la QA. Relis le diff : la story est-elle tenue ? Les garde-fous (gate, "
           "souveraineté) sont-ils en place ? Les tests couvrent-ils l'essentiel et le repli "
           "honnête ? Liste ce qui manque, sobrement."),
}


def persona_bmad(role: str) -> tuple[dict, str]:
    """(meta, corps) d'une skill-persona BMAD prête à fabriquer (role: analyst/architect/dev/qa)."""
    cle = (role or "").strip().lower()
    if cle not in _PERSONAS:
        raise ValueError(f"persona inconnue : {role} (attendu : {', '.join(sorted(_PERSONAS))})")
    titre, desc, corps = _PERSONAS[cle]
    meta = {"name": f"persona-{cle}", "description": desc,
            "allowed-tools": ["Read", "Grep"], "mcp": []}
    return meta, f"# Persona BMAD — {titre}\n\n{corps}\n"


# ── I/O fichier (les seules fonctions qui touchent le disque) ───────────────────

class ErreurSkill(Exception):
    """Refus métier (descripteur invalide, doublon, introuvable)."""


def _dossier(nom: str, racine: str | None = None) -> str:
    return os.path.join(racine or RACINE, nom)


def creer(meta: dict, corps: str, *, racine: str | None = None,
          scripts: dict | None = None, ecraser: bool = False) -> dict:
    """Crée (valide d'abord) une skill sur le disque : `<racine>/<name>/SKILL.md` (+ scripts).

    Refuse un descripteur invalide ou un doublon (sauf `ecraser=True`). Renvoie le descripteur
    relu (source de vérité = le fichier écrit)."""
    erreurs = valider(meta)
    if erreurs:
        raise ErreurSkill("descripteur invalide : " + " ; ".join(erreurs))
    nom = normaliser(meta)["name"]
    dossier = _dossier(nom, racine)
    if os.path.exists(dossier) and not ecraser:
        raise ErreurSkill(f"la skill « {nom} » existe déjà")
    os.makedirs(dossier, exist_ok=True)
    with open(os.path.join(dossier, "SKILL.md"), "w", encoding="utf-8") as f:
        f.write(composer_skill_md(meta, corps))
    for rel, contenu in (scripts or {}).items():
        # Garde-fou : pas d'évasion hors du dossier de la skill.
        chemin = os.path.normpath(os.path.join(dossier, rel))
        if not chemin.startswith(os.path.abspath(dossier) + os.sep) \
                and not chemin.startswith(dossier + os.sep):
            raise ErreurSkill(f"chemin de script hors du dossier : {rel}")
        os.makedirs(os.path.dirname(chemin), exist_ok=True)
        with open(chemin, "w", encoding="utf-8") as f:
            f.write(contenu)
    return lire(nom, racine=racine)


def lire(nom: str, *, racine: str | None = None) -> dict | None:
    """Descripteur COMPLET d'une skill (avec son corps) ou None si introuvable."""
    chemin = os.path.join(_dossier(nom, racine), "SKILL.md")
    try:
        with open(chemin, encoding="utf-8") as f:
            return parser_skill_md(f.read())
    except FileNotFoundError:
        return None


def lister(racine: str | None = None) -> list[dict]:
    """Descripteurs (SANS le corps : bon marché, c'est le niveau-0) triés par nom."""
    base = racine or RACINE
    out: list[dict] = []
    if not os.path.isdir(base):
        return out
    for nom in sorted(os.listdir(base)):
        sk = lire(nom, racine=racine)
        if sk and sk.get("name"):
            sk.pop("corps", None)
            out.append(sk)
    return out


def supprimer(nom: str, *, racine: str | None = None) -> bool:
    """Supprime une skill (son dossier). True si quelque chose a été retiré."""
    import shutil
    dossier = _dossier(nom, racine)
    if not os.path.isdir(dossier):
        return False
    shutil.rmtree(dossier)
    return True
