"""Tests du pont : autorisation, relais à l'assistant (mocké), persistance, repli honnête."""
import asyncio

import adaptateurs as A
import conversations as C
import correspondance as K
import pont
import client_assistant
import voix


def _run(coro):
    return asyncio.run(coro)


class FauxAdaptateur(A.Adaptateur):
    nom = "faux"

    def __init__(self):
        self.envoyes = []
        self.telecharges = []
        self.audios = []

    def configure(self) -> bool:
        return True

    async def envoyer(self, id_externe: str, texte: str) -> bool:
        self.envoyes.append((id_externe, texte))
        return True

    async def telecharger_media(self, media_id: str) -> bytes:
        self.telecharges.append(media_id)
        return b"\x00\x01octets-audio"

    async def envoyer_audio(self, id_externe: str, audio: bytes, format: str = "ogg") -> bool:
        self.audios.append((id_externe, audio, format))
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


def test_vocal_transcrit_puis_relaye(monkeypatch):
    """Message vocal autorisé → téléchargé, transcrit (Whisper local mocké), relayé comme texte."""
    faux = _brancher(monkeypatch, reponse="Bien reçu.")

    async def fausse_transcription(audio, nom="voix.ogg", langue=None, **_):
        assert audio == b"\x00\x01octets-audio"
        return {"texte": "rappelle-moi demain", "place_holder": False, "backend": "local"}

    monkeypatch.setattr(voix, "transcrire", fausse_transcription)
    K.lier("faux", "v1", "u@wp")
    e = A.Entrant("faux", "v1", "", "Garina", media_id="AwAC", media_type="audio")
    r = _run(pont.traiter("faux", e))
    assert r["ok"] is True and r["transcrit"] == "rappelle-moi demain"
    assert faux.telecharges == ["AwAC"]
    # le texte transcrit devient le message user persisté + relayé à l'assistant
    fil = C.charger("faux", "v1")
    assert fil[0]["role"] == "user" and fil[0]["content"] == "rappelle-moi demain"
    assert faux.envoyes == [("v1", "Bien reçu.")]


def test_vocal_repli_honnete_si_moteur_ko(monkeypatch):
    """Moteur STT KO (place_holder) → on prévient l'interlocuteur, rien de faux n'est relayé."""
    faux = _brancher(monkeypatch, reponse="ne devrait pas être appelé")

    async def stt_vide(audio, nom="voix.ogg", langue=None, **_):
        return {"texte": "", "place_holder": True, "backend": "placeholder"}

    monkeypatch.setattr(voix, "transcrire", stt_vide)
    K.lier("faux", "v2", "u@wp")
    e = A.Entrant("faux", "v2", "", "Garina", media_id="X", media_type="audio")
    r = _run(pont.traiter("faux", e))
    assert r["ok"] is False and r["raison"] == "transcription_indisponible"
    assert faux.envoyes and "vocal" in faux.envoyes[0][1].lower()
    assert C.charger("faux", "v2") == []        # rien n'est persisté, rien de faux relayé


def test_vocal_repond_aussi_en_vocal(monkeypatch):
    """Speech-to-speech : message vocal → réponse texte ENVOYÉE + réponse VOCALE synthétisée."""
    monkeypatch.setenv("CONNEXION_TTS", "1")
    faux = _brancher(monkeypatch, reponse="Avec plaisir.")

    async def stt(audio, nom="voix.ogg", langue=None, **_):
        return {"texte": "merci", "place_holder": False, "backend": "local"}

    async def tts(texte, voix=None, langue=None, **_):
        assert texte == "Avec plaisir."
        return {"audio": b"OGG", "format": "ogg", "backend": "piper"}

    monkeypatch.setattr(voix, "transcrire", stt)
    monkeypatch.setattr(voix, "synthetiser", tts)
    K.lier("faux", "v3", "u@wp")
    e = A.Entrant("faux", "v3", "", "Garina", media_id="m", media_type="audio")
    r = _run(pont.traiter("faux", e))
    assert r["ok"] is True and r["vocalise"] is True
    assert faux.envoyes == [("v3", "Avec plaisir.")]        # le texte part toujours (transcription lisible)
    assert faux.audios == [("v3", b"OGG", "ogg")]            # + la bulle vocale


def test_message_texte_ne_vocalise_pas(monkeypatch):
    """Un message ÉCRIT ordinaire reçoit une réponse écrite — pas de synthèse vocale inutile."""
    monkeypatch.setenv("CONNEXION_TTS", "1")
    faux = _brancher(monkeypatch, reponse="ok")
    appels = {"tts": 0}

    async def tts(*a, **k):
        appels["tts"] += 1
        return {"audio": b"X", "format": "ogg"}

    monkeypatch.setattr(voix, "synthetiser", tts)
    K.lier("faux", "v4", "u@wp")
    r = _run(pont.traiter("faux", A.Entrant("faux", "v4", "coucou", "Garina")))
    assert r["vocalise"] is False and appels["tts"] == 0
    assert faux.audios == []


