"""S150 — validation Pydantic : vérifications statiques et modèles inline.

Ces tests ne nécessitent pas le stack Docker complet (pas d'import de app.main).
Ils valident :
  1. Que les modèles Pydantic ajoutés se comportent correctement.
  2. Que les endpoints modifiés n'utilisent plus request.json() brut.
"""

from __future__ import annotations

import pathlib

import pytest
from pydantic import BaseModel, ValidationError

_ROUTERS = pathlib.Path(__file__).resolve().parent.parent / "app" / "routers"


# ── Modèles Pydantic ajoutés ────────────────────────────────────────────────


class CorpsLlmGlobal(BaseModel):
    provider: str
    model: str


class CorpsRunAgent(BaseModel):
    task: str = ""


class CorpsBrief(BaseModel):
    ventureId: str | None = None


def test_corps_llm_global_rejette_corps_vide():
    with pytest.raises(ValidationError) as exc:
        CorpsLlmGlobal()
    champs = [e["loc"][0] for e in exc.value.errors()]
    assert "provider" in champs
    assert "model" in champs


def test_corps_llm_global_rejette_model_manquant():
    with pytest.raises(ValidationError) as exc:
        CorpsLlmGlobal(provider="openai")
    champs = [e["loc"][0] for e in exc.value.errors()]
    assert "model" in champs


def test_corps_llm_global_accepte_champs_requis():
    m = CorpsLlmGlobal(provider="openai", model="gpt-4o")
    assert m.provider == "openai"
    assert m.model == "gpt-4o"


def test_corps_run_agent_task_par_defaut():
    m = CorpsRunAgent()
    assert m.task == ""


def test_corps_run_agent_accepte_task_explicite():
    m = CorpsRunAgent(task="analyse le marché")
    assert m.task == "analyse le marché"


def test_corps_brief_venture_id_par_defaut():
    m = CorpsBrief()
    assert m.ventureId is None


def test_corps_brief_accepte_venture_id():
    m = CorpsBrief(ventureId="v-123")
    assert m.ventureId == "v-123"


# ── Vérifications statiques ─────────────────────────────────────────────────


def _lire(fichier: str) -> str:
    return (_ROUTERS / fichier).read_text()


def test_agents_n_utilise_plus_request_json():
    contenu = _lire("agents.py")
    assert "await request.json()" not in contenu
    assert "CorpsRunAgent" in contenu


def test_llm_config_n_utilise_plus_request_json_dans_put_global():
    contenu = _lire("llm_config.py")
    assert "CorpsLlmGlobal" in contenu
    # put_global ne doit plus avoir request.json() — vérifier la fonction spécifique
    lignes = contenu.splitlines()
    dans_put_global = False
    for ligne in lignes:
        if "async def put_global" in ligne:
            dans_put_global = True
        if dans_put_global and "@router" in ligne and "put_global" not in ligne:
            dans_put_global = False
        if dans_put_global:
            assert "await request.json()" not in ligne, "put_global utilise encore request.json()"


def test_brief_n_utilise_plus_request_json():
    contenu = _lire("brief.py")
    assert "await request.json()" not in contenu
    assert "CorpsBrief" in contenu


def test_facturation_patch_utilise_body():
    contenu = _lire("facturation.py")
    assert "Body(" in contenu
    # update_doc ne doit plus faire await request.json()
    assert "body = await request.json()" not in contenu


def test_kb_patch_utilise_body():
    contenu = _lire("kb.py")
    assert "Body(" in contenu
    assert "body = await request.json()" not in contenu


def test_agents_factory_patch_utilise_body():
    contenu = _lire("agents_factory.py")
    assert "Body(" in contenu
    assert "body = await request.json()" not in contenu


def test_veille_patch_utilise_body():
    contenu = _lire("veille.py")
    assert "Body(" in contenu
    # Les deux PATCH veille ne doivent plus faire await request.json()
    assert "body = await request.json()" not in contenu


def test_skills_patch_utilise_body():
    contenu = _lire("skills.py")
    assert "Body(" in contenu
    assert "body = await request.json()" not in contenu
