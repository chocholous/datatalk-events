import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import get_settings

log = logging.getLogger(__name__)


def create_scheduler(scrape_func, daily_reminder_func) -> AsyncIOScheduler:
    settings = get_settings()
    scheduler = AsyncIOScheduler()

    # Weekly scrape + Google Calendar sync
    cron_parts = settings.scrape_schedule.split()
    scheduler.add_job(
        scrape_func,
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

    # Daily reminder at 8:00 about today's events
    scheduler.add_job(
        daily_reminder_func,
        CronTrigger(hour=8, minute=0),
        id="daily_reminder",
        replace_existing=True,
    )

    log.info(f"Scheduler configured: scrape={settings.scrape_schedule}, daily reminder=8:00")
    return scheduler
