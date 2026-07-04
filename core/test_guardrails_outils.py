"""Tests Sprint S143 — Guardrails outils."""

import pytest
from guardrails_outils import Config, Guardrail

ARGS_A = {"q": "recherche"}
ARGS_B = {"q": "autre"}


def _guardrail(seuil_warn_id=2, seuil_block_id=4,
               seuil_warn_outil=3, seuil_block_outil=6,
               seuil_warn_idem=3, seuil_block_idem=5) -> Guardrail:
    return Guardrail(config=Config(
        seuil_warn_echecs_identiques=seuil_warn_id,
        seuil_block_echecs_identiques=seuil_block_id,
        seuil_warn_resultat_identique=seuil_warn_idem,
        seuil_block_resultat_identique=seuil_block_idem,
        seuil_warn_echecs_meme_outil=seuil_warn_outil,
        seuil_block_echecs_meme_outil=seuil_block_outil,
    ))


def test_1_premier_echec_identique_allow():
    g = _guardrail()
    action, _ = g.before_call("recherche_web", ARGS_A)
    assert action == "allow"
    g.after_call("recherche_web", ARGS_A, "err", erreur=True)
    action, _ = g.before_call("recherche_web", ARGS_A)
    assert action == "allow"


def test_2_trois_echecs_identiques_warn():
    g = _guardrail()
    for _ in range(2):
        g.after_call("recherche_web", ARGS_A, "err", erreur=True)
    action, msg = g.before_call("recherche_web", ARGS_A)
    assert action == "warn"
    assert msg is not None


def test_3_cinq_echecs_identiques_block():
    g = _guardrail()
    for _ in range(4):
        g.after_call("recherche_web", ARGS_A, "err", erreur=True)
    action, msg = g.before_call("recherche_web", ARGS_A)
    assert action == "block"
    assert "recherche_web" in (msg or "")


def test_4_echecs_varies_meme_outil_block():
    g = _guardrail()
    # 4 échecs avec args différents → compteur meme_outil monte
    for i in range(6):
        g.after_call("recherche_web", {"q": str(i)}, "err", erreur=True)
    action, msg = g.before_call("recherche_web", {"q": "nouveau"})
    assert action == "block"


def test_5_resultat_identique_x2_allow():
    g = _guardrail()
    g.after_call("memoire_lire", ARGS_A, '{"data": "x"}', erreur=False)
    g.after_call("memoire_lire", ARGS_A, '{"data": "x"}', erreur=False)
    action, _ = g.verifier_idempotence("memoire_lire", ARGS_A)
    assert action == "allow"


def test_6_resultat_identique_x3_warn():
    g = _guardrail()
    for _ in range(3):
        g.after_call("memoire_lire", ARGS_A, '{"data": "x"}', erreur=False)
    action, msg = g.verifier_idempotence("memoire_lire", ARGS_A)
    assert action == "warn"
    assert msg is not None


def test_7_resultat_identique_x6_block():
    g = _guardrail()
    for _ in range(6):
        g.after_call("memoire_lire", ARGS_A, '{"data": "x"}', erreur=False)
    action, msg = g.verifier_idempotence("memoire_lire", ARGS_A)
    assert action == "block"
    assert "memoire_lire" in (msg or "")


def test_8_succes_apres_echec_remet_compteurs_a_zero():
    g = _guardrail()
    for _ in range(3):
        g.after_call("recherche_web", ARGS_A, "err", erreur=True)
    g.after_call("recherche_web", ARGS_A, '{"ok": true}', erreur=False)
    action, _ = g.before_call("recherche_web", ARGS_A)
    assert action == "allow"


def test_9_reinitialiser_vide_tout():
    g = _guardrail()
    for _ in range(4):
        g.after_call("recherche_web", ARGS_A, "err", erreur=True)
    g.reinitialiser()
    action, _ = g.before_call("recherche_web", ARGS_A)
    assert action == "allow"
    action2, _ = g.verifier_idempotence("recherche_web", ARGS_A)
    assert action2 == "allow"


def test_10_args_differents_compteurs_independants():
    # seuil_outil élevé pour ne tester QUE l'indépendance des signatures
    g = _guardrail(seuil_warn_outil=10, seuil_block_outil=20)
    for _ in range(4):
        g.after_call("recherche_web", ARGS_A, "err", erreur=True)
    # ARGS_B n'a jamais échoué → compteur per-signature à zéro → allow
    action, _ = g.before_call("recherche_web", ARGS_B)
    assert action == "allow"
