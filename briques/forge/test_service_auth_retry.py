"""Filet de retry sur le jeton de service Keycloak (même motif que briques/memoire,
bug constaté en prod le 2026-07-23) : si Core Forge répond 401 sur le jeton de service
mémoïsé (révoqué avant sa péremption annoncée — secret changé, client désactivé), on
invalide le cache et on réessaie UNE fois avec un jeton frais avant d'abandonner. Un 401
sur un jeton UTILISATEUR n'est jamais retenté (Forge ne peut pas en fabriquer un meilleur).

Aucun réseau : `client.request` et `_auth` sont de faux objets.
"""
import asyncio

import main


class _FakeResponse:
    def __init__(self, status):
        self.status_code = status


class _FakeClientSequence:
    """Renvoie les réponses de `sequence` dans l'ordre, une par appel `.request()`."""
    def __init__(self, sequence):
        self._sequence = list(sequence)
        self.appels = 0

    async def request(self, methode, url, headers=None, **kw):
        self.appels += 1
        return self._sequence.pop(0)


def test_appel_protege_reessaie_une_fois_si_jeton_service_expire():
    main._JETON_UTILISATEUR.set(None)

    class _AuthSequence:
        configure = True

        def __init__(self):
            self.appels_token = 0
            self.invalide = False

        async def token(self, client):
            self.appels_token += 1
            return f"TOKEN-{self.appels_token}"

        def invalider(self):
            self.invalide = True

    auth = _AuthSequence()
    orig_auth = main._auth
    main._auth = auth
    try:
        client = _FakeClientSequence([_FakeResponse(401), _FakeResponse(200)])
        r = asyncio.run(main._appel_protege(client, "GET", "/api/agents"))
    finally:
        main._auth = orig_auth

    assert r.status_code == 200
    assert client.appels == 2
    assert auth.appels_token == 2
    assert auth.invalide is True


def test_appel_protege_abandonne_si_le_jeton_frais_echoue_aussi():
    main._JETON_UTILISATEUR.set(None)

    class _AuthOK:
        configure = True

        async def token(self, client):
            return "TOKEN"

        def invalider(self):
            pass

    orig_auth = main._auth
    main._auth = _AuthOK()
    try:
        client = _FakeClientSequence([_FakeResponse(401), _FakeResponse(401)])
        r = asyncio.run(main._appel_protege(client, "GET", "/api/agents"))
    finally:
        main._auth = orig_auth

    assert r.status_code == 401
    assert client.appels == 2  # un seul réessai, pas de boucle


def test_appel_protege_ne_reessaie_pas_si_cest_le_jeton_utilisateur_qui_echoue():
    jeton = main._JETON_UTILISATEUR.set("USER-JWT")

    class _AuthExplose:
        configure = True

        async def token(self, client):
            raise AssertionError("le token de service ne doit pas être sollicité")

        def invalider(self):
            raise AssertionError("le cache de service ne doit pas être invalidé")

    orig_auth = main._auth
    main._auth = _AuthExplose()
    try:
        client = _FakeClientSequence([_FakeResponse(401)])
        r = asyncio.run(main._appel_protege(client, "GET", "/api/agents"))
    finally:
        main._auth = orig_auth
        main._JETON_UTILISATEUR.reset(jeton)

    assert r.status_code == 401
    assert client.appels == 1
