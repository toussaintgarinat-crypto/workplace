from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.node import Node, NodeStatus
from app.models.gardien import GardienLog
from app.llm.client import LLMClient
from app.llm.gardien_prompts import (
    SUGGEST_IPCRa,
    SUMMARIZE_CLUSTER,
    INFERENCE_LINKS,
    ARCHIVE_DECISION,
)


class Suggestor:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.llm = LLMClient()

    async def suggest_for_node(self, space_id: UUID, node_id: UUID) -> Optional[GardienLog]:
        result = await self.db.execute(
            select(Node).where(Node.id == node_id, Node.space_id == space_id)
        )
        node = result.scalar_one_or_none()
        if not node:
            return None

        prompt = SUGGEST_IPCRa.format(
            current_stage=node.ipcra_stage.value,
            days=7,
            content=f"Titre: {node.title}\n\n{node.content_md[:1000]}",
        )

        try:
            suggestion = await self.llm.chat([
                {"role": "system", "content": "Tu es un assistant spécialisé dans l'organisation de notes personnelles."},
                {"role": "user", "content": prompt},
            ])
        except Exception:
            suggestion = "ressource: Fait partie des ressources"

        log = GardienLog(
            space_id=space_id,
            action="suggest_ipcra",
            node_id=node.id,
            details={
                "current_stage": node.ipcra_stage.value,
                "llm_suggestion": suggestion,
            },
            status="proposed",
        )
        self.db.add(log)
        await self.db.commit()
        await self.db.refresh(log)
        return log

    async def summarize_cluster(self, space_id: UUID, node_ids: list[UUID]) -> Optional[GardienLog]:
        result = await self.db.execute(
            select(Node).where(Node.id.in_(node_ids), Node.space_id == space_id)
        )
        nodes = result.scalars().all()
        if len(nodes) < 2:
            return None

        titles = "\n".join(f"- {n.title}" for n in nodes)
        prompt = SUMMARIZE_CLUSTER.format(count=len(nodes), content=titles)

        try:
            summary = await self.llm.chat([
                {"role": "system", "content": "Tu es un assistant spécialisé dans l'organisation de notes personnelles."},
                {"role": "user", "content": prompt},
            ])
        except Exception:
            summary = "Impossible de générer un résumé"

        log = GardienLog(
            space_id=space_id,
            action="summarize_cluster",
            details={
                "node_ids": [str(nid) for nid in node_ids],
                "llm_summary": summary,
            },
            status="proposed",
        )
        self.db.add(log)
        await self.db.commit()
        await self.db.refresh(log)
        return log

    async def infer_links(self, space_id: UUID, node_id: UUID) -> list[GardienLog]:
        result = await self.db.execute(
            select(Node).where(Node.id == node_id, Node.space_id == space_id)
        )
        node = result.scalar_one_or_none()
        if not node:
            return []

        existing = await self.db.execute(
            select(Node).where(
                Node.space_id == space_id,
                Node.status == NodeStatus.active,
                Node.id != node_id,
            ).limit(20)
        )
        existing_nodes = existing.scalars().all()
        if not existing_nodes:
            return []

        existing_text = "\n".join(f"- {n.id}: {n.title}" for n in existing_nodes)
        prompt = INFERENCE_LINKS.format(
            content=f"Titre: {node.title}\n\n{node.content_md[:500]}",
            existing=existing_text,
        )

        try:
            result_text = await self.llm.chat([
                {"role": "system", "content": "Tu es un assistant spécialisé dans l'organisation de notes personnelles."},
                {"role": "user", "content": prompt},
            ])
        except Exception:
            result_text = "Aucun lien détecté"

        logs = []
        for existing_node in existing_nodes[:5]:
            log = GardienLog(
                space_id=space_id,
                action="infer_link",
                node_id=node_id,
                details={
                    "target_node_id": str(existing_node.id),
                    "target_title": existing_node.title,
                    "llm_analysis": result_text,
                },
                status="proposed",
            )
            self.db.add(log)
            logs.append(log)

        await self.db.commit()
        for log in logs:
            await self.db.refresh(log)
        return logs

    async def archive_decision(self, space_id: UUID, node_id: UUID) -> Optional[GardienLog]:
        result = await self.db.execute(
            select(Node).where(Node.id == node_id, Node.space_id == space_id)
        )
        node = result.scalar_one_or_none()
        if not node:
            return None

        prompt = ARCHIVE_DECISION.format(
            content=f"Titre: {node.title}\n\n{node.content_md[:500]}",
        )

        try:
            decision = await self.llm.chat([
                {"role": "system", "content": "Tu es un assistant spécialisé dans l'organisation de notes personnelles."},
                {"role": "user", "content": prompt},
            ])
        except Exception:
            decision = "archiver: Passer en archive froide"

        log = GardienLog(
            space_id=space_id,
            action="suggest_archive",
            node_id=node.id,
            details={
                "storage_tier": "cold_archive",
                "llm_decision": decision,
            },
            status="proposed",
        )
        self.db.add(log)
        await self.db.commit()
        await self.db.refresh(log)
        return log
