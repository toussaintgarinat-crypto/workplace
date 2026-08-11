"""S228 — routage structurel des tours de conversation vers l'entretien Forge actif.

Offline, calqué sur test_accord_action.py : le registre en mémoire est testé seul, sans
serveur ni réseau réel (l'appel HTTP à Forge est testé séparément, httpx mocké).
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import entretien_routage  # noqa: E402


def setup_function():
    entretien_routage.REGISTRE._actifs.clear()


def test_activer_puis_actif():
    entretien_routage.REGISTRE.activer("fil-1", "venture-1")
    assert entretien_routage.REGISTRE.actif("fil-1") == "venture-1"


def test_actif_none_si_jamais_active():
    assert entretien_routage.REGISTRE.actif("fil-inconnu") is None


def test_desactiver():
    entretien_routage.REGISTRE.activer("fil-1", "venture-1")
    entretien_routage.REGISTRE.desactiver("fil-1")
    assert entretien_routage.REGISTRE.actif("fil-1") is None


def test_isolation_par_fil_accord():
    """Deux fils_accord distincts (donc deux (fil, personne) distincts, cf. accord_action.cle)
    ne partagent JAMAIS le même entretien actif — non-régression directe de la leçon S222."""
    entretien_routage.REGISTRE.activer("web:dashboard\x00alice", "venture-alice")
    entretien_routage.REGISTRE.activer("web:dashboard\x00bob", "venture-bob")
    assert entretien_routage.REGISTRE.actif("web:dashboard\x00alice") == "venture-alice"
    assert entretien_routage.REGISTRE.actif("web:dashboard\x00bob") == "venture-bob"


def test_est_pause_detecte_les_mots_cles_explicites():
    assert entretien_routage.est_pause("pause")
    assert entretien_routage.est_pause("On reprendra plus tard, merci")
    assert entretien_routage.est_pause("PAUSE STP")


def test_est_pause_faux_sur_message_normal():
    assert not entretien_routage.est_pause("On est une SARL de 5 salariés")
    assert not entretien_routage.est_pause("")


def test_repondre_appelle_forge_et_renvoie_le_json():
    calls = []

    class _FakeResp:
        status_code = 200

        def json(self):
            return {"question": "Et ensuite ?", "statut": "en_cours", "sectionCourante": "processus.commercial"}

    class _FakeClient:
        async def post(self, url, **kw):
            calls.append((url, kw))
            return _FakeResp()

    async def _run():
        return await entretien_routage.repondre(
            registre=object(), fil_accord="fil-1", venture_id="venture-1",
            message="On qualifie puis on envoie un devis.", client=_FakeClient(),
            base_forge="http://forge.test/api")

    data = asyncio.run(_run())
    assert data["question"] == "Et ensuite ?"
    assert calls[0][0] == "http://forge.test/api/ventures/venture-1/entretien/repondre"
    assert calls[0][1]["json"] == {"message": "On qualifie puis on envoie un devis."}


def test_repondre_desactive_le_registre_quand_termine():
    entretien_routage.REGISTRE.activer("fil-1", "venture-1")

    class _FakeResp:
        status_code = 200

        def json(self):
            return {"question": None, "statut": "termine"}

    class _FakeClient:
        async def post(self, url, **kw):
            return _FakeResp()

    async def _run():
        return await entretien_routage.repondre(
            registre=object(), fil_accord="fil-1", venture_id="venture-1",
            message="Terminé.", client=_FakeClient(), base_forge="http://forge.test/api")

    asyncio.run(_run())
    assert entretien_routage.REGISTRE.actif("fil-1") is None
