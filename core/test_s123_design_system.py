"""Tests-contrat du design system partagé (S123).

Invariant : UNE source unique de tokens visuels (shared/static/workplace.css) ;
le Cœur la sert au dashboard ; chaque brique front en a une copie NON DIVERGENTE
(motif Docker COPY . + outils/sync_socle.sh) ; chaque front l'adopte via <link>
et alias ses variables sur var(--wp-*). 100 % hors-ligne, additif.
"""

import os
from pathlib import Path

# Secrets requis AVANT l'import du Cœur (main importe le coffre, la Gateway, etc.).
os.environ.setdefault("VAULT_SECRET", "test-secret-0123456789")
os.environ.setdefault("GATEWAY_KEY", "test")

import main  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

client = TestClient(main.app)

RACINE = Path(__file__).resolve().parent.parent
SOURCE = RACINE / "shared" / "static" / "workplace.css"

# Tokens canoniques que tout front peut référencer (le contrat figé du système).
TOKENS = [
    "--wp-bg", "--wp-surface", "--wp-surface-2", "--wp-border",
    "--wp-text", "--wp-muted", "--wp-faint",
    "--wp-accent", "--wp-accent-2",
    "--wp-ok", "--wp-warn", "--wp-err",
    "--wp-radius", "--wp-radius-sm", "--wp-gap", "--wp-shadow",
    "--wp-font", "--wp-mono",
]

# Briques servant un front autoporté qui adopte le design system.
BRIQUES_FRONT = ["synopsis", "voix", "personnages", "studio", "transcription"]


def test_source_unique_definit_tous_les_tokens():
    """shared/static/workplace.css existe et déclare chaque token canonique."""
    assert SOURCE.exists(), "la source unique du design system est absente"
    css = SOURCE.read_text(encoding="utf-8")
    manquants = [t for t in TOKENS if t + ":" not in css.replace(" ", "")]
    assert not manquants, f"tokens absents de la source : {manquants}"


def test_source_ne_contient_que_des_tokens():
    """Charger le fichier ne doit RIEN altérer : aucune règle de mise en page,
    seulement le bloc :root de custom properties."""
    css = SOURCE.read_text(encoding="utf-8")
    # Pas de reset/box-sizing ni de sélecteurs universels (inertie garantie).
    assert "box-sizing" not in css
    assert "*{" not in css.replace(" ", "")


def test_coeur_sert_le_design_system():
    """GET /workplace.css renvoie la source, en text/css."""
    r = client.get("/workplace.css")
    assert r.status_code == 200
    assert "text/css" in r.headers["content-type"]
    assert "--wp-bg" in r.text
    # C'est bien la source unique (octet pour octet).
    assert r.text == SOURCE.read_text(encoding="utf-8")


def test_copies_briques_non_divergentes():
    """Chaque brique front a une copie BYTE-identique (sync_socle.sh n'a pas dérivé)."""
    attendu = SOURCE.read_bytes()
    for b in BRIQUES_FRONT:
        copie = RACINE / "briques" / b / "workplace.css"
        assert copie.exists(), f"copie manquante : {b} (lancer outils/sync_socle.sh)"
        assert copie.read_bytes() == attendu, f"copie divergente : {b} (relancer la synchro)"
    # Le Cœur aussi (contexte de build core/).
    assert (RACINE / "core" / "workplace.css").read_bytes() == attendu


def test_fronts_adoptent_le_systeme():
    """Chaque front charge /workplace.css et alias ses variables sur var(--wp-*)."""
    for b in BRIQUES_FRONT:
        html = (RACINE / "briques" / b / "front.html").read_text(encoding="utf-8")
        assert '<link rel="stylesheet" href="/workplace.css">' in html, f"{b}: <link> absent"
        assert "var(--wp-" in html, f"{b}: aucun alias sur les tokens partagés"


def test_dashboard_charge_le_systeme():
    """Le dashboard du Cœur référence aussi le design system."""
    html = client.get("/dashboard").text
    assert '<link rel="stylesheet" href="/workplace.css">' in html
