"""Extraction de texte depuis différents types de fichiers.

Tout ce qui est ici est **synchrone et gourmand en CPU** : PyMuPDF ouvre le PDF,
Tesseract océrise page par page à 200 dpi. Sur un scan de plusieurs dizaines de
pages, `extraire_texte` tient la seconde de CPU par page.

Les endpoints d'ingestion sont `async` : appelé directement, ce code s'exécuterait
donc **dans la boucle d'événements** et la brique entière cesserait de répondre
pendant l'OCR — `/sante` compris, donc healthcheck rouge (timeout 10 s, 3 essais)
sur un simple gros document. C'est le motif du « 500 fantôme du digest » : le travail
aboutit, la plateforme dit qu'il a échoué. D'où `extraire_texte_async` ci-dessous, seul
point d'entrée que les endpoints doivent utiliser (S212).
"""

import asyncio
import io
import logging
import mimetypes
import os
import re
import tempfile
from concurrent.futures import ThreadPoolExecutor

import reseau

logger = logging.getLogger(__name__)

_CTRL_RE = re.compile(r"[\x00\x01-\x08\x0B\x0C\x0E-\x1F\x7F\uD800-\uDFFF]")

# Pool DÉDIÉ, et pas `fastapi.concurrency.run_in_threadpool` : ce dernier partage le
# threadpool AnyIO (40 jetons) qui sert AUSSI tout endpoint déclaré `def` — dont
# `/sante`. Une rafale d'ingestions y prendrait des jetons au healthcheck, et on
# retomberait sur l'indisponibilité qu'on vient de corriger, en plus discret.
# Ici l'extraction ne peut jamais prendre le jeton de personne : au-delà de
# INGESTION_EXTRACTIONS_PARALLELES, les ingestions font la queue en `await` (boucle libre).
# 2 par défaut : Tesseract sature un cœur à lui seul, le HP en a 6 pour ~54 conteneurs.
_PARALLELISME = max(1, int(os.getenv("INGESTION_EXTRACTIONS_PARALLELES", "2")))
_POOL = ThreadPoolExecutor(max_workers=_PARALLELISME, thread_name_prefix="ingestion-extraction")


async def extraire_texte_async(contenu: bytes, nom_fichier: str,
                               type_mime: str | None = None) -> str:
    """`extraire_texte` sans bloquer la boucle d'événements — à utiliser depuis un endpoint."""
    return await asyncio.get_running_loop().run_in_executor(
        _POOL, extraire_texte, contenu, nom_fichier, type_mime)


def _nettoyer(texte: str) -> str:
    return _CTRL_RE.sub("", texte).strip()


def _essayer_markitdown(contenu: bytes, nom_fichier: str) -> str | None:
    try:
        from markitdown import MarkItDown
        suffixe = os.path.splitext(nom_fichier)[1] or ".bin"
        with tempfile.NamedTemporaryFile(suffix=suffixe, delete=False) as tmp:
            tmp.write(contenu)
            chemin_tmp = tmp.name
        try:
            resultat = MarkItDown().convert(chemin_tmp)
            texte = (resultat.text_content or "").strip()
            return texte if texte else None
        finally:
            os.unlink(chemin_tmp)
    except Exception as e:
        logger.debug("MarkItDown indisponible : %s", e)
        return None


def _extraire_pdf_texte(contenu: bytes) -> str:
    """Extraction de la couche texte du PDF (sans OCR)."""
    try:
        import fitz
        doc = fitz.open(stream=contenu, filetype="pdf")
        return "\n".join(page.get_text() for page in doc)
    except ImportError:
        return ""


def _extraire_pdf_ocr(contenu: bytes) -> str:
    """OCR sur PDF scanné via Tesseract (fallback)."""
    try:
        import fitz
        import pytesseract
        from PIL import Image

        doc = fitz.open(stream=contenu, filetype="pdf")
        lignes = []
        for page in doc:
            pix = page.get_pixmap(dpi=200)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            lignes.append(pytesseract.image_to_string(img, lang="fra+eng"))
        return "\n".join(lignes)
    except Exception as e:
        logger.warning("OCR PDF échoué : %s", e)
        return ""


