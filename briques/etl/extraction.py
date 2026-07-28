"""Extraction de texte depuis différents types de fichiers."""

import io
import logging
import mimetypes
import os
import re
import tempfile

import reseau

logger = logging.getLogger(__name__)

_CTRL_RE = re.compile(r"[\x00\x01-\x08\x0B\x0C\x0E-\x1F\x7F\uD800-\uDFFF]")


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

    # MarkItDown couvre PDF, Word, Excel, PowerPoint, HTML, CSV…
    texte = _essayer_markitdown(contenu, nom_fichier)
    if texte:
        return _nettoyer(texte)

    # Fallbacks
    if mime == "application/pdf" or nom_fichier.lower().endswith(".pdf"):
        texte = _extraire_pdf_texte(contenu)
        if len(texte.strip()) < 100:
            texte = _extraire_pdf_ocr(contenu)
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
    return extraire_texte(contenu, nom, type_mime), nom
