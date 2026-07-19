"""Brique « ecoute » — mot-clé « comme Siri » (openWakeWord) + paliers commerciaux S43.

S42 a livré le **moteur** : flux micro WebSocket → événement « réveil » (`detecteur.py`).
S43 ajoute les **deux paliers commerciaux** par-dessus le même moteur :

  • **Gratuit** : un catalogue de noms réellement embarqués (`catalogue.py`) ; le client
    en choisit un, le WS `/ecoute?mot=…` charge le modèle correspondant.
  • **Payant** : commande d'un **nom de marque** (`commandes.py`), facturée Stripe one-off
    (`paiement.py`, motif S21), entraînée par une **file pilotée par l'horloge S29**
    (`entrainement.py`, tâche déclarée au manifest). Une fois livré, le nom sur mesure
    rejoint la liste sélectionnable du WS.

Contrat WebSocket `/ecoute` (inchangé S42, + paramètre `mot`) :
  - trames binaires PCM 16 kHz mono int16 (flux micro) ;
  - `{"type":"pret","mot":…,"seuil":…}` à l'ouverture, `{"type":"reveil",…}` à chaque
    détection ; `?mot=<modèle>` choisit le nom (défaut = `hey_jarvis`).
"""
import os

from fastapi import (Depends, FastAPI, HTTPException, Request, WebSocket,
                     WebSocketDisconnect)
from pydantic import BaseModel
from starlette.websockets import WebSocketState

import catalogue
import commandes as cmd
import entrainement
import paiement
from detecteur import Detecteur, MOT_DEFAUT, SEUIL_DEFAUT
import auth

app = FastAPI(
    title="Workplace — brique ecoute",
    description="Détection de mot-clé (openWakeWord) + paliers commerciaux (gratuit/payant). "
                "Le navigateur streame le micro, le serveur signale chaque réveil. S42+S43.",
    version="0.2.0",
)

MAGASIN = cmd.MagasinCommandes()


# ── Santé ────────────────────────────────────────────────────────────────────

@app.get("/sante", tags=["sante"])
async def sante():
    """Santé : charge réellement le modèle par défaut (un /sante qui ne charge rien
    mentirait) et expose les compteurs des paliers."""
    try:
        Detecteur()  # lève si le modèle ONNX est absent/illisible
        MAGASIN.init_db()
        livrees = len(MAGASIN.livrees())
        return {"statut": "ok", "mot": MOT_DEFAUT, "seuil": SEUIL_DEFAUT,
                "moteur": "openwakeword", "noms_gratuits": len(catalogue.CATALOGUE_GRATUIT),
                "noms_sur_mesure_livres": livrees}
    except Exception as e:  # pragma: no cover - chemin d'erreur infra
        return {"statut": "degrade", "erreur": str(e)}


# ── Catalogue (palier gratuit + noms sur mesure livrés) ──────────────────────

def _resoudre_modele(mot: str) -> str | None:
    """Renvoie la référence à donner au `Detecteur` pour `mot`, ou None s'il est inconnu.

    - nom du catalogue gratuit → le nom lui-même (modèle embarqué) ;
    - nom sur mesure **livré** → le chemin du .onnx installé.
    """
    if catalogue.est_gratuit(mot):
        return mot
    chemin = entrainement.chemin_modele(mot)
    if chemin.exists() and any(c["modele"] == mot for c in MAGASIN.livrees()):
        return str(chemin)
    return None


@app.get("/noms", tags=["catalogue"])
async def noms():
    """Tous les noms sélectionnables : gratuits (embarqués) + sur mesure livrés."""
    MAGASIN.init_db()
    sur_mesure = [{"modele": c["modele"], "label": c["nom_marque"], "palier": "payant",
                   "factice": bool(c.get("factice"))} for c in MAGASIN.livrees()]
    gratuits = [{**n, "palier": "gratuit"} for n in catalogue.CATALOGUE_GRATUIT]
    return {"defaut": catalogue.nom_defaut(), "gratuits": gratuits, "sur_mesure": sur_mesure}


# ── WebSocket de détection ───────────────────────────────────────────────────

@app.websocket("/ecoute")
async def ecoute(ws: WebSocket):
    """Flux micro (binaire PCM int16 16 kHz) → événements « reveil ». `?mot=` choisit
    le modèle (défaut hey_jarvis) ; un nom inconnu ferme proprement (code 1008)."""
    mot = ws.query_params.get("mot") or MOT_DEFAUT
    ref = _resoudre_modele(mot)
    await ws.accept()
    if ref is None:
        await ws.send_json({"type": "erreur",
                            "message": f"Nom « {mot} » inconnu (ni gratuit ni livré)."})
        await ws.close(code=1008)
        return
    detecteur = Detecteur(mot=ref)
    await ws.send_json({"type": "pret", "mot": detecteur.mot, "seuil": detecteur.seuil})
    try:
        while True:
            msg = await ws.receive()
            if msg.get("type") == "websocket.disconnect":
                break
            pcm = msg.get("bytes")
            if pcm is None:
                if msg.get("text") == "reset":
                    detecteur.reset()
                continue
            for reveil in detecteur.alimenter(pcm):
                await ws.send_json({"type": "reveil", **reveil})
    except WebSocketDisconnect:
        pass
    finally:
        if ws.application_state != WebSocketState.DISCONNECTED:
            await ws.close()


