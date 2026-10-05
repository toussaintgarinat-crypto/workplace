"""Filet S239 — contrat du YAML de la Gateway pour l'option B (Mistral en tête, Kilo en filet).

Hors-ligne : on lit `briques/gateway/litellm_config.yaml`, aucun LiteLLM ni réseau. La preuve
de bout en bout (chargement réel, repli effectif) se fait sur une LiteLLM v1.86.2 locale ;
ce filet verrouille seulement les invariants qu'une retouche du YAML pourrait casser sans
bruit :
  1. la Forge (`forge/defaut`, en base depuis S240) a un repli Gateway vers `gratuit/auto` puis `gratuit/secours`,
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


def test_forge_defaut_hors_yaml_mais_repli_gratuit_conserve(conf):
    """S240 : `forge/defaut` vit EN BASE (piloté par le Cœur depuis ⚙ Cerveau). Le déclarer
    aussi ici le doublerait ; son repli, lui, reste dans router_settings (prouvé sur LiteLLM
    v1.86.2 : il s'applique au groupe créé en base)."""
    assert "forge/defaut" not in _modeles(conf)
    assert _replis(conf).get("forge/defaut") == ["gratuit/auto", "gratuit/secours"]


def test_aucun_modele_perso_dans_le_yaml(conf):
    """`perso/*` = modèles ajoutés depuis ⚙ Cerveau (S240), retirables par le Cœur : aucun
    modèle du YAML ne doit porter ce préfixe."""
    assert not [n for n in _modeles(conf) if n.startswith("perso/")]


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


# ── Revue S239, I4 : la politique de mise au frigo doit faire ce que ses commentaires disent ──
# Lu dans LiteLLM v1.86.2 (router_utils/cooldown_handlers.py) : le seuil effectif vaut
# `get_allowed_fails_from_policy(e) or allowed_fails` → une valeur 0 retombe sur
# `allowed_fails` (3) ; et le frigo se déclenche quand le N-ième échec DÉPASSE le seuil.
# `AllowedFailsPolicy` ne connaît que ces six clés — toute autre est ignorée en silence.
CLES_POLITIQUE_LITELLM = {
    "BadRequestErrorAllowedFails", "AuthenticationErrorAllowedFails",
    "TimeoutErrorAllowedFails", "RateLimitErrorAllowedFails",
    "ContentPolicyViolationErrorAllowedFails", "InternalServerErrorAllowedFails",
}


def _politique(conf):
    return conf["router_settings"].get("allowed_fails_policy") or {}


def test_politique_seulement_des_cles_connues_de_litellm(conf):
    inconnues = set(_politique(conf)) - CLES_POLITIQUE_LITELLM
    assert inconnues == set(), f"clés ignorées par LiteLLM v1.86.2 : {inconnues}"


def test_politique_aucun_zero_qui_retomberait_sur_allowed_fails(conf):
    zeros = [k for k, v in _politique(conf).items() if v == 0]
    assert zeros == [], f"0 vaut `allowed_fails` ({conf['router_settings'].get('allowed_fails')})"


def test_cle_invalide_au_frigo_des_le_deuxieme_refus(conf):
    """Seuil 1 = le plus strict exprimable (0 retomberait sur 3)."""
    assert _politique(conf)["AuthenticationErrorAllowedFails"] == 1


def test_gratuits_jamais_au_frigo_pour_quota(conf):
    assert _politique(conf)["RateLimitErrorAllowedFails"] >= 100


def test_un_gratuit_qui_pend_part_au_frigo(conf):
    """2e relecture S239 : un seuil Timeout élevé gardait « disponible » un gratuit qui PEND,
    et le Cœur attendait son timeout (10 s) à chaque tour, gratuit après gratuit. Seuil par
    défaut (`allowed_fails`) : peu coûteux, puisque le frigo des gratuits ne dure qu'une
    minute (cooldown_time de déploiement)."""
    assert "TimeoutErrorAllowedFails" not in _politique(conf)


def test_mistral_frigo_court_par_deploiement(conf):
    """2e relecture S239 : quelques timeouts + une 503 passagère suffisent à mettre Mistral au
    frigo ; avec l'heure globale, la Forge aurait été servie par Kilo pendant 1 h — contraire
    à l'option B (Mistral en tête, Kilo en secours)."""
    m = _modeles(conf)
    # `forge/defaut` en base depuis S240 : son frigo de 120 s est posé par le Cœur
    # (modeles_gateway.COOLDOWN_FORGE_S, test_forge_modele.py).
    visés = [n for n in m if n.startswith("mistral/")]
    assert set(visés) >= {"mistral/small", "mistral/large"}
    for nom in visés:
        assert m[nom].get("cooldown_time") == 120, nom


def test_alias_gratuits_frigo_court_par_deploiement(conf):
    """`cooldown_time` de déploiement prime sur celui du routeur (router.py:6739) : un gratuit
    saturé une minute ne doit pas disparaître une heure."""
    for nom, p in _modeles(conf).items():
        if nom.startswith("gratuit/"):
            assert p.get("cooldown_time") == 60, nom
