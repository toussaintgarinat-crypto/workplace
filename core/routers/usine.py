"""Routes « usine » du Cœur (extrait de main.py, S114).

Usine à applications : livraisons (lister/détail/supprimer/décrocher/reprendre).
"""
import uuid
from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile
from etat import registre
import cycle_de_vie
import orchestrateur
import outils
from urls_ui import GENERATEUR_URL_PUBLIQUE

router = APIRouter()


@router.post("/usine/livrer", status_code=202, tags=["usine"])
async def livrer(
    background_tasks: BackgroundTasks,
    fichiers: list[UploadFile] = File(default=[]),
    nom_entreprise: str = Form("Entreprise"),
    persistance: str = Form("hebergee"),
    messagerie: bool = Form(False),
    packager: bool = Form(False),
    email_client: str = Form(""),
    contact_client: str = Form(""),
    langue: str = Form("fr"),
):
    """Livre une entreprise en une commande : ingère les documents, lance l'audit,
    génère l'app (→ packaging optionnel). Renvoie un id de livraison à suivre.

    - `fichiers` : documents de l'entreprise (optionnel — sinon on audite les
      documents déjà ingérés).
    - `persistance` : « hebergee » (multi-utilisateur, défaut) ou « autonome ».
    - `messagerie` : embarquer la messagerie Oria (mode hébergé requis).
    - `packager` : produire en plus un bundle Docker de déploiement.
    - `email_client` : si fourni, on crée à la livraison un compte d'accès Oria à cet
      email + envoie un lien « définis ton mot de passe » et rattache le client à son
      espace (S23, best-effort). `contact_client` = nom du contact (optionnel).
    - `langue` (S37) : langue de l'app livrée — « fr » (défaut) | « en » | « es » | « ar ».
      Toute valeur inconnue est ramenée à « fr » par le générateur (repli honnête).
    """
    mode = "hebergee" if persistance == "hebergee" else "autonome"
    langue = (langue or "fr").strip().lower()[:2] or "fr"
    email_client = (email_client or "").strip()
    contact_client = (contact_client or "").strip()
    # Lire le contenu des uploads AVANT de rendre la main (les fichiers temporaires
    # sont fermés à la fin de la requête ; la tâche de fond tourne après).
    charges = [(f.filename, await f.read(), f.content_type) for f in fichiers]

    livraison_id = str(uuid.uuid4())
    orchestrateur.creer_livraison(livraison_id, nom_entreprise, mode, messagerie, packager,
                                  email_client, contact_client)
    background_tasks.add_task(
        orchestrateur.executer_pipeline,
        registre, livraison_id, charges, mode, messagerie, packager,
        email_client, contact_client, langue,
    )
    return {"id": livraison_id, "statut": "en_cours", "nom_entreprise": nom_entreprise,
            "mode": mode, "messagerie": messagerie, "packager": packager, "langue": langue,
            "compte_client": bool(email_client), "nb_fichiers": len(charges)}


def _enrichir_livraison(liv: dict) -> dict:
    """Ajoute les URLs publiques de l'app (vues depuis le navigateur)."""
    if liv.get("app_id"):
        liv["url_apercu"] = f"{GENERATEUR_URL_PUBLIQUE}/apps/{liv['app_id']}/apercu"
        liv["url_html"] = f"{GENERATEUR_URL_PUBLIQUE}/apps/{liv['app_id']}/html"
    return liv


@router.get("/usine/livraisons", tags=["usine"])
def lister_livraisons():
    """Tableau des entreprises livrées."""
    livraisons = [_enrichir_livraison(l) for l in orchestrateur.lister_livraisons()]
    return {"total": len(livraisons), "livraisons": livraisons}


@router.get("/usine/livraisons/{livraison_id}", tags=["usine"])
def detail_livraison(livraison_id: str):
    liv = orchestrateur.lire_livraison(livraison_id)
    if not liv:
        raise HTTPException(404, "Livraison introuvable")
    return _enrichir_livraison(liv)


@router.delete("/usine/livraisons/{livraison_id}", status_code=204, tags=["usine"])
def supprimer_livraison(livraison_id: str):
    orchestrateur.supprimer_livraison(livraison_id)


# ── Cycle de vie des entreprises (S6) ────────────────────────────────────────
# Décrocher = sortir l'entreprise des bases centrales vers un dossier portable.
# Reprendre = la réinjecter pour la modifier, puis on peut la re-décrocher.

@router.post("/usine/livraisons/{livraison_id}/decrocher", tags=["usine"])
async def decrocher_entreprise(livraison_id: str):
    """Met une entreprise « de côté » : rassemble son état dans un dossier portable
    et la retire des bases centrales (la solution principale est libérée)."""
    try:
        return await cycle_de_vie.decrocher(registre, livraison_id)
    except ValueError as e:
        raise HTTPException(404, str(e))
    except cycle_de_vie.EchecCycle as e:
        raise HTTPException(502, str(e))


@router.post("/usine/livraisons/{livraison_id}/reprendre", tags=["usine"])
async def reprendre_entreprise(livraison_id: str):
    """Réinjecte une entreprise décrochée dans la solution principale (pour la modifier)."""
    try:
        return await cycle_de_vie.reprendre(registre, livraison_id)
    except ValueError as e:
        raise HTTPException(404, str(e))
    except cycle_de_vie.EchecCycle as e:
        raise HTTPException(502, str(e))


# ── Assistant conversationnel du Cœur (S7) ───────────────────────────────────
# Un agent qui dialogue et pilote l'usine via ses outils (lecture + actions
# gardées par confirmation). Flux d'événements en SSE.
