"""Tests du pont : autorisation, relais à l'assistant (mocké), persistance, repli honnête."""
import asyncio

import httpx
import pytest

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
        self.photos = []
        self.documents = []

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

    async def envoyer_photo(self, id_externe: str, image: bytes, nom: str = "image.png") -> bool:
        self.photos.append((id_externe, image, nom))
        return True

    async def envoyer_document(self, id_externe: str, contenu: bytes, nom: str = "fichier") -> bool:
        self.documents.append((id_externe, contenu, nom))
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


# ── Pièces jointes (S196) : images/PDF/HTML produits par un outil, relayées en plus du texte

class _RespMedia:
    def __init__(self, content=b"OCTETS", status=200):
        self.content = content
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPError("brique média injoignable")


def _fake_httpx_medias(monkeypatch, reponses: dict | None = None):
    """Remplace `pont.httpx` par un faux client GET (pas de vrai réseau). `reponses` associe
    une URL exacte à une `_RespMedia` (sinon 200/OCTETS par défaut)."""
    reponses = reponses or {}

    class _FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url):
            return reponses.get(url, _RespMedia())

    monkeypatch.setattr(pont, "httpx", type("_H", (), {
        "AsyncClient": _FakeClient, "HTTPError": httpx.HTTPError}))


def test_envoyer_medias_image_va_en_sendphoto(monkeypatch):
    _fake_httpx_medias(monkeypatch)
    faux = FauxAdaptateur()
    n = _run(pont._envoyer_medias(faux, "x1", [
        {"url": "http://images-interne/fichiers/img-abc.png", "nom": "image_generer"}]))
    assert n == 1
    assert faux.photos == [("x1", b"OCTETS", "img-abc.png")]
    assert faux.documents == []


def test_envoyer_medias_document_va_en_senddocument(monkeypatch):
    _fake_httpx_medias(monkeypatch)
    faux = FauxAdaptateur()
    n = _run(pont._envoyer_medias(faux, "x1", [
        {"url": "http://export-interne/fichiers/rapport.pdf", "nom": "export_pdf"}]))
    assert n == 1
    assert faux.documents == [("x1", b"OCTETS", "rapport.pdf")]
    assert faux.photos == []


def test_envoyer_medias_echec_reseau_ignore_sans_lever(monkeypatch):
    """Un média KO (brique injoignable) n'interrompt pas les autres — repli honnête."""
    _fake_httpx_medias(monkeypatch, reponses={
        "http://images-interne/fichiers/boum.png": _RespMedia(status=500)})
    faux = FauxAdaptateur()
    n = _run(pont._envoyer_medias(faux, "x1", [
        {"url": "http://images-interne/fichiers/boum.png", "nom": "image_generer"},
        {"url": "http://images-interne/fichiers/ok.png", "nom": "image_generer"},
    ]))
    assert n == 1
    assert faux.photos == [("x1", b"OCTETS", "ok.png")]


def test_envoyer_medias_adaptateur_sans_piece_jointe_ignore(monkeypatch):
    """Un adaptateur qui ne sait pas envoyer de pièce jointe (NotImplementedError, cf. classe
    de base Adaptateur) ne fait jamais échouer le tour — repli honnête."""
    _fake_httpx_medias(monkeypatch)

    class _AdaptateurSansPieceJointe(A.Adaptateur):
        nom = "sans-pj"

    n = _run(pont._envoyer_medias(_AdaptateurSansPieceJointe(), "x1", [
        {"url": "http://images-interne/fichiers/img.png", "nom": "image_generer"}]))
    assert n == 0


def test_traiter_relaie_le_media_produit_par_un_outil(monkeypatch):
    """Bout-en-bout : l'assistant produit une image pendant le tour (medias= peuplé par
    client_assistant.converser) → le pont l'envoie APRÈS le texte, sans jamais le remplacer."""
    faux = FauxAdaptateur()
    monkeypatch.setitem(A.REGISTRE, "faux", faux)
    _fake_httpx_medias(monkeypatch)

    async def fausse_converser(messages, medias=None, **_):
        if medias is not None:
            medias.append({"url": "http://images-interne/fichiers/img-abc.png",
                           "nom": "image_generer"})
        return "Voici ton image."

    monkeypatch.setattr(client_assistant, "converser", fausse_converser)
    K.lier("faux", "m1", "u@wp")
    r = _run(pont.traiter("faux", A.Entrant("faux", "m1", "fais-moi une image de chat", "Garina")))
    assert r["ok"] is True and r["medias_envoyes"] == 1
    assert faux.envoyes == [("m1", "Voici ton image.")]          # le texte part toujours
    assert faux.photos == [("m1", b"OCTETS", "img-abc.png")]      # + la pièce jointe


