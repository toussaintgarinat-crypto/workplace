"""S239 T4 — OpenCode Go exige un `x-opencode-session` stable PAR CONVERSATION.

Sans lui, Go répond 400 « missing x-opencode-session » (constaté le 2026-10-05). L'en-tête
part du Cœur (seul à connaître la conversation) et la Gateway le relaie à l'amont pour les
seuls `go/*` (`model_group_settings.forward_client_headers_to_llm_api`).

Verrouillé ici :
  1. l'en-tête n'est envoyé QUE pour `go/*` — ni Kilo, ni Mistral n'ont à le recevoir ;
  2. il est stable pour une même conversation (`fil`) et différent d'une conversation à
     l'autre ;
  3. il ne contient rien de personnel : le `fil` du Cœur embarque l'identité de la personne
     (`accord_action.cle`), on n'en envoie qu'une empreinte à clé ;
  4. sans `fil`, une valeur est quand même envoyée (sinon 400), stable le temps de l'appel ;
  5. même comportement en streaming.
"""
import asyncio
import os
import sys
import tempfile

_tmp = tempfile.mkdtemp()
os.environ.setdefault("USAGE_LLM_PATH", os.path.join(_tmp, "usage.jsonl"))
os.environ.setdefault("MODELE_JOURNAL_PATH", os.path.join(_tmp, "modele.jsonl"))
os.environ.setdefault("GATEWAY_KEY", "sk-test-local")
sys.path.insert(0, os.path.dirname(__file__))

import llm_pipeline  # noqa: E402

FIL = "web:dashboard\x00alice@example.org"


class _Resp:
    def __init__(self, statut=200):
        self.status_code = statut
        self.headers = {}

    def json(self):
        return {"choices": [{"message": {"content": "pong", "tool_calls": None}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1}}


class _Client:
    """Enregistre les en-têtes de chaque appel ; échoue (500) sur les modèles de `echecs`."""

    def __init__(self, echecs=()):
        self.appels = []          # [(modele, entetes)]
        self._echecs = set(echecs)

    async def post(self, url, *, headers=None, json=None, **k):
        self.appels.append((json["model"], dict(headers or {})))
        return _Resp(500 if json["model"] in self._echecs else 200)

    def stream(self, methode, url, *, headers=None, json=None, **k):
        self.appels.append((json["model"], dict(headers or {})))
        return _Flux()

    async def aclose(self):
        pass


class _Flux:
    status_code = 200

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def aiter_lines(self):
        yield 'data: {"choices":[{"delta":{"content":"pong"}}]}'
        yield "data: [DONE]"


def _completer(modeles, fil=FIL, echecs=()):
    client = _Client(echecs)
    asyncio.run(llm_pipeline.completer([{"role": "user", "content": "ping"}],
                                       modeles=modeles, fil=fil, client=client))
    return client.appels


def _session(entetes):
    return {k.lower(): v for k, v in entetes.items()}.get("x-opencode-session")


def test_en_tete_uniquement_pour_go():
    appels = _completer(["mistral/small", "kilo/a/b", "go/deepseek-v4-pro"],
                        echecs={"mistral/small", "kilo/a/b"})
    par_modele = {m: _session(h) for m, h in appels}
    assert par_modele["mistral/small"] is None
    assert par_modele["kilo/a/b"] is None
    assert par_modele["go/deepseek-v4-pro"]


def test_stable_par_conversation_et_distinct_entre_conversations():
    a1 = _session(_completer(["go/glm-5"], fil=FIL)[0][1])
    a2 = _session(_completer(["go/glm-5"], fil=FIL)[0][1])
    b = _session(_completer(["go/glm-5"], fil="telegram:42\x00bob")[0][1])
    assert a1 == a2
    assert a1 != b


def test_aucune_donnee_personnelle():
    s = _session(_completer(["go/glm-5"], fil=FIL)[0][1])
    assert "alice" not in s and "dashboard" not in s and "@" not in s
    assert len(s) <= 64


def test_sans_fil_une_session_est_quand_meme_envoyee():
    appels = _completer(["go/glm-5", "go/kimi-k2.6"], fil=None, echecs={"go/glm-5"})
    s1, s2 = _session(appels[0][1]), _session(appels[1][1])
    assert s1 and s1 == s2, "stable le temps de l'appel, même après bascule de modèle"


def test_l_autorisation_gateway_est_conservee():
    _, h = _completer(["go/glm-5"])[0]
    assert h["Authorization"] == f"Bearer {llm_pipeline.GATEWAY_KEY}"


def test_streaming_meme_regle():
    async def tourner(modele):
        client = _Client()
        async for _ in llm_pipeline.completer_flux([{"role": "user", "content": "ping"}],
                                                   modeles=[modele], fil=FIL, client=client):
            pass
        return client.appels[0][1]
    assert _session(asyncio.run(tourner("go/glm-5")))
    assert _session(asyncio.run(tourner("mistral/small"))) is None
