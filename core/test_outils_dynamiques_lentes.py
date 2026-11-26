import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
os.environ.setdefault("GATEWAY_KEY", "sk-test-local")

import outils_communs  # noqa: E402


def _cap(chemin):
    return {"nom": "x", "chemin": chemin, "methode": "POST"}


def test_routes_de_sauvegarde_ont_un_timeout_long():
    assert outils_communs._timeout_dynamique(_cap("/apps/{app}/sauvegarder")) \
        >= outils_communs.TIMEOUT_MUTATION_LONGUE
    assert outils_communs._timeout_dynamique(_cap("/apps/{app}/sauvegardes/verifier")) \
        > outils_communs.TIMEOUT_MUTATION_LONGUE


def test_route_quelconque_garde_le_timeout_du_client():
    assert outils_communs._timeout_dynamique(_cap("/apps/{app}/etat")) is None
