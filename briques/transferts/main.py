"""Brique « transferts » — transfert de gros fichiers chiffrés bout-en-bout (S196).

Le serveur ne voit JAMAIS le clair : chaque fichier est chiffré (AES-256-GCM)
dans le navigateur de l'expéditeur AVANT l'upload, la clé vit uniquement dans
le fragment `#` de l'URL de partage (jamais envoyée au serveur, cf.
docs/ENCRYPTION.md du dépôt suitenumerique/transfers, vendoring du design en
S196). Ce fichier ne contient donc AUCUNE ligne de crypto : c'est un simple
stockage de blobs opaques + métadonnées + expiration.

Deux niveaux d'auth (cf. plan S196 § Risques/Décisions) :
  • `cle_api` (API_KEYS) gate les routes de GESTION : créer/lister/révoquer.
  • Les routes d'upload de partie / finalisation / téléchargement PUBLIC ne
    sont PAS gatées par API_KEYS (motif briques/restaurant, accès par QR) :
    leur protection vient de jetons non devinables (`jeton_upload`,
    `jeton_public` + fragment de clé côté navigateur).
  • `verifier_cle_horloge` (TRANSFERTS_KEY) gate uniquement /purge/executer,
    appelée par core/horloge.py (même motif que briques/veille-info).
"""
import os
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from pydantic import BaseModel

import stockage

app = FastAPI(title="Transferts — fichiers chiffrés bout-en-bout", version="0.1.0")

# Crée les tables si besoin (idempotent) — à l'import, une fois TRANSFERTS_DIR/
# TRANSFERTS_DB fixés par l'environnement (cf. stockage.py, pas de CREATE TABLE
# implicite dans _conn() ici contrairement à d'autres briques).
stockage.init_db()

_cors = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()] or ["*"]
app.add_middleware(CORSMiddleware, allow_origins=_cors, allow_methods=["*"], allow_headers=["*"])

API_KEYS = {k.strip() for k in os.getenv("API_KEYS", "").split(",") if k.strip()}


def cle_api(x_api_key: Optional[str] = Header(None),
            authorization: Optional[str] = Header(None),
            x_user_id: Optional[str] = Header(None)) -> str:
    presentee = x_api_key or (authorization or "").removeprefix("Bearer ").strip() or None
    if API_KEYS and presentee not in API_KEYS:
        raise HTTPException(401, "Clé API manquante ou invalide (header X-API-Key).")
    return x_user_id or "perso"


def verifier_cle_horloge(authorization: Optional[str] = Header(None)) -> None:
    """Gate de /purge/executer : jeton partagé TRANSFERTS_KEY (motif verifier_cle_horloge
    de briques/veille-info) — fail-closed si TRANSFERTS_KEY est défini."""
    attendu = os.environ.get("TRANSFERTS_KEY")
    if not attendu:
        return
    presentee = (authorization or "").removeprefix("Bearer ").strip()
    if presentee != attendu:
        raise HTTPException(401, "Jeton horloge invalide (header Authorization: Bearer ...).")


STATIC_DIR = Path(__file__).parent / "static"

TAILLE_PARTIE_OCTETS = int(os.getenv("TAILLE_PARTIE_OCTETS", str(16 * 1024 * 1024)))
TAILLE_MAX_OCTETS = int(os.getenv("TAILLE_MAX_OCTETS", str(20 * 1024 ** 3)))
EXPIRATION_MAX_HEURES = float(os.getenv("EXPIRATION_MAX_HEURES", "168"))
EXPIRATION_DEFAUT_HEURES = float(os.getenv("EXPIRATION_DEFAUT_HEURES", "72"))


class NouveauTransfert(BaseModel):
    expiration_heures: float = EXPIRATION_DEFAUT_HEURES


class NouveauFichier(BaseModel):
    nom: str
    type_mime: str = "application/octet-stream"
    taille_clair: int
    taille_partie: int


def _jeton_upload(x_upload_token: Optional[str] = Header(None)) -> str:
    if not x_upload_token:
        raise HTTPException(403, "En-tête X-Upload-Token manquant.")
    return x_upload_token


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def accueil():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/sante", tags=["système"])
def sante():
    return {"ok": True}