def test_traiter_repli_honnete_pas_de_media_envoye(monkeypatch):
    """Assistant KO (repli honnête) : même si un média avait été partiellement collecté avant
    la levée, on n'envoie JAMAIS de pièce jointe sur un tour en repli."""
    faux = FauxAdaptateur()
    monkeypatch.setitem(A.REGISTRE, "faux", faux)
    _fake_httpx_medias(monkeypatch)

    async def fausse_converser(messages, medias=None, **_):
        if medias is not None:
            medias.append({"url": "http://images-interne/fichiers/img.png", "nom": "x"})
        raise RuntimeError("assistant KO")

    monkeypatch.setattr(client_assistant, "converser", fausse_converser)
    K.lier("faux", "m2", "u@wp")
    r = _run(pont.traiter("faux", A.Entrant("faux", "m2", "salut", "Garina")))
    assert r["ok"] is True and r["repli"] is True and r["medias_envoyes"] == 0
    assert faux.photos == [] and faux.documents == []


# ── Historique cross-surface (web ⇄ Telegram ⇄ tout autre canal) ────────────

def test_historique_croise_defaut_off_utilise_le_fil_local(monkeypatch):
    """Sans `CONNEXION_HISTORIQUE_CROISE`, comportement inchangé : fil local seulement,
    aucun appel à `client_assistant.historique_utilisateur`."""
    appels = {"n": 0}

    async def jamais_appele(utilisateur, **_):
        appels["n"] += 1
        return ["ne devrait jamais être vu"]

    monkeypatch.setattr(client_assistant, "historique_utilisateur", jamais_appele)
    faux = _brancher(monkeypatch, reponse="ok")
    K.lier("faux", "h1", "u@wp")
    C.ajouter("faux", "h1", "user", "vieux message local")
    _run(pont.traiter("faux", A.Entrant("faux", "h1", "coucou", "Garina")))
    assert appels["n"] == 0


def test_historique_croise_actif_fusionne_les_surfaces(monkeypatch):
    """Flag activé + compte connu → l'historique vient du journal unifié du Cœur (web +
    Telegram), pas du seul fil local du canal courant."""
    monkeypatch.setenv("CONNEXION_HISTORIQUE_CROISE", "1")
    captures = {}

    async def capter(messages, **_):
        captures["messages"] = messages
        return "ok"

    async def fausse_historique(utilisateur, **_):
        assert utilisateur == "u@wp"
        return [{"role": "user", "content": "dit sur le web"},
                {"role": "assistant", "content": "répondu sur le web"}]

    monkeypatch.setitem(A.REGISTRE, "faux", FauxAdaptateur())
    monkeypatch.setattr(client_assistant, "converser", capter)
    monkeypatch.setattr(client_assistant, "historique_utilisateur", fausse_historique)
    K.lier("faux", "h2", "u@wp")
    _run(pont.traiter("faux", A.Entrant("faux", "h2", "et maintenant sur telegram", "Garina")))
    contenus = [m["content"] for m in captures["messages"]]
    assert "dit sur le web" in contenus
    assert "et maintenant sur telegram" in contenus


def test_historique_croise_repli_honnete_si_coeur_ko(monkeypatch):
    """Cœur injoignable pour l'historique croisé → repli sur le fil local, jamais une panne."""
    monkeypatch.setenv("CONNEXION_HISTORIQUE_CROISE", "1")

    async def historique_ko(utilisateur, **_):
        raise RuntimeError("Cœur injoignable")

    monkeypatch.setattr(client_assistant, "historique_utilisateur", historique_ko)
    faux = _brancher(monkeypatch, reponse="ok quand même")
    K.lier("faux", "h3", "u@wp")
    C.ajouter("faux", "h3", "user", "ancien message local")
    r = _run(pont.traiter("faux", A.Entrant("faux", "h3", "toujours là ?", "Garina")))
    assert r["ok"] is True and r["repli"] is False


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


