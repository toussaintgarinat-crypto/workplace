"""Filet S239 — contrat du YAML de la Gateway pour l'option B (Mistral en tête, Kilo en filet).

Hors-ligne : on lit `briques/gateway/litellm_config.yaml`, aucun LiteLLM ni réseau. La preuve
de bout en bout (chargement réel, repli effectif) se fait sur une LiteLLM v1.86.2 locale ;
ce filet verrouille seulement les invariants qu'une retouche du YAML pourrait casser sans
bruit :
  1. la Forge (`forge/defaut`) a un repli Gateway vers `gratuit/auto` puis `gratuit/secours`,
     le Cœur (`mistral/small`) n'en a AUCUN — sa cascade et son journal de modèles font foi ;
  2. `gratuit/auto` vise le routeur de Kilo sans clé (`anonymous`, jamais vide), doublé de
     `gratuit/secours` (l'autre méta-routeur servi par Kilo) ;
  3. aucun modèle du YAML ne porte un préfixe géré par `gateway-sync` (`free/`, `kilo/`) ;
  4. chaque `go/*` envoie un User-Agent propre (exigence d'OpenCode Go).
"""
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

CONFIG = Path(__file__).resolve().parent.parent / "briques" / "gateway" / "litellm_config.yaml"


@pytest.fixture(scope="module")
def conf():
    return yaml.safe_load(CONFIG.read_text())


def _modeles(conf):
    return {m["model_name"]: m["litellm_params"] for m in conf["model_list"]}


def _replis(conf):
    replis = {}
    for entree in conf.get("router_settings", {}).get("fallbacks", []) or []:
        replis.update(entree)
    return replis


def test_forge_defaut_mistral_avec_repli_gratuit(conf):
    m = _modeles(conf)
    assert m["forge/defaut"]["model"] == m["mistral/small"]["model"]
    assert m["forge/defaut"]["api_key"] == "os.environ/MISTRAL_API_KEY"
    assert _replis(conf).get("forge/defaut") == ["gratuit/auto", "gratuit/secours"]


def test_le_coeur_na_aucun_repli_gateway(conf):
    """Un repli caché sur `mistral/small` ferait journaliser au Cœur un modèle qui n'a pas
    répondu (`journal_modele` = vérité)."""
    replis = _replis(conf)
    assert "mistral/small" not in replis
    assert set(replis) == {"forge/defaut", "gratuit/auto"}, replis


def test_gratuit_auto_routeur_kilo_sans_cle(conf):
    p = _modeles(conf)["gratuit/auto"]
    assert p["model"] == "openai/kilo-auto/free"
    assert p["api_base"] == "https://api.kilo.ai/api/gateway"
    assert p["api_key"] == "anonymous"


def test_gratuit_secours_second_meta_routeur_kilo(conf):
    """Constaté le 2026-10-05 sur une LiteLLM locale : `kilo-auto/free` renvoyait 429 en série
    (fournisseur amont saturé) pendant que `openrouter/free`, servi par le même Kilo, répondait.
    Un seul méta-routeur est donc un point de panne unique pour la Forge."""
    p = _modeles(conf)["gratuit/secours"]
    assert p["model"] == "openai/openrouter/free"
    assert p["api_base"] == "https://api.kilo.ai/api/gateway"
    assert p["api_key"] == "anonymous"
    assert _replis(conf).get("gratuit/auto") == ["gratuit/secours"]


def test_aucun_prefixe_du_sync_dans_le_yaml(conf):
    """LiteLLM recharge son YAML au démarrage : un `free/*`/`kilo/*` ici cohabiterait avec
    ceux du sync en base — deux sources de vérité (cf. ADR S202)."""
    fautifs = [n for n in _modeles(conf) if n.startswith(("free/", "kilo/"))]
    assert fautifs == []


def test_go_envoie_un_user_agent_propre(conf):
    go = {n: p for n, p in _modeles(conf).items() if n.startswith("go/")}
    assert go, "les modèles go/* ont disparu du YAML"
    sans_ua = [n for n, p in go.items()
               if (p.get("extra_headers") or {}).get("User-Agent") != "workplace-coeur/1.0"]
    assert sans_ua == []


def test_en_tetes_client_relayes_aux_seuls_go(conf):
    """`x-opencode-session` vient du Cœur, par requête (S239 T4). LiteLLM ne relaie les
    en-têtes `x-*` du client que pour les groupes listés ici — à ne PAS élargir : Kilo,
    Mistral, etc. n'ont pas à recevoir un identifiant de conversation. Le réglage global
    `general_settings.forward_client_headers_to_llm_api` relaierait à TOUS les modèles."""
    groupes = (conf["litellm_settings"].get("model_group_settings") or {}) \
        .get("forward_client_headers_to_llm_api")
    assert groupes == ["go/*"]
    assert not conf["general_settings"].get("forward_client_headers_to_llm_api")
