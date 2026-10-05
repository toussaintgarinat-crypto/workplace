"""Format des clés écrites dans le .env de la Gateway (revue S240, I2).

`_ecrire_cle_env` écrit `NOM=valeur` ligne à ligne : une valeur portant `\\n` injecterait une
ligne de plus (ex. `OPENROUTER_API_KEY=x\\nLITELLM_MASTER_KEY=…`). On n'accepte donc que les
caractères des formats réels de clés.

$ cd core && python3 -m pytest test_cle_fournisseur.py -v
"""
import os

os.environ.setdefault("VAULT_SECRET", "test-secret-0123456789")
os.environ.setdefault("GATEWAY_KEY", "test")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import config_assistant  # noqa: E402
import main  # noqa: E402

client = TestClient(main.app)

# Formats réels (valeurs fabriquées, jamais de vraies clés).
VALIDES = ["sk-or-v1-0123456789abcdef0123456789abcdef", "sk-ant-api03-AbC_dEf-123456_xyz-AA",
           "gsk_AbCdEf0123456789", "AIzaSyA-bc_DEF0123456789", "AbCdEf0123456789XyZ0123456789ab",
           "sk-proj-AbC_123-xyz.45"]
INVALIDES = ["", "a b", "x\nLITELLM_MASTER_KEY=vole", "x\r", "a=b", "clé", "x;y", "x#y", '"x"']


@pytest.mark.parametrize("cle", VALIDES)
def test_formats_reels_acceptes(cle):
    config_assistant._ecrire_cle_env("GROQ_API_KEY", cle)
    assert config_assistant._lire_cle_env("GROQ_API_KEY") == cle


@pytest.mark.parametrize("cle", INVALIDES)
def test_caracteres_dangereux_refuses(cle):
    avant = config_assistant.GATEWAY_ENV_PATH.read_text() if config_assistant.GATEWAY_ENV_PATH.exists() else ""
    with pytest.raises(ValueError):
        config_assistant._ecrire_cle_env("GROQ_API_KEY", cle)
    apres = config_assistant.GATEWAY_ENV_PATH.read_text() if config_assistant.GATEWAY_ENV_PATH.exists() else ""
    assert apres == avant


def test_routes_refusent_400_sans_recreer_la_gateway(monkeypatch):
    appels = []

    async def faux_recreer():
        appels.append(1)
        return True
    monkeypatch.setattr(config_assistant, "recreer_gateway", faux_recreer)
    r = client.post("/assistant/cle-fournisseur",
                    json={"fournisseur": "groq", "cle": "gsk_x\nLITELLM_MASTER_KEY=vole"})
    assert r.status_code == 400
    r = client.post("/assistant/cle-openrouter", json={"cle": "sk-or-x y"})
    assert r.status_code == 400
    assert not appels
