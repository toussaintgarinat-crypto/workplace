import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
os.environ.setdefault("GATEWAY_KEY", "sk-test-local")

import outils_communs  # noqa: E402


def _cap(chemin):
    return {"nom": "x", "chemin": chemin, "methode": "POST"}


def test_routes_de_sauvegarde_ont_un_timeout_long():
    assert outils_communs._timeout_dynamique(_cap("/apps/{app}/sauvegarder")) \
        > outils_communs.TIMEOUT_MUTATION_LONGUE
    assert outils_communs._timeout_dynamique(_cap("/apps/{app}/sauvegardes/verifier")) \
        > outils_communs.TIMEOUT_MUTATION_LONGUE


def test_route_quelconque_garde_le_timeout_du_client():
    assert outils_communs._timeout_dynamique(_cap("/apps/{app}/etat")) is None


def test_timeout_verification_depasse_le_delai_global_de_la_brique():
    # 540 = sauvegarde.DELAI_GLOBAL_S (briques/livraison) : le Cœur ne doit jamais couper avant.
    assert outils_communs.TIMEOUT_VERIFICATION > 540
