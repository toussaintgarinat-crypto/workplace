"""S241 — branches SQL : chaque branche ne voit QUE les lignes de l'utilisateur."""
from app import recherche_documents as rd
from app.db import SessionLocal
from tests.s241_outils import ajouter_article, ajouter_document, base, integration  # noqa: F401

TOUT = frozenset({"document", "kb"})


def test_extrait_autour_centre_sur_le_premier_mot():
    texte = "x" * 500 + " chaudière " + "y" * 500
    extrait = rd.extrait_autour(texte, ["chaudiere"], 100)
    assert "chaudière" in extrait and len(extrait) <= 102  # + « … » éventuels


def test_extrait_autour_sans_mot_trouve_prend_le_debut():
    assert rd.extrait_autour("abc def", ["zzz"], 3) == "abc…"


@integration
async def test_plein_texte_isole_et_couvre_les_deux_tables(base):
    d = await ajouter_document("alice", "Devis toiture", "Réfection de la toiture, 12 000 €.")
    k = await ajouter_article("alice", "Toiture : procédure", "Vérifier les tuiles.")
    await ajouter_document("bob", "Devis toiture Bob", "Toiture de Bob.")
    async with SessionLocal() as s:
        cles = await rd.plein_texte(s, "toiture", "alice", TOUT, 10)
        assert set(cles) == {("document", d), ("kb", k)}
        assert await rd.plein_texte(s, "toiture", "alice", frozenset({"kb"}), 10) == [("kb", k)]


@integration
async def test_trigrammes_rattrapent_la_faute_de_frappe(base):
    d = await ajouter_document("alice", "Contrat", "Contrat de maintenance annuelle.")
    async with SessionLocal() as s:
        assert await rd.plein_texte(s, "maintenence", "alice", TOUT, 10) == []
        assert await rd.trigrammes(s, "maintenence", "alice", TOUT, 10) == [("document", d)]
        assert await rd.trigrammes(s, "maintenence", "bob", TOUT, 10) == []


@integration
async def test_exacts_trouvent_la_reference_et_signalent_le_titre(base):
    titre = await ajouter_document("alice", "FAC-2026-0042", "Facture de mars.")
    corps = await ajouter_document("alice", "Relance", "Rappel : FAC-2026-0042 impayée.")
    await ajouter_document("alice", "Autre", "FAC-2026-00421 n'est pas la même.")
    async with SessionLocal() as s:
        trouves = await rd.exacts(s, ["FAC-2026-0042"], "alice", TOUT, 10)
        assert set(trouves) == {("document", titre), ("document", corps)}
        assert trouves[("document", titre)].dans_titre is True
        assert trouves[("document", corps)].dans_titre is False
        assert await rd.exacts(s, ["FAC-2026-0042"], "bob", TOUT, 10) == {}


@integration
async def test_existants_et_fiches_recoupent_par_utilisateur(base):
    a = await ajouter_document("alice", "A", "texte A")
    b = await ajouter_document("bob", "B", "texte B")
    async with SessionLocal() as s:
        assert await rd.existants(s, [("document", a), ("document", b)], "alice") == {("document", a)}
        fiches = await rd.fiches(s, [("document", a), ("document", b)], "alice")
        assert set(fiches) == {("document", a)} and fiches[("document", a)].titre == "A"
