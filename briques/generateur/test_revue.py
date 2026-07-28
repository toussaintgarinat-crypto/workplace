"""« App vivante » (S31) — brique `donnees` et LLM mockés, aucun réseau.

Écrit à l'origine comme script autonome (`def run()`), donc jamais exécuté par le filet.
Converti en tests pytest le 2026-07-28 — les 5 scénarios sont conservés à l'identique.
Les scénarios 4 et 5 réutilisaient la variable `usage` produite par le scénario 1 : elle
devient une **fixture**, ce qui les rend indépendants de l'ordre d'exécution.
"""
import asyncio

import httpx
import pytest

import revue as rv

# La VRAIE classe, figée à l'import : un brancheur créé après un premier branchement
# capturerait sinon le FAUX client précédent (cf. le commentaire jumeau de test_pont_crm.py).
_VRAI_CLIENT = httpx.Client

PLAN = {"entites": [
    {"id": "planning", "nom": "Planning"},
    {"id": "devis", "nom": "Devis"},
    {"id": "factures", "nom": "Factures"},
]}

ENTITES = {
    "planning": [{"_id": f"p{i}"} for i in range(40)],   # massivement utilisé
    "devis": [],                                          # dormant (0 enr.)
    "factures": [{"_id": "f1"}, {"_id": "f2"}],           # non consenti → invisible
}

AUDIT = {"nom_entreprise": "Atelier Test",
         "problemes": {"pareto": {"vital_few": ["devis"]}},
         "priorites": {"moscow": {"must": ["Devis rapides"]}}}


def _transport(etat):
    def handler(request: httpx.Request) -> httpx.Response:
        etat["calls"].append(f"{request.method} {request.url.path}")
        if etat.get("donnees_ko"):
            raise httpx.ConnectError("donnees down")
        if request.method == "GET" and request.url.path.endswith("/export"):
            return httpx.Response(200, json={"entites": etat["entites"]})
        return httpx.Response(404, json={"path": request.url.path})
    return httpx.MockTransport(handler)


@pytest.fixture
def donnees(monkeypatch):
    """Branche `revue` sur une fausse brique `donnees`."""
    def brancher(**options):
        etat = {"entites": ENTITES, "calls": [], **options}
        transport = _transport(etat)

        def faux_client(*a, **k):
            k.pop("timeout", None)
            return _VRAI_CLIENT(transport=transport)

        monkeypatch.setattr(rv.httpx, "Client", faux_client)
        return etat
    return brancher


@pytest.fixture
def usage(donnees):
    """La mesure du scénario 1, dont les propositions (4 et 5) ont besoin."""
    donnees()
    return rv.mesurer_usage("app-1", PLAN, {"actif": True, "entites": ["planning", "devis"]})


def test_mesure_consentie_pareto_trie_dormants_reperes_non_consenties_invisibles(donnees):
    donnees()
    u = rv.mesurer_usage("app-1", PLAN, {"actif": True, "entites": ["planning", "devis"]})
    assert u["consenti"] and u["total_enregistrements"] == 40, u
    assert u["compte"] == {"planning": 40, "devis": 0}, u["compte"]
    assert u["pareto"][0]["entite_id"] == "planning" and u["pareto"][0]["part_pct"] == 100.0, u["pareto"]
    assert u["modules_dormants"] == ["devis"], u["modules_dormants"]
    assert "factures" in u["non_consenties"], u["non_consenties"]
    assert "factures" not in u["compte"], "une entité non consentie ne doit pas être mesurée"


def test_consentement_non_aucune_mesure_ni_appel_reseau(donnees):
    """Souveraineté : partage désactivé ⇒ on ne touche même pas au réseau."""
    etat = donnees()
    u = rv.mesurer_usage("app-1", PLAN, {"actif": False, "entites": ["planning"]})
    assert not u["consenti"] and u["total_enregistrements"] == 0, u
    assert etat["calls"] == [], "aucun appel réseau si partage désactivé"


def test_donnees_injoignable_best_effort_mesure_vide_sans_exception(donnees):
    donnees(donnees_ko=True)
    u = rv.mesurer_usage("app-1", PLAN, {"actif": True, "entites": ["planning"]})
    assert u["consenti"] and u["total_enregistrements"] == 0, u
    assert "échouée" in u["message"], u["message"]


def test_proposition_llm_normalisee(monkeypatch, usage):
    async def faux_llm(prompt):
        return {
            "resume": "Le planning explose, les devis dorment.",
            "pareto_commentaire": "Le Pareto a basculé vers le Planning.",
            "modules_proposes": [{"nom": "Disponibilités", "raison": "planning saturé"}],
            "modules_sous_utilises": [{"module": "Devis", "justification": "0 usage"}],
        }

    monkeypatch.setattr(rv, "appeler_llm", faux_llm)
    prop = asyncio.run(rv.proposer_increment(AUDIT, PLAN, usage, []))
    assert prop["source"] == "llm", prop
    assert prop["modules_proposes"][0]["nom"] == "Disponibilités", prop
    # clés alternatives normalisées (module/justification → nom/raison)
    assert prop["modules_sous_utilises"][0] == {"nom": "Devis", "raison": "0 usage"}, \
        prop["modules_sous_utilises"]


def test_repli_heuristique_quand_le_llm_est_en_panne(monkeypatch, usage):
    async def llm_ko(prompt):
        raise RuntimeError("Gateway indisponible")

    monkeypatch.setattr(rv, "appeler_llm", llm_ko)
    prop = asyncio.run(rv.proposer_increment(AUDIT, PLAN, usage, []))
    assert prop["source"] == "heuristique", prop
    assert "Devis" in {m["nom"] for m in prop["modules_sous_utilises"]}, prop["modules_sous_utilises"]
    assert "Planning" in prop["pareto_commentaire"], prop["pareto_commentaire"]
