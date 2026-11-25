from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.entities import RateLimitEvent


def check_database_rate_limit(db: Session, scope_key: str, endpoint: str) -> None:
    settings = get_settings()
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
        seconds=settings.auth_rate_limit_window_seconds
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
    if count >= settings.auth_rate_limit_attempts:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many attempts. Please try again later.",
        )
    db.add(RateLimitEvent(scope_key=scope_key, endpoint=endpoint))
    db.commit()
