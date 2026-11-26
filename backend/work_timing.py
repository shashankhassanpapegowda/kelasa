"""Per-employee work timings.

A day resolves as: date override, then that weekday on the weekly schedule,
then the employee's existing shift (the default). No saved timing means the
default, so late marking, checkout reminders and auto-close stay as they are
today.

Kelasa does not record overtime. A scheduled window is only a comparison for
attendance (hours worked against the day). Time after the end is not overtime.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from typing import Iterable, Optional
from zoneinfo import ZoneInfo

DEFAULT_GRACE_MINUTES = 10
LEGACY_GRACE_MINUTES = 15
MAX_GRACE = 120
MAX_BREAK = 600
WEEKDAY_KEYS = {str(i) for i in range(7)}
WEEKDAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def parse_hhmm(value: Optional[str]) -> Optional[time]:
    """H:MM or HH:MM. Seconds and other shapes are rejected."""
    if not value or not isinstance(value, str):
        return None
    text = value.strip()
    parts = text.split(":")
    if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit() or len(parts[1]) != 2:
        return None
    if len(parts[0]) not in (1, 2):
        return None
    hour, minute = int(parts[0]), int(parts[1])
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return time(hour, minute)


def canonical_hhmm(value: Optional[str]) -> Optional[str]:
    parsed = parse_hhmm(value)
    if not parsed:
        return None
    return f"{parsed.hour:02d}:{parsed.minute:02d}"


def window_minutes(start: Optional[str], end: Optional[str]) -> Optional[int]:
    a, b = parse_hhmm(start), parse_hhmm(end)
    if not a or not b:
        return None
    mins = (b.hour * 60 + b.minute) - (a.hour * 60 + a.minute)
    return mins if mins > 0 else None


@dataclass
class DayTiming:
    source: str  # override | weekly | default
    working: bool
    start: Optional[str] = None
    end: Optional[str] = None
    break_minutes: Optional[int] = None
    grace_minutes: int = LEGACY_GRACE_MINUTES
    scheduled_minutes: Optional[int] = None

    @property
    def uses_schedule(self) -> bool:
        return self.source in ("override", "weekly")

    def public(self) -> dict:
        """Fields the UI needs. Omitted for employees with no saved timing."""
        work = None
        if self.scheduled_minutes is not None:
            if self.break_minutes is None:
                work = self.scheduled_minutes
            else:
                work = max(0, self.scheduled_minutes - self.break_minutes)
        return {
            "source": self.source,
            "working": self.working,
            "off": self.uses_schedule and not self.working,
            "start": self.start,
            "end": self.end,
            "break_minutes": self.break_minutes,
            "grace_minutes": self.grace_minutes if self.uses_schedule else None,
            "scheduled_minutes": self.scheduled_minutes if self.uses_schedule else None,
            "scheduled_work_minutes": work if self.uses_schedule else None,
        }


def _week_entry(week: Optional[dict], weekday: int) -> Optional[dict]:
    if not week:
        return None
    raw = week.get(str(weekday))
    if raw is None:
        raw = week.get(weekday)
    return raw if isinstance(raw, dict) else None


def _from_entry(source: str, entry: dict, grace: int) -> DayTiming:
    if not entry.get("working"):
        return DayTiming(source=source, working=False, grace_minutes=grace)
    start = canonical_hhmm(entry.get("start"))
    end = canonical_hhmm(entry.get("end"))
    raw_break = entry.get("break_minutes")
    break_minutes = None if raw_break is None or raw_break == "" else int(raw_break)
    return DayTiming(
        source=source,
        working=True,
        start=start,
        end=end,
        break_minutes=break_minutes,
        grace_minutes=grace,
        scheduled_minutes=window_minutes(start, end) if start and end else None,
    )


def resolve_day(day: date, schedule: Optional[dict], override: Optional[dict],
                legacy_start: Optional[str] = None, legacy_end: Optional[str] = None) -> DayTiming:
    """override > weekly > the existing shift (default)."""
    grace = DEFAULT_GRACE_MINUTES
    if schedule and schedule.get("grace_minutes") is not None:
        grace = int(schedule["grace_minutes"])
    if override:
        return _from_entry("override", override, grace)
    if schedule:
        entry = _week_entry(schedule.get("week") or {}, day.weekday())
        if entry is not None:
            return _from_entry("weekly", entry, grace)
    start = canonical_hhmm(legacy_start) if legacy_start else None
    end = canonical_hhmm(legacy_end) if legacy_end else None
    return DayTiming(
        source="default",
        working=bool(start),
        start=start,
        end=end,
        grace_minutes=LEGACY_GRACE_MINUTES,
        scheduled_minutes=window_minutes(start, end) if start and end else None,
    )


def cap_shift(timing: DayTiming, legacy_start: Optional[str], legacy_end: Optional[str]):
    """Start/end for reminders and auto-close. Scheduled end when that day is a
    working saved timing; otherwise the existing shift, unchanged."""
    if timing.uses_schedule and timing.working and timing.start and timing.end:
        return timing.start, timing.end
    return legacy_start, legacy_end


def _delta_minutes(moment: datetime, day: date, hhmm: str, tz_name: str) -> Optional[int]:
    parsed = parse_hhmm(hhmm)
    if not parsed:
        return None
    tz = ZoneInfo(tz_name or "Asia/Kolkata")
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    local = moment.astimezone(tz)
    anchor = datetime.combine(day, parsed, tz)
    return int((local - anchor).total_seconds() / 60.0)


def late_minutes(check_in: datetime, day: date, timing: DayTiming, tz_name: str) -> Optional[int]:
    """Minutes late after grace. None when the day has no start (scheduled off,
    or no shift at all). A saved timing uses its grace (default 10). The
    existing shift keeps the 15-minute grace."""
    if not timing.working or not timing.start:
        return None
    delta = _delta_minutes(check_in, day, timing.start, tz_name)
    if delta is None:
        return None
    grace = timing.grace_minutes if timing.uses_schedule else LEGACY_GRACE_MINUTES
    return max(delta - grace, 0)


def early_minutes(check_out: datetime, day: date, timing: DayTiming, tz_name: str) -> Optional[int]:
    """Minutes before the scheduled end. None when no saved working window —
    the existing shift is not flagged early. Leaving after the end is 0.
    That extra time is not overtime."""
    if not timing.uses_schedule or not timing.working or not timing.end:
        return None
    delta = _delta_minutes(check_out, day, timing.end, tz_name)
    if delta is None:
        return None
    return max(-delta, 0)


def validate_grace(value) -> int:
    try:
        minutes = int(value)
    except (TypeError, ValueError):
        raise ValueError("Grace must be a whole number of minutes") from None
    if minutes < 0 or minutes > MAX_GRACE:
        raise ValueError(f"Grace must be between 0 and {MAX_GRACE} minutes")
    return minutes


def _validate_entry(raw, label: str) -> dict:
    if not isinstance(raw, dict) or "working" not in raw:
        raise ValueError(f"Say whether {label} is a working day")
    if not raw.get("working"):
        return {"working": False}
    start = canonical_hhmm(raw.get("start") if isinstance(raw.get("start"), str) else None)
    end = canonical_hhmm(raw.get("end") if isinstance(raw.get("end"), str) else None)
    if not start or not end:
        raise ValueError(f"Use HH:MM start and end for {label}")
    span = window_minutes(start, end)
    if span is None:
        raise ValueError(f"End must be after start on the same day for {label}")
    out = {"working": True, "start": start, "end": end}
    if raw.get("break_minutes") is None or raw.get("break_minutes") == "":
        return out
    try:
        br = int(raw.get("break_minutes"))
    except (TypeError, ValueError):
        raise ValueError(f"Break minutes must be a number for {label}") from None
    if br < 0 or br > MAX_BREAK:
        raise ValueError(f"Break must be between 0 and {MAX_BREAK} minutes")
    if br >= span:
        raise ValueError(f"Break must be shorter than the working window for {label}")
    out["break_minutes"] = br
    return out


def validate_week(week: dict) -> dict:
    if not isinstance(week, dict):
        raise ValueError("Week must list each weekday")
    clean = {}
    for key in sorted(WEEKDAY_KEYS, key=int):
        if key not in week and int(key) not in week:
            raise ValueError("Set every weekday, Monday through Sunday")
        raw = week[key] if key in week else week[int(key)]
        clean[key] = _validate_entry(raw, WEEKDAY_NAMES[int(key)])
    return clean


def validate_override(body: dict) -> dict:
    return _validate_entry(body, "this day")


def summarize_week(week: dict, grace: int) -> str:
    parts = [f"grace {grace}m"]
    for i, name in enumerate(WEEKDAY_NAMES):
        entry = week[str(i)]
        if not entry.get("working"):
            parts.append(f"{name} off")
        else:
            br = f" break {entry['break_minutes']}m" if entry.get("break_minutes") is not None else ""
            parts.append(f"{name} {entry['start']}-{entry['end']}{br}")
    return "; ".join(parts)


def summarize_override(day: str, entry: dict) -> str:
    if not entry.get("working"):
        return f"{day} off"
    br = f" break {entry['break_minutes']}m" if entry.get("break_minutes") is not None else ""
    return f"{day} {entry['start']}-{entry['end']}{br}"


def manager_may_edit(actor: dict, target: dict, in_scope: bool) -> Optional[str]:
    """None when allowed, otherwise the same refusal the team console already uses.

    Admin manages everyone. A sub-admin manages employees inside the scope from
    scoped_user_ids (reportees, managed branches, managed departments) and
    cannot change their own timing or another manager's.
    """
    role = actor.get("role")
    if role == "admin":
        return None
    if role != "sub_admin":
        return "Admin access required"
    if target.get("user_id") == actor.get("user_id"):
        return "Only an admin can change your own settings"
    if target.get("role") in ("admin", "sub_admin"):
        return "Only an admin can manage another admin"
    if not in_scope:
        return "This employee is not in your team"
    return None


def split_editable(actor: dict, candidates: Iterable[dict], scope_ids: Optional[set]):
    """Split targets the way bulk apply does. scope_ids None means unrestricted (admin)."""
    allowed, skipped = [], []
    for target in candidates:
        in_scope = scope_ids is None or target.get("user_id") in scope_ids
        reason = manager_may_edit(actor, target, in_scope)
        if reason is None:
            allowed.append(target)
        else:
            skipped.append({
                "user_id": target.get("user_id"),
                "name": target.get("name"),
                "reason": reason,
            })
    return allowed, skipped
