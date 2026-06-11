"""State OAuth signé (anti-CSRF, S35) — émission, vérification, falsification, expiration.

Le conftest fixe `VAULT_SECRET` ; le state en dérive sa clé de signature.
"""

from __future__ import annotations

import time

import pytest

from config import settings
from services import oauth_state


def test_aller_retour_recupere_user_id():
    state = oauth_state.emettre("user-42")
    assert oauth_state.verifier(state) == "user-42"


def test_state_est_opaque_pas_le_user_id_brut():
    # L'identité ne doit pas apparaître en clair (contrairement à l'ancien state=user_id).
    state = oauth_state.emettre("alice@example.com")
    assert "alice@example.com" not in state


def test_signature_falsifiee_rejetee():
    state = oauth_state.emettre("user-42")
    corps, _, sig = state.partition(".")
    forge = f"{corps}.{'A' * len(sig)}"
    with pytest.raises(oauth_state.StateError):
        oauth_state.verifier(forge)


def test_payload_modifie_rejete():
    # Changer l'identité sans re-signer doit échouer (intégrité).
    autre = oauth_state.emettre("attaquant")
    corps_attaquant = autre.split(".", 1)[0]
    sig_legitime = oauth_state.emettre("user-42").split(".", 1)[1]
    with pytest.raises(oauth_state.StateError):
        oauth_state.verifier(f"{corps_attaquant}.{sig_legitime}")


def test_state_expire_rejete():
    t0 = 1_000_000.0
    state = oauth_state.emettre("user-42", ttl=600, maintenant=t0)
    # Encore valide juste avant l'échéance, rejeté après.
    assert oauth_state.verifier(state, maintenant=t0 + 599) == "user-42"
    with pytest.raises(oauth_state.StateError):
        oauth_state.verifier(state, maintenant=t0 + 601)


def test_state_malforme_rejete():
    for mauvais in ("", "sans-point", "a.b.c.d"[:3]):
        with pytest.raises(oauth_state.StateError):
            oauth_state.verifier(mauvais)


def test_secret_dedie_prioritaire_sur_vault():
    # GOOGLE_STATE_SECRET, s'il est posé, prime ; un state signé avec l'un n'est pas
    # vérifiable avec l'autre (clés distinctes).
    settings.GOOGLE_STATE_SECRET = "secret-dedie-pour-le-state-oauth"
    try:
        state = oauth_state.emettre("user-42")
        assert oauth_state.verifier(state) == "user-42"
        settings.GOOGLE_STATE_SECRET = ""  # repli VAULT_SECRET → autre clé
        with pytest.raises(oauth_state.StateError):
            oauth_state.verifier(state)
    finally:
        settings.GOOGLE_STATE_SECRET = ""
