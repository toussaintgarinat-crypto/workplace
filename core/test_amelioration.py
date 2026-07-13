"""Auto-amélioration des prompts — proposer → A/B → gate humain (Sprint S69).

Autonome : aucun réseau. Store redirigé en temporaire ; proprioception + juge + LLM
mockés. On vérifie : proposition depuis un point faible, repli template, A/B honnête,
et surtout le GATE (appliquer refusé si non validé ; un seul addendum actif ; réversible).
    $ cd core && python3 test_amelioration.py
"""
import asyncio
import os
import sys
import tempfile

os.environ.setdefault("GATEWAY_KEY", "test")
_TMP = tempfile.mkdtemp()
os.environ["AMELIORATION_PATH"] = os.path.join(_TMP, "amel.json")
os.environ["PROPRIOCEPTION_PATH"] = os.path.join(_TMP, "proprio.jsonl")
sys.path.insert(0, os.path.dirname(__file__))

import amelioration  # noqa: E402
import config_assistant  # noqa: E402
import llm_pipeline  # noqa: E402
import proprioception  # noqa: E402


def _reset():
    # On vide le store que le module utilise vraiment (`amelioration.STORE_PATH`, figé à son
    # import), pas `os.environ["AMELIORATION_PATH"]` : en suite complète le module peut être
    # importé plus tôt et gelé sur le chemin du conftest — nettoyer via l'env viderait un autre
    # fichier et laisserait des propositions d'autres tests s'accumuler (pollution d'ordre).
    try:
        os.remove(amelioration.STORE_PATH)
    except FileNotFoundError:
        pass


def _run(coro):
    return asyncio.run(coro)


def _mesure_avec_faible(dim="honnetete", score=0.2):
    cible = "S70" if dim == "completude" else "S69"
    return {"propositions": [{"flux": "chat", "dimension": dim, "score": score,
                              "cible_sprint": cible, "suggestion": "revoir le prompt"}]}


class _LLM:
    """Mocke chaine_modeles + completer (texte d'addendum scriptable, ou panne)."""
    def __init__(self, addendum="Cite toujours ta source.", echoue=False, no_model=False):
        self.addendum, self.echoue, self.no_model = addendum, echoue, no_model

    def __enter__(self):
        self._o = (config_assistant.chaine_modeles, llm_pipeline.completer)

        async def _chaine(conf=None):
            return [] if self.no_model else ["free/test"]
        config_assistant.chaine_modeles = _chaine

        async def _completer(messages, **kw):
            if self.echoue:
                return llm_pipeline.Resultat(erreur="KO")
            return llm_pipeline.Resultat(message={"content": self.addendum},
                                         modele_utilise="free/test")
        llm_pipeline.completer = _completer
        return self

    def __exit__(self, *a):
        config_assistant.chaine_modeles, llm_pipeline.completer = self._o


def _patch_mesure(mesure):
    async def _m(conf=None):
        return mesure
    proprioception.mesurer = _m


# ── Proposer ─────────────────────────────────────────────────────────────────

def test_addendum_actif_vide_par_defaut():
    _reset()
    assert amelioration.addendum_actif() == ""


def test_rien_a_proposer_si_aucun_point_faible_prompt():
    _reset()
    _o = proprioception.mesurer
    try:
        _patch_mesure({"propositions": [{"flux": "chat", "dimension": "completude",
                                         "score": 0.2, "cible_sprint": "S70",
                                         "suggestion": "x"}]})  # cible S70, pas S69
        with _LLM():
            r = _run(amelioration.proposer())
        assert r["statut"] == "rien_a_proposer"
    finally:
        proprioception.mesurer = _o


def test_propose_un_addendum_genere_par_llm():
    _reset()
    _o = proprioception.mesurer
    try:
        _patch_mesure(_mesure_avec_faible("honnetete", 0.2))
        with _LLM(addendum="N'invente jamais un fait non vérifié."):
            r = _run(amelioration.proposer())
        p = r["proposition"]
        assert r["statut"] == "propose" and p["statut"] == "propose"
        assert p["dimension"] == "honnetete" and p["genere_par"] == "llm"
        assert "invente" in p["addendum"]
        assert amelioration.addendum_actif() == ""   # proposé ≠ actif
    finally:
        proprioception.mesurer = _o


