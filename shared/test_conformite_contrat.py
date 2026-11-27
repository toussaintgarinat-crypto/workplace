import subprocess
import sys
from pathlib import Path

import pytest

from shared import contrat_donnees as C
from shared.conformite_contrat import Refus, verifier_conformite

CLE = b"k"
RACINE = Path(__file__).resolve().parent.parent


class AppMemoire:
    """App de référence : un dict {utilisateur: [objets]}. Chaque drapeau simule une fuite
    ou un défaut précis, pour vérifier que le harnais détecte chaque garde-fou.

    fuite            : export/état ignorent le cloisonnement (détecté tôt, par la distinction).
    fuite_reset      : reset efface TOUS les utilisateurs (portée correcte à l'export).
    fuite_import     : import écrit dans TOUS les utilisateurs.
    import_partiel   : un import refusé vide d'abord la cible puis lève Refus.
    reset_refus_efface : un reset refusé (mauvaise empreinte) vide tout puis lève Refus.
    reset_refus_a_tort : reset valide refusé à tort (HTTP 4xx sur le nominal).
    import_refus_a_tort : import valide refusé à tort (HTTP 4xx sur le nominal).
    """

    def __init__(self, fuite=False, fuite_reset=False, fuite_import=False,
                 import_partiel=False, reset_refus_efface=False,
                 reset_refus_a_tort=False, import_refus_a_tort=False):
        self.d = {}
        self.fuite = fuite
        self.fuite_reset = fuite_reset
        self.fuite_import = fuite_import
        self.import_partiel = import_partiel
        self.reset_refus_efface = reset_refus_efface
        self.reset_refus_a_tort = reset_refus_a_tort
        self.import_refus_a_tort = import_refus_a_tort

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
        if self.reset_refus_efface:
            self.d.clear()
        if self.etat(u)[1] != empreinte:
            raise Refus("empreinte")
        if self.reset_refus_a_tort:
            raise Refus("trop tôt")
        if self.fuite or self.fuite_reset:
            self.d.clear()
        else:
            self.d[u] = []

    def importer(self, u, octets):
        try:
            _, o = C.lire_paquet(octets, CLE, "memoire", u, "1")
        except C.PaquetInvalide as e:
            if self.import_partiel:
                self.d[u] = []
            raise Refus(e.raison)
        if self.import_refus_a_tort:
            raise Refus("trop tôt")
        if self.fuite_import:
            for k in self.d:
                self.d[k] = o["notes"]
        else:
            self.d[u] = o["notes"]


def test_app_conforme_passe():
    verifier_conformite(AppMemoire())


def test_app_qui_fuit_echoue():
    with pytest.raises(AssertionError,
                       match="les deux utilisateurs doivent avoir des données distinctes"):
        verifier_conformite(AppMemoire(fuite=True))


def test_reset_qui_fuit_echoue_sur_le_garde_fou_reset():
    with pytest.raises(AssertionError,
                       match="le reset de claire ne doit PAS toucher marina"):
        verifier_conformite(AppMemoire(fuite_reset=True))


def test_import_qui_fuit_echoue_sur_le_garde_fou_import():
    with pytest.raises(AssertionError,
                       match="l'import de claire ne doit PAS toucher marina"):
        verifier_conformite(AppMemoire(fuite_import=True))


def test_import_refuse_partiellement_echoue():
    with pytest.raises(AssertionError,
                       match="un import refusé ne doit rien modifier"):
        verifier_conformite(AppMemoire(import_partiel=True))


def test_reset_refuse_qui_efface_echoue():
    with pytest.raises(AssertionError,
                       match="un reset refusé ne doit rien modifier"):
        verifier_conformite(AppMemoire(reset_refus_efface=True))


def test_reset_nominal_refuse_a_tort_echoue():
    with pytest.raises(AssertionError, match="refusé à tort"):
        verifier_conformite(AppMemoire(reset_refus_a_tort=True))


def test_import_nominal_refuse_a_tort_echoue():
    with pytest.raises(AssertionError, match="refusé à tort"):
        verifier_conformite(AppMemoire(import_refus_a_tort=True))


def test_gardes_survivent_a_python_O():
    # Sous `python -O`, les `assert` disparaissent : les gardes doivent rester actifs.
    code = (
        "import sys\n"
        "from shared.conformite_contrat import verifier_conformite\n"
        "from shared.test_conformite_contrat import AppMemoire\n"
        "try:\n"
        "    verifier_conformite(AppMemoire(fuite_reset=True))\n"
        "except AssertionError as e:\n"
        "    print(e)\n"
        "    sys.exit(0)\n"
        "sys.exit(1)\n"
    )
    r = subprocess.run([sys.executable, "-O", "-c", code], cwd=RACINE,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "le reset de claire ne doit PAS toucher marina" in r.stdout
