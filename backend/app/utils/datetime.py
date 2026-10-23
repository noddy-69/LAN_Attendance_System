"""Datetime utilities. All DB timestamps are stored in UTC; IST is display-only."""
from datetime import datetime, timezone, timedelta

IST = timezone(timedelta(hours=5, minutes=30))


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def to_ist(dt: datetime | None) -> datetime | None:
    """Convert a UTC-aware datetime to IST. Frontend uses this for display."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(IST)


def ensure_utc(dt: datetime) -> datetime:
    """Attach UTC tzinfo if the datetime is naive."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt
