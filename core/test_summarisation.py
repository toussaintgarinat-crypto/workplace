"""Tests de la summarisation à froid (S138, chantier 3b).

    $ cd core && python3 -m pytest test_summarisation.py -v
"""
import asyncio
import os
import sys

os.environ.setdefault("GATEWAY_KEY", "test")
sys.path.insert(0, os.path.dirname(__file__))

import pytest
import summarisation as sm
import trimming


# ── Helpers ──────────────────────────────────────────────────────────────────

def run(coro):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


def _msgs(n: int, contenu: str = "Message de test assez long pour compter.") -> list[dict]:
    """Génère n messages user/assistant alternés."""
    out = []
    for i in range(n):
        role = "user" if i % 2 == 0 else "assistant"
        out.append({"role": role, "content": f"{contenu} #{i}"})
    return out


CONF_BASE = {"model": "gpt-4o", "fallback_models": ["free/mistral"], "langue": "fr"}


class _FakeClient:
    """Client httpx factice qui simule la Gateway."""

    def __init__(self, resume="Résumé synthétique.", status=200):
        self._resume = resume
        self._status = status
        self.appels = 0

    async def post(self, url, **kwargs):
        self.appels += 1
        if self._status >= 400:
            return _FakeResponse(self._status, {})
        corps = {
            "choices": [{"message": {"content": self._resume}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 50},
        }
        return _FakeResponse(200, corps)


class _FakeResponse:
    def __init__(self, status, body):
        self.status_code = status
        self._body = body

    def json(self):
        return self._body


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_1_sous_seuil_pas_de_condensation():
    """Un historique court (sous le seuil de tokens) est renvoyé inchangé."""
    msgs = _msgs(2)
    conf = {**CONF_BASE, "seuil_resume_tokens": 999999}
    client = _FakeClient()
    result = run(sm.condenser(client, msgs, conf))
    assert result == msgs
    assert client.appels == 0


def test_2_au_dessus_seuil_condense():
    """Un historique long est condensé : la Gateway est appelée et le résumé injecté."""
    msgs = _msgs(30, "x" * 60)
    conf = {**CONF_BASE, "seuil_resume_tokens": 1, "resume_garder": 4}
    client = _FakeClient("Résumé court.")
    result = run(sm.condenser(client, msgs, conf))
    assert client.appels == 1
    # Le résultat contient un message système de résumé
    resumé = [m for m in result if m.get("role") == "system" and "Résumé" in (m.get("content") or "")]
    assert resumé


def test_3_messages_systeme_preserves():
    """Les messages système sont toujours conservés tels quels."""
    sys_msg = {"role": "system", "content": "Tu es un assistant.", "pinned": True}
    msgs = [sys_msg] + _msgs(20, "y" * 80)
    conf = {**CONF_BASE, "seuil_resume_tokens": 1, "resume_garder": 4}
    client = _FakeClient("Condensé.")
    result = run(sm.condenser(client, msgs, conf))
    assert sys_msg in result


def test_4_recents_preserves():
    """Les N derniers tours (resume_garder) sont préservés sans modification."""
    msgs = _msgs(20, "z" * 80)
    garder = 6
    conf = {**CONF_BASE, "seuil_resume_tokens": 1, "resume_garder": garder}
    client = _FakeClient("Condensé.")
    result = run(sm.condenser(client, msgs, conf))
    # Les garder derniers messages doivent apparaître dans le résultat
    recents = msgs[-garder:]
    for m in recents:
        assert m in result


def test_5_repli_si_gateway_ko():
    """Si la Gateway renvoie 500, on renvoie l'historique inchangé."""
    msgs = _msgs(30, "a" * 80)
    conf = {**CONF_BASE, "seuil_resume_tokens": 1, "resume_garder": 4}
    client = _FakeClient(status=500)
    result = run(sm.condenser(client, msgs, conf))
    assert result == msgs


def test_6_repli_si_resume_vide():
    """Si la Gateway renvoie un résumé vide, l'historique est renvoyé inchangé."""
    msgs = _msgs(30, "b" * 80)
    conf = {**CONF_BASE, "seuil_resume_tokens": 1, "resume_garder": 4}
    client = _FakeClient(resume="")
    result = run(sm.condenser(client, msgs, conf))
    assert result == msgs


def test_7_modele_resume_depuis_conf():
    """Si conf contient modele_resume, c'est lui qui est utilisé (non le modèle principal)."""
    msgs = _msgs(30, "c" * 80)
    conf = {**CONF_BASE, "seuil_resume_tokens": 1, "resume_garder": 4,
            "modele_resume": "free/mistral-tiny"}
    client = _FakeClient("Résumé.")
    result = run(sm.condenser(client, msgs, conf))
    assert client.appels == 1  # un seul appel (avec le modèle résumé)


def test_8_sans_modele_sans_condensation():
    """Sans modèle disponible, pas de condensation."""
    msgs = _msgs(30, "d" * 80)
    conf = {"seuil_resume_tokens": 1, "resume_garder": 4}  # ni model ni fallback
    client = _FakeClient()
    result = run(sm.condenser(client, msgs, conf))
    assert result == msgs
    assert client.appels == 0


def test_9_trop_peu_de_messages_pas_de_condensation():
    """Avec moins de garder+2 messages non-système, pas de condensation."""
    msgs = _msgs(4, "e" * 100)
    conf = {**CONF_BASE, "seuil_resume_tokens": 1, "resume_garder": 6}
    client = _FakeClient()
    result = run(sm.condenser(client, msgs, conf))
    assert result == msgs
    assert client.appels == 0


def test_10_pas_de_message_tool_en_tete_recents():
    """Les messages 'tool' orphelins ne doivent pas ouvrir la fenêtre recents."""
    sys_msg = {"role": "system", "content": "Contexte système."}
    anciens = _msgs(20, "f" * 60)
    # Forcer un message tool en tête des recents (ne doit pas être premier)
    tool_msg = {"role": "tool", "tool_call_id": "x", "content": "résultat"}
    recents_bruts = [tool_msg] + _msgs(4, "g" * 20)
    msgs = [sys_msg] + anciens + recents_bruts
    conf = {**CONF_BASE, "seuil_resume_tokens": 1, "resume_garder": len(recents_bruts)}
    client = _FakeClient("Résumé.")
    result = run(sm.condenser(client, msgs, conf))
    # Le premier message non-système du résultat ne doit pas être un tool
    non_sys = [m for m in result if m.get("role") != "system"]
    if non_sys:
        # Le résumé (pinned system) peut être premier, sinon le premier non-sys ne doit pas être tool
        premier = non_sys[0]
        assert premier.get("role") != "tool"
