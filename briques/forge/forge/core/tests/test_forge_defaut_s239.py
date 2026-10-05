"""S239 (revue I2) — le modèle par défaut de la Forge est `forge/defaut`, via la Gateway.

`forge/defaut` est un alias de la Gateway (Mistral, avec repli vers les gratuits Kilo —
cf. briques/gateway/litellm_config.yaml) : la Forge n'a pas de cascade à elle, c'est la
Gateway qui lui donne son filet. Avant ce correctif, l'alias n'était JAMAIS utilisé :
le compose de la brique fixait `go/deepseek-v4-flash` dans `environment:` (qui l'emporte
sur le .env), et les presets de pôle prenaient le défaut SERVEUR de la colonne.
"""

from pathlib import Path

from app.config import Settings
from app.llm import AVAILABLE_PROVIDERS, gateway_model, preset_pole_defaut
from app.models import LlmPresets

RACINE_BRIQUE = Path(__file__).resolve().parents[3]  # briques/forge
SCRIPT_SQL = (Path(__file__).resolve().parents[1] / "scripts"
              / "s239_presets_forge_defaut.sql")


def test_defauts_du_code():
    assert Settings.model_fields["DEFAULT_LLM_PROVIDER"].default == "gateway"
    assert Settings.model_fields["DEFAULT_LLM_MODEL"].default == "forge/defaut"


def test_gateway_model_passe_l_alias_tel_quel():
    assert gateway_model("gateway", "forge/defaut") == "forge/defaut"


def test_alias_propose_dans_la_liste_gateway():
    gw = next(p for p in AVAILABLE_PROVIDERS if p["id"] == "gateway")
    assert gw["models"][0] == "forge/defaut"


def test_compose_workplace_ne_fige_plus_go():
    """`environment:` l'emporte sur le .env : c'est ici que le défaut se joue réellement."""
    compose = (RACINE_BRIQUE / "docker-compose.yml").read_text()
    assert "- DEFAULT_LLM_PROVIDER=gateway\n" in compose
    assert "- DEFAULT_LLM_MODEL=forge/defaut\n" in compose
    assert "DEFAULT_LLM_MODEL=go/" not in compose


def test_defaut_serveur_de_la_colonne_pour_les_bases_neuves():
    c = LlmPresets.__table__.c
    assert "gateway" in str(c.provider.server_default.arg)
    assert "forge/defaut" in str(c.model.server_default.arg)


def test_preset_de_pole_explicite_independant_du_defaut_serveur(monkeypatch):
    """Une base DÉJÀ créée garde `go/deepseek-v4-flash` en défaut de colonne (create_all
    n'altère pas une table existante) : le preset doit donc porter ses valeurs lui-même."""
    monkeypatch.setattr("app.config.settings.DEFAULT_LLM_PROVIDER", "gateway")
    monkeypatch.setattr("app.config.settings.DEFAULT_LLM_MODEL", "forge/defaut")
    p = preset_pole_defaut(scope_id="p1", venture_id=None, updated_by="u1")
    assert (p.scope_type, p.scope_id, p.updated_by) == ("pole", "p1", "u1")
    assert (p.provider, p.model) == ("gateway", "forge/defaut")


def test_les_routeurs_passent_par_le_preset_explicite():
    app = Path(__file__).resolve().parents[1] / "app" / "routers"
    for nom in ("ventures.py", "poles.py"):
        src = (app / nom).read_text()
        assert "LlmPresets(scope_type=\"pole\"" not in src, nom
        assert "preset_pole_defaut(" in src, nom


def test_script_sql_ne_touche_que_l_ancien_defaut_exact():
    sql = SCRIPT_SQL.read_text()
    updates = [l for l in sql.splitlines() if l.strip().upper().startswith("UPDATE")]
    assert len(updates) == 1
    bloc = sql[sql.upper().index("UPDATE llm_presets".upper()):].split(";")[0]
    assert "provider = 'opencode'" in bloc and "model = 'go/deepseek-v4-flash'" in bloc
    assert "DELETE" not in sql.upper()
