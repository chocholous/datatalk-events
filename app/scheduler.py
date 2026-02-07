import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import get_settings

log = logging.getLogger(__name__)


def create_scheduler(job_func) -> AsyncIOScheduler:
    settings = get_settings()
    scheduler = AsyncIOScheduler()
    cron_parts = settings.scrape_schedule.split()
    scheduler.add_job(
        job_func,
        CronTrigger(
            minute=cron_parts[0],
            hour=cron_parts[1],
            day=cron_parts[2],
            month=cron_parts[3],
            day_of_week=cron_parts[4],
        ),
        id="scraper",
        replace_existing=True,
    )
    log.info(f"Scheduler configured: {settings.scrape_schedule}")
    return scheduler
