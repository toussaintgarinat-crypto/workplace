from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select

from app.database import async_session_factory
from app.models.node import Node
from app.models.gardien import GardienConfigModel
from app.services.tier_service import TierService
from app.services.gardien_service import GardienService

scheduler = AsyncIOScheduler()


async def run_tier_demotion():
    async with async_session_factory() as session:
        result = await session.execute(select(Node.space_id).distinct())
        space_ids = result.scalars().all()
        for sid in space_ids:
            svc = TierService(session)
            await svc.apply_tier_demotion(sid)


async def run_gardien_for_all():
    async with async_session_factory() as session:
        result = await session.execute(
            select(GardienConfigModel.space_id).distinct()
        )
        space_ids = result.scalars().all()
        for sid in space_ids:
            svc = GardienService(session)
            config = await svc.load_config(sid)
            if config.mode != "off":
                await svc.run(sid)


def start_scheduler():
    scheduler.add_job(
        run_tier_demotion,
        IntervalTrigger(hours=24),
        id="tier_demotion",
        replace_existing=True,
    )
    scheduler.add_job(
        run_gardien_for_all,
        IntervalTrigger(hours=1),
        id="gardien_auto",
        replace_existing=True,
    )
    scheduler.start()


def stop_scheduler():
    scheduler.shutdown(wait=False)
