"""Calendar-month retention for check-in and check-out selfies.

Kept: the current calendar month in Asia/Kolkata, plus SELFIE_RETENTION_MONTHS
previous calendar months (default 1). Anything taken before 00:00 IST on the
first day of that window is deleted.

Examples with the default (1):
  15 Dec -> keep from 1 Nov onward
   1 Jan -> keep from 1 Dec onward
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def selfie_retention_months() -> int:
    """How many previous calendar months to keep, in addition to the current one.

    Unset, blank, or not a whole number falls back to 1. A negative value also
    falls back to 1 so a bad env cannot widen the purge. Explicit 0 keeps only
    the current calendar month.
    """
    raw = os.environ.get("SELFIE_RETENTION_MONTHS", "1")
    try:
        months = int(str(raw).strip())
    except (TypeError, ValueError):
        return 1
    if months < 0:
        return 1
    return months


def selfie_retention_cutoff(now: datetime | None = None, months: int | None = None) -> datetime:
    """UTC instant of 00:00 Asia/Kolkata on the first day still kept.

    A selfie taken at this instant is kept. A selfie taken strictly earlier is
    eligible for deletion. ``months`` is the number of previous calendar months
    to keep besides the current one (default from SELFIE_RETENTION_MONTHS).
    """
    if months is None:
        months = selfie_retention_months()
    elif months < 0:
        months = 1
    local = (now or _utcnow()).astimezone(IST)
    year, month = local.year, local.month - months
    while month <= 0:
        month += 12
        year -= 1
    start = datetime(year, month, 1, tzinfo=IST)
    return start.astimezone(timezone.utc)


def photo_taken_before(taken_iso: str | None, cutoff: datetime) -> bool:
    """True only when the selfie timestamp is strictly before the cutoff.

    Missing or unparseable timestamps are not treated as expired. The purge
    calls this before deleting, so a photo the calendar rule still covers is
    never scrubbed just because a string comparison looked old.
    """
    if not taken_iso or not isinstance(taken_iso, str):
        return False
    try:
        taken = datetime.fromisoformat(taken_iso)
    except ValueError:
        return False
    if taken.tzinfo is None:
        taken = taken.replace(tzinfo=timezone.utc)
    return taken < cutoff
