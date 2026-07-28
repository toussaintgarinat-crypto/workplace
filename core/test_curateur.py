"""Curator — cycle de curation + brouillons de capacités (Sprint S70).

Autonome : aucun réseau. Stores temporaires ; proprioception/amélioration/LLM mockés.
On vérifie : le cycle propose (prompt S69 + capacité S70) et SURFACE un digest 🔔 sans
rien appliquer ; le gate humain des capacités (retenir/rejeter) ; le repli template.
    $ cd core && python3 test_curateur.py
"""
import asyncio
import os
import sys
import tempfile

os.environ.setdefault("GATEWAY_KEY", "test")
_TMP = tempfile.mkdtemp()
os.environ["CAPACITES_PROPOSEES_PATH"] = os.path.join(_TMP, "cap.json")
os.environ["AMELIORATION_PATH"] = os.path.join(_TMP, "amel.json")
os.environ["RAPPELS_DB"] = os.path.join(_TMP, "rappels.db")
os.environ["PROPRIOCEPTION_PATH"] = os.path.join(_TMP, "proprio.jsonl")
sys.path.insert(0, os.path.dirname(__file__))

import amelioration  # noqa: E402
import config_assistant  # noqa: E402
import curateur  # noqa: E402
import llm_pipeline  # noqa: E402
import proactif  # noqa: E402
import proprioception  # noqa: E402


class _Reg:
    def __init__(self):
        self.briques = {}


def _reset():
    # On vide les fichiers que les modules utilisent VRAIMENT (globals figés à l'import), pas
    # `os.environ` : en suite complète, un module importé plus tôt gèle son chemin sur celui du
    # conftest — nettoyer via l'env viderait d'autres fichiers et laisserait les stores
    # (capacités proposées, propositions d'amélioration, rappels) accumuler d'un test à l'autre.
    for p in (curateur.CAPACITES_PATH, amelioration.STORE_PATH, proactif.DB):
        try:
            os.remove(p)
        except FileNotFoundError:
            pass
    proactif.init_db()


def _run(coro):
    return asyncio.run(coro)


def _mesure(props):
    return {"n": 3, "source": "juge", "moyennes": {"pertinence": 0.8, "honnetete": 0.4,
            "completude": 0.3}, "points_faibles": ["honnetete", "completude"],
            "propositions": props}


def _faiblesse(dim, cible):
    return {"flux": "chat", "dimension": dim, "score": 0.3, "cible_sprint": cible,
            "suggestion": "x"}


# ── Brouillons de capacités ──────────────────────────────────────────────────

def test_proposer_capacite_template_si_pas_de_modele():
    _reset()
    _o = config_assistant.chaine_modeles
    try:
        async def _vide(conf=None):
            return []
        config_assistant.chaine_modeles = _vide
        b = _run(curateur.proposer_capacite(_Reg(), _faiblesse("completude", "S70"), {}, None))
        assert b["statut"] == "propose" and b["declaration"]["genere_par"] == "template"
        assert "IMPLÉMENTER" in b["note"]                    # honnêteté : non câblé
        assert curateur.lister_capacites()["brouillons"][0]["id"] == b["id"]
    finally:
        config_assistant.chaine_modeles = _o


def test_proposer_capacite_llm():
    _reset()
    _oc, _ocomp = config_assistant.chaine_modeles, llm_pipeline.completer
    try:
        async def _chaine(conf=None):
            return ["free/test"]
        config_assistant.chaine_modeles = _chaine

        async def _comp(messages, **kw):
            import json
            return llm_pipeline.Resultat(message={"content": json.dumps(
                {"nom": "chercher_contrat", "brique_suggeree": "ingestion",
                 "description": "cherche un contrat", "methode": "GET",
                 "chemin": "/contrats", "raison": "comble la complétude"})},
                modele_utilise="free/test")
        llm_pipeline.completer = _comp
        b = _run(curateur.proposer_capacite(_Reg(), _faiblesse("completude", "S70"), {}, None))
        d = b["declaration"]
        assert d["genere_par"] == "llm" and d["nom"] == "chercher_contrat"
        assert d["brique_suggeree"] == "ingestion" and d["methode"] == "GET"
    finally:
        config_assistant.chaine_modeles, llm_pipeline.completer = _oc, _ocomp


