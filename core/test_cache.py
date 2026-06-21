"""Prompt caching conditionnel (Sprint S90b) — pose les points de cache selon le fournisseur.

Autonome, aucun réseau : on vérifie la détection de fournisseur et le marquage `cache_control`
sur le DERNIER message système — posé pour Anthropic, no-op (charge identique) pour OpenAI /
local. On vérifie aussi qu'on ne MUTE jamais les messages de l'appelant.
    $ cd core && python3 test_cache.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import cache  # noqa: E402


def _messages():
    return [
        {"role": "system", "content": "PROMPT FONDATEUR STABLE"},
        {"role": "system", "content": "Date : lundi (volatil)"},
        {"role": "user", "content": "bonjour"},
    ]


def test_fournisseur_detecte():
    assert cache.fournisseur("anthropic/claude-sonnet-4-6") == "anthropic"
    assert cache.fournisseur("claude-3-5-sonnet") == "anthropic"
    assert cache.fournisseur("openai/gpt-4o-mini") == "openai"
    assert cache.fournisseur("gpt-4o") == "openai"
    assert cache.fournisseur("ollama/llama3") == "local"
    assert cache.fournisseur("free/qwen") == "local"
    assert cache.fournisseur("go/sonnet") == "local"
    assert cache.fournisseur("") == "autre"


def test_anthropic_marque_le_dernier_systeme():
    msgs = _messages()
    out = cache.appliquer(msgs, "anthropic/claude-sonnet-4-6")
    # Le DERNIER message système (index 1) porte un cache_control ephemeral en blocs.
    bloc = out[1]["content"]
    assert isinstance(bloc, list) and bloc[0]["type"] == "text"
    assert bloc[0]["text"] == "Date : lundi (volatil)"
    assert bloc[0]["cache_control"] == {"type": "ephemeral"}
    # Le 1er système et le user restent intacts (chaînes).
    assert out[0]["content"] == "PROMPT FONDATEUR STABLE"
    assert out[2]["content"] == "bonjour"


def test_openai_et_local_no_op_meme_objet():
    msgs = _messages()
    # OpenAI auto-cache + local : on ne touche PAS la charge (et on rend la liste d'origine).
    assert cache.appliquer(msgs, "openai/gpt-4o-mini") is msgs
    assert cache.appliquer(msgs, "ollama/llama3") is msgs
    assert cache.appliquer(msgs, "free/x") is msgs


def test_ne_mute_pas_l_appelant():
    msgs = _messages()
    avant = msgs[1]["content"]
    cache.appliquer(msgs, "anthropic/claude-sonnet-4-6")
    assert msgs[1]["content"] == avant  # str intact : la copie n'a pas muté l'entrée


def test_sans_systeme_no_op():
    msgs = [{"role": "user", "content": "hello"}]
    assert cache.appliquer(msgs, "anthropic/claude-sonnet-4-6") is msgs


def test_contenu_deja_en_blocs():
    msgs = [{"role": "system", "content": [{"type": "text", "text": "A"},
                                           {"type": "text", "text": "B"}]}]
    out = cache.appliquer(msgs, "anthropic/claude-3-5-sonnet")
    assert out[0]["content"][-1]["cache_control"] == {"type": "ephemeral"}
    assert "cache_control" not in out[0]["content"][0]  # seul le dernier bloc est marqué
    assert msgs[0]["content"][-1] == {"type": "text", "text": "B"}  # original intact


if __name__ == "__main__":
    for nom, fn in list(globals().items()):
        if nom.startswith("test_") and callable(fn):
            fn()
            print(f"  ✓ {nom}")
    print("\n✅ TOUS LES TESTS PASSENT")