# ═══ S245 : approbation Telegram — callbacks, code à 6 chiffres ═══════════════════════
import logging
import re

ID_AP = "a1" * 16                                   # 32 hex


class FauxApprob(FauxAdaptateur):
    """FauxAdaptateur + API boutons/callback qui enregistre ses appels."""
    nom = "faux"

    def __init__(self):
        super().__init__()
        self.reponses_cb = []
        self.editions = []
        self.boutons = []

    async def repondre_callback(self, callback_id, texte=""):
        self.reponses_cb.append((callback_id, texte))

    async def editer_message(self, chat_id, message_id, texte):
        self.editions.append((chat_id, message_id, texte))

    async def envoyer_boutons(self, id_externe, texte, boutons):
        self.boutons.append((id_externe, texte, boutons))
        return {"chat_id": id_externe, "message_id": 1}


class _Coeur:
    """Faux Cœur : consigne les appels de client_assistant et rend des réponses scriptées."""
    def __init__(self, monkeypatch, decision=None, armer=None, code=None):
        self.decisions, self.armements, self.codes = [], [], []
        self.utilisateurs = []
        self._decision = decision if decision is not None else {"ok": True, "raison": "ok"}
        self._armer = armer if armer is not None else {"ok": True}
        self._code = code if code is not None else {"pris_en_charge": False}

        async def _d(id_, decision, par, utilisateur):
            self.utilisateurs.append(utilisateur)
            self.decisions.append((id_, decision, par))
            return self._decision

        async def _a(id_, par, utilisateur):
            self.armements.append((id_, par))
            return self._armer

        async def _c(par, code, utilisateur):
            self.codes.append((par, code))
            if isinstance(self._code, Exception):
                raise self._code
            return self._code

        monkeypatch.setattr(client_assistant, "decider_approbation", _d)
        monkeypatch.setattr(client_assistant, "armer_code", _a)
        monkeypatch.setattr(client_assistant, "soumettre_code", _c)

    @property
    def appels(self):
        return self.decisions + self.armements + self.codes


def _approbateur(ident):
    K.lier("faux", ident, f"{ident}@wp")
    assert K.definir_approbateur("faux", ident, True) is not None


def _cb(from_id, data=None, chat_id=None, chat_type="private"):
    return A.Callback("faux", from_id, chat_id or from_id, chat_type, 7, "cbid",
                      data if data is not None else f"ap:{ID_AP}:ok")


def _installer(monkeypatch, **kw):
    faux = FauxApprob()
    monkeypatch.setitem(A.REGISTRE, "faux", faux)
    return faux, _Coeur(monkeypatch, **kw)


def test_callback_transmet_l_utilisateur_lie_de_l_approbateur(monkeypatch):
    faux, coeur = _installer(monkeypatch, decision={"ok": True, "raison": "ok"})
    _approbateur("cb-u1")                                  # lié à « cb-u1@wp »
    _run(pont.traiter_callback("faux", _cb("cb-u1")))
    assert coeur.utilisateurs == ["cb-u1@wp"]


# 1
def test_callback_non_approbateur_ignore_sans_appeler_le_coeur(monkeypatch, caplog):
    faux, coeur = _installer(monkeypatch)
    K.lier("faux", "cb-lie-simple", "u@wp")          # lié mais PAS approbateur
    with caplog.at_level(logging.WARNING):
        r = _run(pont.traiter_callback("faux", _cb("cb-lie-simple")))
    assert r == {"ok": False, "raison": "ignore"}
    assert coeur.appels == []
    assert faux.reponses_cb == [] and faux.editions == [] and faux.envoyes == []   # pas d'oracle
    assert "ignoré" in caplog.text and "cb-lie-simple" in caplog.text
    assert ID_AP not in caplog.text                  # jamais le contenu du callback_data