def test_ecoute_ordinaire_ne_vocalise_pas(monkeypatch):
    """'Écoute, j'ai un problème audio' — faux positifs évités, pas de TTS non demandé."""
    monkeypatch.setenv("CONNEXION_TTS", "1")
    faux = _brancher(monkeypatch, reponse="ok")
    appels = {"tts": 0}

    async def tts(*a, **k):
        appels["tts"] += 1
        return {"audio": b"X", "format": "ogg"}

    monkeypatch.setattr(voix, "synthetiser", tts)
    K.lier("faux", "v7", "u@wp")
    r = _run(pont.traiter("faux", A.Entrant("faux", "v7", "écoute, j'ai un problème audio", "Garina")))
    assert r["vocalise"] is False and appels["tts"] == 0


def test_message_texte_demande_vocale_se_vocalise(monkeypatch):
    """Un texte demandant explicitement un vocal ('fais-moi un vocal de ça') déclenche le TTS."""
    monkeypatch.setenv("CONNEXION_TTS", "1")
    faux = _brancher(monkeypatch, reponse="Voici ta réponse lue.")

    async def tts(texte, voix=None, langue=None, **_):
        assert texte == "Voici ta réponse lue."
        return {"audio": b"MP3", "format": "mp3", "backend": "piper"}

    monkeypatch.setattr(voix, "synthetiser", tts)
    K.lier("faux", "v6", "u@wp")
    r = _run(pont.traiter("faux", A.Entrant("faux", "v6", "fais-moi un vocal de ce texte", "Garina")))
    assert r["ok"] is True and r["vocalise"] is True
    assert faux.envoyes == [("v6", "Voici ta réponse lue.")]   # texte toujours envoyé
    assert faux.audios == [("v6", b"MP3", "mp3")]               # + bulle vocale


def test_vocal_repli_honnete_si_tts_indisponible(monkeypatch):
    """TTS indisponible (placeholder → None) : le texte est parti, aucune fausse voix envoyée."""
    monkeypatch.setenv("CONNEXION_TTS", "1")
    faux = _brancher(monkeypatch, reponse="Voilà.")

    async def stt(audio, nom="voix.ogg", langue=None, **_):
        return {"texte": "salut", "place_holder": False}

    async def tts_absent(texte, voix=None, langue=None, **_):
        return None                                          # placeholder honnête de la brique voix

    monkeypatch.setattr(voix, "transcrire", stt)
    monkeypatch.setattr(voix, "synthetiser", tts_absent)
    K.lier("faux", "v5", "u@wp")
    e = A.Entrant("faux", "v5", "", "Garina", media_id="m", media_type="audio")
    r = _run(pont.traiter("faux", e))
    assert r["ok"] is True and r["vocalise"] is False
    assert faux.envoyes == [("v5", "Voilà.")] and faux.audios == []


def test_sonder_reseau_non_configure():
    # email_sms n'est pas configuré → sondage honnête à vide, sans réseau.
    r = _run(pont.sonder("email_sms"))
    assert r == {"ok": True, "reseau": "email_sms", "traites": 0, "configure": False}


# ── Envoi proactif (rappels d'agenda poussés par le Cœur) — S80 ──────────────

def test_cibles_pour_ne_rend_que_les_lies():
    K.lier("faux", "push1", "garina@push")
    # Un interlocuteur en attente (non lié) ne doit pas être une cible.
    K.resoudre("faux", "push-attente", "Inconnu")
    cibles = K.cibles_pour("garina@push")
    assert ("faux", "push1") in cibles
    assert all(util_id != "push-attente" for _, util_id in cibles)


def test_pousser_envoie_sur_le_reseau_lie(monkeypatch):
    import main
    faux = FauxAdaptateur()
    monkeypatch.setitem(A.REGISTRE, "faux", faux)
    K.lier("faux", "push2", "garina@push2")
    r = _run(main.pousser(main.Pousser(utilisateur="garina@push2", texte="🔔 Rappel : Dentiste"),
                          _cle="public"))
    assert r["ok"] is True and r["envoyes"] == 1
    assert faux.envoyes == [("push2", "🔔 Rappel : Dentiste")]


def test_pousser_repli_honnete_sans_cible(monkeypatch):
    import main
    r = _run(main.pousser(main.Pousser(utilisateur="personne@nulle-part", texte="x"),
                          _cle="public"))
    assert r == {"ok": True, "envoyes": 0, "cibles": 0, "detail": []}
