"""Tests de la synchronisation des modèles gratuits (S202, sources multiples S239). Aucun réseau réel.

Ce qui doit être verrouillé, dans l'ordre d'importance :
  1. le sync est DIFFÉRENTIEL et ne touche QUE les `free/*` — sinon il balaierait les
     modèles payants déclarés dans le YAML, qui sont le repli de toute la cascade ;
  2. un modèle disparu du catalogue est bien SUPPRIMÉ (c'est tout l'objet du sprint) ;
  3. un échec unitaire ne fige pas la liste entière ;
  4. (S239) chaque source ne gère QUE son préfixe, et une source en panne n'empêche pas
     l'autre de se synchroniser ni n'efface ses modèles.
"""
import os

import pytest

os.environ.setdefault("LITELLM_MASTER_KEY", "cle-test")
os.environ.setdefault("OPENROUTER_API_KEY", "cle-openrouter-test")

import sync  # noqa: E402


def _modele(mid, ctx=100000, tools=True, texte=True):
    return {"id": mid, "context_length": ctx,
            "pricing": {"prompt": "0", "completion": "0"},
            "supported_parameters": ["tools"] if tools else [],
            "architecture": {"modality": "text->text" if texte else "text->image"}}


class _FauxClient:
    """Client HTTP factice : sert /model/info et enregistre les ajouts/suppressions."""

    def __init__(self, actuels: dict, echouer_sur: str | None = None,
                 info_en_plus: list | None = None):
        self._actuels = actuels
        self._info_en_plus = info_en_plus or []
        self._echouer_sur = echouer_sur
        self.ajouts, self.suppressions = [], []
        self.params = {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, url, **k):
        data = [{"model_name": n, "model_info": {"id": i, "db_model": True}}
                for n, i in self._actuels.items()]
        return _Resp({"data": data + self._info_en_plus})

    def post(self, url, json=None, **k):
        if url.endswith("/model/new"):
            if json["model_name"] == self._echouer_sur:
                raise RuntimeError("LiteLLM a refusé")
            self.ajouts.append(json["model_name"])
            self.params[json["model_name"]] = json["litellm_params"]
        elif url.endswith("/model/delete"):
            self.suppressions.append(json["id"])
        return _Resp({})


class _Resp:
    def __init__(self, corps):
        self._corps = corps

    def json(self):
        return self._corps

    def raise_for_status(self):
        return None


def _preparer(monkeypatch, catalogue, actuels, echouer_sur=None, kilo=None,
              info_en_plus=None):
    """`catalogue` = catalogue BRUT d'OpenRouter, `kilo` = celui de Kilo (vide par défaut).

    Une valeur `Exception` simule un catalogue injoignable pour cette source.
    """
    faux = _FauxClient(actuels, echouer_sur, info_en_plus)
    bruts = {"openrouter": catalogue, "kilo": kilo if kilo is not None else []}

    def _brut(source):
        b = bruts[source.nom]
        if isinstance(b, Exception):
            raise b
        return b
    monkeypatch.setattr(sync, "_catalogue_brut", _brut)
    monkeypatch.setattr(sync.httpx, "Client", lambda *a, **k: faux)
    return faux


def test_ajoute_les_nouveaux_gratuits(monkeypatch):
    faux = _preparer(monkeypatch, [_modele("google/gemma-4-31b-it:free")], actuels={})
    r = sync.synchroniser()
    assert r["statut"] == "ok"
    assert faux.ajouts == ["free/google/gemma-4-31b-it"]
    assert faux.suppressions == []


def test_supprime_un_modele_disparu_du_catalogue(monkeypatch):
    """Le cœur du sprint : qwen3-coder est passé payant et crachait 48 NotFoundError/24 h."""
    faux = _preparer(monkeypatch, catalogue=[_modele("google/gemma-4-31b-it:free")],
                     actuels={"free/qwen/qwen3-coder": "id-qwen"})
    r = sync.synchroniser()
    assert r["retires"] == ["free/qwen/qwen3-coder"]
    assert faux.suppressions == ["id-qwen"]


def test_ne_touche_jamais_aux_modeles_hors_free(monkeypatch):
    """Les payants et go/* viennent du YAML et sont le REPLI de la cascade : les balayer
    couperait l'assistant, pas seulement les gratuits."""
    faux = _preparer(monkeypatch, catalogue=[_modele("google/gemma-4-31b-it:free")],
                     actuels={"deepseek/deepseek-v4-flash": "id-payant",
                              "go/glm-5.1": "id-go"})
    sync.synchroniser()
    assert faux.suppressions == [], "aucun modèle hors free/* ne doit être supprimé"


