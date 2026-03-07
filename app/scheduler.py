import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.config import get_settings

log = logging.getLogger(__name__)


def create_scheduler(scrape_func, reminder_func) -> AsyncIOScheduler:
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

    # Every 15 min: check for events starting in ~2h, send Telegram reminders
    scheduler.add_job(
        reminder_func,
        IntervalTrigger(minutes=15),
        id="event_reminder",
        replace_existing=True,
    )

    log.info(f"Scheduler configured: scrape={settings.scrape_schedule}, reminders=every 15min")
    return scheduler