# ── Palier payant : commandes ────────────────────────────────────────────────

class CommandeBody(BaseModel):
    nom_marque: str


@app.get("/paiement/etat", tags=["paiement"])
async def paiement_etat():
    """État honnête de la config Stripe (jamais la clé) — mock vs test/live."""
    return paiement.etat()


@app.post("/commandes", tags=["commandes"])
async def creer_commande(body: CommandeBody, proprietaire: str = Depends(auth.identite)):
    """Commande un nom de marque sur mesure au nom de `proprietaire` (S184 : isolation par
    personne) : crée la commande (idempotente par personne) et émet un lien de paiement
    Stripe (réel ou mock honnête). Si la marque est déjà livrée (catalogue partagé), aucune
    nouvelle commande n'est créée."""
    try:
        commande = MAGASIN.creer(body.nom_marque, proprietaire=proprietaire)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if commande.get("deja_disponible"):
        return {"commande": None, "paiement": None, "deja_disponible": True,
                "message": f"« {body.nom_marque} » est déjà disponible dans le catalogue."}
    # Émet/rafraîchit le lien de paiement tant que c'est en attente.
    checkout = None
    if commande["statut"] == "en_attente_paiement":
        try:
            checkout = paiement.creer_checkout(commande)
        except RuntimeError as e:
            raise HTTPException(status_code=502, detail=str(e))
        commande = MAGASIN.attacher_session(commande["id"], checkout["session_id"])
    return {"commande": cmd.vue(commande), "paiement": checkout}


@app.get("/commandes", tags=["commandes"])
async def lister_commandes(statut: str | None = None,
                           proprietaire: str = Depends(auth.identite)):
    MAGASIN.init_db()
    return [cmd.vue(c) for c in MAGASIN.lister(statut, proprietaire=proprietaire)]


@app.get("/commandes/{cid}", tags=["commandes"])
async def get_commande(cid: str, proprietaire: str = Depends(auth.identite)):
    c = MAGASIN.get(cid, proprietaire=proprietaire)
    if not c:
        raise HTTPException(status_code=404, detail="Commande inconnue.")
    return cmd.vue(c)


@app.post("/commandes/{cid}/payer", tags=["commandes"])
async def payer_mock(cid: str, proprietaire: str = Depends(auth.identite)):
    """Confirmation **mock** (mode dev sans Stripe). En mode live, c'est le webhook signé
    qui confirme → ici on refuse (409) pour ne pas court-circuiter la signature (cf. S21)."""
    if paiement.resoudre_cle():
        raise HTTPException(status_code=409,
                            detail="Stripe configuré : le paiement se confirme par le webhook signé, pas ici.")
    c = MAGASIN.get(cid, proprietaire=proprietaire)
    if not c:
        raise HTTPException(status_code=404, detail="Commande inconnue.")
    return cmd.vue(MAGASIN.marquer_payee(cid))


@app.post("/paiement/webhook", tags=["paiement"])
async def webhook(request: Request):
    """Webhook Stripe **public mais à signature vérifiée** (motif S21). À
    `checkout.session.completed` → la commande correspondante passe `payee`."""
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")
    try:
        event = paiement.verifier_webhook(payload, sig)
    except ValueError as e:
        if str(e) == "non_configure":
            raise HTTPException(status_code=503, detail="Webhook Stripe non configuré.")
        raise HTTPException(status_code=400, detail="Webhook invalide.")
    if event.get("type") == "checkout.session.completed":
        session_id = (event.get("data") or {}).get("object", {}).get("id")
        if session_id:
            c = MAGASIN.par_session(session_id)
            if c:
                MAGASIN.marquer_payee(c["id"])
    return {"received": True}


# ── File d'entraînement (tâche de l'horloge S29) ─────────────────────────────

@app.post("/entrainement/traiter", tags=["entrainement"])
async def traiter(_cle: None = Depends(auth.service_key)):
    """Tâche périodique appelée par l'**horloge S29** (déclarée au manifest) : avance la
    file (payee→entraînement→livrée) et relance les impayées. Idempotente. Gardée par
    ECOUTE_KEY (S184) : credential de service, pas une identité personne."""
    return entrainement.traiter_file(MAGASIN)


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "5800")))
