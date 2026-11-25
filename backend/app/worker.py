import signal
import time
import uuid
from datetime import datetime
import socket
from zoneinfo import ZoneInfo

from croniter import croniter
from sqlalchemy.exc import IntegrityError

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.models.entities import PipelineRun, PipelineSchedule, RunStatus, WorkerHeartbeat
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
            occurrence = schedule.next_run_at
            iterations = 0
            while occurrence and occurrence <= now and iterations < 100:
                existing = db.query(PipelineRun).filter(
                    PipelineRun.schedule_id == schedule.id,
                    PipelineRun.scheduled_at == occurrence,
                ).first()
                if not existing:
                    nested = db.begin_nested()
                    db.add(PipelineRun(
                        pipeline_id=schedule.pipeline_id,
                        schedule_id=schedule.id,
                        scheduled_at=occurrence,
                        workspace_id=schedule.workspace_id,
                        triggered_by=None,
                        status=RunStatus.QUEUED,
                    ))
                    try:
                        db.flush()
                    except IntegrityError:
                        nested.rollback()
                    else:
                        nested.commit()
                schedule.last_run_at = occurrence
                aware = occurrence.replace(tzinfo=tz)
                occurrence = croniter(schedule.cron_expression, aware).get_next(datetime).replace(tzinfo=None)
                iterations += 1
            schedule.next_run_at = occurrence
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
        db = SessionLocal()
        try:
            heartbeat = db.query(WorkerHeartbeat).filter(WorkerHeartbeat.worker_id == worker_id).first()
            if not heartbeat:
                heartbeat = WorkerHeartbeat(worker_id=worker_id, last_seen_at=datetime.utcnow(), hostname=socket.gethostname())
                db.add(heartbeat)
            heartbeat.last_seen_at = datetime.utcnow()
            heartbeat.status = "ONLINE"
            heartbeat.active_job_id = None
            db.commit()
        finally:
            db.close()
        run = claim_next_job(worker_id)
        if run:
            db = SessionLocal()
            try:
                heartbeat = db.query(WorkerHeartbeat).filter(WorkerHeartbeat.worker_id == worker_id).first()
                if heartbeat:
                    heartbeat.active_job_id = run.id
                    heartbeat.last_seen_at = datetime.utcnow()
                    db.commit()
            finally:
                db.close()
            execute_pipeline_run(run.id)
        else:
            time.sleep(settings.pipeline_worker_poll_seconds)
    db = SessionLocal()
    try:
        heartbeat = db.query(WorkerHeartbeat).filter(WorkerHeartbeat.worker_id == worker_id).first()
        if heartbeat:
            heartbeat.status = "SHUTDOWN"
            heartbeat.active_job_id = None
            db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    main()