def test_gate_capacite_retenir_puis_refus():
    _reset()
    async def _vide(conf=None):
        return []
    _o = config_assistant.chaine_modeles
    config_assistant.chaine_modeles = _vide
    try:
        b = _run(curateur.proposer_capacite(_Reg(), _faiblesse("completude", "S70"), {}, None))
        assert curateur.retenir_capacite(b["id"])["ok"]
        assert curateur._charger()["brouillons"][0]["statut"] == "retenue"
        # retenir une 2e fois : refusé (plus au statut « propose »)
        assert curateur.retenir_capacite(b["id"])["ok"] is False
        assert curateur.rejeter_capacite(b["id"])["ok"]   # rejet possible depuis « retenue »
    finally:
        config_assistant.chaine_modeles = _o


# ── Le cycle ─────────────────────────────────────────────────────────────────

def _patch_mesure(props):
    async def _m(conf=None):
        return _mesure(props)
    proprioception.mesurer = _m


def _patch_amelioration():
    """Fait écrire/évaluer une vraie proposition dans le store d'amélioration (sans LLM)."""
    async def _proposer(conf=None, mesure=None):
        data = amelioration._charger()
        prop = {"id": "promptid1", "dimension": "honnetete", "addendum": "Sois honnête.",
                "flux": "chat", "statut": "propose", "eval": None}
        data["propositions"].append(prop)
        amelioration._sauver(data)
        return {"statut": "propose", "proposition": prop}

    async def _evaluer(id_, conf=None):
        data = amelioration._charger()
        p = amelioration._trouver(data, id_)
        p["eval"] = {"recommande": True, "gain_cible": 0.4}
        amelioration._sauver(data)
        return {"ok": True}
    amelioration.proposer, amelioration.evaluer = _proposer, _evaluer


def test_curer_rien_a_proposer():
    _reset()
    _o = proprioception.mesurer
    try:
        _patch_mesure([])                       # aucune proposition
        r = _run(curateur.curer(_Reg()))
        assert r["statut"] == "cree"
        assert r["prompt_propose"] is None and r["capacite_proposee"] is None
        assert "se porte bien" in r["digest"]
        rappels = [x for x in proactif.lister(limite=10) if x.get("type") == "curation"]
        assert len(rappels) == 1
    finally:
        proprioception.mesurer = _o


def test_curer_propose_prompt_et_capacite():
    _reset()
    _om, _op, _oe, _oc = (proprioception.mesurer, amelioration.proposer,
                          amelioration.evaluer, config_assistant.chaine_modeles)
    try:
        _patch_mesure([_faiblesse("honnetete", "S69"), _faiblesse("completude", "S70")])
        _patch_amelioration()

        async def _vide(conf=None):
            return []                            # capacité → repli template (pas de LLM)
        config_assistant.chaine_modeles = _vide

        r = _run(curateur.curer(_Reg()))
        assert r["prompt_propose"] == "promptid1"
        assert r["capacite_proposee"] is not None
        assert "Prompt proposé" in r["digest"] and "recommandé ✅" in r["digest"]
        assert "Capacité esquissée" in r["digest"]
        # le brouillon de capacité est bien persisté au statut « propose »
        assert curateur._charger()["brouillons"][0]["statut"] == "propose"
    finally:
        (proprioception.mesurer, amelioration.proposer, amelioration.evaluer,
         config_assistant.chaine_modeles) = _om, _op, _oe, _oc


def test_curer_idempotent_par_jour():
    _reset()
    _o = proprioception.mesurer
    try:
        _patch_mesure([])
        _run(curateur.curer(_Reg()))
        r2 = _run(curateur.curer(_Reg()))
        assert r2["statut"] == "deja_fait"
        assert len([x for x in proactif.lister(limite=10) if x.get("type") == "curation"]) == 1
    finally:
        proprioception.mesurer = _o


if __name__ == "__main__":
    for nom, fn in list(globals().items()):
        if nom.startswith("test_") and callable(fn):
            fn()
            print(f"  ✓ {nom}")
    print("\n✅ TOUS LES TESTS PASSENT")