def test_modele_deja_present_nest_ni_ajoute_ni_retire(monkeypatch):
    """Idempotence : deux passages rapprochés ne doivent produire aucun effet."""
    faux = _preparer(monkeypatch, catalogue=[_modele("google/gemma-4-31b-it:free")],
                     actuels={"free/google/gemma-4-31b-it": "id-gemma"})
    r = sync.synchroniser()
    assert faux.ajouts == [] and faux.suppressions == []
    assert r["inchanges"] == 1


def test_un_echec_unitaire_ne_bloque_pas_les_autres(monkeypatch):
    """Sinon une seule anomalie fige toute la liste — exactement le problème à supprimer."""
    faux = _preparer(monkeypatch,
                     catalogue=[_modele("a/recalcitrant:free"), _modele("b/sain:free")],
                     actuels={}, echouer_sur="free/a/recalcitrant")
    r = sync.synchroniser()
    assert faux.ajouts == ["free/b/sain"]
    assert len(r["erreurs"]) == 1 and "recalcitrant" in r["erreurs"][0]
    assert r["statut"] == "ok", "un échec unitaire reste un sync réussi"
    assert r["inchanges"] == 0, "un ajout en échec n'est pas un modèle en place"


def test_sans_cle_openrouter_la_source_openrouter_est_ignoree_mais_kilo_tourne(monkeypatch):
    """Hérité de l'ancien script : pas de clé OpenRouter → la source OpenRouter est un no-op,
    jamais une erreur, et ses `free/*` restent en place. Mais depuis S239 Kilo n'a besoin
    d'AUCUNE clé : il doit se synchroniser quand même — c'est tout l'intérêt du filet."""
    monkeypatch.setattr(sync, "OPENROUTER_API_KEY", "")
    faux = _preparer(monkeypatch, catalogue=[_modele("google/gemma-4-31b-it:free")],
                     actuels={"free/qwen/qwen3-coder": "id-qwen"},
                     kilo=[_modele("nvidia/nemotron-3-super-120b-a12b:free")])
    r = sync.synchroniser()
    assert r["sources"]["openrouter"]["statut"] == "ignore"
    assert r["sources"]["kilo"]["statut"] == "ok"
    assert faux.ajouts == ["kilo/nvidia/nemotron-3-super-120b-a12b"]
    assert faux.suppressions == [], "une source ignorée n'efface pas ses modèles"


def test_sans_master_key_ne_fait_rien(monkeypatch):
    monkeypatch.setattr(sync, "LITELLM_MASTER_KEY", "")
    assert sync.synchroniser()["statut"] == "ignore"


# ── S239 : Kilo Code, deuxième source de gratuits, sans clé ─────────────────────────────

def test_kilo_ajoute_ses_gratuits_sous_son_prefixe_avec_cle_anonyme(monkeypatch):
    faux = _preparer(monkeypatch, catalogue=[], actuels={},
                     kilo=[_modele("nvidia/nemotron-3-super-120b-a12b:free"),
                           _modele("inclusionai/ling-3.1-flash")])
    r = sync.synchroniser()
    assert sorted(faux.ajouts) == ["kilo/inclusionai/ling-3.1-flash",
                                   "kilo/nvidia/nemotron-3-super-120b-a12b"]
    p = faux.params["kilo/nvidia/nemotron-3-super-120b-a12b"]
    assert p["model"] == "openai/nvidia/nemotron-3-super-120b-a12b:free"
    assert p["api_base"] == "https://api.kilo.ai/api/gateway"
    # « anonymous » et pas une chaîne vide : Kilo répond 401 à `Bearer None`, ce que
    # produirait un client OpenAI sans clé.
    assert p["api_key"] == "anonymous"
    assert p["num_retries"] == 0 and p["timeout"] <= 10
    # Frigo court PAR DÉPLOIEMENT (prime sur le cooldown_time global d'une heure du routeur,
    # router.py:6739 de LiteLLM v1.86.2) : un gratuit saturé une minute ne disparaît pas 1 h.
    assert p["cooldown_time"] == 60
    assert sorted(r["sources"]["kilo"]["ajoutes"]) == sorted(faux.ajouts)


def test_les_meta_routeurs_sont_exclus(monkeypatch):
    """`kilo-auto/free` et `openrouter/free` routent vers un modèle CHOISI PAR EUX : le
    journal du Cœur ne saurait plus quel modèle a répondu. Ils n'entrent pas dans la cascade."""
    faux = _preparer(monkeypatch, catalogue=[_modele("openrouter/free")], actuels={},
                     kilo=[_modele("kilo-auto/free"), _modele("openrouter/free"),
                           _modele("poolside/laguna-s-2.1:free")])
    sync.synchroniser()
    assert faux.ajouts == ["kilo/poolside/laguna-s-2.1"]


