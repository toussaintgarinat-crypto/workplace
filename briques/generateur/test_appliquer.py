"""« Appliquer l'incrément » (S32/S34) — fonctions pures, aucun réseau.

Écrit à l'origine comme script autonome (`def run()`), donc jamais exécuté par le filet.
Converti en tests pytest le 2026-07-28 — les 7 scénarios sont conservés à l'identique.
Le remplacement de `gateway.appeler_llm` passe désormais par `monkeypatch` : le script
d'origine restaurait à la main, et un échec au milieu laissait la Gateway mockée pour la
suite du fichier.
"""
import asyncio

import pytest

import appliquer
import gateway
from gabarit import generer_html

PLAN = {"nom_app": "Cabinet", "entites": [
    {"id": "planning", "nom": "Planning"},
    {"id": "devis", "nom": "Devis"},
]}

PROPOSITION = {"modules_proposes": [
    {"nom": "Gestion des absences", "raison": "planning saturé"},
]}


def test_un_module_propose_devient_une_entite_crud():
    plan2, ajoutes = appliquer.construire_plan_enrichi(PLAN, PROPOSITION)
    assert ajoutes == [{"id": "gestion-des-absences", "nom": "Gestion des absences"}], ajoutes
    nouvelle = next(e for e in plan2["entites"] if e["id"] == "gestion-des-absences")
    assert nouvelle["description"] == "planning saturé", nouvelle
    assert nouvelle["origine"] == "increment", nouvelle
    assert {c["cle"] for c in nouvelle["champs"]} == {
        "libelle", "statut", "date", "montant", "notes"}, nouvelle["champs"]
    assert len(plan2["entites"]) == 3
    assert PLAN["entites"] != plan2["entites"], "plan d'origine non muté en place"


def test_idempotence_un_module_deja_present_n_est_pas_duplique():
    prop = {"modules_proposes": [
        {"nom": "Planning", "raison": "déjà là"},           # id 'planning' existe
        {"nom": "Gestion des absences", "raison": "neuf"},   # nouveau
    ]}
    plan, ajoutes = appliquer.construire_plan_enrichi(PLAN, prop)
    assert [a["id"] for a in ajoutes] == ["gestion-des-absences"], ajoutes
    assert sum(1 for e in plan["entites"] if e["id"] == "planning") == 1, "pas de doublon"


def test_honnetete_une_proposition_sans_module_n_ajoute_rien():
    plan, ajoutes = appliquer.construire_plan_enrichi(
        PLAN, {"modules_proposes": [], "source": "heuristique"})
    assert ajoutes == []
    assert len(plan["entites"]) == 2, "plan inchangé sans proposition"


def test_robustesse_entrees_degenerees_tolerees_sans_exception():
    sale = {"modules_proposes": [{"nom": "  "}, "pas un dict",
                                 {"raison": "sans nom"}, {"nom": "Suivi RGPD"}]}
    _, ajoutes = appliquer.construire_plan_enrichi({}, sale)
    assert [a["id"] for a in ajoutes] == ["suivi-rgpd"], ajoutes
    assert appliquer.construire_plan_enrichi(None, None) == ({"entites": []}, []), \
        "plan/proposition None tolérés"


def test_le_plan_enrichi_se_regenere_reellement_en_html():
    """Branche le module sur le vrai moteur de rendu : le nouveau module doit apparaître."""
    plan, _ = appliquer.construire_plan_enrichi(PLAN, PROPOSITION)
    html = generer_html({"nom_entreprise": "Cabinet"}, plan)
    assert "Gestion des absences" in html


def test_schema_fin_llm_champs_specifiques_au_lieu_du_generique(monkeypatch):
    async def faux_schema(prompt, langue="fr"):
        return {"icone": "bi-calendar-x", "champs": [
            {"cle": "salarie", "label": "Salarié", "type": "texte"},
            {"cle": "motif", "label": "Motif", "type": "statut",
             "options": ["Congé", "Maladie", "RTT"]},
            {"cle": "debut", "label": "Début", "type": "date"},
        ]}

    monkeypatch.setattr(gateway, "appeler_llm", faux_schema)
    plan, ajoutes = asyncio.run(appliquer.construire_plan_enrichi_llm(
        PLAN, PROPOSITION, {"nom_entreprise": "Cabinet"}))
    nv = next(e for e in plan["entites"] if e["id"] == "gestion-des-absences")
    assert ajoutes[0]["schema"] == "llm", ajoutes
    assert nv["icone"] == "bi-calendar-x", nv
    assert {c["cle"] for c in nv["champs"]} == {"salarie", "motif", "debut"}, nv["champs"]
    motif = next(c for c in nv["champs"] if c["cle"] == "motif")
    assert motif["type"] == "statut" and motif["options"] == ["Congé", "Maladie", "RTT"], motif


def test_repli_generique_quand_le_llm_est_en_panne(monkeypatch):
    """Gateway KO → schéma CRUD générique, source=generique, aucune exception remontée."""
    async def schema_ko(prompt, langue="fr"):
        raise RuntimeError("Gateway indisponible")

    monkeypatch.setattr(gateway, "appeler_llm", schema_ko)
    plan, ajoutes = asyncio.run(appliquer.construire_plan_enrichi_llm(
        PLAN, PROPOSITION, {"nom_entreprise": "Cabinet"}))
    nv = next(e for e in plan["entites"] if e["id"] == "gestion-des-absences")
    assert ajoutes[0]["schema"] == "generique", ajoutes
    assert {c["cle"] for c in nv["champs"]} == {
        "libelle", "statut", "date", "montant", "notes"}, nv["champs"]
