"""Tests de envoi_mail (S199) : appel à la brique Mail (mail_composer + brouillon/envoyer),
motif de digest.py::_pousser_memoire. httpx est mocké, aucun réseau réel."""
import httpx
import pytest

import envoi_mail


class _FausseReponse:
    def __init__(self, json_data, status_code=200):
        self._json = json_data
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("erreur", request=None, response=self)

    def json(self):
        return self._json


def test_envoyer_compose_puis_envoie_le_brouillon(monkeypatch):
    appels = []

    def _faux_post(url, json=None, headers=None, timeout=None):
        appels.append((url, json, headers))
        if url.endswith("/mail/composer"):
            return _FausseReponse({"ok": True, "brouillon": {"id": "brouillon-1"}})
        if url.endswith("/brouillons/brouillon-1/envoyer"):
            return _FausseReponse({"ok": True, "mode": "reel"})
        raise AssertionError(f"URL inattendue : {url}")

    monkeypatch.setattr(envoi_mail.httpx, "post", _faux_post)

    envoi_mail.envoyer("perso:alice", "equipe@example.com",
                       "https://veille-info.example/audio-global/jeton-x.mp3",
                       "Veille du jour", "Bonne écoute")

    assert len(appels) == 2
    url_compose, body_compose, entetes = appels[0]
    assert url_compose.endswith("/mail/composer")
    assert body_compose["a"] == "equipe@example.com"
    assert "https://veille-info.example/audio-global/jeton-x.mp3" in body_compose["dictee"]
    assert body_compose["sujet"] == "Veille du jour"
    assert entetes["X-User-Id"] == "alice"  # préfixe perso: retiré (motif _pousser_memoire)


def test_envoyer_sujet_et_message_par_defaut(monkeypatch):
    appels = []

    def _faux_post(url, json=None, headers=None, timeout=None):
        appels.append((url, json))
        if url.endswith("/mail/composer"):
            return _FausseReponse({"ok": True, "brouillon": {"id": "brouillon-2"}})
        return _FausseReponse({"ok": True})

    monkeypatch.setattr(envoi_mail.httpx, "post", _faux_post)

    envoi_mail.envoyer("perso:bob", "solo@example.com", "https://x.example/a.mp3", None, None)

    body_compose = appels[0][1]
    assert body_compose["sujet"] == "Veille audio"
    assert "Voici la veille audio du jour." in body_compose["dictee"]


def test_envoyer_echec_reseau_leve_erreur_explicite(monkeypatch):
    def _faux_post(url, json=None, headers=None, timeout=None):
        raise httpx.ConnectError("injoignable", request=None)

    monkeypatch.setattr(envoi_mail.httpx, "post", _faux_post)

    with pytest.raises(envoi_mail.EnvoiAudioGlobalError):
        envoi_mail.envoyer("perso:carol", "x@example.com", "https://x.example/a.mp3", None, None)


def test_envoyer_reponse_malformee_leve_erreur_explicite(monkeypatch):
    """Réponse 200 mais corps sans la clé brouillon/id attendue : ne doit PAS laisser
    fuiter un KeyError brut, doit être convertie en EnvoiAudioGlobalError (S199 finding)."""
    def _faux_post(url, json=None, headers=None, timeout=None):
        if url.endswith("/mail/composer"):
            return _FausseReponse({"ok": True})
        raise AssertionError(f"URL inattendue : {url}")

    monkeypatch.setattr(envoi_mail.httpx, "post", _faux_post)

    with pytest.raises(envoi_mail.EnvoiAudioGlobalError):
        envoi_mail.envoyer("perso:dave", "x@example.com", "https://x.example/a.mp3", None, None)
