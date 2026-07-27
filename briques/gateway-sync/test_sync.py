"""Tests de la synchronisation des modèles gratuits (S202). Aucun réseau réel.

Ce qui doit être verrouillé, dans l'ordre d'importance :
  1. le sync est DIFFÉRENTIEL et ne touche QUE les `free/*` — sinon il balaierait les
     modèles payants déclarés dans le YAML, qui sont le repli de toute la cascade ;
  2. un modèle disparu du catalogue est bien SUPPRIMÉ (c'est tout l'objet du sprint) ;
  3. un échec unitaire ne fige pas la liste entière.
"""
import os

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

    def __init__(self, actuels: dict, echouer_sur: str | None = None):
        self._actuels = actuels
        self._echouer_sur = echouer_sur
        self.ajouts, self.suppressions = [], []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, url, **k):
        data = [{"model_name": n, "model_info": {"id": i}} for n, i in self._actuels.items()]
        return _Resp({"data": data})

    def post(self, url, json=None, **k):
        if url.endswith("/model/new"):
            if json["model_name"] == self._echouer_sur:
                raise RuntimeError("LiteLLM a refusé")
            self.ajouts.append(json["model_name"])
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


def _preparer(monkeypatch, catalogue, actuels, echouer_sur=None):
    faux = _FauxClient(actuels, echouer_sur)
    monkeypatch.setattr(sync, "catalogue_gratuits", lambda: catalogue)
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


def test_sans_cle_openrouter_ne_fait_rien(monkeypatch):
    """Comportement hérité de l'ancien script : pas de clé → no-op, jamais une erreur."""
    monkeypatch.setattr(sync, "OPENROUTER_API_KEY", "")
    assert sync.synchroniser()["statut"] == "ignore"


def test_nom_workplace_normalise_le_slug():
    assert sync.nom_workplace("qwen/qwen3-coder:free") == "free/qwen/qwen3-coder"
    assert sync.nom_workplace("nvidia/nemotron-3-nano-30b-a3b:free") == \
        "free/nvidia/nemotron-3-nano-30b-a3b"