def test_callback_inconnu_ou_en_attente_ignore(monkeypatch):
    faux, coeur = _installer(monkeypatch)
    K.resoudre("faux", "cb-attente", "X")
    assert _run(pont.traiter_callback("faux", _cb("cb-attente")))["raison"] == "ignore"
    assert _run(pont.traiter_callback("faux", _cb("cb-jamais-vu")))["raison"] == "ignore"
    assert coeur.appels == []


def test_callback_statut_ouvert_ne_donne_pas_le_droit(monkeypatch):
    faux, coeur = _installer(monkeypatch)
    monkeypatch.setenv("CONNEXION_OUVERT", "1")
    monkeypatch.setenv("CONNEXION_UTILISATEUR_DEFAUT", "patron")
    K.resoudre("faux", "cb-ouvert", "O")
    assert _run(pont.traiter_callback("faux", _cb("cb-ouvert")))["raison"] == "ignore"
    assert coeur.appels == []


# 2
def test_callback_approbateur_en_groupe_ignore(monkeypatch):
    faux, coeur = _installer(monkeypatch)
    _approbateur("cb-grp")
    for t in ("group", "supergroup", "channel", ""):
        r = _run(pont.traiter_callback("faux", _cb("cb-grp", chat_type=t)))
        assert r["raison"] == "ignore"
    assert coeur.appels == [] and faux.reponses_cb == []


# 3
def test_callback_chat_different_de_l_emetteur_ignore(monkeypatch):
    faux, coeur = _installer(monkeypatch)
    _approbateur("cb-autrechat")
    r = _run(pont.traiter_callback("faux", _cb("cb-autrechat", chat_id="999")))
    assert r["raison"] == "ignore"
    assert coeur.appels == [] and faux.reponses_cb == []


# 4
@pytest.mark.parametrize("data", [
    "ap:zzz:ok", f"x:{ID_AP}:ok", f"ap:{ID_AP}:peut-etre", f"ap:{ID_AP}:OK",
    f"ap:{ID_AP}:ok:extra", "ap:" + "a1" * 17 + ":ok", f"ap:{ID_AP.upper()}:ok",
    f" ap:{ID_AP}:ok", f"ap:{ID_AP}:ok\n", "", "ap:" + "f" * 500 + ":ok"])
def test_callback_data_forge_ignore(monkeypatch, data):
    faux, coeur = _installer(monkeypatch)
    _approbateur("cb-forge")
    r = _run(pont.traiter_callback("faux", _cb("cb-forge", data=data)))
    assert r["raison"] == "ignore"
    assert coeur.appels == [] and faux.reponses_cb == []


def test_callback_reseau_inconnu_ignore(monkeypatch):
    coeur = _Coeur(monkeypatch)
    r = _run(pont.traiter_callback("n-existe-pas", _cb("x")))
    assert r["raison"] == "ignore" and coeur.appels == []


# 5
def test_callback_ok_reversible_decide_et_edite(monkeypatch):
    faux, coeur = _installer(monkeypatch, decision={"ok": True, "raison": "ok"})
    _approbateur("cb-5")
    r = _run(pont.traiter_callback("faux", _cb("cb-5")))
    assert r["ok"] is True
    assert coeur.decisions == [(ID_AP, "ok", "faux:cb-5")]
    assert coeur.armements == []
    assert faux.reponses_cb and faux.reponses_cb[0][0] == "cbid"
    assert faux.editions and faux.editions[0][:2] == ("cb-5", 7)
    assert "approuv" in faux.editions[0][2].lower()


# 6
def test_callback_ko_decide_refus(monkeypatch):
    faux, coeur = _installer(monkeypatch, decision={"ok": True, "raison": "ok"})
    _approbateur("cb-6")
    r = _run(pont.traiter_callback("faux", _cb("cb-6", data=f"ap:{ID_AP}:ko")))
    assert r["ok"] is True
    assert coeur.decisions == [(ID_AP, "ko", "faux:cb-6")]
    assert coeur.armements == []
    assert "refus" in faux.editions[0][2].lower()


