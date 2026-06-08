"""Brique ETL / Ingestion — Workplace v0.1.0"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, HttpUrl

import extraction
import stockage

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(name)s  %(message)s")
logger = logging.getLogger("etl")


@asynccontextmanager
async def lifespan(app: FastAPI):
    stockage.initialiser()
    logger.info("Brique ETL démarrée — DB initialisée")
    yield


app = FastAPI(
    title="Workplace — Brique ETL",
    description="Ingestion de documents : extraction de texte et stockage pour l'Audit.",
    version="0.1.0",
    lifespan=lifespan,
)


# ── Schémas ──────────────────────────────────────────────────────────────────

class IngressionURL(BaseModel):
    url: HttpUrl


class ReponseDocument(BaseModel):
    id: str
    nom: str
    source: str
    type_mime: str | None
    taille: int
    nb_caracteres: int
    date_ingestion: str


class ReponseDocumentComplet(ReponseDocument):
    texte_extrait: str
    metadonnees: dict


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/sante")
def sante():
    nb = stockage.compter()
    return {"statut": "ok", "service": "etl", "documents_ingeres": nb}


@app.post("/ingerer", summary="Uploader et ingérer un fichier")
async def ingerer_fichier(fichier: UploadFile = File(...)):
    contenu = await fichier.read()
    taille = len(contenu)
    if taille == 0:
        raise HTTPException(status_code=400, detail="Fichier vide")
    if taille > 50 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Fichier trop grand (max 50 Mo)")

    logger.info("Ingestion fichier : %s (%d octets)", fichier.filename, taille)
    texte = extraction.extraire_texte(contenu, fichier.filename or "inconnu", fichier.content_type)

    doc_id = stockage.sauvegarder(
        nom=fichier.filename or "inconnu",
        source="upload",
        type_mime=fichier.content_type,
        taille=taille,
        texte=texte,
    )

    logger.info("Document sauvegardé : %s (%d caractères extraits)", doc_id, len(texte))
    return {
        "id": doc_id,
        "nom": fichier.filename,
        "nb_caracteres": len(texte),
        "message": "Document ingéré avec succès",
    }


@app.post("/ingerer/url", summary="Ingérer depuis une URL")
async def ingerer_url(corps: IngressionURL):
    url_str = str(corps.url)
    logger.info("Ingestion URL : %s", url_str)

    try:
        texte, nom = await extraction.extraire_depuis_url(url_str)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Impossible de récupérer l'URL : {e}")

    doc_id = stockage.sauvegarder(
        nom=nom,
        source=url_str,
        type_mime="text/html",
        taille=len(texte.encode()),
        texte=texte,
        metadonnees={"url_originale": url_str},
    )

    return {
        "id": doc_id,
        "nom": nom,
        "url": url_str,
        "nb_caracteres": len(texte),
        "message": "URL ingérée avec succès",
    }


@app.post("/documents/import", summary="Réimporter un document (reprise de dossier S6)")
def importer_document(doc: dict):
    """Réinsère un document complet (id + texte déjà extrait préservés).

    Utilisé par le Cœur pour « reprendre » une entreprise précédemment décrochée,
    sans relancer l'extraction.
    """
    doc_id = stockage.importer(doc)
    return {"id": doc_id, "message": "Document réimporté"}


@app.get("/documents", summary="Lister les documents ingérés")
def lister_documents(
    limite: int = 50,
    offset: int = 0,
    categorie: str | None = None,
    projet: str | None = None,
    entreprise_id: str | None = None,
):
    docs = stockage.lister(
        limite=limite, offset=offset,
        categorie=categorie, projet=projet, entreprise_id=entreprise_id,
    )
    return {"total": stockage.compter(), "offset": offset, "documents": docs}


@app.get("/dossiers", summary="Dossiers : documents regroupés par projet et catégorie")
def lister_dossiers():
    return stockage.dossiers()


class Classement(BaseModel):
    categorie: str | None = None
    tags: list[str] | None = None
    entreprise_id: str | None = None
    entreprise_nom: str | None = None
    projet: str | None = None
    resume: str | None = None


@app.patch("/documents/{doc_id}/classement", summary="Classer/ranger un document")
def classer_document(doc_id: str, classement: Classement):
    if not stockage.classer(doc_id, classement.model_dump()):
        raise HTTPException(status_code=404, detail="Document introuvable")
    return {"id": doc_id, "message": "Document classé", "classement": stockage.lire(doc_id)["metadonnees"].get("classement", {})}


@app.get("/documents/{doc_id}", summary="Lire un document (texte extrait)")
def lire_document(doc_id: str):
    doc = stockage.lire(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document introuvable")
    return doc


@app.delete("/documents/{doc_id}", summary="Supprimer un document")
def supprimer_document(doc_id: str):
    ok = stockage.supprimer(doc_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Document introuvable")
    return {"message": "Document supprimé"}
