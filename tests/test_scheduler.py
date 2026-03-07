from app.scheduler import create_scheduler


async def _dummy_job():
    pass


class TestScheduler:
    def test_create_scheduler_registers_jobs(self):
        scheduler = create_scheduler(_dummy_job, _dummy_job)
        try:
            jobs = scheduler.get_jobs()
            assert len(jobs) == 2
            job_ids = {j.id for j in jobs}
            assert job_ids == {"scraper", "event_reminder"}
        finally:
            if scheduler.running:
                scheduler.shutdown(wait=False)
