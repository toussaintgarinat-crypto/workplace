"""Brique « ecoute » (S42) — service de mot-clé « comme Siri » (openWakeWord).

POURQUOI une brique serveur et pas le navigateur : openWakeWord est Python/ONNX,
pas du JS. Le navigateur capte le micro et **streame** l'audio ici par WebSocket
(protocole calqué sur l'intégration Unmute existante, `core/main.py`), exactement
comme Unmute reçoit le flux micro. Bonus marque blanche : l'audio passe par NOTRE
infra, plus par Google (≠ Web Speech actuel).

Contrat WebSocket `/ecoute` :
  - le client envoie des **trames binaires** PCM 16 kHz mono int16 (le flux micro) ;
  - le serveur renvoie un **message JSON** `{"type":"reveil","mot":...,"score":...}`
    à chaque détection du mot-clé ;
  - à l'ouverture, le serveur annonce `{"type":"pret","mot":...,"seuil":...}`.

Le navigateur, à réception de « reveil », déclenche la capture de la commande puis
l'envoie à `/assistant/chat` (fournisseur `creerWakeWord()` côté Cœur).

La détection elle-même vit dans `detecteur.py` (testable hors ligne). Ici on ne fait
que le câblage réseau : un `Detecteur` par connexion (état/réfraction isolés).
"""
import os

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from detecteur import Detecteur, MOT_DEFAUT, SEUIL_DEFAUT

app = FastAPI(
    title="Workplace — brique ecoute",
    description="Détection de mot-clé (openWakeWord) en flux WebSocket. Le navigateur "
                "streame le micro, le serveur signale chaque réveil. S42.",
    version="0.1.0",
)


@app.get("/sante", tags=["sante"])
async def sante():
    """Santé de la brique. Charge le modèle au moins une fois pour prouver qu'il est
    bien embarqué et opérant (honnêteté : un /sante qui ne charge rien mentirait)."""
    try:
        Detecteur()  # lève si le modèle ONNX est absent/illisible
        return {"statut": "ok", "mot": MOT_DEFAUT, "seuil": SEUIL_DEFAUT, "moteur": "openwakeword"}
    except Exception as e:  # pragma: no cover - chemin d'erreur infra
        return {"statut": "degrade", "erreur": str(e)}


@app.websocket("/ecoute")
async def ecoute(ws: WebSocket):
    """Flux micro entrant (binaire PCM int16 16 kHz) → événements « reveil » sortants."""
    await ws.accept()
    detecteur = Detecteur()
    await ws.send_json({"type": "pret", "mot": detecteur.mot, "seuil": detecteur.seuil})
    try:
        while True:
            msg = await ws.receive()
            if msg.get("type") == "websocket.disconnect":
                break
            pcm = msg.get("bytes")
            if pcm is None:
                # Texte de contrôle (ex. {"type":"reset"}) : on tolère, on relance le flux.
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


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "5800")))
