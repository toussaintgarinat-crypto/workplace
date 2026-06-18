"""Fournisseurs OCR — registre PROVIDER-AGNOSTIQUE (« les yeux » du Cœur).

Un document/image peut être « lu » par plusieurs moteurs, essayés dans un ORDRE de
préférence configurable (`VISION_PROVIDERS`). Chaque fournisseur expose la même interface
minimale, calquée sur `briques/images/fournisseurs.py` :

    nom            : identifiant court (clé du registre, valeur de `backend`) ;
    disponible()   : la config est-elle là (lib installée / clé API) ? — sync, SANS réseau ;
    async extraire(data, nom_fichier, mime) -> str   # texte extrait, sinon LÈVE.

Le moteur (moteur.py) balaie les fournisseurs DISPONIBLES dans l'ordre et retient le
PREMIER texte non vide obtenu ; si aucun ne répond, il rend un repli HONNÊTE qui le DIT
(`place_holder: true`). On ne fait jamais passer un repli pour du vrai texte, et on
n'invente jamais de contenu.

Cascade livrée (souverain d'abord, puis hébergés à clé) :
  • markitdown — Microsoft MarkItDown : convertit LOCALEMENT PDF/docx/pptx/html/images →
    Markdown structuré. Souverain, gratuit, hors-ligne. Idéal pour les documents nés
    numériques (texte déjà sélectionnable).
  • tesseract  — Tesseract OCR LOCAL (via pytesseract) : reconnaît le texte d'une image
    scannée/photographiée. Souverain, gratuit, hors-ligne. Idéal pour les scans.
  • mistral    — Mistral OCR (API `mistral-ocr`) : OCR haute fidélité (mise en page,
    tableaux, manuscrit) rendu en Markdown. Hébergé, à clé.
  • google     — Google Cloud Vision (DOCUMENT_TEXT_DETECTION) : OCR robuste multilingue.
    Hébergé, à clé.

Aucune clé n'est embarquée : chaque fournisseur se configure par variables d'env. Les deux
moteurs LOCAUX (markitdown/tesseract) ne sont « disponibles » que si leur bibliothèque est
installée (et `VISION_LOCAL != 0`) ; sinon ils sont simplement ignorés — on retombe sur le
suivant, puis sur le repli honnête.
"""
import asyncio
import base64
import importlib.util
import io
import os
import shutil
import tempfile
from pathlib import Path
from typing import Optional

import httpx


def _importable(module: str) -> bool:
    """La bibliothèque est-elle installée ? (sync, sans l'importer réellement)."""
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def _local_actif() -> bool:
    """Kill-switch des moteurs locaux (les tests offline forcent VISION_LOCAL=0)."""
    return os.getenv("VISION_LOCAL", "1") != "0"


def _data_uri(data: bytes, mime: str) -> str:
    return f"data:{mime};base64,{base64.b64encode(data).decode()}"


# ── Moteurs LOCAUX souverains (bibliothèque Python, aucun réseau) ──────────────
class MarkItDown:
    """Microsoft MarkItDown — document (PDF/Office/HTML/image) → Markdown, en LOCAL.

    Bibliothèque synchrone : on l'exécute dans un thread pour ne pas bloquer la boucle.
    Couvre surtout les documents nés numériques (texte déjà présent dans le fichier)."""
    nom = "markitdown"

    def disponible(self) -> bool:
        return _local_actif() and _importable("markitdown")

    async def extraire(self, data: bytes, nom_fichier: str, mime: str) -> Optional[str]:
        return await asyncio.to_thread(self._convertir, data, nom_fichier)

    @staticmethod
    def _convertir(data: bytes, nom_fichier: str) -> str:
        from markitdown import MarkItDown as _MID
        suffixe = Path(nom_fichier or "fichier").suffix or ".bin"
        with tempfile.NamedTemporaryFile(suffix=suffixe, delete=False) as tmp:
            tmp.write(data)
            chemin = tmp.name
        try:
            res = _MID().convert(chemin)
            return (getattr(res, "text_content", "") or "").strip()
        finally:
            os.unlink(chemin)


