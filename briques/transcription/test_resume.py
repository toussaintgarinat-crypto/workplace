"""Tests de la synthèse : repli heuristique honnête, parsing JSON, chemin LLM (mock)."""
import asyncio

import prompts
import resume


def _run(coro):
    return asyncio.run(coro)


# ── prompts (pur) ────────────────────────────────────────────────
def test_consigne_langue():
    assert prompts.consigne_langue("es") == "en español"
    assert prompts.consigne_langue(None) == "en français"
    assert prompts.consigne_langue("zz") == "en français"      # repli fr


def test_repli_heuristique_premieres_phrases():
    txt = "Première phrase. Deuxième phrase. Troisième phrase. Quatrième de trop."
    out = prompts.repli_heuristique(txt)
    assert out["source"] == "heuristique"
    assert "Première phrase." in out["resume"]
    assert "Quatrième" not in out["resume"]                    # plafonné à 3 phrases
    assert out["points_action"] == [] and out["decisions"] == []


# ── parsing JSON tolérant ────────────────────────────────────────
def test_extraire_json_brut():
    assert resume._extraire_json('{"resume": "ok"}') == {"resume": "ok"}


def test_extraire_json_avec_fences():
    contenu = 'Voici :\n```json\n{"resume": "ok", "themes": ["a"]}\n```'
    assert resume._extraire_json(contenu) == {"resume": "ok", "themes": ["a"]}


def test_extraire_json_illisible():
    assert resume._extraire_json("pas du tout du json") is None


def test_normaliser_force_la_forme():
    out = resume._normaliser({"resume": " r ", "points_action": "tâche unique",
                              "themes": ["x", "", "y"]})
    assert out["resume"] == "r"
    assert out["points_action"] == ["tâche unique"]            # str → liste
    assert out["themes"] == ["x", "y"]                          # vides filtrés
    assert out["decisions"] == [] and out["source"] == "llm"


# ── resumer (async) ──────────────────────────────────────────────
def test_resumer_texte_vide():
    out = _run(resume.resumer(""))
    assert out["source"] == "vide"


def test_resumer_sans_gateway_repli_heuristique(monkeypatch):
    monkeypatch.delenv("GATEWAY_KEY", raising=False)
    out = _run(resume.resumer("Une réunion s'est tenue. On a parlé du budget."))
    assert out["source"] == "heuristique"


def test_resumer_avec_gateway_mock(monkeypatch):
    monkeypatch.setenv("GATEWAY_KEY", "k-test")

    class _Rep:
        def raise_for_status(self): ...
        def json(self):
            return {"choices": [{"message": {"content":
                    '{"resume": "synthèse", "points_action": ["faire X"], '
                    '"themes": ["budget"], "decisions": ["valider Y"]}'}}]}

    class _Client:
        def __init__(self, *a, **k): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): ...
        async def post(self, *a, **k): return _Rep()

    monkeypatch.setattr(resume.httpx, "AsyncClient", _Client)
    out = _run(resume.resumer("transcription longue", langue="fr"))
    assert out["source"] == "llm"
    assert out["resume"] == "synthèse"
    assert out["points_action"] == ["faire X"]
    assert out["decisions"] == ["valider Y"]


def test_resumer_gateway_en_panne_repli(monkeypatch):
    monkeypatch.setenv("GATEWAY_KEY", "k-test")

    class _Client:
        def __init__(self, *a, **k): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): ...
        async def post(self, *a, **k): raise RuntimeError("gateway down")

    monkeypatch.setattr(resume.httpx, "AsyncClient", _Client)
    out = _run(resume.resumer("du texte transcrit ici."))
    assert out["source"] == "heuristique"                       # repli honnête
