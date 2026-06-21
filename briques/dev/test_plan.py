"""S88 — le plan BMAD : structuration + repli honnête local (sans LLM, déterministe).

La preuve LIVE avec un vrai LLM (plan lisible en FR) se fait à part ; ici on prouve que le
plan est TOUJOURS structuré (mini-PRD + stories + domaine) et que l'absence de LLM ne casse
rien (repli honnête, jamais d'exception, `genere_par="local"`)."""
import asyncio

import plan


def test_structurer_decoupe_les_trois_sections():
    texte = ("## Mini-PRD\nLivrer un champ référence.\n"
             "## Stories\n- modéliser le domaine\n- implémenter\n- tester\n"
             "## Domaine (DDD)\nEntité Référence, agrégat Message.")
    d = plan._structurer(texte, "ia")
    assert d["prd"] == "Livrer un champ référence."
    assert d["stories"] == ["modéliser le domaine", "implémenter", "tester"]
    assert "Référence" in d["domaine"]
    assert d["genere_par"] == "ia"


def test_plan_local_structure_et_honnete():
    d = plan.plan_local("ajouter un champ référence", "mail")
    assert d["genere_par"] == "local"
    assert d["prd"] and len(d["stories"]) >= 3 and d["domaine"]
    assert "mail" in d["texte"]
    # Le domaine est imposé EN PREMIER dans les stories (DDD : domaine pur avant la technique).
    assert "domaine" in d["stories"][0].lower()


def test_concevoir_repli_local_sans_llm():
    # GATEWAY_MODEL vidé (conftest) → repli honnête, aucun appel réseau, plan exploitable.
    d = asyncio.run(plan.concevoir("ajouter un filtre par entreprise", "mail"))
    assert d["genere_par"] == "local"
    assert d["prd"] and d["stories"] and d["domaine"]
