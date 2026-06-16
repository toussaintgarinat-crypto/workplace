"""Destinations d'ARCHIVAGE des notes — registre, sur le motif provider-agnostique.

À la différence des fournisseurs ASR (cascade : on essaie le suivant si l'un échoue), une
destination est un CHOIX explicite par appel (`destination=...`), avec un défaut. C'est un
**pont consenti** (esprit S24) : jamais automatique, et si la destination demandée échoue,
on le DIT (`ok: false`, erreur claire) — on ne perd jamais des notes en silence.

Destinations livrées :
  • memoire  — la brique MÉMOIRE Workplace (port 5600), SOUVERAINE. Défaut. POST /retenir.
  • dossier  — écrit un fichier .md dans un dossier au choix. Si ce dossier est synchronisé
               par Google Drive / iCloud / Dropbox (app de bureau), la note remonte toute
               seule sur le drive — « drive au choix » sans OAuth, universel et souverain.
  • gdrive   — l'API Google Drive directement (OAuth, refresh token). Upload du .md dans un
               dossier Drive. Opt-in, configuré par variables d'env.

Interface commune :
    nom            : identifiant court ;
    disponible()   : la destination est-elle configurée ? — sync, sans réseau ni I/O ;
    async deposer(paquet, **options) -> dict   # {ok, ...} ; LÈVE en cas d'échec réel.
"""
import json
import os
from pathlib import Path
from typing import Optional

import httpx

import rendu


class Memoire:
    """Brique MÉMOIRE Workplace (souveraine). On dépose le résumé en Markdown comme un
    souvenir `/retenir`, en gardant points d'action / thèmes / décisions en metadata."""
    nom = "memoire"

    def _url(self) -> str:
        return os.getenv("MEMOIRE_URL", "http://host.docker.internal:5600").rstrip("/")

    def disponible(self) -> bool:
        return bool(self._url())

    async def deposer(self, paquet: dict, *, type: Optional[str] = None,
                      wing: Optional[str] = None, room: Optional[str] = None,
                      espace: Optional[str] = None, **_) -> dict:
        corps = {
            "contenu": rendu.markdown(paquet),
            "titre": paquet["titre"],
            "type": type or os.getenv("NOTES_MEMOIRE_TYPE", "ressource"),
            "wing": wing or os.getenv("NOTES_MEMOIRE_WING", "transcription"),
            "room": room or "reunions",
            "metadata": {"date": paquet.get("date"), "langue": paquet.get("langue"),
                         "themes": paquet.get("themes"),
                         "points_action": paquet.get("points_action"),
                         "decisions": paquet.get("decisions"),
                         "source": "brique transcription"},
        }
        if espace:
            corps["espace"] = espace
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(f"{self._url()}/retenir", json=corps)
            r.raise_for_status()
            rep = r.json()
        return {"ok": True, "destination": "memoire", "id": rep.get("id"),
                "titre": rep.get("titre"), "souverain": True}


class Dossier:
    """Écrit un fichier Markdown dans un dossier au choix. Le dossier vient de l'appel
    (`dossier=`) ou de NOTES_DOSSIER. Pointe-le vers un dossier synchronisé par ton drive
    (Google Drive/iCloud/Dropbox) et la note y atterrit sans OAuth ni API tierce."""
    nom = "dossier"

    def _defaut(self) -> str:
        return os.getenv("NOTES_DOSSIER", "")

    def disponible(self) -> bool:
        return bool(self._defaut())

    async def deposer(self, paquet: dict, *, dossier: Optional[str] = None, **_) -> dict:
        cible = (dossier or self._defaut()).strip()
        if not cible:
            raise RuntimeError("Aucun dossier indiqué (param `dossier` ou env NOTES_DOSSIER).")
        rep = Path(cible).expanduser()
        rep.mkdir(parents=True, exist_ok=True)
        nom_fichier = f"{paquet['date']}-{rendu.slug(paquet['titre'])}.md"
        chemin = (rep / nom_fichier).resolve()
        # Garde-fou : on n'écrit que SOUS le dossier cible (pas de traversée via le titre).
        if not str(chemin).startswith(str(rep.resolve())):
            raise RuntimeError("Chemin de note invalide.")
        chemin.write_text(rendu.markdown(paquet), encoding="utf-8")
        return {"ok": True, "destination": "dossier", "fichier": str(chemin),
                "dossier": str(rep)}


