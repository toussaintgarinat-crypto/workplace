"""Registre des sessions actives par compte (relai propre entre appareils).

$ cd core && python3 -m pytest test_session_registre.py -v
"""
import os
import tempfile

os.environ["SESSION_REGISTRE_DB"] = os.path.join(tempfile.mkdtemp(), "session_registre.db")

import session_registre  # noqa: E402


def test_premiere_session_ne_renvoie_aucune_ancienne_session():
    generation, ancienne = session_registre.nouvelle_session("marina", "iPhone")
    assert generation == 1
    assert ancienne is None


def test_deuxieme_session_incremente_et_renvoie_l_ancienne():
    session_registre.nouvelle_session("thomas", "iPhone")
    generation, ancienne = session_registre.nouvelle_session("thomas", "MacBook")
    assert generation == 2
    assert ancienne is not None
    assert ancienne.generation == 1
    assert ancienne.appareil == "iPhone"


def test_generation_actuelle_reflete_la_derniere_connexion():
    session_registre.nouvelle_session("alex", "iPhone")
    session_registre.nouvelle_session("alex", "MacBook")
    assert session_registre.generation_actuelle("alex") == 2


def test_generation_actuelle_compte_inconnu_renvoie_none():
    assert session_registre.generation_actuelle("jamais-connecte") is None


def test_deux_comptes_ont_des_generations_independantes():
    session_registre.nouvelle_session("compte_a", "iPhone")
    session_registre.nouvelle_session("compte_b", "iPhone")
    session_registre.nouvelle_session("compte_a", "MacBook")
    assert session_registre.generation_actuelle("compte_a") == 2
    assert session_registre.generation_actuelle("compte_b") == 1
