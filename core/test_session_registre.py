"""Registre des sessions actives par compte (relai propre entre appareils).

$ cd core && python3 -m pytest test_session_registre.py -v
"""
import os
import tempfile

import pytest

os.environ["SESSION_REGISTRE_DB"] = os.path.join(tempfile.mkdtemp(), "session_registre.db")

import session_registre  # noqa: E402


@pytest.fixture(autouse=True)
def _db_isolee():
    """Repointe `session_registre.DB` vers un fichier neuf à CHAQUE test.

    La ligne `os.environ[...]` ci-dessus ne suffit pas seule en suite combinée :
    `session_registre.DB` est lu depuis l'environnement une seule fois, à l'IMPORT du
    module. Si un autre fichier de test importé plus tôt dans la même collecte pytest
    (p. ex. `test_auth_routes.py`, qui déclenche `session_registre.nouvelle_session` via
    `/auth/callback`, ou désormais `test_auth.py`, Task 4) a importé `session_registre`
    avant ce fichier, ce module est déjà en cache (`sys.modules`) et la ligne ci-dessus
    n'a plus aucun effet — les tests d'ici hériteraient silencieusement de générations déjà
    avancées ailleurs (p. ex. `marina`, sub partagé avec `test_auth_routes.py`). Réaffecter
    l'attribut du module (relu à chaque appel par `_conn()`, jamais figé dans une closure)
    donne une base neuve par test, quel que soit l'ordre de collecte pytest."""
    ancien = session_registre.DB
    session_registre.DB = os.path.join(tempfile.mkdtemp(), "session_registre.db")
    try:
        yield
    finally:
        session_registre.DB = ancien


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


def test_connexions_concurrentes_ne_recoivent_jamais_la_meme_generation():
    """Race condition (Critical 2, revue finale whole-branch) : le SELECT puis le calcul
    `generation+1` en Python puis l'INSERT...ON CONFLICT n'étaient PAS atomiques — deux
    connexions quasi-simultanées pouvaient lire la même ancienne génération et écrire la
    même nouvelle (reproduit 5/5 sur l'ancien code par le reviewer). Deux threads
    synchronisés par une barrière pour maximiser la fenêtre de recouvrement : sur le code
    non corrigé, cette assertion échoue de façon fiable (dupliqués observés en pratique)."""
    import threading

    sub = "course-concurrente"
    barriere = threading.Barrier(2)
    resultats: list[int] = []
    verrou = threading.Lock()

    def _connecter(appareil: str) -> None:
        barriere.wait()
        generation, _ = session_registre.nouvelle_session(sub, appareil)
        with verrou:
            resultats.append(generation)

    threads = [
        threading.Thread(target=_connecter, args=("iPhone",)),
        threading.Thread(target=_connecter, args=("MacBook",)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(resultats) == 2
    assert resultats[0] != resultats[1], (
        f"deux connexions concurrentes ont reçu la même génération : {resultats}"
    )
    assert sorted(resultats) == [1, 2]