def test_repli_template_si_llm_indisponible():
    _reset()
    _o = proprioception.mesurer
    try:
        _patch_mesure(_mesure_avec_faible("honnetete", 0.2))
        with _LLM(no_model=True):
            r = _run(amelioration.proposer())
        p = r["proposition"]
        assert p["genere_par"] == "template"
        assert p["addendum"] == amelioration._TEMPLATES["honnetete"]
    finally:
        proprioception.mesurer = _o


# ── Gate humain ──────────────────────────────────────────────────────────────

def _proposer_une(dim="honnetete"):
    _o = proprioception.mesurer
    try:
        _patch_mesure(_mesure_avec_faible(dim, 0.2))
        with _LLM(addendum="Sois honnête."):
            return _run(amelioration.proposer())["proposition"]["id"]
    finally:
        proprioception.mesurer = _o


def test_appliquer_refuse_si_non_valide():
    _reset()
    pid = _proposer_une()
    r = amelioration.appliquer(pid)            # encore au statut « propose »
    assert r["ok"] is False and "refusée" in r["erreur"].lower()
    assert amelioration.addendum_actif() == ""  # rien activé


def test_flux_complet_valider_puis_appliquer_active():
    _reset()
    pid = _proposer_une()
    assert amelioration.valider(pid)["ok"]
    assert amelioration.appliquer(pid)["ok"]
    actif = amelioration.addendum_actif()
    assert actif.startswith("\n- ") and "Sois honnête." in actif  # puce, actif après gate


def test_un_seul_addendum_actif():
    _reset()
    pid1 = _proposer_une("honnetete")
    amelioration.valider(pid1); amelioration.appliquer(pid1)
    pid2 = _proposer_une("pertinence")
    amelioration.valider(pid2); amelioration.appliquer(pid2)
    data = amelioration._charger()
    actifs = [p for p in data["propositions"] if p["statut"] == "applique"]
    assert len(actifs) == 1 and data["actif_id"] == pid2   # le 1er est « remplace »


def test_rejeter_un_actif_le_desactive():
    _reset()
    pid = _proposer_une()
    amelioration.valider(pid); amelioration.appliquer(pid)
    assert amelioration.addendum_actif() != ""
    amelioration.rejeter(pid)
    assert amelioration.addendum_actif() == "" and amelioration._charger()["actif_id"] is None


def test_desactiver_revient_au_prompt_fondateur():
    _reset()
    pid = _proposer_une()
    amelioration.valider(pid); amelioration.appliquer(pid)
    amelioration.desactiver()
    assert amelioration.addendum_actif() == ""


# ── Évaluer (A/B honnête) ────────────────────────────────────────────────────

def test_evaluer_recommande_si_gain_sans_regression():
    _reset()
    pid = _proposer_une("honnetete")
    # Trace une question pour le flux « chat ».
    _ol = proprioception.TRACE_PATH
    proprioception.tracer("Une question ?", "rep", etiquette="chat")
    _osb, _orep, _ojuge, _ochaine = (amelioration._systeme_base, amelioration._reponse,
                                     proprioception._juger, config_assistant.chaine_modeles)
    try:
        amelioration._systeme_base = lambda conf: "BASE"

        async def _rep(client, question, systeme, modeles, conf):
            return "AP" if systeme != "BASE" else "AV"   # addendum → réponse « après »
        amelioration._reponse = _rep

        async def _juge(client, ligne, conf):
            bon = ligne["reponse"] == "AP"
            return {"pertinence": 0.8, "honnetete": 0.9 if bon else 0.3,
                    "completude": 0.8, "commentaire": "", "_juge": True}
        proprioception._juger = _juge

        async def _chaine(conf=None):
            return ["free/test"]
        config_assistant.chaine_modeles = _chaine

        r = _run(amelioration.evaluer(pid, echantillon=2))
        ev = r["eval"]
        assert r["ok"] and ev["recommande"] is True
        assert ev["gain_cible"] > 0 and ev["regressions"] == {}
        # l'éval est persistée sur la proposition
        assert amelioration._charger()["propositions"][0]["eval"]["recommande"] is True
    finally:
        (amelioration._systeme_base, amelioration._reponse, proprioception._juger,
         config_assistant.chaine_modeles) = _osb, _orep, _ojuge, _ochaine
        proprioception.TRACE_PATH = _ol


if __name__ == "__main__":
    for nom, fn in list(globals().items()):
        if nom.startswith("test_") and callable(fn):
            fn()
            print(f"  ✓ {nom}")
    print("\n✅ TOUS LES TESTS PASSENT")
