"""S241 — branches SQL : chaque branche ne voit QUE les lignes de l'utilisateur."""
import unicodedata

from sqlalchemy import text

from app import recherche_documents as rd
from app.db import SessionLocal
from tests.s241_outils import ajouter_article, ajouter_document, base, integration  # noqa: F401

TOUT = frozenset({"document", "kb"})


def test_extrait_autour_centre_sur_le_premier_mot():
    texte = "x" * 500 + " chaudière " + "y" * 500
    extrait = rd.extrait_autour(texte, ["chaudiere"], 100)
    assert "chaudière" in extrait and len(extrait) <= 102  # + « … » éventuels


def test_extrait_autour_texte_nfd_garde_les_positions():
    texte = unicodedata.normalize("NFD", "é" * 200 + "x" * 300 + " chaudière " + "y" * 500)
    extrait = rd.extrait_autour(texte, ["chaudiere"], 100)
    assert "chaudière" in unicodedata.normalize("NFC", extrait)


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
    k = await ajouter_article("alice", "Procédure", "Plan de maintenance préventive.")
    db = await ajouter_document("bob", "Maintenance", "Contrat de maintenance de Bob.")
    async with SessionLocal() as s:
        assert await rd.plein_texte(s, "maintenence", "alice", TOUT, 10) == []
        assert set(await rd.trigrammes(s, "maintenence", "alice", TOUT, 10)) == {("document", d), ("kb", k)}
        assert await rd.trigrammes(s, "maintenence", "alice", frozenset({"kb"}), 10) == [("kb", k)]
        assert await rd.trigrammes(s, "maintenence", "bob", TOUT, 10) == [("document", db)]


@integration
async def test_requete_trigrammes_utilise_l_index_gin(base):
    await ajouter_document("alice", "Contrat", "Contrat de maintenance annuelle.")
    await ajouter_document("bob", "Autre", "Rien de commun.")
    async with SessionLocal() as s:
        await s.execute(text("SET LOCAL enable_seqscan = off"))
        # Sur 2 lignes le planificateur préfère idx_documents_user (user_id) à l'index trigramme
        # (coût GIN estimé plus haut) ; on l'écarte (DDL transactionnel, annulé en fin de session)
        # pour vérifier que l'index trigramme est UTILISABLE par la requête de production.
        await s.execute(text("DROP INDEX idx_documents_user"))
        sql = rd.sql_trigrammes([rd.TABLES["document"]])
        await s.execute(text(f"SET LOCAL pg_trgm.word_similarity_threshold = {rd.SEUIL_TRIGRAMME}"))
        plan = "\n".join(r[0] for r in (await s.execute(
            text("EXPLAIN " + sql), {"moi": "alice", "q": "maintenence", "limite": 10})).all())
    assert "idx_documents_texte_trgm" in plan, plan


@integration
async def test_exacts_trouvent_la_reference_et_signalent_le_titre(base):
    titre = await ajouter_document("alice", "FAC-2026-0042", "Facture de mars.")
    corps = await ajouter_document("alice", "Relance", "Rappel : FAC-2026-0042 impayée.")
    await ajouter_document("alice", "Autre", "FAC-2026-00421 n'est pas la même.")
    k = await ajouter_article("alice", "Procédure FAC-2026-0042", "Voir la facture.")
    db = await ajouter_document("bob", "Facture", "Bob : FAC-2026-0042 réglée.")
    async with SessionLocal() as s:
        trouves = await rd.exacts(s, ["FAC-2026-0042"], "alice", TOUT, 10)
        assert set(trouves) == {("document", titre), ("document", corps), ("kb", k)}
        assert trouves[("document", titre)].dans_titre is True
        assert trouves[("document", corps)].dans_titre is False
        assert trouves[("kb", k)].dans_titre is True
        assert set(await rd.exacts(s, ["FAC-2026-0042"], "bob", TOUT, 10)) == {("document", db)}


@integration
async def test_existants_et_fiches_recoupent_par_utilisateur(base):
    a = await ajouter_document("alice", "A", "texte A")
    b = await ajouter_document("bob", "B", "texte B")
    async with SessionLocal() as s:
        assert await rd.existants(s, [("document", a), ("document", b)], "alice") == {("document", a)}
        fiches = await rd.fiches(s, [("document", a), ("document", b)], "alice")
        assert set(fiches) == {("document", a)} and fiches[("document", a)].titre == "A"
