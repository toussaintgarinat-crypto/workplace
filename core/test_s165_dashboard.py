"""Tests S165 — fil d'activité + jeton assistant ciblable au dashboard.

Le dashboard sert : (1) la task trace de l'assistant (panneau « Activité », statuts
ok/err/gate, bouton ⏹ d'intervention) ; (2) le jeton 🎯 déplaçable en Pointer Events
à déposer sur une brique (onglets + cartes du Registre) ; (3) l'envoi de la cible au
Cœur (`cible` dans le corps de /assistant/chat).
"""

import os

os.environ.setdefault("VAULT_SECRET", "test-secret-0123456789")
os.environ.setdefault("GATEWAY_KEY", "test")

import main  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

client = TestClient(main.app)


def _html():
    return client.get("/dashboard").text


def test_fil_activite_present():
    html = _html()
    assert 'id="fil-activite"' in html
    assert 'id="fa-corps"' in html
    assert "Activité de l'assistant" in html
    # Les trois statuts existent en CSS : réussite, échec, gate de confirmation.
    assert ".fa-entree.ok .pic" in html
    assert ".fa-entree.err .pic" in html
    assert ".fa-entree.gate .pic" in html


def test_trace_cablee_sur_les_evenements_sse():
    """`outil` alimente la trace, `resultat_outil` la solde (ok/échec/gate)."""
    html = _html()
    assert "traceOutil(evt)" in html
    assert "traceResultat(evt)" in html
    assert "traceInterrompue()" in html      # pas de faux ✓ après un ⏹


def test_bouton_stop_intervention():
    html = _html()
    assert 'id="btn-stop"' in html
    assert "stopperTour" in html
    assert "AbortController" in html
    assert "signal: TOUR_ABORT.signal" in html   # l'abandon coupe bien le fetch SSE


def test_jeton_ciblable_present():
    html = _html()
    assert 'id="jeton-assistant"' in html
    assert "initJetonAssistant" in html
    assert "setPointerCapture" in html           # pilier Pointer Events du rapport


def test_cibles_de_drop_declarees():
    """Onglets briques + cartes du Registre sont des cibles (`data-cible-brique`)."""
    html = _html()
    assert 'data-cible-brique="agenda"' in html
    assert 'data-cible-brique="mail"' in html
    assert 'data-cible-brique="geo"' in html
    assert 'data-cible-brique="${b.nom}"' in html   # cartes du Registre (rendu JS)


def test_cible_envoyee_au_coeur():
    """Le corps de /assistant/chat transporte la brique ciblée + le chip est visible."""
    html = _html()
    assert "_chatBody.cible = CIBLE_BRIQUE" in html
    assert 'id="chip-cible"' in html


def test_yeux_bouton_et_capture():
    """Phase « yeux » : le 👁 du chip capture la zone ciblée (getDisplayMedia)."""
    html = _html()
    assert "donnerLesYeux" in html
    assert "getDisplayMedia" in html
    assert "preferCurrentTab" in html
    # Surface sans capture (ex. Mini App) : message honnête, pas d'échec silencieux.
    assert "pas disponible sur cette surface" in html


def test_capture_envoyee_une_seule_fois():
    """La capture part avec le prochain message, puis est consommée (one-shot)."""
    html = _html()
    assert "_chatBody.capture = CAPTURE_CIBLE" in html
    assert "CAPTURE_CIBLE = null" in html   # reset à l'envoi ET au changement de cible


if __name__ == "__main__":
    for nom, fn in list(globals().items()):
        if nom.startswith("test_") and callable(fn):
            fn()
            print(f"  ✓ {nom}")
    print("\n✅ TOUS LES TESTS PASSENT")
