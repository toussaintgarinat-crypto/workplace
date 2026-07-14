"""Routes « profil » du Cœur (extrait de main.py, S114).

Profil & identité de l'opérateur, auto-amélioration et curateur.
"""
import os
from fastapi import APIRouter
from etat import registre
import amelioration
import assistant
import curateur
import horloge
import identite
import proprioception

router = APIRouter()

# Le refactor S114 a déplacé ces routes ici mais laissé `_lire_profil`/`profil_get`/`profil_post`
# référencer PROFIL_PATH/PROFIL_DEFAUT_PATH sans les définir → NameError, /profil en 500. On les
# (re)définit ici, mêmes valeurs que le router assistant (env, sinon volume /data et défaut baké).
PROFIL_PATH = os.getenv("PROFIL_PATH", "/data/profil.md")
PROFIL_DEFAUT_PATH = os.getenv("PROFIL_DEFAUT_PATH", "/app/profil_defaut.md")


@router.get("/amelioration", tags=["assistant"])
async def amelioration_lister():
    """Liste les propositions d'addendum de prompt + l'addendum actif (S69)."""
    return amelioration.lister()


@router.post("/amelioration/proposer", tags=["assistant"])
async def amelioration_proposer():
    """Propose un addendum de prompt à partir d'un point faible de la proprioception
    (réflexion façon GEPA, repli template honnête). INACTIF tant que non validé."""
    return await amelioration.proposer()


@router.post("/amelioration/{id_}/evaluer", tags=["assistant"])
async def amelioration_evaluer(id_: str):
    """A/B honnête : rejoue des questions sous prompt actuel vs + addendum, note les deux."""
    return await amelioration.evaluer(id_)


@router.post("/amelioration/{id_}/valider", tags=["assistant"])
async def amelioration_valider(id_: str):
    """Gate humain — étape 1 : valide la proposition (ne l'active pas encore)."""
    return amelioration.valider(id_)


@router.post("/amelioration/{id_}/appliquer", tags=["assistant"])
async def amelioration_appliquer(id_: str):
    """Gate humain — étape 2 : active l'addendum (refusé si non validé). Réversible."""
    return amelioration.appliquer(id_)


@router.post("/amelioration/{id_}/rejeter", tags=["assistant"])
async def amelioration_rejeter(id_: str):
    """Écarte une proposition ; la désactive si elle était active."""
    return amelioration.rejeter(id_)


@router.post("/amelioration/desactiver", tags=["assistant"])
async def amelioration_desactiver():
    """Revient au prompt fondateur : aucun addendum actif (historique conservé)."""
    return amelioration.desactiver()


# ── Curator (S70) : cycle hebdo proprioception → propositions → digest 🔔 ─────
@router.post("/curateur/cycle", tags=["assistant"])
async def curateur_cycle(forcer: bool = False):
    """Un tour de curation (S70) : mesure → propose un addendum de prompt (S69) + un
    brouillon de capacité manquante → dépose un digest en rappel 🔔. PROPOSE, n'applique
    rien. Idempotent par jour ; déclenché par l'horloge (tâche `curation-hebdo`)."""
    return await curateur.curer(registre, forcer=forcer)


@router.get("/curateur/capacites", tags=["assistant"])
async def curateur_capacites():
    """Brouillons de capacités proposés (spécifications à implémenter, S70)."""
    return curateur.lister_capacites()


@router.post("/curateur/capacites/{id_}/retenir", tags=["assistant"])
async def curateur_retenir(id_: str):
    """Gate humain : retient un brouillon comme spéc à implémenter (n'active rien)."""
    return curateur.retenir_capacite(id_)


@router.post("/curateur/capacites/{id_}/rejeter", tags=["assistant"])
async def curateur_rejeter(id_: str):
    """Écarte un brouillon de capacité."""
    return curateur.rejeter_capacite(id_)


def _lire_profil() -> str:
    for chemin in (PROFIL_PATH, PROFIL_DEFAUT_PATH):
        try:
            with open(chemin, encoding="utf-8") as f:
                return f.read()
        except FileNotFoundError:
            continue
    return ""


@router.get("/profil", tags=["profil"])
async def profil_get():
    """Profil de l'utilisateur (Markdown). Renvoie la version enregistrée si elle
    existe, sinon le défaut baké dans l'image."""
    return {"contenu": _lire_profil(), "modifie": os.path.exists(PROFIL_PATH)}


@router.post("/profil", tags=["profil"])
async def profil_post(corps: dict):
    """Enregistre le profil dans le volume du Cœur (persistant)."""
    contenu = corps.get("contenu", "")
    os.makedirs(os.path.dirname(PROFIL_PATH), exist_ok=True)
    with open(PROFIL_PATH, "w", encoding="utf-8") as f:
        f.write(contenu)
    return {"ok": True, "taille": len(contenu)}


# ── Fiche d'identité structurée + dérivations (S48 — « se présenter ») ──
# « Se présenter » via 5 champs (prénoms, nom, date/heure/lieu de naissance) → l'assistant
# en dérive plein d'infos (âge, anniversaire, signes, numérologie, mini-thème astral) ET
# reçoit un digest compact dans son contexte. La fiche est À CÔTÉ du profil Markdown libre.
@router.get("/profil/identite", tags=["profil"])
async def identite_get():
    """Fiche d'identité enregistrée + tout ce qu'on en dérive (calcul à la volée)."""
    fiche = identite.charger_fiche()
    return {"fiche": fiche, "derive": identite.deriver(fiche),
            "modifie": identite.FICHE_PATH.exists()}


@router.patch("/profil/identite", tags=["profil"])
async def identite_patch(corps: dict):
    """Met à jour la fiche (champs connus fusionnés) et renvoie les dérivations à jour."""
    fiche = identite.enregistrer_fiche(corps or {})
    return {"ok": True, "fiche": fiche, "derive": identite.deriver(fiche)}
