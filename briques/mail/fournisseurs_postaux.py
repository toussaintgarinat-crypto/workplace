"""Routage POSTAL — dépose (ou pas) un courrier physique chez un prestataire externe
(impression + affranchissement + dépôt). `MockRouteurPostal` : ne dépose RIEN
réellement, honnête sur ce fait dans sa réponse — motif `geo/fournisseurs.py`
(mock honnête d'abord). Aucun prestataire réel (ex. Merci Facteur) n'est branché
dans cette itération : quand il existera, cette factory gagnera la même bascule
explicite par variable d'env que les autres fournisseurs du parc (ex.
GEO_FOURNISSEUR), jamais une détection silencieuse."""
from __future__ import annotations


class MockRouteurPostal:
    nom = "mock"

    def deposer(self, courrier: dict) -> dict:
        return {"ok": True, "reel": False, "fournisseur": self.nom,
                "message": "SIMULÉ : aucun courrier physique n'a été déposé (aucun "
                           "prestataire postal réel n'est branché)."}


def routeur_postal() -> MockRouteurPostal:
    return MockRouteurPostal()
