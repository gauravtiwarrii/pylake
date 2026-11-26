"""Pipeline worker process.

Runs continuously, claiming queued pipeline runs and executing them.
Designed to be deployed as a long-lived process (Railway, Docker, bare-metal).

Start with:
    python -m app.worker
"""
import logging
import signal
import socket
import time
import uuid
from datetime import datetime, timezone

from croniter import croniter
from sqlalchemy.exc import IntegrityError

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.models.entities import PipelineRun, PipelineSchedule, RunStatus, WorkerHeartbeat
from app.services.pipeline_engine import claim_next_job, execute_pipeline_run

logger = logging.getLogger("pylake.worker")

running = True
_BACKOFF_SECONDS = 5  # pause after an unexpected loop-level error


def handle_shutdown(signum, frame):
    global running
    running = False
    logger.info("Shutdown signal received; draining current job then stopping")


def trigger_due_schedules() -> None:
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        schedules = db.query(PipelineSchedule).filter(
            PipelineSchedule.enabled.is_(True),
            PipelineSchedule.next_run_at.is_not(None),
            PipelineSchedule.next_run_at <= now,
        ).all()
        for schedule in schedules:
            try:
                from zoneinfo import ZoneInfo
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


def _update_heartbeat(worker_id: str, active_job_id=None) -> None:
    db = SessionLocal()
    try:
        heartbeat = db.query(WorkerHeartbeat).filter(
            WorkerHeartbeat.worker_id == worker_id
        ).first()
        if not heartbeat:
            heartbeat = WorkerHeartbeat(
                worker_id=worker_id,
                last_seen_at=datetime.now(timezone.utc).replace(tzinfo=None),
                hostname=socket.gethostname(),
            )
            db.add(heartbeat)
        heartbeat.last_seen_at = datetime.now(timezone.utc).replace(tzinfo=None)
        heartbeat.status = "ONLINE"
        heartbeat.active_job_id = active_job_id
        db.commit()
    finally:
        db.close()


def _mark_offline(worker_id: str) -> None:
    db = SessionLocal()
    try:
        heartbeat = db.query(WorkerHeartbeat).filter(
            WorkerHeartbeat.worker_id == worker_id
        ).first()
        if heartbeat:
            heartbeat.status = "SHUTDOWN"
            heartbeat.active_job_id = None
            db.commit()
    finally:
        db.close()


def main() -> None:
    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)

    settings = get_settings()
    worker_id = f"pylake-worker-{uuid.uuid4()}"
    hostname = socket.gethostname()

    # Log startup without printing any secret values.
    logger.info(
        "Worker starting: worker_id=%s hostname=%s env=%s poll_interval=%ss",
        worker_id,
        hostname,
        settings.app_env,
        settings.pipeline_worker_poll_seconds,
    )

    while running:
        try:
            trigger_due_schedules()
            _update_heartbeat(worker_id)

            run = claim_next_job(worker_id)
            if run:
                logger.info("Claimed pipeline run %s", run.id)
                _update_heartbeat(worker_id, active_job_id=run.id)
                execute_pipeline_run(run.id)
                logger.info("Completed pipeline run %s", run.id)
            else:
                time.sleep(settings.pipeline_worker_poll_seconds)

        except Exception:
            # Log the full traceback but keep the process alive.
            logger.exception(
                "Unhandled exception in worker loop (worker_id=%s); backing off %ss",
                worker_id,
                _BACKOFF_SECONDS,
            )
            time.sleep(_BACKOFF_SECONDS)

    _mark_offline(worker_id)
    logger.info("Worker stopped cleanly: worker_id=%s", worker_id)


if __name__ == "__main__":
    main()
