"""Brique « connexion » — parler à l'assistant depuis ses messageries (WhatsApp/Discord/Telegram…).

Pont bidirectionnel entre les réseaux externes et l'assistant du Cœur (`POST :5100/assistant/chat`,
flux SSE, stateless). Provider-agnostique (un adaptateur par réseau, cf. adaptateurs.py),
multi-utilisateur avec consentement (correspondance.py), historique persisté par interlocuteur
(conversations.py). Repli HONNÊTE : aucun réseau non configuré n'est simulé.

  • GET  /sante                  : réseaux connus / configurés + assistant joignable ;
  • GET  /webhook/{reseau}       : vérification d'abonnement (WhatsApp hub.challenge) ;
  • POST /webhook/{reseau}       : réception signée d'un message → relais à l'assistant ;
  • POST /sonder/{reseau}        : tirage actif (Telegram getUpdates) — appelé par l'horloge S29 ;
  • POST /envoyer                : envoi sortant manuel (admin) ;
  • GET/POST/DELETE /correspondances : administration du mapping interlocuteur → utilisateur.
"""
import os
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

import adaptateurs
import client_assistant
import correspondance
import pont

app = FastAPI(title="Connexion — pont messageries ↔ assistant", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

API_KEYS = {k.strip() for k in os.getenv("API_KEYS", "").split(",") if k.strip()}


def cle_api(x_api_key: Optional[str] = Header(None),
            authorization: Optional[str] = Header(None)) -> str:
    """Auth BYO optionnelle (X-API-Key ou Bearer). Mode ouvert si `API_KEYS` vide."""
    presentee = x_api_key or (authorization or "").removeprefix("Bearer ").strip() or None
    if not API_KEYS:
        return presentee or "public"
    if presentee in API_KEYS:
        return presentee
    raise HTTPException(401, "Clé API manquante ou invalide (header X-API-Key).")


class Envoi(BaseModel):
    reseau: str
    id_externe: str
    texte: str


class Liaison(BaseModel):
    reseau: Optional[str] = None
    id_externe: Optional[str] = None
    utilisateur: str
    code: Optional[str] = None        # alternative : lier par code de liaison


@app.get("/sante", tags=["système"])
async def sante():
    """État : réseaux connus, configurés, ordre, et assistant du Cœur joignable ?"""
    assistant_ok = False
    try:
        import httpx
        async with httpx.AsyncClient(timeout=3) as c:
            r = await c.get(client_assistant.url_chat().replace("/chat", "/config"))
            assistant_ok = r.status_code == 200
    except Exception:  # noqa: BLE001
        assistant_ok = False
    return {
        "ok": True,
        "reseaux": list(adaptateurs.REGISTRE.keys()),
        "ordre": adaptateurs.ordre(),
        "configures": adaptateurs.disponibles(),
        "mode_ouvert": correspondance.ouvert(),
        "assistant_joignable": assistant_ok,
    }


@app.get("/webhook/{reseau}", tags=["webhook"])
async def webhook_verif(reseau: str, request: Request):
    """Vérification d'abonnement webhook (WhatsApp renvoie `hub.challenge`)."""
    ad = adaptateurs.obtenir(reseau)
    if ad is None:
        raise HTTPException(404, f"Réseau inconnu : {reseau}")
    verif = getattr(ad, "verifier_get", None)
    if verif:
        defi = verif(dict(request.query_params))
        if defi is not None:
            return PlainTextResponse(defi)
        raise HTTPException(403, "Vérification d'abonnement refusée.")
    return {"ok": True, "reseau": reseau}


@app.post("/webhook/{reseau}", tags=["webhook"])
async def webhook(reseau: str, request: Request):
    """Réception d'un message entrant signé → relais à l'assistant. Auth = SIGNATURE du réseau."""
    ad = adaptateurs.obtenir(reseau)
    if ad is None:
        raise HTTPException(404, f"Réseau inconnu : {reseau}")
    corps = await request.body()
    if not ad.verifier_webhook(dict(request.headers), corps):
        raise HTTPException(401, "Signature de webhook invalide.")
    payload = await request.json()
    # Discord : répondre au PING par un PONG (type 1).
    if reseau == "discord" and isinstance(payload, dict) and payload.get("type") == 1:
        return {"type": 1}
    entrants = ad.parser_entrant(payload)
    comptes = [await pont.traiter(reseau, e) for e in entrants]
    return {"ok": True, "recus": len(entrants),
            "autorises": sum(1 for c in comptes if c.get("ok"))}


@app.post("/sonder/{reseau}", tags=["webhook"])
async def sonder(reseau: str):
    """Tirage actif des messages (Telegram getUpdates). Appelé par l'horloge S29 (manifest)."""
    if adaptateurs.obtenir(reseau) is None:
        raise HTTPException(404, f"Réseau inconnu : {reseau}")
    return await pont.sonder(reseau)


@app.post("/envoyer", tags=["admin"])
async def envoyer(body: Envoi, _cle: str = Depends(cle_api)):
    """Envoi sortant manuel (test / notification). Gardé par clé API."""
    ad = adaptateurs.obtenir(body.reseau)
    if ad is None:
        raise HTTPException(404, f"Réseau inconnu : {body.reseau}")
    if not ad.configure():
        raise HTTPException(409, f"Réseau « {body.reseau} » non configuré.")
    ok = await ad.envoyer(body.id_externe, body.texte)
    return {"ok": bool(ok)}


@app.get("/correspondances", tags=["admin"])
async def correspondances_lister(_cle: str = Depends(cle_api)):
    """Liste des interlocuteurs connus et de leur rattachement (consentement)."""
    return {"correspondances": correspondance.lister()}


@app.post("/correspondances", tags=["admin"])
async def correspondances_lier(body: Liaison, _cle: str = Depends(cle_api)):
    """Relie un interlocuteur à un utilisateur Workplace, par (réseau, id) OU par code."""
    if body.code:
        e = correspondance.lier_par_code(body.code, body.utilisateur)
        if e is None:
            raise HTTPException(404, "Code de liaison inconnu.")
        return {"ok": True, "correspondance": e}
    if not (body.reseau and body.id_externe):
        raise HTTPException(422, "Fournis (reseau + id_externe) ou un code de liaison.")
    e = correspondance.lier(body.reseau, body.id_externe, body.utilisateur)
    return {"ok": True, "correspondance": e}


@app.delete("/correspondances", tags=["admin"])
async def correspondances_delier(reseau: str, id_externe: str, _cle: str = Depends(cle_api)):
    """Détache un interlocuteur (il repassera « en attente »)."""
    return {"ok": correspondance.delier(reseau, id_externe)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "5870")))
