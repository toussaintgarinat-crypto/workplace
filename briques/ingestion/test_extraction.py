"""S212 — filet de non-régression de l'extraction, écrit AVANT de toucher markitdown.

`markitdown` était épinglé en `0.0.1a3` — une **alpha**, en position **principale** :
`extraire_texte` lui donne le fichier avant tout fallback (`extraction.py`). Un composant
alpha sur le chemin critique, sans un seul test qui verrouille son comportement, c'est un
bump à l'aveugle garanti. Ce fichier est donc le préalable au bump : il décrit ce que la
brique doit savoir extraire, quelle que soit la bibliothèque qui le fait.

Les fixtures sont **fabriquées à l'exécution** (PyMuPDF, python-docx, openpyxl — déjà dans
`requirements.txt`) plutôt que versionnées en binaire : un PDF de référence dans Git ne se
relit pas en revue, et personne ne saurait dire ce qu'il contient six mois plus tard.

Deux familles de tests, et la distinction compte pour le bump :
  • ce que la brique promet (« sait lire un XLSX ») — le contrat, insensible au moteur ;
  • la chaîne de repli elle-même (markitdown neutralisé) — ce qui reste debout si le
    moteur principal régresse ou disparaît.
"""

import io

import pytest

import extraction

MARQUEUR = "Griffon-Sextant-42"      # improbable dans du bruit d'extraction


# ── Fixtures fabriquées ──────────────────────────────────────────────────────

def _pdf(texte: str | None = MARQUEUR) -> bytes:
    """PDF d'une page. `texte=None` → page vide = le cas « scan » (aucune couche texte)."""
    fitz = pytest.importorskip("fitz")
    doc = fitz.open()
    page = doc.new_page()
    if texte:
        page.insert_text((72, 72), texte, fontsize=14)
    return doc.tobytes()


def _docx() -> bytes:
    docx = pytest.importorskip("docx")
    document = docx.Document()
    document.add_paragraph(MARQUEUR)
    tampon = io.BytesIO()
    document.save(tampon)
    return tampon.getvalue()


def _xlsx() -> bytes:
    openpyxl = pytest.importorskip("openpyxl")
    classeur = openpyxl.Workbook()
    classeur.active["A1"] = MARQUEUR
    tampon = io.BytesIO()
    classeur.save(tampon)
    return tampon.getvalue()


def _png() -> bytes:
    Image = pytest.importorskip("PIL.Image")
    tampon = io.BytesIO()
    Image.new("RGB", (40, 20), "white").save(tampon, format="PNG")
    return tampon.getvalue()


@pytest.fixture
def sans_markitdown(monkeypatch):
    """Neutralise le moteur principal pour exercer la chaîne de repli seule."""
    monkeypatch.setattr(extraction, "_essayer_markitdown", lambda contenu, nom: None)


# ── Le contrat : ce que la brique promet de savoir lire ──────────────────────

def test_pdf():
    assert MARQUEUR in extraction.extraire_texte(_pdf(), "doc.pdf", "application/pdf")


def test_docx():
    mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    assert MARQUEUR in extraction.extraire_texte(_docx(), "doc.docx", mime)


def test_xlsx():
    """Le canari du bump : le XLSX n'a AUCUN fallback, markitdown est le seul chemin.

    `openpyxl` est dans `requirements.txt` mais aucun code de la brique ne l'appelle —
    il n'y est que comme dépendance de markitdown. Si ce test rougit après un bump,
    la brique a perdu Excel en silence.
    """
    mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert MARQUEUR in extraction.extraire_texte(_xlsx(), "classeur.xlsx", mime)


def test_html_sans_le_bruit_de_page():
    html = (f"<html><head><style>p{{color:red}}</style></head>"
            f"<body><script>var a=1</script><p>{MARQUEUR}</p>"
            f"<footer>mentions légales</footer></body></html>").encode()
    texte = extraction.extraire_texte(html, "page.html", "text/html")
    assert MARQUEUR in texte
    assert "var a=1" not in texte, "le JS ne doit pas finir indexé comme du contenu"