# 7
def test_callback_destructif_arme_le_code_sans_jamais_l_afficher(monkeypatch):
    faux, coeur = _installer(monkeypatch, decision={"ok": False, "raison": "code_requis"},
                             armer={"ok": True, "code": "654321"})   # même si le Cœur en rendait un
    _approbateur("cb-7")
    r = _run(pont.traiter_callback("faux", _cb("cb-7")))
    assert r["raison"] == "code_demande"
    assert coeur.armements == [(ID_AP, "faux:cb-7")]
    assert len(faux.envoyes) == 1 and faux.envoyes[0][0] == "cb-7"
    texte = faux.envoyes[0][1]
    assert "app" in texte.lower() and "6 chiffres" in texte
    assert not re.search(r"\d{6}", texte)
    assert "654321" not in texte and not any("654321" in str(x) for x in faux.reponses_cb)


def test_callback_ko_destructif_n_arme_pas(monkeypatch):
    """Un refus ne déclenche jamais l'armement d'une saisie de code."""
    faux, coeur = _installer(monkeypatch, decision={"ok": True, "raison": "ok"})
    _approbateur("cb-7b")
    _run(pont.traiter_callback("faux", _cb("cb-7b", data=f"ap:{ID_AP}:ko")))
    assert coeur.armements == []


def test_callback_armement_refuse_n_annonce_pas_de_saisie(monkeypatch):
    faux, coeur = _installer(monkeypatch, decision={"ok": False, "raison": "code_requis"},
                             armer={"ok": False, "raison": "expiree"})
    _approbateur("cb-7c")
    _run(pont.traiter_callback("faux", _cb("cb-7c")))
    assert faux.envoyes == []
    assert faux.reponses_cb and "expir" in faux.reponses_cb[0][1].lower()


# 8
@pytest.mark.parametrize("raison,mot", [("expiree", "expir"), ("deja_decidee", "trait")])
def test_callback_expiree_ou_deja_decidee_edite_sans_executer(monkeypatch, raison, mot):
    faux, coeur = _installer(monkeypatch, decision={"ok": False, "raison": raison})
    _approbateur("cb-8")
    r = _run(pont.traiter_callback("faux", _cb("cb-8")))
    assert r == {"ok": False, "raison": raison}
    assert coeur.armements == []
    assert faux.editions and mot in faux.editions[0][2].lower()
    assert faux.envoyes == []


def test_callback_coeur_injoignable_repli_honnete(monkeypatch):
    faux, coeur = _installer(monkeypatch)

    async def boom(*a, **k):
        raise httpx.ConnectError("coeur KO")

    monkeypatch.setattr(client_assistant, "decider_approbation", boom)
    _approbateur("cb-9")
    r = _run(pont.traiter_callback("faux", _cb("cb-9")))
    assert r == {"ok": False, "raison": "noyau_injoignable"}
    assert faux.reponses_cb and "indisponible" in faux.reponses_cb[0][1].lower()
    assert faux.editions == []                       # rien n'est présenté comme décidé


# ── saisie du code à 6 chiffres ──────────────────────────────────────────────────────
def _brancher_code(monkeypatch, code=None, **kw):
    faux = FauxApprob()
    monkeypatch.setitem(A.REGISTRE, "faux", faux)
    coeur = _Coeur(monkeypatch, code=code, **kw)
    appels = []

    async def converser(messages, **_):
        appels.append(messages)
        return "réponse assistant"

    monkeypatch.setattr(client_assistant, "converser", converser)
    return faux, coeur, appels


# 9
@pytest.mark.parametrize("retour,attendu", [
    ({"pris_en_charge": True, "ok": True, "raison": "ok"}, "Code bon"),
    ({"pris_en_charge": True, "ok": False, "raison": "code_faux", "restants": 2},
     "2 essai"),
    ({"pris_en_charge": True, "ok": False, "raison": "essais_epuises", "restants": 0},
     "REFUSÉE"),
    ({"pris_en_charge": True, "ok": False, "raison": "expiree"}, "expir"),
])
def test_code_d_un_approbateur_arme_n_est_pas_relaye(monkeypatch, retour, attendu):
    faux, coeur, appels = _brancher_code(monkeypatch, code=retour)
    _approbateur("code-9")
    r = _run(pont.traiter("faux", A.Entrant("faux", "code-9", "123456", "G")))
    assert r["ok"] is True
    assert appels == []                              # JAMAIS relayé au LLM
    assert coeur.codes == [("faux:code-9", "123456")]
    assert len(faux.envoyes) == 1 and attendu in faux.envoyes[0][1]
    assert "123456" not in faux.envoyes[0][1]
    assert C.charger("faux", "code-9") == []         # le code n'entre pas dans l'historique


