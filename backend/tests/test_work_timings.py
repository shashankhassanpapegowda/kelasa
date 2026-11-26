"""Work timings: override > weekly > existing shift, late/early in IST, sub-admin scope.

Kelasa does not record overtime. Leaving after the scheduled end is on time
for the early check (0), not an overtime balance.
"""
from datetime import date, datetime, timezone

import pytest

from work_timing import (
    DEFAULT_GRACE_MINUTES,
    LEGACY_GRACE_MINUTES,
    cap_shift,
    early_minutes,
    late_minutes,
    manager_may_edit,
    resolve_day,
    split_editable,
    summarize_override,
    validate_grace,
    validate_override,
    validate_week,
)

TZ = "Asia/Kolkata"
# 2026-11-26 is a Thursday. Friday is the 27th.
THU = date(2026, 11, 26)
FRI = date(2026, 11, 27)
SUN = date(2026, 11, 29)


def ist(day: str, hhmm: str) -> datetime:
    """Local IST wall time as an aware datetime (converted through UTC on compare)."""
    from zoneinfo import ZoneInfo
    local = datetime.fromisoformat(f"{day}T{hhmm}:00").replace(tzinfo=ZoneInfo(TZ))
    return local.astimezone(timezone.utc)


def office_week(start="09:30", end="18:30", break_minutes=60, weekend_off=True):
    week = {}
    for i in range(7):
        if weekend_off and i >= 5:
            week[str(i)] = {"working": False}
        else:
            entry = {"working": True, "start": start, "end": end}
            if break_minutes is not None:
                entry["break_minutes"] = break_minutes
            week[str(i)] = entry
    return {"grace_minutes": DEFAULT_GRACE_MINUTES, "week": week}


def test_resolution_override_beats_weekly_beats_default():
    schedule = office_week()
    override = {"working": True, "start": "11:00", "end": "16:00", "break_minutes": 30}
    overridden = resolve_day(FRI, schedule, override, "08:00", "17:00")
    bare = resolve_day(FRI, None, override, "08:00", "17:00")
    assert bare.source == "override" and bare.grace_minutes == 10 and bare.start == "11:00"
    assert overridden.source == "override"
    assert (overridden.start, overridden.end, overridden.break_minutes) == ("11:00", "16:00", 30)
    assert overridden.scheduled_minutes == 5 * 60
    assert overridden.public()["scheduled_work_minutes"] == 5 * 60 - 30
    assert overridden.grace_minutes == 10

    weekly = resolve_day(FRI, schedule, None, "08:00", "17:00")
    assert weekly.source == "weekly"
    assert (weekly.start, weekly.end) == ("09:30", "18:30")
    assert weekly.scheduled_minutes == 9 * 60
    assert weekly.public()["scheduled_work_minutes"] == 8 * 60

    default = resolve_day(FRI, None, None, "08:00", "17:00")
    assert default.source == "default"
    assert (default.start, default.end) == ("08:00", "17:00")
    assert default.grace_minutes == LEGACY_GRACE_MINUTES
    assert default.public()["scheduled_minutes"] is None
    assert "overtime" not in default.public()


def test_weekday_off_and_override_off_win_over_the_existing_shift():
    schedule = office_week()
    sunday = resolve_day(SUN, schedule, None, "09:00", "18:00")
    assert sunday.source == "weekly" and sunday.working is False
    assert late_minutes(ist("2026-11-29", "11:00"), SUN, sunday, TZ) is None

    forced_off = resolve_day(FRI, schedule, {"working": False}, "09:00", "18:00")
    assert forced_off.source == "override" and forced_off.working is False
    assert cap_shift(forced_off, "09:00", "18:00") == ("09:00", "18:00")


def test_missing_weekday_falls_through_to_the_existing_shift():
    schedule = {"grace_minutes": 5, "week": {"0": {"working": True, "start": "09:00", "end": "18:00"}}}
    timing = resolve_day(FRI, schedule, None, "08:15", "16:45")
    assert timing.source == "default"
    assert (timing.start, timing.end, timing.grace_minutes) == ("08:15", "16:45", 15)


def test_no_schedule_and_no_shift_is_the_current_default():
    timing = resolve_day(THU, None, None, None, None)
    assert timing.source == "default" and timing.working is False
    assert late_minutes(ist("2026-11-26", "10:00"), THU, timing, TZ) is None
    assert early_minutes(ist("2026-11-26", "17:00"), THU, timing, TZ) is None
    assert cap_shift(timing, None, None) == (None, None)


def test_late_and_early_in_ist_use_saved_grace_not_overtime():
    schedule = office_week(start="09:30", end="18:30", break_minutes=None)
    timing = resolve_day(THU, schedule, None, "09:00", "18:00")
    # 09:40 IST is exactly the 10-minute grace. 09:41 is one minute late.
    assert late_minutes(ist("2026-11-26", "09:40"), THU, timing, TZ) == 0
    assert late_minutes(ist("2026-11-26", "09:41"), THU, timing, TZ) == 1
    assert late_minutes(ist("2026-11-26", "09:29"), THU, timing, TZ) == 0
    # The UTC instant 04:11Z is 09:41 IST on the attendance date, not the UTC clock.
    assert late_minutes(datetime(2026, 11, 26, 4, 11, tzinfo=timezone.utc), THU, timing, TZ) == 1

    assert early_minutes(ist("2026-11-26", "18:00"), THU, timing, TZ) == 30
    assert early_minutes(ist("2026-11-26", "18:30"), THU, timing, TZ) == 0
    # After the end: still at work, not overtime.
    assert early_minutes(ist("2026-11-26", "19:10"), THU, timing, TZ) == 0


