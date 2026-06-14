"""Mapping du client Mémoire d'Oria vers la brique Workplace (port 5600).

Les tests e2e patchent ``mempalace_client.*`` ; ici on prouve la **logique de
mapping réelle** (espace par user, payload /retenir, mapping /rappeler, no-ops KG,
dégradation gracieuse) avec la brique mockée (respx) — sans réseau.
"""
import json

import httpx
import pytest
import respx

import mempalace_client as mp

BASE = "http://memoire-test:5600"


@pytest.fixture
def memoire_on(monkeypatch):
    monkeypatch.setenv("MEMOIRE_URL", BASE)
    return BASE


def test_desactivee_par_defaut(monkeypatch):
    monkeypatch.delenv("MEMOIRE_URL", raising=False)
    assert mp.prefetch("x", user_id="u1") == []
    assert mp.sync("c", "s", "input", "t", user_id="u1") is False
    assert mp.sync_document("c", "d", "n", "o") == 0
    assert mp.sync_conversation_turn("q", "r", "u1") is False


def test_espace_par_user():
    assert mp._espace("u1") == "oria-user-u1"
    assert mp._espace(None) is None


@respx.mock
def test_sync_payload_et_espace(memoire_on):
    route = respx.post(f"{BASE}/retenir").mock(return_value=httpx.Response(200, json={"retenu": True}))
    ok = mp.sync("Le héros doute", "sess9", "input", "Chapitre 1", user_id="u1")
    assert ok is True
    corps = json.loads(route.calls.last.request.content)
    assert corps["type"] == "input"
    assert corps["wing"] == "wing_user"
    assert corps["room"] == "ipcra-sessions"
    assert corps["hall"] == "hall_events"
    assert corps["espace"] == "oria-user-u1"
    assert corps["metadata"]["phase"] == "input"


@respx.mock
def test_prefetch_mappe_score_et_extrait(memoire_on):
    respx.get(f"{BASE}/rappeler").mock(return_value=httpx.Response(200, json={
        "souvenirs": [{"id": "n1", "titre": "T", "extrait": "le client aime le bleu",
                       "type": "input", "score": 0.82}]}))
    hits = mp.prefetch("préférences", n=3, user_id="u1")
    assert len(hits) == 1
    assert hits[0]["text"] == "le client aime le bleu"
    assert hits[0]["similarity"] == 0.82
    assert hits[0]["wing"] == "wing_user"


@respx.mock
def test_prefetch_passe_espace_user(memoire_on):
    route = respx.get(f"{BASE}/rappeler").mock(return_value=httpx.Response(200, json={"souvenirs": []}))
    mp.prefetch("q", user_id="u42")
    assert route.calls.last.request.url.params["espace"] == "oria-user-u42"


@respx.mock
def test_sync_document_compte_les_chunks(memoire_on):
    respx.post(f"{BASE}/retenir").mock(return_value=httpx.Response(200, json={"retenu": True}))
    contenu = "\n\n".join(f"Paragraphe {i} " + "x" * 500 for i in range(3))
    n = mp.sync_document(contenu, "doc1", "Rapport.md", owner_id="u1")
    assert n >= 2  # plusieurs chunks écrits


@respx.mock
def test_degradation_si_brique_500(memoire_on):
    respx.post(f"{BASE}/retenir").mock(return_value=httpx.Response(500, text="boom"))
    assert mp.sync("c", "s", "input", "t", user_id="u1") is False


def test_kg_sont_des_noops():
    assert mp.create_branch("s") is False
    assert mp.merge_branch("s") == {"merged": 0, "conflicts": []}
    assert mp.check_contradictions("s") == []


def test_format_context_block():
    assert mp.format_context_block([]) == ""
    out = mp.format_context_block([{"text": "z" * 600, "wing": "wing_user", "room": "documents", "similarity": 0.7}])
    assert "## Mémoires pertinentes (Mémoire Workplace)" in out
    assert "wing_user/documents" in out
    assert "…" in out
