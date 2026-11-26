"""Days paid from Kelasa attendance.

Phase 1 day status (attendance_calc.day_status, including the half-day and
punch-error rules used by the employee calendar) is applied before a day is
counted. NDP = present (half day = 0.5) + approved paid leave + holidays +
weekly offs inside the joining/exit window, capped at NWD. LOP = NWD − NDP.
"""
from __future__ import annotations

import calendar
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from attendance_calc import day_status, shift_minutes
from payroll_calc import D, ZERO

HALF = Decimal("0.5")


def _parse(value: Optional[str]):
    if not value:
        return None
    return date.fromisoformat(value[:10])


def classify_day(day: date, *, today: date, sessions: list, leave: Optional[dict], holiday: bool,
                 weekly_off, has_shift: bool, joined: Optional[date], pending_invite: bool,
                 shift_start: Optional[str] = None, shift_end: Optional[str] = None) -> str:
    """Same status the calendar shows, so payroll and the calendar cannot disagree."""
    present = bool(sessions)
    late = has_shift and any((s.get("late_by_minutes") or 0) > 0 for s in sessions)
    status = day_status(
        day, today=today, present=present, late=late, on_leave=bool(leave), holiday=holiday,
        weekly_off=weekly_off or [], has_shift=has_shift, joined=joined, pending_invite=pending_invite,
    )
    net = sum((s.get("net_work_minutes") or 0) for s in sessions)
    open_now = any(not s.get("check_out") for s in sessions)
    half_shift = (shift_minutes(shift_start, shift_end) or 0) / 2
    if sessions and any((s.get("auto_closed") and not s.get("regularized")) or s.get("over_cap") for s in sessions):
        return "punch_error"
    if sessions and not open_now and half_shift and net < half_shift and day != today:
        return "half_day"
    if leave and leave.get("half_day"):
        return "half_day"
    if day == today and not sessions and status == "absent":
        return "today"
    return status


def days_paid(*, year: int, month: int, nwd: Decimal, today: date, joining: Optional[str] = None,
              exit_date: Optional[str] = None, weekly_off=None, holidays=None, sessions_by_date=None,
              leaves=None, has_shift: bool = True, pending_invite: bool = False,
              shift_start: Optional[str] = None, shift_end: Optional[str] = None,
              leave_types=None) -> dict:
    """Build the NDP breakdown for one employee and one month."""
    weekly_off = list(weekly_off or [])
    holiday_set = set(holidays or [])
    sessions_by_date = sessions_by_date or {}
    paid_codes = {}
    for lt in leave_types or []:
        paid_codes[lt.get("code") or lt.get("name")] = bool(lt.get("paid", True))
        paid_codes[lt.get("name")] = bool(lt.get("paid", True))
    joined = _parse(joining)
    exited = _parse(exit_date)
    first = date(year, month, 1)
    last = date(year, month, calendar.monthrange(year, month)[1])

    present = ZERO
    half_days = ZERO
    paid_leave = {}
    holiday_days = ZERO
    weekly_off_days = ZERO
    lop_days = ZERO
    ndp = ZERO

    def on_leave(day: date):
        for lv in leaves or []:
            start = _parse(lv.get("start_date"))
            end = _parse(lv.get("end_date"))
            if start and end and start <= day <= end and lv.get("status", "approved") == "approved":
                return lv
        return None

    day = first
    while day <= last:
        active = (joined is None or day >= joined) and (exited is None or day <= exited)
        lv = on_leave(day) if active else None
        status = classify_day(
            day, today=today, sessions=sessions_by_date.get(day.isoformat(), []) if active else [],
            leave=lv, holiday=day.isoformat() in holiday_set, weekly_off=weekly_off,
            has_shift=has_shift, joined=joined, pending_invite=pending_invite,
            shift_start=shift_start, shift_end=shift_end,
        ) if active else "not_joined"

        worked = ZERO
        if status in ("present", "late", "punch_error"):
            worked = D(1)
            present += 1
        elif status == "half_day":
            sessions = sessions_by_date.get(day.isoformat(), [])
            net = sum((s.get("net_work_minutes") or 0) for s in sessions)
            half_shift = (shift_minutes(shift_start, shift_end) or 0) / 2
            if sessions and (not half_shift or net < half_shift):
                worked = HALF
                half_days += 1
            elif sessions:
                worked = D(1)
                present += 1

        leave_part = ZERO
        if lv:
            portion = HALF if lv.get("half_day") else D(1)
            type_name = lv.get("leave_type") or lv.get("type_name") or "Leave"
            code = lv.get("type_code") or type_name
            is_paid = lv.get("paid")
            if is_paid is None:
                is_paid = paid_codes.get(code, paid_codes.get(type_name, True))
            if is_paid:
                leave_part = portion
                paid_leave[type_name] = paid_leave.get(type_name, ZERO) + portion

        day_paid = worked + leave_part
        if day_paid == 0 and status == "holiday":
            day_paid = D(1)
            holiday_days += 1
        elif day_paid == 0 and status == "weekly_off":
            day_paid = D(1)
            weekly_off_days += 1
        if day_paid > 1:
            day_paid = D(1)
        if not active or day_paid == 0:
            if day_paid == 0:
                lop_days += 1
        ndp += day_paid
        day += timedelta(days=1)

    if ndp > D(nwd):
        ndp = D(nwd)
    return {
        "nwd": D(nwd),
        "ndp": ndp,
        "lop": D(nwd) - ndp,
        "present": present,
        "half_days": half_days,
        "paid_leave": {k: v for k, v in paid_leave.items()},
        "holidays": holiday_days,
        "weekly_offs": weekly_off_days,
        "unpaid_or_absent": lop_days,
    }
