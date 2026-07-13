"""Pouls autonome — le cœur qui bat tout seul (Sprint S67).

Autonome : aucun réseau. On redirige les side-cars (rappels + journal d'usage) vers un
dossier temporaire et on mocke le co-agent (S66) pour piloter le battement et vérifier :
idempotence par jour, dépôt en rappel 🔔, et le garde-fou du BUDGET QUOTIDIEN de tokens.
    $ cd core && python3 test_pouls.py
"""
import asyncio
import os
import sys
import tempfile

os.environ.setdefault("GATEWAY_KEY", "test")
_TMP = tempfile.mkdtemp()
os.environ["RAPPELS_DB"] = os.path.join(_TMP, "rappels.db")
os.environ["USAGE_LLM_PATH"] = os.path.join(_TMP, "usage.jsonl")
sys.path.insert(0, os.path.dirname(__file__))

import coagent  # noqa: E402
import journal_usage  # noqa: E402
import pouls  # noqa: E402
import proactif  # noqa: E402


def _reset():
    """Repart d'un journal et d'une base de rappels vierges entre les cas.

    On vide les fichiers que les modules utilisent VRAIMENT (`proactif.DB`,
    `journal_usage.JOURNAL_PATH`), pas `os.environ` : ces chemins sont figés au premier
    import du module. En suite complète, un module importé plus tôt gèle son chemin sur
    celui du conftest ; nettoyer via `os.environ` viderait un autre fichier et laisserait
    la vraie base accumuler (pollution d'ordre)."""
    for p in (proactif.DB, journal_usage.JOURNAL_PATH):
        try:
            os.remove(p)
        except FileNotFoundError:
            pass
    proactif.init_db()


class _CoAgentMock:
    """Remplace coagent.executer_objectif : renvoie un compte rendu scriptable et
    journalise les tokens consommés sous l'étiquette `pouls` (comme le vrai)."""
    def __init__(self, cr, *, tokens_journalises=None):
        self.cr = cr
        self.tokens = tokens_journalises if tokens_journalises is not None else cr.get("tokens", 0)
        self.appels = []

    def __enter__(self):
        self._o = coagent.executer_objectif

        async def _fake(objectif, registre, *, budget_tokens=None, etiquette="coagent", **kw):
            self.appels.append({"objectif": objectif, "budget_tokens": budget_tokens,
                                "etiquette": etiquette})
            if self.tokens:
                journal_usage.enregistrer(modele="free/test", etiquette=etiquette,
                                          tokens_in=self.tokens, tokens_out=0, cout_usd=0)
            return dict(self.cr)
        coagent.executer_objectif = _fake
        return self

    def __exit__(self, *a):
        coagent.executer_objectif = self._o


def _cr(ok=True, synthese="3 priorités du jour…", **extra):
    base = {"ok": ok, "synthese": synthese, "etapes": 2, "tokens": 1000,
            "cout_usd": 0.0, "raison_arret": "abouti", "outils_appeles": ["lister_entreprises"],
            "modele": "free/test"}
    base.update(extra)
    return base


def _run(coro):
    return asyncio.run(coro)


def test_bat_et_depose_un_rappel():
    _reset()
    with _CoAgentMock(_cr()) as m:
        r = _run(pouls.battre(None))
    assert r["ok"] and r["statut"] == "cree"
    assert r["synthese"].startswith("3 priorités")
    assert m.appels[0]["etiquette"] == "pouls"          # étiquette dédiée (budget séparé)
    rappels = [x for x in proactif.lister(limite=10) if x.get("type") == "pouls"]
    assert len(rappels) == 1 and rappels[0]["titre"].startswith("Point du")


def test_idempotent_par_jour():
    _reset()
    with _CoAgentMock(_cr()):
        _run(pouls.battre(None))
        r2 = _run(pouls.battre(None))
    assert r2["statut"] == "deja_fait"                  # un seul battement par jour
    assert len([x for x in proactif.lister(limite=10) if x.get("type") == "pouls"]) == 1


def test_forcer_rejoue_sans_dupliquer():
    _reset()
    with _CoAgentMock(_cr(synthese="version 2")):
        _run(pouls.battre(None))
        r2 = _run(pouls.battre(None, forcer=True))
    assert r2["statut"] == "cree" and r2["synthese"] == "version 2"
    rappels = [x for x in proactif.lister(limite=10) if x.get("type") == "pouls"]
    assert len(rappels) == 1                            # remplacé, pas dupliqué


def test_budget_jour_plafonne_le_run(monkeypatch=None):
    _reset()
    pouls.BUDGET_JOUR_TOKENS = 5000
    try:
        with _CoAgentMock(_cr(), tokens_journalises=0) as m:
            _run(pouls.battre(None))
        # 1er battement : budget restant = plafond entier.
        assert m.appels[0]["budget_tokens"] == 5000
    finally:
        pouls.BUDGET_JOUR_TOKENS = 0


def test_budget_jour_epuise_ne_bat_pas():
    _reset()
    pouls.BUDGET_JOUR_TOKENS = 5000
    try:
        # On simule 5000 tokens « pouls » déjà dépensés aujourd'hui (UTC).
        journal_usage.enregistrer(modele="free/test", etiquette="pouls",
                                  tokens_in=5000, tokens_out=0, cout_usd=0)
        with _CoAgentMock(_cr()) as m:
            r = _run(pouls.battre(None))
        assert r["statut"] == "budget_jour_atteint"
        assert m.appels == []                           # le co-agent n'est même pas réveillé
        assert not [x for x in proactif.lister(limite=10) if x.get("type") == "pouls"]
    finally:
        pouls.BUDGET_JOUR_TOKENS = 0


def test_budget_illimite_passe_none_au_coagent():
    _reset()
    assert pouls.BUDGET_JOUR_TOKENS == 0                # défaut illimité
    with _CoAgentMock(_cr()) as m:
        _run(pouls.battre(None))
    assert m.appels[0]["budget_tokens"] is None         # → défaut du co-agent (S66)


def test_echec_coagent_remonte_sans_rappel():
    _reset()
    with _CoAgentMock(_cr(ok=False, synthese="", erreur="Aucun modèle disponible.")):
        r = _run(pouls.battre(None))
    assert r["ok"] is False and r["statut"] == "echec"
    assert not [x for x in proactif.lister(limite=10) if x.get("type") == "pouls"]


def test_synthese_vide_pas_de_rappel():
    _reset()
    with _CoAgentMock(_cr(synthese="   ")):
        r = _run(pouls.battre(None))
    assert r["statut"] == "rien_a_dire"                 # honnêteté : pas de rappel vide
    assert not [x for x in proactif.lister(limite=10) if x.get("type") == "pouls"]


def test_objectif_personnalise_transmis():
    _reset()
    with _CoAgentMock(_cr()) as m:
        _run(pouls.battre(None, objectif="Vérifie les impayés"))
    assert m.appels[0]["objectif"] == "Vérifie les impayés"


if __name__ == "__main__":
    for nom, fn in list(globals().items()):
        if nom.startswith("test_") and callable(fn):
            fn()
            print(f"  ✓ {nom}")
    print("\n✅ TOUS LES TESTS PASSENT")