def test_kilo_filtre_payant_sans_outils_et_non_texte(monkeypatch):
    payant = _modele("anthropic/claude-x")
    payant["pricing"] = {"prompt": "0.000003", "completion": "0.000015"}
    routeur_negatif = _modele("kilo-auto/efficient")
    routeur_negatif["pricing"] = {"prompt": "-1", "completion": "-1"}
    faux = _preparer(monkeypatch, catalogue=[], actuels={},
                     kilo=[payant, routeur_negatif, _modele("a/sans-outils:free", tools=False),
                           _modele("b/image:free", texte=False), _modele("c/bon:free")])
    sync.synchroniser()
    assert faux.ajouts == ["kilo/c/bon"]


def test_kilo_top_n_et_exclusion_configurable(monkeypatch):
    monkeypatch.setattr(sync, "KILO_TOP_N", 2)
    monkeypatch.setattr(sync, "KILO_EXCLURE", "nvidia/, liquid/")
    faux = _preparer(monkeypatch, catalogue=[], actuels={},
                     kilo=[_modele("nvidia/gros:free", ctx=1_000_000),
                           _modele("liquid/lfm:free", ctx=900_000),
                           _modele("a/moyen:free", ctx=200_000),
                           _modele("b/grand:free", ctx=500_000),
                           _modele("c/petit:free", ctx=50_000)])
    sync.synchroniser()
    assert faux.ajouts == ["kilo/b/grand", "kilo/a/moyen"]


def test_chaque_source_ne_gere_que_son_prefixe(monkeypatch):
    """Kilo vide ne doit pas balayer les `free/*`, et inversement — et les alias du YAML
    (`gratuit/auto`, `forge/defaut`) ne sont à AUCUNE source."""
    faux = _preparer(monkeypatch, catalogue=[_modele("google/gemma-4-31b-it:free")],
                     actuels={"free/google/gemma-4-31b-it": "id-gemma",
                              "kilo/vieux/modele": "id-vieux",
                              "gratuit/auto": "id-alias", "forge/defaut": "id-forge"},
                     kilo=[])
    r = sync.synchroniser()
    assert faux.suppressions == ["id-vieux"]
    assert r["sources"]["openrouter"]["inchanges"] == 1
    assert r["sources"]["kilo"]["retires"] == ["kilo/vieux/modele"]


def test_une_source_en_panne_nefface_rien_et_nempeche_pas_lautre(monkeypatch):
    faux = _preparer(monkeypatch, catalogue=RuntimeError("OpenRouter 401 User not found"),
                     actuels={"free/qwen/qwen3-coder": "id-qwen"},
                     kilo=[_modele("c/bon:free")])
    r = sync.synchroniser()
    assert faux.ajouts == ["kilo/c/bon"]
    assert faux.suppressions == [], "catalogue injoignable ≠ catalogue vide"
    assert r["sources"]["openrouter"]["statut"] == "erreur"
    assert "401" in r["sources"]["openrouter"]["raison"]
    assert r["statut"] == "ok"
    # Agrégat de compatibilité (/sync et la tâche d'horloge lisent ces clés).
    assert r["ajoutes"] == ["kilo/c/bon"]
    assert any("openrouter" in e for e in r["erreurs"])


def test_toutes_les_sources_en_panne_leve(monkeypatch):
    """Sans aucune source utile, `/sync` doit répondre 502 (lisible par l'horloge), comme
    avant S239 quand le catalogue unique était injoignable."""
    _preparer(monkeypatch, catalogue=RuntimeError("panne A"), actuels={},
              kilo=RuntimeError("panne B"))
    with pytest.raises(RuntimeError, match="panne"):
        sync.synchroniser()


def test_ne_supprime_jamais_un_modele_du_yaml(monkeypatch):
    """Défense en profondeur : un modèle déclaré dans le YAML (`db_model` faux dans
    `/model/info`) ne peut pas être supprimé par `/model/delete` — même s'il portait un
    préfixe géré par erreur, on ne le touche pas."""
    faux = _preparer(monkeypatch, catalogue=[], actuels={}, kilo=[],
                     info_en_plus=[{"model_name": "kilo/yaml/fixe",
                                    "model_info": {"id": "id-yaml", "db_model": False}}])
    sync.synchroniser()
    assert faux.suppressions == []


def test_nom_workplace_normalise_le_slug():
    assert sync.nom_workplace("qwen/qwen3-coder:free") == "free/qwen/qwen3-coder"
    assert sync.nom_workplace("nvidia/nemotron-3-nano-30b-a3b:free") == \
        "free/nvidia/nemotron-3-nano-30b-a3b"
    assert sync.nom_workplace("poolside/laguna-s-2.1:free", "kilo/") == \
        "kilo/poolside/laguna-s-2.1"