# 10 (révisé revue finale) : approbateur + 6 chiffres sans saisie armée => JAMAIS relayé
def test_code_sans_saisie_armee_d_un_approbateur_n_est_jamais_relaye(monkeypatch):
    faux, coeur, appels = _brancher_code(monkeypatch, code={"pris_en_charge": False})
    _approbateur("code-10")
    r = _run(pont.traiter("faux", A.Entrant("faux", "code-10", "123456", "G")))
    assert r["ok"] is True and r.get("reponse") is None
    assert appels == []                              # rien dans converser
    assert coeur.codes == [("faux:code-10", "123456")]
    assert len(faux.envoyes) == 1
    assert "Aucune saisie de code en cours" in faux.envoyes[0][1]
    assert "123456" not in faux.envoyes[0][1]
    assert C.charger("faux", "code-10") == []        # jamais dans l'historique


def test_code_prerequis_non_reunis_message_honnete(monkeypatch):
    faux, coeur, appels = _brancher_code(
        monkeypatch, code={"pris_en_charge": True, "ok": False, "raison": "prerequis"})
    _approbateur("code-pre")
    _run(pont.traiter("faux", A.Entrant("faux", "code-pre", "123456", "G")))
    assert appels == []
    assert "Pas encore prête : sauvegarde non vérifiée" in faux.envoyes[0][1]
    assert "123456" not in faux.envoyes[0][1]


def test_non_approbateur_six_chiffres_reste_relaye(monkeypatch):
    faux, coeur, appels = _brancher_code(monkeypatch, code={"pris_en_charge": False})
    K.lier("faux", "code-10b", "u@wp")
    r = _run(pont.traiter("faux", A.Entrant("faux", "code-10b", "123456", "G")))
    assert r["reponse"] == "réponse assistant" and len(appels) == 1 and coeur.codes == []


# 11
def test_code_d_un_non_approbateur_est_relaye_et_jamais_soumis(monkeypatch):
    faux, coeur, appels = _brancher_code(monkeypatch, code={"pris_en_charge": True, "ok": True,
                                                            "raison": "ok"})
    K.lier("faux", "code-11", "u@wp")                # lié, pas approbateur
    r = _run(pont.traiter("faux", A.Entrant("faux", "code-11", "123456", "G")))
    assert r["ok"] is True and len(appels) == 1
    assert coeur.codes == []


@pytest.mark.parametrize("texte", ["12345", "1234567", "12345a", "123 456", "ma carte 123456",
                                   "١٢٣٤٥٦", "123456\n123456"])
def test_texte_qui_n_est_pas_exactement_six_chiffres_n_appelle_pas_le_coeur(monkeypatch, texte):
    faux, coeur, appels = _brancher_code(monkeypatch)
    _approbateur("code-fmt")
    _run(pont.traiter("faux", A.Entrant("faux", "code-fmt", texte, "G")))
    assert coeur.codes == [] and len(appels) == 1


def test_code_approbateur_coeur_en_erreur_ne_part_jamais_au_llm(monkeypatch):
    faux, coeur, appels = _brancher_code(monkeypatch, code=httpx.ConnectError("KO"))
    _approbateur("code-err")
    r = _run(pont.traiter("faux", A.Entrant("faux", "code-err", "123456", "G")))
    assert appels == []                              # les chiffres pourraient être un code
    assert r["ok"] is False
    assert len(faux.envoyes) == 1 and "indisponible" in faux.envoyes[0][1].lower()
    assert "123456" not in faux.envoyes[0][1]
    assert C.charger("faux", "code-err") == []


def test_code_non_autorise_ne_declenche_pas_le_coeur(monkeypatch):
    faux, coeur, appels = _brancher_code(monkeypatch)
    r = _run(pont.traiter("faux", A.Entrant("faux", "code-inconnu", "123456", "G")))
    assert r["raison"] == "non_autorise" and coeur.codes == [] and appels == []


