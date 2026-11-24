"""Pure attendance calculations: session caps, net work, overtime and day status."""
from datetime import datetime, date, time, timedelta, timezone
from typing import Optional, Iterable
from zoneinfo import ZoneInfo

MAX_NET_MINUTES = 16 * 60
LATE_GRACE_MINUTES = 15
DEFAULT_WEEKLY_OFF = [6]  # Monday=0 … Sunday=6


def parse_dt(s: str) -> datetime:
    dt = datetime.fromisoformat(s)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _hm(s: Optional[str]) -> Optional[time]:
    if not s:
        return None
    try:
        h, m = s.split(":")[:2]
        return time(int(h), int(m))
    except (ValueError, AttributeError):
        return None


def shift_minutes(shift_start: Optional[str], shift_end: Optional[str]) -> Optional[int]:
    a, b = _hm(shift_start), _hm(shift_end)
    if not a or not b:
        return None
    mins = (b.hour * 60 + b.minute) - (a.hour * 60 + a.minute)
    return mins if mins > 0 else mins + 24 * 60


def session_cap(check_in_iso: str, tz_name: str, shift_start: Optional[str], shift_end: Optional[str]) -> datetime:
    """Latest moment a session can run: shift end on the check-in day, else 23:59 of that day.
    Night shifts (end <= start) and check-ins after shift end close at 23:59 the same day."""
    tz = ZoneInfo(tz_name)
    cin = parse_dt(check_in_iso).astimezone(tz)
    end_of_day = datetime.combine(cin.date(), time(23, 59), tz)
    a, b = _hm(shift_start), _hm(shift_end)
    if a and b and b > a:
        shift_end_dt = datetime.combine(cin.date(), b, tz)
        if shift_end_dt > cin:
            return shift_end_dt.astimezone(timezone.utc)
    return end_of_day.astimezone(timezone.utc)


def compute_session(check_in_iso: str, check_out_iso: str, break_minutes: int,
                    shift_start: Optional[str] = None, shift_end: Optional[str] = None) -> dict:
    total = max(0, int((parse_dt(check_out_iso) - parse_dt(check_in_iso)).total_seconds() // 60))
    net = max(0, total - int(break_minutes or 0))
    over_cap = net > MAX_NET_MINUTES
    if over_cap:
        net = MAX_NET_MINUTES
    planned = shift_minutes(shift_start, shift_end)
    overtime = max(0, net - planned) if planned else 0
    return {"duration_minutes": total, "net_work_minutes": net, "over_cap": over_cap, "overtime_minutes": overtime}


def late_by(minutes_after_shift_start: int) -> int:
    return max(0, minutes_after_shift_start - LATE_GRACE_MINUTES)


def is_late(late_by_minutes: Optional[int], has_shift: bool) -> bool:
    """late_by_minutes is stored after the 15-minute grace."""
    return has_shift and (late_by_minutes or 0) > 0


def day_status(day: date, *, today: date, present: bool, late: bool, on_leave: bool, holiday: bool,
               weekly_off: Iterable[int], has_shift: bool, joined: Optional[date], pending_invite: bool) -> str:
    """One of: present, late, leave, holiday, weekly_off, not_joined, no_shift, future, absent."""
    if present:
        return "late" if late else "present"
    if day > today:
        return "future"
    if pending_invite or (joined and day < joined):
        return "not_joined"
    if on_leave:
        return "leave"
    if holiday:
        return "holiday"
    if day.weekday() in set(weekly_off):
        return "weekly_off"
    if not has_shift:
        return "no_shift"
    return "absent"
