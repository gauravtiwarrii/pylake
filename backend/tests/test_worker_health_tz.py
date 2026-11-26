"""Regression: PostgreSQL returns timezone-aware heartbeat timestamps; comparing them
with a naive cutoff raised TypeError and made /workers/health return 500 in production."""
from datetime import datetime, timedelta, timezone

from app.api.v1.observability import _as_utc as obs_as_utc
from app.api.v1.pipelines import _as_utc as pipe_as_utc


def test_as_utc_handles_naive_and_aware():
    for fn in (obs_as_utc, pipe_as_utc):
        naive = datetime(2026, 1, 1, 12, 0, 0)
        aware = datetime(2026, 1, 1, 17, 30, 0, tzinfo=timezone(timedelta(hours=5, minutes=30)))
        assert fn(naive) == datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        assert fn(aware) == datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=90)
        assert (fn(naive) < cutoff) is True
        assert (fn(datetime.now(timezone.utc)) < cutoff) is False
