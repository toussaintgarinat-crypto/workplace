"""Filet de retry sur le jeton de service Keycloak (même motif que briques/memoire et
briques/forge, bug constaté en prod le 2026-07-23) : si Oria répond 401 sur le jeton
mémoïsé (révoqué avant sa péremption annoncée), on invalide le cache et on réessaie UNE
fois avec un jeton frais avant d'abandonner.

Aucun réseau : `httpx.request`/`httpx.post` sont monkeypatchés.
"""
import main


class _FauxReponse:
    def __init__(self, status, corps=None, texte=""):
        self.status_code = status
        self._corps = corps or {}
        self.text = texte

    def json(self):
        return self._corps


def _reset_cache():
    main._token_cache["access_token"] = ""
    main._token_cache["expires_at"] = 0.0


def _mock_login(monkeypatch, jetons):
    """`httpx.post` (login Keycloak) renvoie les jetons de `jetons` dans l'ordre, un par
    appel."""
    sequence = list(jetons)

    def faux_post(url, data=None, timeout=None):
        nom = sequence.pop(0)
        return _FauxReponse(200, {"access_token": nom, "expires_in": 300})

    monkeypatch.setattr(main.httpx, "post", faux_post)


def test_oria_reessaie_une_fois_si_jeton_expire(monkeypatch):
    _reset_cache()
    _mock_login(monkeypatch, ["TOKEN-1", "TOKEN-2"])

    reponses = [_FauxReponse(401, texte="Invalid token"), _FauxReponse(200, {"worlds": []})]
    entetes_vus = []

    def faux_request(method, url, headers=None, timeout=None, **kw):
        entetes_vus.append(headers["Authorization"])
        return reponses.pop(0)

    monkeypatch.setattr(main.httpx, "request", faux_request)

    corps = main._oria("GET", "/worlds/")
    assert corps == {"worlds": []}
    assert entetes_vus == ["Bearer TOKEN-1", "Bearer TOKEN-2"]


def test_oria_abandonne_si_le_jeton_frais_echoue_aussi(monkeypatch):
    _reset_cache()
    _mock_login(monkeypatch, ["TOKEN-1", "TOKEN-2"])

    appels = {"n": 0}

    def faux_request(method, url, headers=None, timeout=None, **kw):
        appels["n"] += 1
        return _FauxReponse(401, texte="Invalid token")

    monkeypatch.setattr(main.httpx, "request", faux_request)

    try:
        main._oria("GET", "/worlds/")
        assert False, "devait lever HTTPException"
    except main.HTTPException as e:
        assert e.status_code == 401
    assert appels["n"] == 2  # un seul réessai, pas de boucle


def test_oria_ne_reessaie_pas_sur_une_autre_erreur(monkeypatch):
    """Un 500 (ou toute erreur ≠ 401) n'est pas un problème de jeton — pas de réessai."""
    _reset_cache()
    _mock_login(monkeypatch, ["TOKEN-1"])

    appels = {"n": 0}

    def faux_request(method, url, headers=None, timeout=None, **kw):
        appels["n"] += 1
        return _FauxReponse(500, texte="erreur interne")

    monkeypatch.setattr(main.httpx, "request", faux_request)

    try:
        main._oria("GET", "/worlds/")
        assert False, "devait lever HTTPException"
    except main.HTTPException as e:
        assert e.status_code == 500
    assert appels["n"] == 1
