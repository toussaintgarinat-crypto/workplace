"""Co-agent exécutif — le « lobe frontal » borné et lecture seule (Sprint S66).

Autonome : aucun réseau. On script `llm_pipeline.completer` et la trousse d'outils en
mémoire pour piloter la boucle profonde et vérifier les DEUX garde-fous souverains
(budget de tokens = coût de la pensée ; lecture seule = pas de pouvoir sur le corps).
    $ cd core && python3 test_coagent.py
"""
import asyncio
import os
import sys

os.environ.setdefault("GATEWAY_KEY", "test")  # llm_pipeline l'exige à l'import
sys.path.insert(0, os.path.dirname(__file__))

import coagent  # noqa: E402
import config_assistant  # noqa: E402
import llm_pipeline  # noqa: E402
import outils  # noqa: E402


def _spec(nom):
    return {"type": "function", "function": {"name": nom, "description": nom}}


def _msg_outil(nom):
    return {"content": None, "tool_calls": [
        {"id": "1", "function": {"name": nom, "arguments": "{}"}}]}


def _msg_texte(txt):
    return {"content": txt, "tool_calls": []}


class _Patch:
    """Installe une trousse + un script de réponses LLM, restaure tout à la sortie."""
    def __init__(self, reponses, actions=("agir_y",), trousse=("lire_x", "agir_y", "coagent_lancer")):
        self.reponses = list(reponses)        # liste de (message|None, tokens) OU Resultat
        self.actions = set(actions)
        self.trousse = trousse
        self.executes = []

    def __enter__(self):
        self._o = (outils.outils_pour, outils.est_action, outils.executer,
                   llm_pipeline.completer, config_assistant.chaine_modeles)
        outils.outils_pour = lambda reg: [_spec(n) for n in self.trousse]
        outils.est_action = lambda nom, reg: nom in self.actions

        async def _exec(nom, args, reg):
            self.executes.append(nom)
            return '{"ok": true}'
        outils.executer = _exec

        async def _chaine(conf=None):
            return ["free/test"]
        config_assistant.chaine_modeles = _chaine

        async def _completer(messages, *, tools=None, **kw):
            # Si on RETIRE les outils (synthèse finale forcée), on renvoie une conclusion.
            if not tools:
                return llm_pipeline.Resultat(message=_msg_texte("SYNTHÈSE finale"),
                                             modele_utilise="free/test",
                                             tokens_in=5, tokens_out=5)
            msg, toks = self.reponses.pop(0)
            if isinstance(msg, llm_pipeline.Resultat):
                return msg
            return llm_pipeline.Resultat(message=msg, modele_utilise="free/test",
                                         tokens_in=toks, tokens_out=0)
        llm_pipeline.completer = _completer
        return self

    def __exit__(self, *a):
        (outils.outils_pour, outils.est_action, outils.executer,
         llm_pipeline.completer, config_assistant.chaine_modeles) = self._o


def _run(coro):
    return asyncio.run(coro)


def test_outils_lecture_retire_actions_et_soi_meme():
    with _Patch([]):
        noms = {s["function"]["name"] for s in coagent._outils_lecture(None)}
    assert noms == {"lire_x"}          # agir_y (action) et coagent_lancer (soi) écartés


def test_objectif_vide_refuse_proprement():
    r = _run(coagent.executer_objectif("   ", None))
    assert r["ok"] is False and r["raison_arret"] == "erreur"
    assert not r["outils_appeles"]


def test_aboutit_quand_le_modele_conclut_sans_outil():
    with _Patch([(_msg_texte("Voici le plan."), 30)]):
        r = _run(coagent.executer_objectif("plan", None, conf={}))
    assert r["ok"] and r["raison_arret"] == "abouti"
    assert r["synthese"] == "Voici le plan." and r["etapes"] == 1
    assert r["tokens"] == 30


def test_execute_les_outils_de_lecture_puis_conclut():
    script = [(_msg_outil("lire_x"), 10), (_msg_texte("Fait."), 20)]
    with _Patch(script) as p:
        r = _run(coagent.executer_objectif("obj", None, conf={}))
    assert p.executes == ["lire_x"]            # l'outil de lecture a bien été appelé
    assert r["raison_arret"] == "abouti" and r["synthese"] == "Fait."
    assert r["outils_appeles"] == ["lire_x"] and r["tokens"] == 30


