"""Brique « jeu-factions-public » — exposition publique du jeu (S220). Comptes email + mot
de passe propres à la brique, AUCUNE dépendance à core/ ni à Keycloak — voir
docs/superpowers/specs/2026-08-03-jeu-factions-public-design.md."""
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Jeu-factions-public — exposition publique du jeu (PvE)", version="0.1.0")

_cors = [o.strip() for o in os.getenv("JEU_FACTIONS_PUBLIC_CORS_ORIGINS", "*").split(",") if o.strip()] or ["*"]
app.add_middleware(CORSMiddleware, allow_origins=_cors, allow_methods=["*"], allow_headers=["*"])


@app.get("/sante", tags=["système"])
def sante():
    return {"statut": "ok"}
