import signal
import time
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from croniter import croniter

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.models.entities import PipelineRun, PipelineSchedule, RunStatus
from app.services.pipeline_engine import claim_next_job, execute_pipeline_run

running = True


def handle_shutdown(signum, frame):
    global running
    running = False


def trigger_due_schedules() -> None:
    db = SessionLocal()
    try:
        now = datetime.utcnow()
        schedules = db.query(PipelineSchedule).filter(
            PipelineSchedule.enabled.is_(True),
            PipelineSchedule.next_run_at.is_not(None),
            PipelineSchedule.next_run_at <= now,
        ).all()
        for schedule in schedules:
            try:
                tz = ZoneInfo(schedule.timezone)
            except Exception:
                continue
            base = datetime.now(tz).replace(tzinfo=None)
            next_run = croniter(schedule.cron_expression, base).get_next(datetime).replace(tzinfo=None)
            existing = db.query(PipelineRun).filter(
                PipelineRun.pipeline_id == schedule.pipeline_id,
                PipelineRun.created_at >= schedule.next_run_at,
                PipelineRun.created_at < next_run,
            ).first()
            if not existing:
                db.add(PipelineRun(
                    pipeline_id=schedule.pipeline_id,
                    workspace_id=schedule.workspace_id,
                    triggered_by=None,
                    status=RunStatus.QUEUED,
                ))
            schedule.last_run_at = schedule.next_run_at
            schedule.next_run_at = next_run
        db.commit()
    finally:
        db.close()


def main() -> None:
    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)
    settings = get_settings()
    worker_id = f"pylake-worker-{uuid.uuid4()}"
    while running:
        trigger_due_schedules()
        run = claim_next_job(worker_id)
        if run:
            execute_pipeline_run(run.id)
        else:
            time.sleep(settings.pipeline_worker_poll_seconds)


if __name__ == "__main__":
    main()