class Tesseract:
    """Tesseract OCR LOCAL (via pytesseract + Pillow). Reconnaît le texte d'une IMAGE.

    Nécessite le binaire `tesseract` installé en plus de la lib Python. Langues réglables
    par `TESSERACT_LANG` (ex. `fra+eng`)."""
    nom = "tesseract"

    def disponible(self) -> bool:
        return (_local_actif() and _importable("pytesseract") and _importable("PIL")
                and shutil.which("tesseract") is not None)

    async def extraire(self, data: bytes, nom_fichier: str, mime: str) -> Optional[str]:
        return await asyncio.to_thread(self._ocr, data)

    @staticmethod
    def _ocr(data: bytes) -> str:
        import pytesseract
        from PIL import Image
        langue = os.getenv("TESSERACT_LANG", "fra+eng")
        with Image.open(io.BytesIO(data)) as img:
            return (pytesseract.image_to_string(img, lang=langue) or "").strip()


# ── Moteurs HÉBERGÉS à clé (HTTP, OCR haute fidélité) ──────────────────────────
class Mistral:
    """Mistral OCR (`POST /v1/ocr`, modèle `mistral-ocr-latest`). Rend du Markdown par page.

    On envoie le fichier en data-URI base64 : `document_url` pour un PDF, `image_url` sinon
    (l'API accepte les deux). Réponse : `{"pages": [{"markdown": …}, …]}` → on concatène."""
    nom = "mistral"
    timeout = 120

    def disponible(self) -> bool:
        return bool(os.getenv("MISTRAL_API_KEY"))

    async def extraire(self, data: bytes, nom_fichier: str, mime: str) -> Optional[str]:
        modele = os.getenv("MISTRAL_OCR_MODEL", "mistral-ocr-latest")
        uri = _data_uri(data, mime or "application/octet-stream")
        if (mime or "").startswith("image/"):
            document = {"type": "image_url", "image_url": uri}
        else:
            document = {"type": "document_url", "document_url": uri}
        body = {"model": modele, "document": document}
        headers = {"Authorization": f"Bearer {os.getenv('MISTRAL_API_KEY')}"}
        async with httpx.AsyncClient(timeout=self.timeout) as c:
            r = await c.post("https://api.mistral.ai/v1/ocr", headers=headers, json=body)
            r.raise_for_status()
            pages = (r.json() or {}).get("pages") or []
            return "\n\n".join((p.get("markdown") or "").strip() for p in pages).strip()


class Google:
    """Google Cloud Vision — `images:annotate` avec `DOCUMENT_TEXT_DETECTION`.

    Clé API simple en query string (`GOOGLE_VISION_API_KEY`, repli `GOOGLE_API_KEY`).
    Réponse : `responses[0].fullTextAnnotation.text`. N'accepte que des images (les PDF
    passent par l'API Files asynchrone, hors périmètre ici → on laisse la cascade replier)."""
    nom = "google"
    timeout = 60

    def _cle(self) -> Optional[str]:
        return os.getenv("GOOGLE_VISION_API_KEY") or os.getenv("GOOGLE_API_KEY")

    def disponible(self) -> bool:
        return bool(self._cle())

    async def extraire(self, data: bytes, nom_fichier: str, mime: str) -> Optional[str]:
        body = {"requests": [{
            "image": {"content": base64.b64encode(data).decode()},
            "features": [{"type": "DOCUMENT_TEXT_DETECTION"}],
        }]}
        url = f"https://vision.googleapis.com/v1/images:annotate?key={self._cle()}"
        async with httpx.AsyncClient(timeout=self.timeout) as c:
            r = await c.post(url, json=body)
            r.raise_for_status()
            rep = ((r.json() or {}).get("responses") or [{}])[0]
            texte = (rep.get("fullTextAnnotation") or {}).get("text")
            if not texte:
                annots = rep.get("textAnnotations") or []
                texte = annots[0].get("description") if annots else None
            return (texte or "").strip()


# ── Registre + ordre de préférence ────────────────────────────────────────────
REGISTRE = {f.nom: f for f in (MarkItDown(), Tesseract(), Mistral(), Google())}

# Défaut : souverains LOCAUX d'abord (gratuit/hors-ligne), puis les hébergés à clé propre.
# Surchargé par `VISION_PROVIDERS` (liste, ex. "mistral" ou "tesseract,google").
ORDRE_DEFAUT = ["markitdown", "tesseract", "mistral", "google"]


def ordre() -> list:
    """Ordre de préférence effectif (filtré sur les fournisseurs connus du registre)."""
    brut = [n.strip().lower() for n in os.getenv("VISION_PROVIDERS", "").split(",") if n.strip()]
    noms = brut or ORDRE_DEFAUT
    return [n for n in noms if n in REGISTRE]


def disponibles() -> list:
    """Fournisseurs configurés (lib installée / clé présente), dans l'ordre de préférence."""
    return [n for n in ordre() if REGISTRE[n].disponible()]