# ── sonder : dispatch par type ─────────────────────────────────────────────────────────
def test_sonder_dispatche_callback_et_message(monkeypatch):
    class _Sonde(FauxApprob):
        async def recuperer(self):
            return [A.Entrant("faux", "sd-1", "salut", "G"), _cb("sd-2")]

    faux = _Sonde()
    monkeypatch.setitem(A.REGISTRE, "faux", faux)
    vus = {"cb": [], "msg": []}

    async def faux_cb(reseau, cb):
        vus["cb"].append(cb.from_id)
        return {"ok": True, "raison": "ok"}

    async def faux_traiter(reseau, e, **k):
        vus["msg"].append(e.id_externe)
        return {"ok": True}

    monkeypatch.setattr(pont, "traiter_callback", faux_cb)
    monkeypatch.setattr(pont, "traiter", faux_traiter)
    r = _run(pont.sonder("faux"))
    assert vus == {"cb": ["sd-2"], "msg": ["sd-1"]}
    assert r["traites"] == 2 and r["autorises"] == 2


# ── S245 (revue) : source non authentifiée, Telegram isolé, journal ───────────────────
def test_code_d_un_approbateur_via_source_non_authentifiee_est_ignore(monkeypatch):
    faux, coeur, appels = _brancher_code(monkeypatch, code={"pris_en_charge": True, "ok": True,
                                                            "raison": "ok"})
    _approbateur("code-na")
    r = _run(pont.traiter("faux", A.Entrant("faux", "code-na", "123456", "G"),
                          source_authentifiee=False))
    assert coeur.codes == [] and appels == [] and faux.envoyes == []
    assert r["ok"] is True


def test_code_d_un_non_approbateur_via_source_non_authentifiee_reste_ordinaire(monkeypatch):
    faux, coeur, appels = _brancher_code(monkeypatch)
    K.lier("faux", "code-na2", "u@wp")
    r = _run(pont.traiter("faux", A.Entrant("faux", "code-na2", "123456", "G"),
                          source_authentifiee=False))
    assert coeur.codes == [] and len(appels) == 1 and r["reponse"] == "réponse assistant"


def test_message_ordinaire_d_un_approbateur_via_source_non_authentifiee_est_relaye(monkeypatch):
    faux, coeur, appels = _brancher_code(monkeypatch)
    _approbateur("code-na3")
    _run(pont.traiter("faux", A.Entrant("faux", "code-na3", "bonjour", "G"),
                      source_authentifiee=False))
    assert len(appels) == 1


@pytest.mark.parametrize("casse", ["repondre_callback", "envoyer", "editer_message"])
def test_callback_telegram_en_panne_apres_decision_garde_le_verdict(monkeypatch, casse):
    faux, coeur = _installer(monkeypatch, decision={"ok": True, "raison": "ok"})

    async def panne(*a, **k):
        raise httpx.ConnectError("telegram KO")

    monkeypatch.setattr(faux, casse, panne)
    _approbateur("cb-tgko")
    r = _run(pont.traiter_callback("faux", _cb("cb-tgko")))
    assert r == {"ok": True, "raison": "ok"}
    assert coeur.decisions == [(ID_AP, "ok", "faux:cb-tgko")]


def test_callback_armement_telegram_en_panne_garde_code_demande(monkeypatch):
    faux, coeur = _installer(monkeypatch, decision={"ok": False, "raison": "code_requis"})

    async def panne(*a, **k):
        raise httpx.ConnectError("telegram KO")

    monkeypatch.setattr(faux, "envoyer", panne)
    monkeypatch.setattr(faux, "repondre_callback", panne)
    _approbateur("cb-tgko2")
    r = _run(pont.traiter_callback("faux", _cb("cb-tgko2")))
    assert r == {"ok": True, "raison": "code_demande"}


def test_code_coeur_en_erreur_journalise_sans_les_chiffres(monkeypatch, caplog):
    faux, coeur, appels = _brancher_code(monkeypatch, code=httpx.ConnectError("KO"))
    _approbateur("code-log")
    with caplog.at_level(logging.WARNING):
        _run(pont.traiter("faux", A.Entrant("faux", "code-log", "123456", "G")))
    assert any(r.levelno == logging.WARNING for r in caplog.records)
    assert "123456" not in caplog.text