def test_borne_le_budget_de_tokens():
    # Chaque étape consomme 10000 tokens : budget 5000 → coupe dès la 1re étape.
    script = [(_msg_outil("lire_x"), 10000), (_msg_outil("lire_x"), 10000)]
    with _Patch(script):
        r = _run(coagent.executer_objectif("obj", None, conf={}, budget_tokens=5000))
    assert r["raison_arret"] == "budget"
    assert r["synthese"] == "SYNTHÈSE finale"   # synthèse finale forcée, lecture seule
    assert r["tokens"] >= 10000


def test_borne_le_nombre_d_etapes():
    # Toujours un appel d'outil, tokens faibles → c'est le plafond d'étapes qui coupe.
    script = [(_msg_outil("lire_x"), 5)] * 10
    with _Patch(script):
        r = _run(coagent.executer_objectif("obj", None, conf={}, max_etapes=3))
    assert r["raison_arret"] == "max_etapes"
    assert r["etapes"] == 3 and r["synthese"] == "SYNTHÈSE finale"


def test_erreur_modele_remontee_honnetement():
    script = [(llm_pipeline.Resultat(erreur="Aucun modèle disponible."), 0)]
    with _Patch(script):
        r = _run(coagent.executer_objectif("obj", None, conf={}))
    assert r["ok"] is False and r["raison_arret"] == "erreur"
    assert "modèle" in r["erreur"]


def test_compte_rendu_marque_lecture_seule():
    with _Patch([(_msg_texte("ok"), 1)]):
        r = _run(coagent.executer_objectif("obj", None, conf={}))
    assert "LECTURE SEULE" in r["note"]         # honnêteté : aucune action exécutée


if __name__ == "__main__":
    for nom, fn in list(globals().items()):
        if nom.startswith("test_") and callable(fn):
            fn()
            print(f"  ✓ {nom}")
    print("\n✅ TOUS LES TESTS PASSENT")


# ── Revue S240, I1 : le co-agent n'hérite JAMAIS du droit admin, et ne sort pas de sa trousse ──

def test_outil_hors_trousse_refuse_sans_execution():
    """Le LLM peut halluciner un nom d'outil (ou se le faire injecter) : seul ce qui est dans
    la trousse de lecture s'exécute."""
    script = [(_msg_outil("agir_y"), 10), (_msg_texte("Fait."), 10)]
    with _Patch(script) as p:
        r = _run(coagent.executer_objectif("obj", None, conf={}))
    assert p.executes == []
    assert r["outils_appeles"] == ["agir_y"]


def test_coagent_lance_depuis_un_tour_admin_ne_peut_pas_executer_dev():
    """Même lancé depuis un tour admin du cerveau, le co-agent tourne SANS ce droit :
    `dev_ide_executer`, même s'il figurait dans la trousse, est refusé par outils.executer."""
    import droits
    vu = []
    script = [(_msg_outil("dev_ide_executer"), 10), (_msg_texte("Fait."), 10)]
    with _Patch(script, actions=(), trousse=("dev_ide_executer",)):
        async def _exec(nom, args, reg):
            vu.append((nom, droits.ADMIN_CERVEAU.get()))
            return '{"ok": true}'
        outils.executer = _exec

        async def tour_admin():
            jeton = droits.ADMIN_CERVEAU.set(True)
            try:
                r = await coagent.executer_objectif("obj", None, conf={})
                apres = droits.ADMIN_CERVEAU.get()
            finally:
                droits.ADMIN_CERVEAU.reset(jeton)
            return r, apres
        r, apres = _run(tour_admin())
    assert vu == [("dev_ide_executer", False)]   # exécuté SANS droit admin → refusé en vrai
    assert apres is True                         # le droit du tour appelant est restauré


def test_dev_ide_executer_vraiment_refuse_dans_le_coagent():
    """Bout en bout avec le VRAI outils.executer : refus, aucun appel à la brique."""
    import droits
    import json as _json
    appels = []
    script = [(_msg_outil("dev_ide_executer"), 10), (_msg_texte("Fait."), 10)]
    with _Patch(script, actions=(), trousse=("dev_ide_executer",)) as p:
        outils.executer = p._o[2]  # vrai executer

        async def _faux_executer_interne(nom, args, reg):
            appels.append(nom)
            return "exécuté"
        ancien = outils._executer
        outils._executer = _faux_executer_interne
        try:
            async def tour_admin():
                jeton = droits.ADMIN_CERVEAU.set(True)
                try:
                    return await coagent.executer_objectif("obj", None, conf={})
                finally:
                    droits.ADMIN_CERVEAU.reset(jeton)
            _run(tour_admin())
        finally:
            outils._executer = ancien
    assert appels == []
