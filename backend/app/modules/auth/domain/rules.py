"""Políticas ya aprobadas para las sesiones locales."""

from datetime import datetime, timedelta


def failed_login(previous_failures: int, now: datetime) -> tuple[int, datetime | None]:
    failures = min(7, previous_failures + 1)
    minutes = 0 if failures < 5 else (15 if failures == 5 else 30 if failures == 6 else 60)
    return failures, now + timedelta(minutes=minutes) if minutes else None


def family_expiry(now: datetime, remember: bool) -> datetime:
    return now + (timedelta(days=14) if remember else timedelta(hours=8))
