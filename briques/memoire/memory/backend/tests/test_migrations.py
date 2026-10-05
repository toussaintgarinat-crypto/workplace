import uuid

import pytest
from sqlalchemy import select, text

from app import database as db_module
from app.migrations_demarrage import appliquer_migrations, vecteur_graine_42
from app.models.node import IpCraStage, Node, NodeType
from tests.outils_embedder import vecteur_factice

pytestmark = pytest.mark.asyncio


class TestMigrations:
    async def test_idempotente(self):
        async with db_module.engine.begin() as conn:
            await appliquer_migrations(conn)
            await appliquer_migrations(conn)

    async def test_extensions_et_colonne(self):
        async with db_module.engine.begin() as conn:
            ext = set((await conn.execute(text("SELECT extname FROM pg_extension"))).scalars())
            assert {"vector", "unaccent", "pg_trgm"} <= ext
            col = await conn.execute(text(
                "SELECT 1 FROM information_schema.columns WHERE table_name='nodes' AND column_name='recherche_tsv'"
            ))
            assert col.scalar() == 1

    async def test_tsv_sans_accents_et_stemme(self, test_space):
        async with db_module.async_session_factory() as db:
            node = Node(space_id=uuid.UUID(test_space["id"]), type=NodeType.input, ipcra_stage=IpCraStage.input,
                        title="Réunion budget", content_md="Les factures fournisseurs")
            db.add(node)
            await db.commit()
            r = await db.execute(text(
                "SELECT recherche_tsv @@ to_tsquery('simple', 'reunion'),"
                "       recherche_tsv @@ to_tsquery('french', 'facture')"
                " FROM nodes WHERE id = :id"), {"id": node.id})
            assert tuple(r.one()) == (True, True)

    async def test_nettoie_la_graine_42_et_seulement_elle(self, test_space):
        sid = uuid.UUID(test_space["id"])
        async with db_module.async_session_factory() as db:
            empoisonne = Node(space_id=sid, type=NodeType.input, ipcra_stage=IpCraStage.input,
                              title="Écrit pendant une panne", content_md="x", embedding=vecteur_graine_42())
            sain = Node(space_id=sid, type=NodeType.input, ipcra_stage=IpCraStage.input,
                        title="Sain", content_md="y", embedding=vecteur_factice("sain"))
            db.add_all([empoisonne, sain])
            await db.commit()
            ids = (empoisonne.id, sain.id)
        async with db_module.engine.begin() as conn:
            await appliquer_migrations(conn)
        async with db_module.async_session_factory() as db:
            vecs = dict((await db.execute(select(Node.id, Node.embedding).where(Node.id.in_(ids)))).all())
        assert vecs[ids[0]] is None
        assert vecs[ids[1]] is not None

    async def test_souvenir_geant_inserable_et_trouve(self, client, auth_headers, test_space):
        """to_tsvector échoue au-delà de 1 Mo : sans plafond, la colonne générée ferait
        échouer tout INSERT d'une note géante."""
        contenu = "zorglub " + " ".join(f"mot{i}" for i in range(170_000))
        assert len(contenu) > 1_400_000
        r = await client.post(f"/api/v1/spaces/{test_space['id']}/nodes",
                              json={"type": "input", "title": "Note géante", "content_md": contenu},
                              headers=auth_headers)
        assert r.status_code == 201, r.text[:300]
        r = await client.get(f"/api/v1/spaces/{test_space['id']}/search", params={"q": "zorglub"},
                             headers=auth_headers)
        assert r.status_code == 200, r.text[:300]
        assert r.json()[0]["title"] == "Note géante"
