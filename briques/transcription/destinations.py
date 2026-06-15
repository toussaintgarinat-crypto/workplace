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

À venir (incrément séparé) : `gdrive` via l'API Google Drive (OAuth, pont Google S27/S35).

Interface commune :
    nom            : identifiant court ;
    disponible()   : la destination est-elle configurée ? — sync, sans réseau ni I/O ;
    async deposer(paquet, **options) -> dict   # {ok, ...} ; LÈVE en cas d'échec réel.
"""
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


# ── Registre + défaut ───────────────────────────────────────────
REGISTRE = {d.nom: d for d in (Memoire(), Dossier())}

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