class GoogleDrive:
    """API Google Drive directement (OAuth utilisateur, refresh token). Upload du .md des
    notes dans un dossier Drive. Opt-in, configuré par env :
      GDRIVE_CLIENT_ID, GDRIVE_CLIENT_SECRET, GDRIVE_REFRESH_TOKEN (obtenus une fois via le
      consentement OAuth, scope drive.file), GDRIVE_FOLDER_ID (optionnel : dossier cible).
    Le refresh token est échangé contre un access token à chaque dépôt (pas de stockage)."""
    nom = "gdrive"

    def _conf(self) -> dict:
        return {k: os.getenv(f"GDRIVE_{k.upper()}", "") for k in
                ("client_id", "client_secret", "refresh_token", "folder_id")}

    def disponible(self) -> bool:
        c = self._conf()
        return bool(c["client_id"] and c["client_secret"] and c["refresh_token"])

    async def _access_token(self, client: httpx.AsyncClient) -> str:
        c = self._conf()
        r = await client.post("https://oauth2.googleapis.com/token", data={
            "client_id": c["client_id"], "client_secret": c["client_secret"],
            "refresh_token": c["refresh_token"], "grant_type": "refresh_token"})
        r.raise_for_status()
        jeton = r.json().get("access_token")
        if not jeton:
            raise RuntimeError("Google n'a pas renvoyé d'access_token (refresh token invalide ?).")
        return jeton

    async def deposer(self, paquet: dict, *, dossier: Optional[str] = None, **_) -> dict:
        if not self.disponible():
            raise RuntimeError("Google Drive non configuré (GDRIVE_CLIENT_ID / CLIENT_SECRET / "
                               "REFRESH_TOKEN). Voir le README.")
        folder = (dossier or self._conf()["folder_id"]).strip()
        nom_fichier = f"{paquet['date']}-{rendu.slug(paquet['titre'])}.md"
        meta: dict = {"name": nom_fichier, "mimeType": "text/markdown"}
        if folder:
            meta["parents"] = [folder]
        # Upload multipart/related : 1) métadonnées JSON, 2) le Markdown.
        front = "----gdrive-notes-boundary"
        corps = (
            f"--{front}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n"
            f"{json.dumps(meta)}\r\n"
            f"--{front}\r\nContent-Type: text/markdown\r\n\r\n"
            f"{rendu.markdown(paquet)}\r\n--{front}--"
        ).encode("utf-8")
        async with httpx.AsyncClient(timeout=45) as client:
            jeton = await self._access_token(client)
            r = await client.post(
                "https://www.googleapis.com/upload/drive/v3/files",
                params={"uploadType": "multipart", "fields": "id,name,webViewLink"},
                headers={"Authorization": f"Bearer {jeton}",
                         "Content-Type": f"multipart/related; boundary={front}"},
                content=corps)
            r.raise_for_status()
            rep = r.json()
        return {"ok": True, "destination": "gdrive", "id": rep.get("id"),
                "nom": rep.get("name"), "lien": rep.get("webViewLink"), "souverain": False}


# ── Registre + défaut ───────────────────────────────────────────
REGISTRE = {d.nom: d for d in (Memoire(), Dossier(), GoogleDrive())}

# Souverain par défaut : la mémoire. Surchargé par NOTES_DESTINATION_DEFAUT.
DEFAUT = os.getenv("NOTES_DESTINATION_DEFAUT", "memoire")


def defaut() -> str:
    d = (os.getenv("NOTES_DESTINATION_DEFAUT", "") or DEFAUT).strip().lower()
    return d if d in REGISTRE else "memoire"


def disponibles() -> list:
    return [n for n, d in REGISTRE.items() if d.disponible()]


async def archiver(paquet: dict, destination: Optional[str] = None, **options) -> dict:
    """Dépose `paquet` dans la destination CHOISIE (ou le défaut). Pont consenti : si la
    destination est inconnue/non configurée ou échoue, on rend `{ok: false, erreur}` —
    on ne perd jamais les notes en silence."""
    nom = (destination or defaut()).strip().lower()
    dest = REGISTRE.get(nom)
    if not dest:
        return {"ok": False, "destination": nom,
                "erreur": f"Destination inconnue (connues : {list(REGISTRE)})."}
    # Pas de verrou `disponible()` ici : une option d'appel (ex. `dossier=`) peut fournir
    # ce qui manque à la config par défaut. `deposer` lève une erreur claire si rien n'est
    # exploitable → remontée en {ok: false} (pont consenti, jamais en silence).
    try:
        return await dest.deposer(paquet, **options)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "destination": nom, "erreur": str(e)[:200]}
