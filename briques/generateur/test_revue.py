"""Preuve offline de « l'app vivante » (S31) — brique donnees mockée, LLM mocké.

On vérifie le module `revue` :

  1. **mesure consentie** : seules les entités en liste blanche sont comptées, le
     Pareto est trié, les modules **dormants** (0 enr.) sont repérés ; les entités
     NON consenties restent invisibles (souveraineté) ;
  2. **consentement = Non** → AUCUNE mesure, aucun appel réseau (souveraineté) ;
  3. **donnees injoignable** → best-effort, consenti=True mais mesure vide, 0 exception ;
  4. **proposition LLM** : `proposer_increment` renvoie la proposition du LLM (source=llm),
     normalisée (modules_proposes / sous_utilises en {nom, raison}) ;
  5. **repli heuristique** : LLM en panne → source=heuristique, les modules dormants
     remontent en modules_sous_utilises, AUCUNE exception.

Lancer : `python3 test_revue.py`.
"""
import asyncio
import json

import httpx


# ── Faux backend (brique donnees) ────────────────────────────────────────────────

def make_transport(state):
    def handler(request: httpx.Request) -> httpx.Response:
        state["calls"].append(f"{request.method} {request.url.path}")
        if state.get("donnees_ko"):
            raise httpx.ConnectError("donnees down")
        if request.method == "GET" and request.url.path.endswith("/export"):
            return httpx.Response(200, json={"entites": state["entites"]})
        return httpx.Response(404, json={"path": request.url.path})
    return httpx.MockTransport(handler)


def patch_client(rv, state):
    transport = make_transport(state)
    orig = httpx.Client

    def fake_client(*a, **k):
        k.pop("timeout", None)
        return orig(transport=transport)

    rv.httpx.Client = fake_client
    return orig


# ── Données communes ─────────────────────────────────────────────────────────────

PLAN = {"entites": [
    {"id": "planning", "nom": "Planning"},
    {"id": "devis", "nom": "Devis"},
    {"id": "factures", "nom": "Factures"},
]}

ENTITES = {
    "planning": [{"_id": f"p{i}"} for i in range(40)],  # massivement utilisé
    "devis": [],                                         # dormant (0 enr.)
    "factures": [{"_id": "f1"}, {"_id": "f2"}],          # non consenti → invisible
}

AUDIT = {"nom_entreprise": "Atelier Test",
         "problemes": {"pareto": {"vital_few": ["devis"]}},
         "priorites": {"moscow": {"must": ["Devis rapides"]}}}


def run():
    import revue as rv
    orig_client = httpx.Client
    ok = 0

    # 1) Mesure consentie : planning + devis partagés, factures NON.
    st = {"entites": ENTITES, "calls": []}
    patch_client(rv, st)
    usage = rv.mesurer_usage("app-1", PLAN, {"actif": True, "entites": ["planning", "devis"]})
    rv.httpx.Client = orig_client
    assert usage["consenti"] and usage["total_enregistrements"] == 40, usage
    assert usage["compte"] == {"planning": 40, "devis": 0}, usage["compte"]
    assert usage["pareto"][0]["entite_id"] == "planning" and usage["pareto"][0]["part_pct"] == 100.0, usage["pareto"]
    assert usage["modules_dormants"] == ["devis"], usage["modules_dormants"]
    assert "factures" in usage["non_consenties"], usage["non_consenties"]
    assert "factures" not in usage["compte"], "une entité non consentie ne doit pas être mesurée"
    print("✅ 1. mesure consentie : Pareto trié (planning 40/100%), devis dormant, factures invisible (souveraineté)")
    ok += 1

    # 2) Consentement = Non → aucune mesure, aucun appel réseau.
    st2 = {"entites": ENTITES, "calls": []}
    patch_client(rv, st2)
    usage2 = rv.mesurer_usage("app-1", PLAN, {"actif": False, "entites": ["planning"]})
    rv.httpx.Client = orig_client
    assert not usage2["consenti"] and usage2["total_enregistrements"] == 0, usage2
    assert st2["calls"] == [], "aucun appel réseau si partage désactivé"
    print("✅ 2. consentement Non : aucune mesure, aucun appel réseau (souveraineté)")
    ok += 1

    # 3) donnees injoignable → best-effort.
    st3 = {"entites": ENTITES, "calls": [], "donnees_ko": True}
    patch_client(rv, st3)
    usage3 = rv.mesurer_usage("app-1", PLAN, {"actif": True, "entites": ["planning"]})
    rv.httpx.Client = orig_client
    assert usage3["consenti"] and usage3["total_enregistrements"] == 0, usage3
    assert "échouée" in usage3["message"], usage3["message"]
    print("✅ 3. donnees injoignable : best-effort, mesure vide, aucune exception")
    ok += 1

    # 4) Proposition LLM (mockée).
    async def faux_llm(prompt):
        return {
            "resume": "Le planning explose, les devis dorment.",
            "pareto_commentaire": "Le Pareto a basculé vers le Planning.",
            "modules_proposes": [{"nom": "Disponibilités", "raison": "planning saturé"}],
            "modules_sous_utilises": [{"module": "Devis", "justification": "0 usage"}],
        }
    orig_llm = rv.appeler_llm
    rv.appeler_llm = faux_llm
    prop = asyncio.run(rv.proposer_increment(AUDIT, PLAN, usage, []))
    rv.appeler_llm = orig_llm
    assert prop["source"] == "llm", prop
    assert prop["modules_proposes"][0]["nom"] == "Disponibilités", prop
    # clés alternatives normalisées (module/justification → nom/raison)
    assert prop["modules_sous_utilises"][0] == {"nom": "Devis", "raison": "0 usage"}, prop["modules_sous_utilises"]
    print("✅ 4. proposition LLM : source=llm, modules normalisés ({nom, raison})")
    ok += 1

    # 5) Repli heuristique (LLM en panne).
    async def llm_ko(prompt):
        raise RuntimeError("Gateway indisponible")
    rv.appeler_llm = llm_ko
    prop2 = asyncio.run(rv.proposer_increment(AUDIT, PLAN, usage, []))
    rv.appeler_llm = orig_llm
    assert prop2["source"] == "heuristique", prop2
    noms_dormants = {m["nom"] for m in prop2["modules_sous_utilises"]}
    assert "Devis" in noms_dormants, prop2["modules_sous_utilises"]
    assert "Planning" in prop2["pareto_commentaire"], prop2["pareto_commentaire"]
    print("✅ 5. repli heuristique : source=heuristique, Devis dormant signalé, aucune exception")
    ok += 1

    print(f"\n{ok}/5 scénarios OK")


if __name__ == "__main__":
    run()
