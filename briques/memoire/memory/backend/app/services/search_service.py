"""Recherche Mémoire (S238) : références exactes, branche lexicale, branche vectorielle.

L'embedder peut être en panne : la recherche reste alors lexicale (mode « lexical ») au lieu
de renvoyer du bruit ou rien. Les classements sont fusionnés par rangs (RRF), jamais en
additionnant des scores de natures différentes ; les références exactes passent devant.
"""
from dataclasses import dataclass
from typing import Optional
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.embedder import Embedder, EmbeddingIndisponible
from app.models.node import Node
from app.schemas.search import SearchResult
from app.services.recherche_conditions import Filtres
from app.services.recherche_fusion import extraire_references, ordonner
from app.services.recherche_lexicale import (
    classement_plein_texte, classement_trigramme, correspondances_exactes,
)
from app.services.recherche_vectorielle import classement_vectoriel

CANDIDATS_MIN = 50


@dataclass
class ResultatRecherche:
    mode: str  # hybride | lexical
    resultats: list[SearchResult]


def _valeur(v, defaut=None):
    return v.value if hasattr(v, "value") else (v if v is not None else defaut)


class SearchService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.embedder = Embedder()

    async def hybrid_search(
        self,
        space_id: UUID,
        query: str,
        type_filter: Optional[str] = None,
        stage_filter: Optional[str] = None,
        tier_filter: Optional[str] = None,
        limit: int = 20,
    ) -> ResultatRecherche:
        if not query or not query.strip():
            return ResultatRecherche("hybride", [])
        filtres = Filtres(space_id, type_filter, stage_filter, tier_filter)
        candidats = max(limit, CANDIDATS_MIN)

        exacts = await correspondances_exactes(self.db, extraire_references(query), filtres, candidats)
        lexical = await classement_plein_texte(self.db, query, filtres, candidats)
        if not lexical:
            lexical = await classement_trigramme(self.db, query, filtres, candidats)

        mode, vectoriel = "hybride", []
        try:
            vecteur = await self.embedder.embed_text(query)
        except EmbeddingIndisponible:
            mode = "lexical"
        else:
            if vecteur:
                vectoriel = await classement_vectoriel(self.db, vecteur, filtres, candidats)

        classes = ordonner(exacts, lexical, vectoriel, limit)
        return ResultatRecherche(mode, await self._hydrater(space_id, classes))

    async def _hydrater(self, space_id: UUID, classes) -> list[SearchResult]:
        if not classes:
            return []
        rows = await self.db.execute(
            select(Node.id, Node.title, Node.content_md, Node.type, Node.storage_tier, Node.happened_at)
            .where(Node.space_id == space_id, Node.id.in_([c.id for c in classes]))
        )
        par_id = {r[0]: r for r in rows.all()}
        return [
            SearchResult(
                id=c.id,
                title=par_id[c.id][1],
                content_md=(par_id[c.id][2] or "")[:300],
                type=_valeur(par_id[c.id][3]),
                storage_tier=_valeur(par_id[c.id][4], "hot"),
                happened_at=par_id[c.id][5],
                score=c.score,
                correspondance=c.correspondance,
            )
            for c in classes
            if c.id in par_id
        ]

    async def vector_search(
        self,
        space_id: UUID,
        query: str,
        limit: int = 10,
        stage_filter: Optional[str] = None,
        type_filter: Optional[str] = None,
    ) -> list[SearchResult]:
        """Recherche purement sémantique (/semantic). Lève EmbeddingIndisponible en panne."""
        query_embedding = await self.embedder.embed_text(query)
        if not query_embedding:
            return []

        embedding_literal = "[" + ",".join(str(v) for v in query_embedding) + "]"
        conditions = ["n.space_id = :space_id", "n.status IN ('active', 'archived')"]
        params = {"space_id": space_id, "limit": limit, "embedding": embedding_literal}
        if type_filter:
            conditions.append("n.type = :type_filter")
            params["type_filter"] = type_filter
        if stage_filter:
            conditions.append("n.ipcra_stage = :stage_filter")
            params["stage_filter"] = stage_filter

        sql = text(f"""
            SELECT n.id, n.title, n.content_md, n.type, n.storage_tier, n.happened_at,
                   1 - (n.embedding <=> CAST(:embedding AS vector)) AS score
            FROM nodes n
            WHERE {" AND ".join(conditions)}
              AND n.embedding IS NOT NULL
            ORDER BY n.embedding <=> CAST(:embedding AS vector)
            LIMIT :limit
        """)
        rows = (await self.db.execute(sql, params)).all()
        return [
            SearchResult(
                id=row[0],
                title=row[1],
                content_md=(row[2] or "")[:300],
                type=_valeur(row[3]),
                storage_tier=_valeur(row[4], "hot"),
                happened_at=row[5],
                score=float(row[6]) if row[6] else 0.0,
                correspondance="vectorielle",
            )
            for row in rows
        ]
