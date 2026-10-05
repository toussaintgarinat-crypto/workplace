"""S239 (revue I3) — journal honnête quand la Gateway sert la Forge via un repli.

`forge/defaut` (Mistral) se replie CÔTÉ GATEWAY sur `gratuit/auto` / `gratuit/secours` :
la Forge reçoit un 200 et, sans ce correctif, journalisait « forge/defaut » pour une
réponse venue d'un gratuit Kilo. LiteLLM le signale par les en-têtes
`x-litellm-attempted-fallbacks` et `x-litellm-model-group` (constaté sur v1.86.2 :
`x-litellm-model-group: gratuit/secours`, `x-litellm-attempted-fallbacks: 1`).
"""

import uuid
from types import SimpleNamespace

from app import react_executor
from app.llm import modele_servi

ENTETES_REPLI = {"x-litellm-attempted-fallbacks": "1", "x-litellm-model-group": "gratuit/secours"}


def test_modele_servi_sans_repli():
    assert modele_servi("forge/defaut", {"x-litellm-attempted-fallbacks": "0",
                                         "x-litellm-model-group": "forge/defaut"},
                        "mistral-small-latest") == ("forge/defaut", False)
    assert modele_servi("forge/defaut", {}, None) == ("forge/defaut", False)


def test_modele_servi_avec_repli():
    assert modele_servi("forge/defaut", ENTETES_REPLI, "liquid/lfm:free") == ("gratuit/secours", True)
    # Sans en-tête de groupe, on se rabat sur le modèle annoncé par la réponse.
    assert modele_servi("forge/defaut", {"x-litellm-attempted-fallbacks": "2"},
                        "liquid/lfm:free") == ("liquid/lfm:free", True)


# ── run_react de bout en bout, avec des doubles (pas de DB, pas de Gateway) ─────────────

class _Session:
    ajouts: list = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def add(self, obj):
        _Session.ajouts.append(obj)

    async def commit(self):
        pass

    async def rollback(self):
        pass

    async def refresh(self, obj):
        obj.id = uuid.uuid4()

    async def execute(self, *a, **k):
        pass


class _Brut:
    def __init__(self, entetes):
        self.headers = entetes

    def parse(self):
        msg = SimpleNamespace(content="pong", tool_calls=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)], model="liquid/lfm:free",
                               usage=SimpleNamespace(prompt_tokens=3, completion_tokens=1))


def _client_double(entetes):
    async def create(**k):
        return _Brut(entetes)
    brut = SimpleNamespace(create=create)
    return lambda: SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
        with_raw_response=brut)))


def _preparer(monkeypatch, entetes):
    _Session.ajouts = []
    monkeypatch.setattr(react_executor, "SessionLocal", _Session)
    monkeypatch.setattr(react_executor, "_client", _client_double(entetes))

    async def sans_rag(*a, **k):
        return ""
    monkeypatch.setattr(react_executor, "get_context", sans_rag)
    monkeypatch.setattr("app.config.settings.DEFAULT_LLM_PROVIDER", "gateway")
    monkeypatch.setattr("app.config.settings.DEFAULT_LLM_MODEL", "forge/defaut")
    monkeypatch.setattr("app.config.settings.FALLBACK_LLM_CHAIN", "")


def _usage():
    from app.models import GovernorUsage
    return [o for o in _Session.ajouts if isinstance(o, GovernorUsage)]


async def test_run_react_journalise_le_modele_du_repli(monkeypatch):
    _preparer(monkeypatch, ENTETES_REPLI)
    r = await react_executor.run_react("ping", session_id="s", user_id="u")
    assert r.answer == "pong"
    assert r.actualModel == "gratuit/secours" and r.actualProvider == "gateway"
    (u,) = _usage()
    assert (u.provider, u.model) == ("gateway", "gratuit/secours")


async def test_run_react_sans_repli_inchange(monkeypatch):
    _preparer(monkeypatch, {"x-litellm-attempted-fallbacks": "0",
                            "x-litellm-model-group": "forge/defaut"})
    r = await react_executor.run_react("ping", session_id="s", user_id="u")
    assert r.actualModel is None and r.actualProvider is None
    (u,) = _usage()
    assert u.model == "forge/defaut"
