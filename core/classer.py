"""Classement automatique d'un document par le LLM (Sprint S9).

Quand l'utilisateur dépose un document, le Cœur l'ingère (brique `ingestion`) puis demande au
**même cerveau** que l'assistant (via le Gateway, modèle réglé dans le panneau
⚙ Cerveau) de le RANGER : catégorie, mots-clés, entreprise rattachée, projet,
et un court résumé. Le résultat est un JSON strict, fusionné ensuite dans les
`metadonnees.classement` du document (cf. `ingestion` : `PATCH /documents/{id}/classement`).

Réutilisé par l'endpoint d'upload ET par l'outil `classer_document` de l'assistant.
Aucune logique métier réécrite : on ne fait qu'appeler le LLM et normaliser sa réponse.
"""

import json
import logging

import config_assistant
import langue as langue_mod
import llm_pipeline

logger = logging.getLogger(__name__)

CATEGORIES = ["devis", "facture", "contrat", "compte_rendu", "specification",
              "courrier", "note", "rapport", "autre"]


def _prompt(langue=None) -> str:
    """Prompt de classement. Les CLÉS et les CATÉGORIES restent structurelles (lues
    par l'ingestion) ; seul le `resume` suit la langue du Jarvis (S39, défaut `fr`)."""
    return (
        "Tu es un archiviste. On te donne le NOM et le TEXTE d'un document, et la liste "
        "des ENTREPRISES connues de la solution. Range ce document.\n"
        "Réponds UNIQUEMENT par un objet JSON valide, sans texte autour, avec ces clés :\n"
        '  "categorie" : une parmi ' + ", ".join(CATEGORIES) + ".\n"
        '  "tags"      : 2 à 5 mots-clés courts (minuscules), tableau de chaînes.\n'
        '  "entreprise": le NOM EXACT d\'une entreprise de la liste si le document la '
        "concerne clairement, sinon null.\n"
        '  "projet"    : le nom d\'un projet/dossier si le document s\'y rapporte '
        "explicitement (ex. « prochain sprint »), sinon null.\n"
        '  "resume"    : une phrase (≤ 200 caractères) résumant le document, '
        + langue_mod.consigne_resume(langue) + ".\n"
    )


def _entreprises_connues() -> list[dict]:
    """[{nom, livraison_id}] depuis l'orchestrateur (import tardif : évite un cycle)."""
    import orchestrateur
    out = []
    for liv in orchestrateur.lister_livraisons():
        nom = liv.get("nom_entreprise")
        if nom:
            out.append({"nom": nom, "livraison_id": liv.get("id")})
    return out


def _extraire_json(contenu: str) -> dict:
    """Parse défensif : tente le JSON direct, sinon isole le premier objet {...}."""
    contenu = (contenu or "").strip()
    try:
        return json.loads(contenu)
    except json.JSONDecodeError:
        debut, fin = contenu.find("{"), contenu.rfind("}")
        if debut != -1 and fin > debut:
            try:
                return json.loads(contenu[debut:fin + 1])
            except json.JSONDecodeError:
                pass
    return {}


async def classer_texte(texte: str, nom: str) -> dict:
    """Demande au LLM de classer un document. Renvoie un classement normalisé.

    Clés renvoyées : categorie, tags[], entreprise_nom, entreprise_id, projet, resume.
    En cas d'échec LLM, renvoie un classement minimal (categorie='autre') sans lever.
    """
    entreprises = _entreprises_connues()
    noms = [e["nom"] for e in entreprises]
    user = (
        f"NOM: {nom}\n"
        f"ENTREPRISES CONNUES: {', '.join(noms) if noms else '(aucune)'}\n"
        f"TEXTE (tronqué):\n{(texte or '')[:4000]}"
    )
    conf = config_assistant.charger()
    modeles = [conf["model"]] + [m for m in conf["fallback_models"] if m != conf["model"]]

    # Pipeline unifié (S138) : bascule de modèles + comptage tokens/coût + journal.
    # Le classement est un prompt court et stable : pas de trimming nécessaire.
    res = await llm_pipeline.completer(
        [{"role": "system", "content": _prompt(conf.get("langue"))},
         {"role": "user", "content": user}],
        modeles=modeles, temperature=0,
        response_format={"type": "json_object"},
        etiquette="classement", trim_contexte=False, cache=True, timeout=60,
    )
    if not res.ok:
        logger.warning("Classement : %s", res.erreur)
    brut = _extraire_json(res.contenu) if res.ok else {}

    return _normaliser(brut, entreprises)


def _normaliser(brut: dict, entreprises: list[dict]) -> dict:
    cat = (brut.get("categorie") or "autre")
    if cat not in CATEGORIES:
        cat = "autre"
    tags = brut.get("tags") or []
    if not isinstance(tags, list):
        tags = [str(tags)]
    tags = [str(t).strip().lower() for t in tags if str(t).strip()][:5]

    nom_ent = brut.get("entreprise")
    ent_id = None
    if nom_ent:
        # Rapprochement souple (casse / espaces) avec une entreprise connue.
        cible = str(nom_ent).strip().lower()
        for e in entreprises:
            if e["nom"].strip().lower() == cible:
                nom_ent, ent_id = e["nom"], e["livraison_id"]
                break
        else:
            nom_ent = None  # le LLM a inventé un nom hors liste → on ignore

    projet = brut.get("projet")
    projet = str(projet).strip() if projet else None
    resume = brut.get("resume")
    resume = str(resume).strip()[:200] if resume else None

    return {"categorie": cat, "tags": tags, "entreprise_nom": nom_ent,
            "entreprise_id": ent_id, "projet": projet, "resume": resume}
