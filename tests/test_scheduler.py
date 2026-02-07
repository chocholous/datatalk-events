from app.scheduler import create_scheduler


async def _dummy_job():
    pass


class TestScheduler:
    def test_create_scheduler_registers_job(self):
        scheduler = create_scheduler(_dummy_job)
        try:
            jobs = scheduler.get_jobs()
            assert len(jobs) == 1
            assert jobs[0].id == "scraper"
        finally:
            # Ensure scheduler is not left in a started state
            if scheduler.running:
                scheduler.shutdown(wait=False)