def test_override_hours_are_what_late_and_early_use():
    schedule = office_week()
    timing = resolve_day(THU, schedule, {"working": True, "start": "11:00", "end": "16:00"}, "09:30", "18:30")
    assert timing.source == "override"
    assert late_minutes(ist("2026-11-26", "11:10"), THU, timing, TZ) == 0
    assert late_minutes(ist("2026-11-26", "11:11"), THU, timing, TZ) == 1
    # 09:41 would be late against the weekly 09:30 start. The override wins.
    assert late_minutes(ist("2026-11-26", "09:41"), THU, timing, TZ) == 0
    assert early_minutes(ist("2026-11-26", "15:50"), THU, timing, TZ) == 10
    assert cap_shift(timing, "09:30", "18:30") == ("11:00", "16:00")


def test_ist_day_is_the_attendance_date_across_utc_midnight():
    # 00:20 IST Friday is 18:50 UTC Thursday. Thursday is scheduled off, Friday starts 09:00.
    week = office_week(start="09:00", end="18:00", break_minutes=None).copy()
    week = {"grace_minutes": 10, "week": dict(week["week"])}
    week["week"]["3"] = {"working": False}
    thursday = resolve_day(THU, week, None, "09:00", "18:00")
    friday = resolve_day(FRI, week, None, "09:00", "18:00")
    moment = datetime(2026, 11, 26, 18, 50, tzinfo=timezone.utc)  # Fri 00:20 IST
    assert thursday.working is False
    assert late_minutes(moment, THU, thursday, TZ) is None
    assert friday.working is True and friday.start == "09:00"
    assert late_minutes(moment, FRI, friday, TZ) == 0
    late_moment = datetime(2026, 11, 27, 3, 41, tzinfo=timezone.utc)  # Fri 09:11 IST
    assert late_minutes(late_moment, FRI, friday, TZ) == 1


def test_default_shift_keeps_the_15_minute_grace_and_is_not_early():
    timing = resolve_day(THU, None, None, "09:00", "18:00")
    assert late_minutes(ist("2026-11-26", "09:15"), THU, timing, TZ) == 0
    assert late_minutes(ist("2026-11-26", "09:16"), THU, timing, TZ) == 1
    assert early_minutes(ist("2026-11-26", "17:00"), THU, timing, TZ) is None
    assert cap_shift(timing, "09:00", "18:00") == ("09:00", "18:00")


def test_zero_grace_and_custom_grace():
    schedule = office_week()
    schedule["grace_minutes"] = 0
    timing = resolve_day(THU, schedule, None)
    assert late_minutes(ist("2026-11-26", "09:31"), THU, timing, TZ) == 1
    schedule["grace_minutes"] = 20
    timing = resolve_day(THU, schedule, None)
    assert late_minutes(ist("2026-11-26", "09:50"), THU, timing, TZ) == 0
    assert late_minutes(ist("2026-11-26", "09:51"), THU, timing, TZ) == 1


def test_validation_rejects_bad_windows_and_accepts_a_full_week():
    with pytest.raises(ValueError):
        validate_week({"0": {"working": True, "start": "09:00", "end": "18:00"}})
    with pytest.raises(ValueError):
        validate_override({"working": True, "start": "18:00", "end": "09:00"})
    with pytest.raises(ValueError):
        validate_override({"working": True, "start": "09:00", "end": "18:00", "break_minutes": 540})
    with pytest.raises(ValueError):
        validate_grace(121)
    week = validate_week(office_week()["week"])
    assert week["4"]["start"] == "09:30" and week["6"] == {"working": False}
    assert validate_grace("10") == 10
    assert summarize_override("2026-11-26", validate_override({"working": False})) == "2026-11-26 off"


def _person(user_id, role="employee", name=None):
    return {"user_id": user_id, "role": role, "name": name or user_id}


def test_sub_admin_scope_matches_the_existing_team_rules():
    sub = _person("sub", "sub_admin", "Sub")
    admin = _person("admin", "admin", "Admin")
    emp = _person("emp", "employee", "Ravi")
    outsider = _person("out", "employee", "Out")
    other_mgr = _person("mgr", "sub_admin", "Other")

    assert manager_may_edit(admin, outsider, False) is None
    assert manager_may_edit(sub, emp, True) is None
    assert manager_may_edit(sub, outsider, False) == "This employee is not in your team"
    assert manager_may_edit(sub, sub, True) == "Only an admin can change your own settings"
    assert manager_may_edit(sub, other_mgr, True) == "Only an admin can manage another admin"
    assert manager_may_edit(sub, admin, True) == "Only an admin can manage another admin"
    assert manager_may_edit(_person("e", "employee"), emp, True) == "Admin access required"

    scope = {"sub", "emp"}  # scoped_user_ids includes the sub-admin themselves
    allowed, skipped = split_editable(sub, [emp, outsider, sub, other_mgr], scope)
    assert [p["user_id"] for p in allowed] == ["emp"]
    reasons = {s["user_id"]: s["reason"] for s in skipped}
    assert "not in your team" in reasons["out"]
    assert "your own settings" in reasons["sub"]
    assert "another admin" in reasons["mgr"]

    everyone, skipped_admin = split_editable(admin, [emp, outsider, sub], None)
    assert [p["user_id"] for p in everyone] == ["emp", "out", "sub"]
    assert skipped_admin == []
