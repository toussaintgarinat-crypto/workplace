from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.node import Node, NodeStatus, NodeType, IpCraStage, StorageTier
from app.schemas.search import SearchResult
from app.llm.embedder import Embedder


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
    ) -> list[SearchResult]:
        if not query:
            return []

        query_embedding = await self.embedder.embed_text(query)
        if not query_embedding:
            return []

        from sqlalchemy import text
        embedding_literal = "[" + ",".join(str(v) for v in query_embedding) + "]"

        conditions = [
            "n.space_id = :space_id",
            "n.status IN ('active', 'archived')",
            "n.embedding IS NOT NULL",
        ]
        params = {"space_id": space_id, "limit": limit, "embedding": embedding_literal}

        if type_filter:
            conditions.append("n.type = :type_filter")
            params["type_filter"] = type_filter
        if stage_filter:
            conditions.append("n.ipcra_stage = :stage_filter")
            params["stage_filter"] = stage_filter
        if tier_filter:
            conditions.append("n.storage_tier = :tier_filter")
            params["tier_filter"] = tier_filter

        where_clause = " AND ".join(conditions)

        search_words = query.strip().split()
        text_rank = ""
        if search_words:
            word_conditions = " OR ".join(
                f"(n.title ILIKE :w{i} OR n.content_md ILIKE :w{i})"
                for i in range(len(search_words))
            )
            for i, w in enumerate(search_words):
                params[f"w{i}"] = f"%{w}%"
            text_rank = f"""
                + CASE WHEN {word_conditions} THEN 0.3 ELSE 0 END
            """

        sql = text(f"""
            SELECT n.id, n.title, n.content_md, n.type, n.storage_tier, n.happened_at,
                   (1 - (n.embedding <=> CAST(:embedding AS vector))) {text_rank} AS score
            FROM nodes n
            WHERE {where_clause}
            ORDER BY score DESC
            LIMIT :limit
        """)

        result = await self.db.execute(sql, params)
        rows = result.all()

        return [
            SearchResult(
                id=row[0],
                title=row[1],
                content_md=(row[2] or "")[:300],
                type=row[3].value if hasattr(row[3], 'value') else row[3],
                storage_tier=row[4].value if hasattr(row[4], 'value') else (row[4] or "hot"),
                happened_at=row[5],
                score=float(row[6]) if row[6] else 0.0,
            )
            for row in rows
        ]

    async def vector_search(
        self,
        space_id: UUID,
        query: str,
        limit: int = 10,
        stage_filter: Optional[str] = None,
        type_filter: Optional[str] = None,
    ) -> list[SearchResult]:
        query_embedding = await self.embedder.embed_text(query)
        if not query_embedding:
            return []

        from sqlalchemy import text
        embedding_literal = "[" + ",".join(str(v) for v in query_embedding) + "]"

        conditions = [
            "n.space_id = :space_id",
            "n.status IN ('active', 'archived')",
        ]
        params = {"space_id": space_id, "limit": limit, "embedding": embedding_literal}

        if type_filter:
            conditions.append("n.type = :type_filter")
            params["type_filter"] = type_filter
        if stage_filter:
            conditions.append("n.ipcra_stage = :stage_filter")
            params["stage_filter"] = stage_filter

        where_clause = " AND ".join(conditions)
        sql = text(f"""
            SELECT n.id, n.title, n.content_md, n.type, n.storage_tier, n.happened_at,
                   1 - (n.embedding <=> CAST(:embedding AS vector)) AS score
            FROM nodes n
            WHERE {where_clause}
              AND n.embedding IS NOT NULL
            ORDER BY n.embedding <=> CAST(:embedding AS vector)
            LIMIT :limit
        """)

        result = await self.db.execute(sql, params)
        rows = result.all()

        return [
            SearchResult(
                id=row[0],
                title=row[1],
                content_md=(row[2] or "")[:300],
                type=row[3].value if hasattr(row[3], 'value') else row[3],
                storage_tier=row[4].value if hasattr(row[4], 'value') else (row[4] or "hot"),
                happened_at=row[5],
                score=float(row[6]) if row[6] else 0.0,
            )
            for row in rows
        ]
