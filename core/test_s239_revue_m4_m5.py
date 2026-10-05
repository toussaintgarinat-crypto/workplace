"""S239, revue M4 + M5 — en-tête Go hors pipeline, fil de secours, alias réservés à la Forge.

M4 : `moa.py` appelle la Gateway SANS passer par `llm_pipeline` ; un modèle de référence
     `go/*` (MOA_MODELES) y recevait donc un 400 « missing x-opencode-session ». Et le fil
     de secours de `converser` valait `sans-fil:{id(messages)}` : une adresse mémoire, que
     Python RÉUTILISE après ramasse-miettes — deux appels sans fil pouvaient partager une
     clé du registre d'accords (et la même session Go).
M5 : `forge/defaut` et `gratuit/*` sont des alias Gateway à repli CACHÉ (réservés à la
     Forge) : choisis comme tête du Cœur, ils feraient journaliser un modèle qui n'a pas
     répondu. Ils ne sont donc pas proposés dans ⚙ Cerveau ni dans la cascade.
"""
import asyncio
import os
import re
import sys
import tempfile

os.environ["ASSISTANT_CONFIG_PATH"] = os.path.join(tempfile.mkdtemp(), "cfg.json")
os.environ.setdefault("GATEWAY_KEY", "sk-test-local")
os.environ["STREAM_ACTIF"] = "1"
os.environ.setdefault("MODELE_JOURNAL_PATH", os.path.join(tempfile.mkdtemp(), "modele.jsonl"))
sys.path.insert(0, os.path.dirname(__file__))

import assistant  # noqa: E402
import config_assistant as C  # noqa: E402
import llm_pipeline  # noqa: E402
import moa  # noqa: E402


# ── M4 : moa ───────────────────────────────────────────────────────────────────────────

class _Client:
    def __init__(self):
        self.appels = []

    async def post(self, url, *, json=None, headers=None, **k):
        self.appels.append((json["model"], {k_.lower(): v for k_, v in (headers or {}).items()}))
        return _Resp()


class _Resp:
    def raise_for_status(self):
        pass

    def json(self):
        return {"choices": [{"message": {"content": "avis"}}]}


def _config(refs, agregateur):
    return moa.ConfigMOA(modeles_reference=refs, agregateur=agregateur)


def test_moa_envoie_la_session_go_aux_seuls_go():
    moa._cache_guidance.clear()
    client = _Client()
    asyncio.run(moa.consulter([{"role": "user", "content": "question moa go"}],
                              _config(["go/glm-5", "mistral/small"], "go/kimi-k2.6"),
                              client, fil="web:dashboard\x00alice"))
    par_modele = {m: h.get("x-opencode-session") for m, h in client.appels}
    attendu = llm_pipeline.session_opencode("web:dashboard\x00alice")
    assert par_modele["go/glm-5"] == attendu
    assert par_modele["go/kimi-k2.6"] == attendu
    assert par_modele["mistral/small"] is None


# ── M4 : fil de secours de converser ─────────────────────────────────────────────────

def _fil_vu_par_le_pipeline():
    vus = []

    async def faux_flux(*a, fil=None, **k):
        vus.append(fil)
        yield {"type": "fin", "message": {"role": "assistant", "content": "ok"}, "resultat": None}

    ancien = llm_pipeline.completer_flux
    llm_pipeline.completer_flux = faux_flux
    try:
        async def tour():
            return [e async for e in assistant.converser(
                [{"role": "user", "content": "salut"}], registre=None)]
        asyncio.run(tour())
        asyncio.run(tour())
    finally:
        llm_pipeline.completer_flux = ancien
    return vus


def test_fil_de_secours_ne_depend_pas_d_une_adresse_memoire():
    f1, f2 = _fil_vu_par_le_pipeline()
    assert re.fullmatch(r"sans-fil:[0-9a-f]{32}", f1), f1
    assert f1 != f2, "deux appels sans fil ne doivent jamais partager de clé"


# ── M5 : alias réservés à la Forge ───────────────────────────────────────────────────

class _RespModeles:
    def raise_for_status(self):
        pass

    def json(self):
        return {"data": [{"id": i} for i in ("mistral/small", "forge/defaut", "gratuit/auto",
                                              "gratuit/secours", "kilo/a/b", "free/c/d")]}


class _ClientModeles:
    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, *a, **k):
        return _RespModeles()


def test_lister_modeles_exclut_les_alias_forge(monkeypatch):
    monkeypatch.setattr(C.httpx, "AsyncClient", _ClientModeles)
    dispo = asyncio.run(C.lister_modeles())
    assert dispo == ["mistral/small", "kilo/a/b", "free/c/d"]
