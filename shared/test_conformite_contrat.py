import pytest

from shared import contrat_donnees as C
from shared.conformite_contrat import Refus, verifier_conformite

CLE = b"k"


class AppMemoire:
    """App de référence : un dict {utilisateur: [objets]}. `fuite=True` simule une app dont
    l'export/reset ignore le cloisonnement."""

    def __init__(self, fuite=False):
        self.d = {}
        self.fuite = fuite

    def _objets(self, u):
        if self.fuite:
            return {"notes": [n for liste in self.d.values() for n in liste]}
        return {"notes": list(self.d.get(u, []))}

    def peupler(self, u):
        self.d[u] = [{"id": f"{u}-1", "t": "a"}, {"id": f"{u}-2", "t": "b"}]

    def exporter(self, u):
        return C.construire_paquet("memoire", u, "1", self._objets(u), CLE)

    def etat(self, u):
        o = self._objets(u)
        return C.comptages(o), C.empreinte(o)

    def reinitialiser(self, u, empreinte):
        if self.etat(u)[1] != empreinte:
            raise Refus("empreinte")
        if self.fuite:
            self.d.clear()
        else:
            self.d[u] = []

    def importer(self, u, octets):
        try:
            _, o = C.lire_paquet(octets, CLE, "memoire", u, "1")
        except C.PaquetInvalide as e:
            raise Refus(e.raison)
        self.d[u] = o["notes"]


def test_app_conforme_passe():
    verifier_conformite(AppMemoire())


def test_app_qui_fuit_echoue():
    with pytest.raises(AssertionError):
        verifier_conformite(AppMemoire(fuite=True))
