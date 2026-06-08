from typing import Optional
from uuid import UUID
from datetime import datetime, timezone, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.node import Node, NodeStatus, IpCraStage, StorageTier
from app.models.gardien import GardienLog, GardienConfigModel
from app.schemas.gardien import GardienConfig
from app.services.node_service import NodeService
from app.llm.suggestor import Suggestor
from app.config import settings


class GardienService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.suggestor = Suggestor(db)

    async def run(self, space_id: UUID) -> dict:
        config = await self.load_config(space_id)
        results: dict[str, int] = {}

        if config.auto_suggest_ipcra:
            count = await self._suggest_ipcra(space_id)
            if count:
                results["suggest_ipcra"] = count

        if config.auto_infer:
            count = await self._infer_links(space_id)
            if count:
                results["infer_links"] = count

        if config.auto_archive:
            count = await self._suggest_archive(space_id)
            if count:
                results["suggest_archive"] = count

        if config.auto_summarize:
            count = await self._summarize(space_id)
            if count:
                results["summarize_cluster"] = count

        return results

    async def _suggest_ipcra(self, space_id: UUID) -> int:
        result = await self.db.execute(
            select(Node).where(
                Node.space_id == space_id,
                Node.status == NodeStatus.active,
                Node.ipcra_stage == IpCraStage.input,
            ).limit(10)
        )
        nodes = result.scalars().all()
        count = 0
        for node in nodes:
            log = await self.suggestor.suggest_for_node(space_id, node.id)
            if log:
                count += 1
        return count

    async def _infer_links(self, space_id: UUID) -> int:
        result = await self.db.execute(
            select(Node).where(
                Node.space_id == space_id,
                Node.status == NodeStatus.active,
            ).order_by(Node.created_at.desc()).limit(5)
        )
        nodes = result.scalars().all()
        count = 0
        for node in nodes:
            logs = await self.suggestor.infer_links(space_id, node.id)
            count += len(logs)
        return count

    async def _suggest_archive(self, space_id: UUID) -> int:
        now = datetime.now(timezone.utc)
        cold_cutoff = now - timedelta(days=settings.tier_cold_archive_days)
        result = await self.db.execute(
            select(Node).where(
                Node.space_id == space_id,
                Node.status == NodeStatus.active,
                Node.storage_tier == StorageTier.archive,
                Node.last_accessed < cold_cutoff,
            ).limit(10)
        )
        nodes = result.scalars().all()
        count = 0
        for node in nodes:
            log = await self.suggestor.archive_decision(space_id, node.id)
            if log:
                count += 1
        return count

    async def _summarize(self, space_id: UUID) -> int:
        result = await self.db.execute(
            select(Node).where(
                Node.space_id == space_id,
                Node.status == NodeStatus.active,
            ).limit(50)
        )
        nodes = result.scalars().all()
        if len(nodes) < 3:
            return 0

        from collections import defaultdict
        groups: dict[str, list[UUID]] = defaultdict(list)
        for n in nodes:
            groups[n.type.value].append(n.id)

        count = 0
        for group_ids in groups.values():
            if len(group_ids) >= 3:
                log = await self.suggestor.summarize_cluster(space_id, group_ids[:10])
                if log:
                    count += 1
        return count

    async def execute_suggestion(self, suggestion_id: UUID) -> bool:
        result = await self.db.execute(
            select(GardienLog).where(GardienLog.id == suggestion_id)
        )
        log = result.scalar_one_or_none()
        if not log or log.status != "proposed":
            return False

        if log.action == "suggest_ipcra" and log.node_id:
            suggestion_text = (log.details or {}).get("llm_suggestion", "")
            stage = self._parse_stage(suggestion_text)
            if stage:
                node_svc = NodeService(self.db)
                await node_svc.update_stage(log.node_id, log.space_id, stage)

        if log.action == "suggest_archive" and log.node_id:
            node_svc = NodeService(self.db)
            await node_svc.update_tier(log.node_id, log.space_id, "cold_archive")

        log.status = "accepted"
        await self.db.commit()
        return True

    def _parse_stage(self, text: str) -> Optional[str]:
        text = text.lower().strip()
        for stage in ["projet", "casquette", "ressource", "archive"]:
            if stage in text:
                return stage
        return None

    async def get_suggestions(self, space_id: UUID) -> list[GardienLog]:
        result = await self.db.execute(
            select(GardienLog).where(
                GardienLog.space_id == space_id,
                GardienLog.status == "proposed",
            ).order_by(GardienLog.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_logs(self, space_id: UUID) -> list[GardienLog]:
        result = await self.db.execute(
            select(GardienLog).where(
                GardienLog.space_id == space_id,
            ).order_by(GardienLog.created_at.desc()).limit(100)
        )
        return list(result.scalars().all())

    async def load_config(self, space_id: UUID) -> GardienConfig:
        result = await self.db.execute(
            select(GardienConfigModel).where(GardienConfigModel.space_id == space_id)
        )
        model = result.scalar_one_or_none()
        if model:
            return GardienConfig(
                mode=model.mode,
                interval_minutes=model.interval_minutes,
                auto_summarize=model.auto_summarize,
                auto_merge=model.auto_merge,
                auto_infer=model.auto_infer,
                auto_suggest_ipcra=model.auto_suggest_ipcra,
                auto_archive=model.auto_archive,
            )
        return GardienConfig()

    async def save_config(self, space_id: UUID, config: GardienConfig) -> GardienConfig:
        result = await self.db.execute(
            select(GardienConfigModel).where(GardienConfigModel.space_id == space_id)
        )
        model = result.scalar_one_or_none()
        if model:
            model.mode = config.mode
            model.interval_minutes = config.interval_minutes
            model.auto_summarize = config.auto_summarize
            model.auto_merge = config.auto_merge
            model.auto_infer = config.auto_infer
            model.auto_suggest_ipcra = config.auto_suggest_ipcra
            model.auto_archive = config.auto_archive
        else:
            model = GardienConfigModel(
                space_id=space_id,
                mode=config.mode,
                interval_minutes=config.interval_minutes,
                auto_summarize=config.auto_summarize,
                auto_merge=config.auto_merge,
                auto_infer=config.auto_infer,
                auto_suggest_ipcra=config.auto_suggest_ipcra,
                auto_archive=config.auto_archive,
            )
            self.db.add(model)
        await self.db.commit()
        return config
