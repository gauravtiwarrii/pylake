from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.entities import RateLimitEvent


def check_database_rate_limit(
    db: Session,
    scope_key: str,
    endpoint: str,
    attempts: int | None = None,
    window_seconds: int | None = None,
) -> None:
    settings = get_settings()
    request_limit = attempts if attempts is not None else settings.auth_rate_limit_attempts
    rate_window = window_seconds if window_seconds is not None else settings.auth_rate_limit_window_seconds
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
        seconds=rate_window
    )
    if db.bind and db.bind.dialect.name == "postgresql":
        advisory_key = f"{scope_key}:{endpoint}"
        db.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:scope_key))"),
            {"scope_key": advisory_key},
        )
    db.query(RateLimitEvent).filter(RateLimitEvent.occurred_at < cutoff).delete()
    count = db.query(RateLimitEvent).filter(
        RateLimitEvent.scope_key == scope_key,
        RateLimitEvent.endpoint == endpoint,
        RateLimitEvent.occurred_at >= cutoff,
    ).count()
    if count >= request_limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many attempts. Please try again later.",
        )
    db.add(RateLimitEvent(scope_key=scope_key, endpoint=endpoint))
    db.commit()