def _extraire_image_ocr(contenu: bytes) -> str:
    """OCR sur une image via Tesseract."""
    try:
        import pytesseract
        from PIL import Image
        img = Image.open(io.BytesIO(contenu))
        return pytesseract.image_to_string(img, lang="fra+eng")
    except Exception as e:
        logger.warning("OCR image échoué : %s", e)
        return ""


def _extraire_docx(contenu: bytes) -> str:
    try:
        from docx import Document
        doc = Document(io.BytesIO(contenu))
        return "\n".join(p.text for p in doc.paragraphs)
    except Exception as e:
        logger.warning("Extraction DOCX échouée : %s", e)
        return ""


def _extraire_html(contenu: bytes) -> str:
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(contenu, "lxml")
        for tag in soup(["script", "style", "nav", "footer"]):
            tag.decompose()
        return soup.get_text(separator="\n")
    except Exception as e:
        logger.warning("Extraction HTML échouée : %s", e)
        return contenu.decode("utf-8", errors="replace")


def extraire_texte(contenu: bytes, nom_fichier: str, type_mime: str | None = None) -> str:
    """Point d'entrée principal — extrait le texte d'un fichier quel que soit son format."""
    mime = type_mime or mimetypes.guess_type(nom_fichier)[0] or ""

    # Images : OCR
    if mime.startswith("image/"):
        return _nettoyer(_extraire_image_ocr(contenu))

    # Texte brut : décodage DIRECT, markitdown court-circuité (S212). Il n'a rien à
    # convertir ici, mais il fait quand même deviner l'encodage par charset-normalizer —
    # et un octet nul dans le fichier suffit à lui faire conclure « UTF-16 ». Mesuré :
    # `a\x00b\x07Griffon-Sextant-42` ressortait en `愀戇䝲楦景渭卥硴慮琭㐲`, stocké tel
    # quel, sans la moindre erreur. Une corruption muette, le pire genre.
    if mime.startswith("text/plain") or nom_fichier.lower().endswith((".txt", ".md", ".log")):
        return _nettoyer(contenu.decode("utf-8", errors="replace"))

    # MarkItDown couvre PDF, Word, Excel, PowerPoint, HTML, CSV…
    texte = _essayer_markitdown(contenu, nom_fichier)
    if texte:
        return _nettoyer(texte)

    # Fallbacks
    if mime == "application/pdf" or nom_fichier.lower().endswith(".pdf"):
        texte = _extraire_pdf_texte(contenu)
        # Moins de 100 caractères = probablement un scan : on TENTE l'OCR. Mais on ne
        # remplace la couche texte que si l'OCR rend davantage (S212) — sinon un OCR
        # qui échoue (Tesseract absent, page illisible) renvoyait "" et faisait perdre
        # le peu de texte réel qu'on avait déjà. Le document finissait vide en base.
        if len(texte.strip()) < 100:
            ocr = _extraire_pdf_ocr(contenu)
            if len(ocr.strip()) > len(texte.strip()):
                texte = ocr
        return _nettoyer(texte)

    if mime in (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/msword",
    ) or nom_fichier.lower().endswith((".docx", ".doc")):
        return _nettoyer(_extraire_docx(contenu))

    if mime in ("text/html", "application/xhtml+xml") or nom_fichier.lower().endswith((".html", ".htm")):
        return _nettoyer(_extraire_html(contenu))

    return _nettoyer(contenu.decode("utf-8", errors="replace"))


async def extraire_depuis_url(url: str) -> tuple[str, str]:
    """Télécharge une URL et extrait le texte. Retourne (texte, nom_fichier).

    Le téléchargement passe par `reseau.telecharger` : cible publique obligatoire,
    re-vérifiée à chaque redirection, et plafond de taille (S211). Les exceptions
    `reseau.UrlInterdite` / `reseau.ContenuTropGros` remontent telles quelles pour
    que `main.py` distingue « refusé » de « injoignable ».
    """
    contenu, url_finale, type_mime = await reseau.telecharger(url)
    # Nom de fichier depuis l'URL FINALE (après redirections) : c'est le document
    # réellement récupéré, pas celui demandé.
    nom = url_finale.rstrip("/").split("/")[-1] or "page"
    if "." not in nom and "html" in type_mime:
        nom += ".html"
    # `_async` : une URL peut pointer sur un PDF scanné aussi bien qu'un upload (S212).
    return await extraire_texte_async(contenu, nom, type_mime), nom
