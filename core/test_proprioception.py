"""Proprioception — le Cœur mesure ses propres sorties (Sprint S68).

Autonome : aucun réseau. Trace redirigée vers un fichier temporaire ; le juge LLM est
mocké pour piloter les scores. On vérifie : capture échantillonnée opt-in, agrégat par
flux, repli heuristique honnête, et PROPOSITIONS de cibles (proposer ≠ appliquer).
    $ cd core && python3 test_proprioception.py
"""
import asyncio
import os
import sys
import tempfile

os.environ.setdefault("GATEWAY_KEY", "test")
_TMP = tempfile.mkdtemp()
os.environ["PROPRIOCEPTION_PATH"] = os.path.join(_TMP, "proprio.jsonl")
sys.path.insert(0, os.path.dirname(__file__))

import config_assistant  # noqa: E402
import llm_pipeline  # noqa: E402
import proprioception  # noqa: E402


def _reset():
    # On vide `proprioception.TRACE_PATH` (le chemin que le module utilise vraiment, figé à
    # son import), pas `os.environ["PROPRIOCEPTION_PATH"]` : en suite complète le module peut
    # être importé plus tôt et gelé sur le chemin du conftest — nettoyer via l'env viderait un
    # autre fichier et laisserait les traces s'accumuler (moyennes faussées, pollution d'ordre).
    try:
        os.remove(proprioception.TRACE_PATH)
    except FileNotFoundError:
        pass


class _Juge:
    """Mocke chaine_modeles + completer pour scripter les notes du juge (ou son échec)."""
    def __init__(self, scores=None, *, echoue=False, json_casse=False):
        self.scores = scores or {"pertinence": 0.9, "honnetete": 0.9, "completude": 0.9,
                                 "commentaire": "ok"}
        self.echoue = echoue
        self.json_casse = json_casse

    def __enter__(self):
        self._o = (config_assistant.chaine_modeles, llm_pipeline.completer)

        async def _chaine(conf=None):
            return [] if self.echoue == "no_model" else ["free/test"]
        config_assistant.chaine_modeles = _chaine

        async def _completer(messages, **kw):
            import json
            if self.echoue is True:
                return llm_pipeline.Resultat(erreur="Gateway KO")
            contenu = "pas du json" if self.json_casse else json.dumps(self.scores)
            return llm_pipeline.Resultat(message={"content": contenu},
                                         modele_utilise="free/test")
        llm_pipeline.completer = _completer
        return self

    def __exit__(self, *a):
        config_assistant.chaine_modeles, llm_pipeline.completer = self._o


def _run(coro):
    return asyncio.run(coro)


def test_echantillonne_eteint_par_defaut():
    # ACTIF par défaut False (pas d'env) → jamais d'échantillon, quel que soit le taux.
    assert proprioception.ACTIF is False
    assert proprioception.echantillonne({}) is False
    assert proprioception.echantillonne({"proprioception_actif": True,
                                         "proprioception_taux": 0}) is False


def test_echantillonne_actif_avec_taux_1():
    assert proprioception.echantillonne({"proprioception_actif": True,
                                         "proprioception_taux": 1}) is True


def test_tracer_puis_relire():
    _reset()
    proprioception.tracer("Q1", "R1", etiquette="chat", outils=["lister_entreprises"])
    proprioception.tracer("Q2", "R2", etiquette="briefing")
    lignes = proprioception._lignes()
    assert [l["question"] for l in lignes] == ["Q1", "Q2"]
    assert lignes[0]["outils"] == ["lister_entreprises"]
    assert proprioception._lignes(limite=1)[0]["question"] == "Q2"   # ne garde que le dernier


def test_mesurer_sans_trace():
    _reset()
    r = _run(proprioception.mesurer())
    assert r["n"] == 0 and r["source"] == "aucune" and r["propositions"] == []


def test_mesurer_avec_juge_agrege_par_flux():
    _reset()
    proprioception.tracer("Q1", "bonne réponse", etiquette="chat")
    proprioception.tracer("Q2", "autre", etiquette="briefing")
    with _Juge({"pertinence": 0.8, "honnetete": 1.0, "completude": 0.7, "commentaire": "ok"}):
        r = _run(proprioception.mesurer())
    assert r["n"] == 2 and r["source"] == "juge" and r["evalues_par_juge"] == 2
    assert set(r["par_flux"]) == {"chat", "briefing"}
    assert r["moyennes"]["honnetete"] == 1.0
    assert r["points_faibles"] == []           # tout ≥ seuil 0.6 → aucun point faible


def test_point_faible_genere_une_proposition_ciblee():
    _reset()
    proprioception.tracer("Q", "réponse douteuse", etiquette="chat")
    # honnêteté faible → cible PROMPTS (S69) ; complétude faible → cible CAPACITÉS (S70).
    with _Juge({"pertinence": 0.9, "honnetete": 0.2, "completude": 0.3, "commentaire": "x"}):
        r = _run(proprioception.mesurer())
    assert "honnetete" in r["points_faibles"] and "completude" in r["points_faibles"]
    par_dim = {p["dimension"]: p for p in r["propositions"]}
    assert par_dim["honnetete"]["cible_sprint"] == "S69"
    assert par_dim["completude"]["cible_sprint"] == "S70"
    # proposer ≠ appliquer : le rapport le dit explicitement.
    assert "Rien n'est modifié" in r["note"]


def test_repli_heuristique_si_juge_indisponible():
    _reset()
    proprioception.tracer("Q", "Je ne sais pas, cette information est indisponible.", etiquette="chat")
    with _Juge(echoue=True):                    # Gateway KO → proxy structurel
        r = _run(proprioception.mesurer())
    assert r["source"] == "heuristique" and r["evalues_par_juge"] == 0
    # L'aveu d'incertitude est récompensé par le proxy d'honnêteté.
    assert r["moyennes"]["honnetete"] >= 0.8


def test_repli_heuristique_si_json_casse():
    _reset()
    proprioception.tracer("Q", "réponse", etiquette="chat")
    with _Juge(json_casse=True):
        r = _run(proprioception.mesurer())
    assert r["source"] == "heuristique"


def test_borne_les_scores_hors_intervalle():
    _reset()
    proprioception.tracer("Q", "r", etiquette="chat")
    with _Juge({"pertinence": 5, "honnetete": -2, "completude": "x", "commentaire": ""}):
        r = _run(proprioception.mesurer())
    m = r["moyennes"]
    assert m["pertinence"] == 1.0 and m["honnetete"] == 0.0 and m["completude"] == 0.0


if __name__ == "__main__":
    for nom, fn in list(globals().items()):
        if nom.startswith("test_") and callable(fn):
            fn()
            print(f"  ✓ {nom}")
    print("\n✅ TOUS LES TESTS PASSENT")
