"""Tests du pont : autorisation, relais à l'assistant (mocké), persistance, repli honnête."""
import asyncio

import adaptateurs as A
import conversations as C
import correspondance as K
import pont
import client_assistant


def _run(coro):
    return asyncio.run(coro)


class FauxAdaptateur(A.Adaptateur):
    nom = "faux"

    def __init__(self):
        self.envoyes = []

    def configure(self) -> bool:
        return True

    async def envoyer(self, id_externe: str, texte: str) -> bool:
        self.envoyes.append((id_externe, texte))
        return True


def _brancher(monkeypatch, reponse="Bonjour !", leve=False):
    """Installe un faux réseau + une fausse réponse d'assistant (sans réseau)."""
    faux = FauxAdaptateur()
    monkeypatch.setitem(A.REGISTRE, "faux", faux)

    async def fausse_converser(messages, **_):
        if leve:
            raise RuntimeError("assistant KO")
        return reponse

    monkeypatch.setattr(client_assistant, "converser", fausse_converser)
    return faux


def test_non_autorise_envoie_accueil(monkeypatch):
    faux = _brancher(monkeypatch)
    r = _run(pont.traiter("faux", A.Entrant("faux", "x1", "salut", "Bob")))
    assert r["ok"] is False and r["raison"] == "non_autorise"
    assert faux.envoyes and "code" in r and r["code"] in faux.envoyes[0][1]
    # rien n'a été relayé à l'assistant ni persisté
    assert C.charger("faux", "x1") == []


def test_flux_complet_autorise(monkeypatch):
    faux = _brancher(monkeypatch, reponse="Voici ta réponse.")
    K.lier("faux", "x2", "garina@workplace")
    r = _run(pont.traiter("faux", A.Entrant("faux", "x2", "ça va ?", "Garina")))
    assert r["ok"] is True and r["repli"] is False
    assert r["reponse"] == "Voici ta réponse."
    assert r["utilisateur"] == "garina@workplace"
    # réponse envoyée sur le réseau + tour persisté (user + assistant)
    assert faux.envoyes == [("x2", "Voici ta réponse.")]
    fil = C.charger("faux", "x2")
    assert [m["role"] for m in fil] == ["user", "assistant"]


def test_systeme_qui_parle(monkeypatch):
    """Le 1ᵉʳ message envoyé à l'assistant est un système « qui parle » (multi-utilisateur)."""
    captures = {}

    async def capter(messages, **_):
        captures["messages"] = messages
        return "ok"

    monkeypatch.setitem(A.REGISTRE, "faux", FauxAdaptateur())
    monkeypatch.setattr(client_assistant, "converser", capter)
    K.lier("faux", "x3", "u@wp")
    _run(pont.traiter("faux", A.Entrant("faux", "x3", "yo", "Zoé")))
    msgs = captures["messages"]
    assert msgs[0]["role"] == "system" and "Zoé" in msgs[0]["content"]
    assert msgs[-1] == {"role": "user", "content": "yo"}


def test_repli_honnete_si_assistant_ko(monkeypatch):
    faux = _brancher(monkeypatch, leve=True)
    K.lier("faux", "x4", "u@wp")
    r = _run(pont.traiter("faux", A.Entrant("faux", "x4", "?", None)))
    assert r["ok"] is True and r["repli"] is True
    assert "joindre l'assistant" in r["reponse"]
    assert faux.envoyes[0][1] == r["reponse"]      # le repli honnête part quand même


def test_sonder_reseau_non_configure():
    # email_sms n'est pas configuré → sondage honnête à vide, sans réseau.
    r = _run(pont.sonder("email_sms"))
    assert r == {"ok": True, "reseau": "email_sms", "traites": 0, "configure": False}
