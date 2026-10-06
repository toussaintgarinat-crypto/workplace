"""S241 — schéma de recherche : idempotent, sans accents, sans casse."""
from sqlalchemy import text

from tests.s241_outils import ajouter_article, ajouter_document, base, integration  # noqa: F401

pytestmark = integration


async def test_schema_rejouable(base):
    from app.db import engine
    from scripts.init_db import appliquer_schema

    async with engine.begin() as conn:
        await appliquer_schema(conn)  # deuxième passage : aucune erreur
        n = (await conn.execute(text(
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_name IN ('documents', 'kb_articles') AND column_name = 'recherche_tsv'"
        ))).scalar_one()
    assert n == 2


async def test_plein_texte_sans_accents_ni_casse(base):
    from app.db import engine

    await ajouter_document("u1", "Évaluation énergétique", "Rapport de la maison Durand.")
    await ajouter_article("u1", "Procédure", "Relancer les CLIENTS en retard.", '["relances"]')
    async with engine.connect() as conn:
        docs = (await conn.execute(text(
            "SELECT count(*) FROM documents "
            "WHERE recherche_tsv @@ plainto_tsquery('simple', forge_unaccent('evaluation'))"
        ))).scalar_one()
        kb = (await conn.execute(text(
            "SELECT count(*) FROM kb_articles "
            "WHERE recherche_tsv @@ plainto_tsquery('french', forge_unaccent('relances'))"
        ))).scalar_one()
    assert docs == 1
    assert kb == 1  # les tags sont indexés (corps en `french` : la requête doit l'être aussi)
