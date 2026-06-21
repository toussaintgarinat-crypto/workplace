"""S91 ↔ S90 — preuve d'intégration : une skill fabriquée par la brique `dev` devient une
**capacité différée** de la PORTE du Cœur, listée et chargeable via `competence_charger`.

On n'imite RIEN : on importe le vrai code du Cœur (`core/outils.py` + `core/catalogue.py`,
livrés en S90) et on lui présente un registre factice dont le manifest `dev` porte les capacités
issues de `skills_atelier.capacite_pour(...)`. Ainsi on prouve le contrat de bout en bout :
niveau-1 → retirée du contexte → listée dans `competence_charger` → son schéma se charge.

Autonome (aucun réseau ; GATEWAY_KEY factice posée AVANT d'importer le Cœur).
    $ cd briques/dev && python3 test_skills_porte.py
"""
import asyncio
import json
import os
import sys

os.environ.setdefault("GATEWAY_KEY", "test")        # core importe llm_pipeline indirectement
# Chemin du Cœur ajouté EN FIN (append) : les modules locaux de la brique (main, domaine…)
# gardent la priorité ; on ne résout via le Cœur que `outils`/`catalogue` (absents ici).
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", "core"))

import skills_atelier as sk     # noqa: E402  (brique dev, local)
import outils                   # noqa: E402  (Cœur, S90)


class _Registre:
    def __init__(self, briques):
        self.briques = briques


def _registre_avec_skills():
    """Registre où la brique `dev` expose 2 skills comme capacités de niveau-1 (porte)."""
    skill_a = {"name": "revue-securite", "description": "Audite un diff (secrets, injections).",
               "mcp": ["github"]}
    skill_b = {"name": "persona-architect", "description": "Conçoit le plan avant le code."}
    capacites = [sk.capacite_pour(skill_a), sk.capacite_pour(skill_b)]
    return _Registre({"dev": {"nom": "dev", "port": 5950, "capacites": capacites}})


def test_capacite_pour_est_niveau1_et_lecture():
    cap = sk.capacite_pour({"name": "revue-securite", "description": "audit"})
    assert cap["nom"] == "skill_revue_securite"
    assert cap["niveau"] == 1 and cap["action"] is False
    assert cap["chemin"] == "/skills/revue-securite/corps"


def test_skill_differee_derriere_competence_charger():
    reg = _registre_avec_skills()
    # Porte OFF (défaut, ex. MCP) : la skill est un outil pleinement présenté.
    noms_off = [s["function"]["name"] for s in outils.outils_pour(reg)]
    assert "skill_revue_securite" in noms_off and outils.META_CHARGER not in noms_off
    # Porte ON : la skill niveau-1 est DIFFÉRÉE, remplacée par competence_charger qui la liste.
    specs_on = outils.outils_pour(reg, porte=True)
    noms_on = [s["function"]["name"] for s in specs_on]
    assert "skill_revue_securite" not in noms_on
    assert "skill_persona_architect" not in noms_on
    assert outils.META_CHARGER in noms_on
    meta = next(s for s in specs_on if s["function"]["name"] == outils.META_CHARGER)
    desc = meta["function"]["description"]
    assert "skill_revue_securite" in desc and "Audite un diff" in desc   # listée pour le LLM


def test_competence_charger_rend_le_schema_de_la_skill():
    reg = _registre_avec_skills()
    out = asyncio.run(outils.executer(outils.META_CHARGER,
                                      {"nom": "skill_revue_securite"}, reg))
    data = json.loads(out)
    assert data["ok"] is True and data["chargee"] == "skill_revue_securite"
    assert data["outil"]["name"] == "skill_revue_securite"


def test_chargee_reapparait_en_outil_appelable():
    reg = _registre_avec_skills()
    noms = [s["function"]["name"]
            for s in outils.outils_pour(reg, chargees={"skill_revue_securite"}, porte=True)]
    assert "skill_revue_securite" in noms          # chargée → schéma complet, appelable
    assert "skill_persona_architect" not in noms   # l'autre reste différée
    assert outils.META_CHARGER in noms             # il reste une skill derrière la porte


if __name__ == "__main__":
    for nom, fn in list(globals().items()):
        if nom.startswith("test_") and callable(fn):
            fn()
            print(f"  ✓ {nom}")
    print("\n✅ TOUS LES TESTS PASSENT")