@app.get("/configuration", tags=["public"])
def configuration():
    return {
        "taille_partie_octets": TAILLE_PARTIE_OCTETS,
        "taille_max_octets": TAILLE_MAX_OCTETS,
        "expiration_max_heures": EXPIRATION_MAX_HEURES,
        "expiration_defaut_heures": EXPIRATION_DEFAUT_HEURES,
    }


@app.get("/sw.js", include_in_schema=False)
def service_worker():
    # Cache-Control: no-cache pour qu'un nouveau déploiement du SW s'active dès
    # le prochain chargement de page (motif upstream, docs/ENCRYPTION.md § SW scope).
    return FileResponse(STATIC_DIR / "sw.js", media_type="application/javascript",
                        headers={"Cache-Control": "no-cache"})


@app.post("/transferts", tags=["gestion"])
def creer_transfert(body: NouveauTransfert, proprietaire: str = Depends(cle_api)):
    heures = min(body.expiration_heures, EXPIRATION_MAX_HEURES)
    if heures <= 0:
        heures = EXPIRATION_DEFAUT_HEURES
    return stockage.creer_transfert(proprietaire, heures)


@app.post("/transferts/{tid}/fichiers", tags=["upload"])
def ajouter_fichier(tid: str, body: NouveauFichier, jeton: str = Depends(_jeton_upload)):
    try:
        return stockage.ajouter_fichier(tid, jeton, body.nom, body.type_mime,
                                        body.taille_clair, body.taille_partie)
    except ValueError as e:
        code = 403 if "jeton" in str(e).lower() else 422
        raise HTTPException(code, str(e)) from e


@app.put("/transferts/{tid}/fichiers/{fid}/parties/{numero}", tags=["upload"])
async def ecrire_partie(tid: str, fid: str, numero: int, request: Request,
                        jeton: str = Depends(_jeton_upload)):
    donnees = await request.body()
    try:
        return stockage.ecrire_partie(tid, fid, jeton, numero, donnees)
    except ValueError as e:
        code = 403 if "jeton" in str(e).lower() else 422
        raise HTTPException(code, str(e)) from e


@app.post("/transferts/{tid}/finaliser", tags=["upload"])
def finaliser(tid: str, jeton: str = Depends(_jeton_upload)):
    try:
        return stockage.finaliser_transfert(tid, jeton)
    except ValueError as e:
        code = 403 if "jeton" in str(e).lower() else 422
        raise HTTPException(code, str(e)) from e


@app.get("/t/{jeton_public}/meta", tags=["public"])
def meta_publique(jeton_public: str):
    pub = stockage.lire_transfert_public(jeton_public)
    if pub is None:
        raise HTTPException(404, "Lien introuvable.")
    if pub["statut"] != "actif":
        raise HTTPException(410, f"Lien {pub['statut']}.")
    return pub


@app.get("/t/{jeton_public}/fichiers/{fid}/chiffre", tags=["public"], include_in_schema=False)
def telecharger_ciphertext(jeton_public: str, fid: str):
    pub = stockage.lire_transfert_public(jeton_public)
    if pub is None:
        raise HTTPException(404, "Lien introuvable.")
    if pub["statut"] != "actif":
        raise HTTPException(410, f"Lien {pub['statut']}.")
    chemin = stockage.chemin_ciphertext(pub["id"], fid).resolve()
    if not str(chemin).startswith(str(stockage.DIR.resolve())) or not chemin.is_file():
        raise HTTPException(404, "Fichier introuvable.")
    stockage.enregistrer_telechargement(pub["id"])

    def flux():
        with open(chemin, "rb") as f:
            while morceau := f.read(1024 * 1024):
                yield morceau

    return StreamingResponse(flux(), media_type="application/octet-stream")


@app.get("/transferts", tags=["gestion"])
def lister(proprietaire: str = Depends(cle_api)):
    return stockage.lister_transferts(proprietaire)


@app.post("/transferts/{tid}/revoquer", tags=["gestion"])
def revoquer_route(tid: str, proprietaire: str = Depends(cle_api)):
    if not stockage.revoquer(tid, proprietaire):
        raise HTTPException(404, "Transfert introuvable (ou pas le vôtre).")
    return {"revoque": True}


@app.post("/purge/executer", tags=["système"], dependencies=[Depends(verifier_cle_horloge)])
def purge():
    return {"purges": stockage.purger_expires()}