def test_texte_brut():
    assert MARQUEUR in extraction.extraire_texte(
        MARQUEUR.encode(), "note.txt", "text/plain")


def test_les_caracteres_de_controle_sont_retires():
    """SQLite les avale, mais ils cassent le JSON rendu à l'assistant.

    Ce test a trouvé une **corruption muette** (S212) : le texte brut passait d'abord par
    markitdown, dont la détection d'encodage voyait l'octet nul et concluait « UTF-16 ».
    `a\\x00b\\x07Griffon-Sextant-42` était stocké en `愀戇䝲楦景渭卥硴慮琭㐲` — sans
    erreur, sans avertissement. D'où le court-circuit du texte brut dans `extraire_texte`.
    """
    texte = extraction.extraire_texte(
        f"a\x00b\x07{MARQUEUR}".encode(), "note.txt", "text/plain")
    assert MARQUEUR in texte
    assert "\x00" not in texte and "\x07" not in texte


def test_le_texte_brut_ne_passe_pas_par_markitdown(monkeypatch):
    """Le court-circuit lui-même : un convertisseur de documents n'a rien à faire ici."""
    monkeypatch.setattr(extraction, "_essayer_markitdown",
                        lambda contenu, nom: pytest.fail("le texte brut doit être décodé direct"))
    assert MARQUEUR in extraction.extraire_texte(MARQUEUR.encode(), "note.txt", "text/plain")


def test_un_pdf_court_garde_sa_couche_texte_si_l_ocr_echoue(sans_markitdown, monkeypatch):
    """Sous 100 caractères on TENTE l'OCR — mais un OCR raté ne doit rien effacer.

    Trouvé en écrivant ce filet : `_extraire_pdf_ocr` renvoie `""` quand Tesseract manque
    ou que la page est illisible, et cette chaîne vide écrasait le texte réel déjà extrait.
    Le document arrivait VIDE en base, sans erreur (S212).
    """
    monkeypatch.setattr(extraction, "_extraire_pdf_ocr", lambda contenu: "")
    assert MARQUEUR in extraction.extraire_texte(_pdf(), "court.pdf", "application/pdf")


# ── La chaîne de repli, moteur principal neutralisé ──────────────────────────

def test_pdf_sans_markitdown_passe_par_pymupdf(sans_markitdown):
    assert MARQUEUR in extraction.extraire_texte(_pdf(), "doc.pdf", "application/pdf")


def test_docx_sans_markitdown_passe_par_python_docx(sans_markitdown):
    mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    assert MARQUEUR in extraction.extraire_texte(_docx(), "doc.docx", mime)


def test_pdf_sans_couche_texte_bascule_sur_l_ocr(sans_markitdown, monkeypatch):
    """Le cas « scan » : PyMuPDF ne rend rien d'utile, Tesseract doit prendre la main."""
    appels = []
    monkeypatch.setattr(extraction, "_extraire_pdf_ocr",
                        lambda contenu: appels.append("ocr") or f"{MARQUEUR} océrisé")

    texte = extraction.extraire_texte(_pdf(texte=None), "scan.pdf", "application/pdf")

    assert appels == ["ocr"], "un PDF sans texte doit déclencher l'OCR, pas rendre du vide"
    assert MARQUEUR in texte


def test_une_image_va_directement_a_l_ocr(monkeypatch):
    """Court-circuit voulu : markitdown ne sait pas océriser, l'y envoyer perdrait le texte."""
    appels = []
    monkeypatch.setattr(extraction, "_extraire_image_ocr",
                        lambda contenu: appels.append("ocr") or MARQUEUR)
    monkeypatch.setattr(extraction, "_essayer_markitdown",
                        lambda contenu, nom: pytest.fail("une image ne doit pas passer par markitdown"))

    assert MARQUEUR in extraction.extraire_texte(_png(), "photo.png", "image/png")
    assert appels == ["ocr"]
