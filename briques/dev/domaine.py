"""Domaine pur de l'auto-atelier (DDD). Aucune dépendance externe, aucun I/O.

L'agrégat central est le **Chantier** : une demande de modification d'une brique, portée
par une **branche git dédiée** (jamais `main`). Son cycle de vie est une petite machine à
états explicite — c'est ce qui garantit qu'on ne « déploie » jamais par accident :

    cree → [planifie] → en_cours → revue → fusionne
                                      └────→ jete

L'étape `planifie` (flux **BMAD léger**, S88) est OPT-IN : quand un chantier l'exige
(`plan_requis`), l'agent « Architect » produit un plan (mini-PRD + stories + note de domaine
DDD) AVANT toute ligne de code, et ce plan doit être validé (gate) pour débloquer le codage.
Sans `plan_requis`, le flux historique `cree → en_cours` reste intact (rétrocompat).

Le langage est métier (Chantier, intention, brique cible, branche, sprint, plan) plutôt que
technique : on raisonne en story d'un sprint, pas en commande git. Le git réel vit dans
`git_atelier.py` ; ici, rien que des règles pures et testables hors-ligne.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field, asdict

# ── États du chantier ─────────────────────────────────────────────────────────
CREE = "cree"            # worktree + branche créés, rien fait encore
PLANIFIE = "planifie"    # plan BMAD produit, en attente de validation (S88, opt-in)
EN_COURS = "en_cours"    # l'agent a travaillé (commits sur la branche)
REVUE = "revue"          # diff prêt, en attente du gate humain
FUSIONNE = "fusionne"    # validé → fusionné dans la base (S87)
JETE = "jete"            # worktree détruit, prod intacte

STATUTS = (CREE, PLANIFIE, EN_COURS, REVUE, FUSIONNE, JETE)

# Transitions autorisées. Tout le reste lève — on ne court-circuite jamais le gate.
_TRANSITIONS = {
    CREE:     {PLANIFIE, EN_COURS, JETE},  # PLANIFIE = flux BMAD ; EN_COURS = flux direct
    PLANIFIE: {PLANIFIE, EN_COURS, JETE},  # PLANIFIE→PLANIFIE : on peut replanifier
    EN_COURS: {REVUE, EN_COURS, JETE},     # EN_COURS→EN_COURS : l'agent peut retravailler
    REVUE:    {FUSIONNE, EN_COURS, JETE},
    FUSIONNE: set(),                       # terminal
    JETE:     set(),                       # terminal
}

# Branches que l'atelier refuse de toucher, par construction (le filet).
BRANCHES_INTERDITES = frozenset({"main", "master", "prod", "production"})

# Briques trop sensibles pour être fusionnées sans déblocage explicite (le rail d'argent, le
# pont d'authentification…) : un bug y a des conséquences financières/sécu. La fusion qui les
# touche est REFUSÉE par défaut, débloquable au cas par cas (cf. `fusion_autorisee`).
BRIQUES_SENSIBLES = frozenset({"paiements", "connexion", "auth"})


class TransitionInvalide(ValueError):
    """Tentative de passer un chantier dans un état non autorisé depuis l'état courant."""


def fusion_autorisee(briques_touchees, debloquees=frozenset()) -> tuple[bool, list]:
    """La fusion peut-elle toucher ces briques ? Refuse les sensibles non débloquées.

    Renvoie `(autorisee, [briques bloquantes triées])`. Une brique sensible n'autorise la
    fusion que si elle figure dans `debloquees` (déblocage explicite, au cas par cas)."""
    bloquantes = (set(briques_touchees) & BRIQUES_SENSIBLES) - set(debloquees)
    return (not bloquantes), sorted(bloquantes)


def transition_autorisee(depuis: str, vers: str) -> bool:
    """Le passage d'état `depuis`→`vers` est-il permis par la machine à états ?"""
    return vers in _TRANSITIONS.get(depuis, set())


def exiger_transition(depuis: str, vers: str) -> None:
    """Valide une transition ; lève `TransitionInvalide` si elle n'est pas permise."""
    if not transition_autorisee(depuis, vers):
        raise TransitionInvalide(f"transition interdite : {depuis} → {vers}")


def slug(texte: str) -> str:
    """Réduit une intention libre à un slug git sûr (a-z0-9 et tirets, borné)."""
    texte = unicodedata.normalize("NFKD", texte or "").encode("ascii", "ignore").decode()
    texte = re.sub(r"[^a-zA-Z0-9]+", "-", texte).strip("-").lower()
    return (texte or "chantier")[:48]


def nom_branche(brique_cible: str, intention: str) -> str:
    """Compose un nom de branche traçable et jamais réservé : `dev/<brique>-<intention>`.

    Préfixe `dev/` exprès : aucune branche d'atelier ne peut s'appeler `main`/`master`/…,
    donc le filet (interdiction de toucher la base) tient dès le nommage."""
    base = slug(brique_cible) if brique_cible else "atelier"
    return f"dev/{base}-{slug(intention)}"[:80]


def branche_protegee(branche: str) -> bool:
    """Vrai si la branche est une branche de prod qu'on ne doit jamais cibler."""
    return (branche or "").strip().lower() in BRANCHES_INTERDITES


@dataclass
class Chantier:
    """Agrégat : une demande de modification portée par une branche git jetable."""
    id: str
    intention: str
    brique_cible: str
    branche: str
    base: str = "HEAD"          # ref de départ (jamais modifiée)
    statut: str = CREE
    agent: str = ""             # "claude_code" | "opencode" | "factice"
    trace_active: bool = False  # narration pas-à-pas (pédagogique), opt-in
    sprint: str = ""            # rattachement à une story de sprint (optionnel)
    worktree: str = ""          # chemin de la copie de travail isolée
    resume: str = ""            # résumé du dernier passage de l'agent
    journal: list = field(default_factory=list)  # trace pas-à-pas si activée
    # ── Flux BMAD léger (S88), opt-in ───────────────────────────────────────────
    plan_requis: bool = False   # exiger un plan validé AVANT de coder (gate de plan)
    plan: dict = field(default_factory=dict)  # mini-PRD + stories + note DDD (cf. plan.py)
    plan_valide: bool = False   # le plan a passé le gate humain → le codage est débloqué

    def avancer(self, vers: str) -> None:
        """Change l'état en validant la transition (sinon lève)."""
        exiger_transition(self.statut, vers)
        self.statut = vers

    @property
    def peut_planifier(self) -> bool:
        """On ne (re)planifie qu'avant de coder : depuis `cree` ou `planifie`."""
        return self.statut in (CREE, PLANIFIE)

    @property
    def code_verrouille_par_plan(self) -> bool:
        """BMAD : tant qu'un plan requis n'est pas validé, le codage est verrouillé."""
        return self.plan_requis and not self.plan_valide

    @property
    def peut_lancer(self) -> bool:
        """L'agent peut-il (re)travailler ? Hors états terminaux ET hors verrou de plan."""
        return self.statut in (CREE, PLANIFIE, EN_COURS, REVUE) and not self.code_verrouille_par_plan

    @property
    def peut_fusionner(self) -> bool:
        """La fusion n'est possible qu'après revue (gate humain), S87."""
        return self.statut == REVUE

    def to_dict(self) -> dict:
        return asdict(self)
