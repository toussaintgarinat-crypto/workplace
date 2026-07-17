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
  • POST /pousser                : envoi PROACTIF à un utilisateur (rappels d'agenda du Cœur) ;
  • GET/POST/DELETE /correspondances : administration du mapping interlocuteur → utilisateur.
"""
import os
from pathlib import Path
from typing import Optional

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import (FileResponse, JSONResponse, PlainTextResponse,
                               RedirectResponse, StreamingResponse)
from pydantic import BaseModel
from starlette.background import BackgroundTask

import adaptateurs
import appareils
import client_assistant
import correspondance
import miniapp
import pont

app = FastAPI(title="Connexion — pont messageries ↔ assistant", version="0.1.0")
# Origines navigateur autorisées : liste explicite via CORS_ORIGINS (CSV). Défaut "*"
# = comportement historique. En contexte MULTI-TENANT (même local : autre tenant/
# assistant sur la machine), définir CORS_ORIGINS=http://localhost:5100,... pour
# qu'une page web tierce ne puisse pas appeler cette brique depuis le navigateur.
_cors = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()] or ["*"]
app.add_middleware(CORSMiddleware, allow_origins=_cors, allow_methods=["*"], allow_headers=["*"])

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


class Pousser(BaseModel):
    utilisateur: str
    texte: str


class Liaison(BaseModel):
    reseau: Optional[str] = None
    id_externe: Optional[str] = None
    utilisateur: str
    code: Optional[str] = None        # alternative : lier par code de liaison


class InitData(BaseModel):
    init_data: str


class MiniChat(BaseModel):
    messages: list
    init_data: Optional[str] = None   # repli si l'en-tête n'est pas transmis


class AppareilPush(BaseModel):
    endpoint: str
    keys: dict = {}
    ua: Optional[str] = None


class EnregistrerAppareil(BaseModel):
    utilisateur: str
    appareil: AppareilPush


class RetirerAppareil(BaseModel):
    endpoint: str


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


@app.post("/pousser", tags=["admin"])
async def pousser(body: Pousser, _cle: str = Depends(cle_api)):
    """Envoi PROACTIF vers un utilisateur (ses messageries liées) — rappels du Cœur.

    Le Cœur ne connaît que l'utilisateur Workplace ; c'est le pont qui sait OÙ le
    joindre (correspondance). On envoie sur chaque réseau lié ET configuré. Repli
    honnête : aucune cible joignable ⇒ `envoyes: 0` (pas une erreur)."""
    cibles = correspondance.cibles_pour(body.utilisateur)
    envoyes, detail = 0, []
    for reseau, id_externe in cibles:
        ad = adaptateurs.obtenir(reseau)
        if ad is None or not ad.configure():
            detail.append({"reseau": reseau, "envoye": False, "raison": "non configuré"})
            continue
        try:
            await ad.envoyer(id_externe, body.texte)
            envoyes += 1
            detail.append({"reseau": reseau, "envoye": True})
        except Exception as ex:  # noqa: BLE001 — un réseau KO ne bloque pas les autres
            detail.append({"reseau": reseau, "envoye": False, "raison": str(ex)})
    return {"ok": True, "envoyes": envoyes, "cibles": len(cibles), "detail": detail}


@app.get("/push/cle_publique", tags=["push"])
async def push_cle_publique():
    """Clé publique VAPID (publique par nature) : le navigateur en a besoin pour s'inscrire."""
    return {"cle": os.getenv("VAPID_PUBLIC_KEY", "")}


@app.post("/push/appareils", tags=["push"])
async def push_enregistrer(body: EnregistrerAppareil, _cle: str = Depends(cle_api)):
    """Enregistre un appareil push web d'un utilisateur (device, PAS abonnement payant).
    L'appareil devient une cible de correspondance → `/pousser` le fanout ensuite."""
    app_enr = appareils.enregistrer(body.utilisateur, body.appareil.model_dump())
    correspondance.lier("webpush", app_enr["endpoint"], body.utilisateur)
    return {"ok": True}


@app.delete("/push/appareils", tags=["push"])
async def push_retirer(body: RetirerAppareil, _cle: str = Depends(cle_api)):
    """Retire un appareil (coupure des notifs sur ce navigateur)."""
    ok = appareils.retirer(body.endpoint)
    correspondance.delier("webpush", body.endpoint)
    return {"ok": ok}


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


# ── Mini App Telegram (S77) : front public GARDÉ, le Cœur reste interne ──────────
# La page est servie DANS Telegram ; elle s'authentifie par `initData` signé (HMAC du
# token bot), résout l'utilisateur via le consentement (correspondance), puis dialogue
# en relayant le flux SSE du Cœur TEL QUEL (les boutons d'action S76 passent au travers).
def _init_data(corps: Optional[str], entete: Optional[str]) -> str:
    return (entete or corps or "").strip()


@app.post("/miniapp/auth", tags=["miniapp"])
async def miniapp_auth(body: InitData, x_telegram_init_data: Optional[str] = Header(None)):
    """Valide l'`initData` Telegram et dit si l'utilisateur est autorisé (sinon : code de
    liaison à transmettre, comme l'accueil du pont). Stateless : rien n'est stocké ici."""
    return miniapp.autoriser(_init_data(body.init_data, x_telegram_init_data))


@app.post("/miniapp/session", tags=["miniapp"])
async def miniapp_session(body: InitData, x_telegram_init_data: Optional[str] = Header(None)):
    """Ouvre une SESSION pour la Mini App « app complète » (S79) : valide l'initData une
    fois et, si autorisé, pose un cookie de session signé. Le reverse-proxy s'appuie ensuite
    sur ce cookie pour servir tout le dashboard du Cœur (sans revalider à chaque requête)."""
    auth = miniapp.autoriser(_init_data(body.init_data, x_telegram_init_data))
    if not auth.get("ok"):
        return JSONResponse(auth, status_code=200)
    jeton = miniapp.creer_session(auth.get("user") or {}, auth.get("utilisateur"))
    rep = JSONResponse({"ok": True, "nom": auth.get("nom")})
    rep.set_cookie(miniapp.COOKIE_SESSION, jeton, max_age=86400, httponly=True,
                   samesite="lax", secure=True, path="/")
    return rep


@app.post("/miniapp/chat", tags=["miniapp"])
async def miniapp_chat(body: MiniChat, x_telegram_init_data: Optional[str] = Header(None)):
    """Relais gardé vers l'assistant du Cœur. Auth = `initData` revalidé à CHAQUE appel
    (stateless). On préfixe un message système « qui parle » (multi-utilisateur) puis on
    proxifie le flux SSE du Cœur sans le dénaturer (deltas, outils, actions S76)."""
    auth = miniapp.autoriser(_init_data(body.init_data, x_telegram_init_data))
    if not auth.get("ok"):
        raise HTTPException(401, auth.get("raison", "non autorisé"))
    qui = auth.get("nom") or "un interlocuteur"
    util = auth.get("utilisateur")
    contexte = ("Tu es l'assistant de Workplace. Tu dialogues via la Mini App Telegram avec "
                f"« {qui} »" + (f" (compte Workplace : {util})." if util else ".")
                + " Réponds en texte clair et concis.")
    messages = [{"role": "system", "content": contexte}, *body.messages]
    # Trace unifiée (S78) : la Mini App est une surface Telegram → même fil que le pont
    # (clé telegram:<id>), pour que tout l'échange figure dans l'historique du Cœur.
    uid = str((auth.get("user") or {}).get("id") or "miniapp")
    corps_coeur = {"messages": messages, "surface": "telegram",
                   "interlocuteur": uid, "utilisateur": util}

    async def flux():
        try:
            async with httpx.AsyncClient(timeout=120) as c:
                async with c.stream("POST", client_assistant.url_chat(),
                                    json=corps_coeur) as r:
                    async for chunk in r.aiter_raw():
                        yield chunk
        except Exception:  # noqa: BLE001 — Cœur injoignable → évènement d'erreur honnête
            import json as _json
            yield ("data: " + _json.dumps(
                {"type": "erreur", "contenu": "Assistant injoignable."}) + "\n\n").encode()

    return StreamingResponse(flux(), media_type="text/event-stream")


@app.get("/miniapp", tags=["miniapp"], include_in_schema=False)
async def miniapp_page():
    """Sert la page de la Mini App (à pointer depuis le menu BotFather, en HTTPS public)."""
    page = Path(__file__).parent / "front_miniapp.html"
    if not page.exists():
        raise HTTPException(404, "Front Mini App absent.")
    return FileResponse(page, media_type="text/html")


def _coeur_base() -> str:
    """Racine interne du Cœur (jamais exposée directement) — même base que client_assistant."""
    return os.getenv("NOYAU_ASSISTANT_URL", "http://host.docker.internal:5100").rstrip("/")


async def _fermer(reponse, client) -> None:
    await reponse.aclose()
    await client.aclose()


# ── Reverse-proxy GARDÉ (S79) : l'app Workplace COMPLÈTE dans la Mini App ────────
# Tout chemin non servi par la brique est relayé au dashboard du Cœur INTERNE, à condition
# de présenter un cookie de session valide (posé par /miniapp/session après un initData
# vérifié). Le Cœur reste interne ; seul un utilisateur Telegram autorisé voit l'app.
# Déclaré EN DERNIER : les routes spécifiques de la brique (sante, webhook, miniapp,
# correspondances…) sont prioritaires. Streaming préservé (SSE du chat, boutons S76).
@app.api_route("/{chemin:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
               include_in_schema=False)
async def proxy_dashboard(chemin: str, request: Request):
    if not miniapp.verifier_session(request.cookies.get(miniapp.COOKIE_SESSION)):
        if request.method == "GET":
            return RedirectResponse("/miniapp")           # pas de session → (ré)authentifier
        raise HTTPException(401, "Session Mini App requise.")
    url = f"{_coeur_base()}/{chemin}"
    corps = await request.body()
    entetes = {k: v for k, v in request.headers.items()
               if k.lower() in ("content-type", "accept", "accept-language")}
    client = httpx.AsyncClient(timeout=None)
    req = client.build_request(request.method, url, params=dict(request.query_params),
                               content=corps, headers=entetes)
    r = await client.send(req, stream=True)
    filtres = ("content-type", "cache-control", "content-disposition")
    sortie = {k: v for k, v in r.headers.items() if k.lower() in filtres}
    return StreamingResponse(r.aiter_raw(), status_code=r.status_code, headers=sortie,
                             background=BackgroundTask(_fermer, r, client))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "5870")))
