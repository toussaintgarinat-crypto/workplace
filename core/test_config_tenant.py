"""Couches de patch déclaratif pour la config assistant (3e chantier veille dsh/Cordis).

Autonome : aucune vraie brique données (httpx.MockTransport). Mêmes conventions que
core/test_muscle.py.
    $ cd core && python3 -m pytest test_config_tenant.py -v
    $ cd core && python3 test_config_tenant.py
"""
import asyncio
import os
import sys
import tempfile

os.environ["ASSISTANT_CONFIG_PATH"] = os.path.join(tempfile.mkdtemp(), "cfg.json")
os.environ.setdefault("GATEWAY_KEY", "sk-test-local")   # config_assistant l'exige à l'import
sys.path.insert(0, os.path.dirname(__file__))

import httpx  # noqa: E402

import config_tenant  # noqa: E402


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _reset_cache():
    config_tenant._cache.clear()


# ── _fusion (JSON Merge Patch, RFC 7386) ────────────────────────────────────

def test_fusion_remplace_cle_simple():
    base = {"a": 1, "b": 2}
    patch = {"b": 3}
    assert config_tenant._fusion(base, patch) == {"a": 1, "b": 3}


def test_fusion_recursive_sur_dict_imbrique():
    base = {"a": {"x": 1, "y": 2}}
    patch = {"a": {"y": 9}}
    assert config_tenant._fusion(base, patch) == {"a": {"x": 1, "y": 9}}


def test_fusion_remplace_liste_entierement():
    base = {"fallback_models": ["m1", "m2"]}
    patch = {"fallback_models": ["m3"]}
    assert config_tenant._fusion(base, patch) == {"fallback_models": ["m3"]}


def test_fusion_ne_mute_pas_base():
    base = {"a": 1}
    config_tenant._fusion(base, {"a": 2})
    assert base == {"a": 1}


if __name__ == "__main__":
    for nom, fn in list(globals().items()):
        if nom.startswith("test_") and callable(fn):
            fn()
            print(f"  ✓ {nom}")
    print("\n✅ TOUS LES TESTS PASSENT")
