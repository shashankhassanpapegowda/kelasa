from datetime import date
from attendance_calc import compute_session, session_cap, day_status, is_late, late_by, MAX_NET_MINUTES

TZ = "Asia/Kolkata"


def ist(s):  # "2026-10-26T17:12" local IST -> UTC iso
    from datetime import datetime
    from zoneinfo import ZoneInfo
    return datetime.fromisoformat(s).replace(tzinfo=ZoneInfo(TZ)).isoformat()


def test_unclosed_single_punch_auto_closes_at_2359_not_546h():
    cap = session_cap(ist("2026-10-26T17:12"), TZ, None, None)
    r = compute_session(ist("2026-10-26T17:12"), cap.isoformat(), 0)
    assert r["net_work_minutes"] == 6 * 60 + 47


def test_unclosed_closes_at_shift_end():
    cap = session_cap(ist("2026-10-26T09:28"), TZ, "09:30", "18:30")
    assert compute_session(ist("2026-10-26T09:28"), cap.isoformat(), 0)["net_work_minutes"] == 9 * 60 + 2


def test_short_session_is_15_minutes_not_24h():
    assert compute_session(ist("2026-10-26T09:28"), ist("2026-10-26T09:43"), 0)["net_work_minutes"] == 15


def test_next_day_checkout_is_capped_by_same_day_cap():
    cap = session_cap(ist("2026-10-26T09:28"), TZ, None, None)
    assert cap.isoformat() < ist("2026-10-27T09:43")
    assert compute_session(ist("2026-10-26T09:28"), cap.isoformat(), 0)["net_work_minutes"] == 14 * 60 + 31


def test_night_shift_closes_2359_same_day():
    cap = session_cap(ist("2026-10-26T21:00"), TZ, "21:00", "06:00")
    assert compute_session(ist("2026-10-26T21:00"), cap.isoformat(), 0)["net_work_minutes"] == 179


def test_net_capped_at_16h_with_flag():
    r = compute_session(ist("2026-10-26T00:00"), ist("2026-10-26T23:59"), 0)
    assert r["net_work_minutes"] == MAX_NET_MINUTES and r["over_cap"]


def test_breaks_subtracted_and_overtime():
    r = compute_session(ist("2026-10-26T09:30"), ist("2026-10-26T20:30"), 60, "09:30", "18:30")
    assert r["net_work_minutes"] == 600 and r["overtime_minutes"] == 60


def test_late_needs_shift_and_15min_grace():
    assert late_by(15) == 0 and late_by(16) == 1
    assert not is_late(late_by(15), True) and is_late(late_by(16), True) and not is_late(late_by(90), False)


def _st(d, **kw):
    base = dict(today=date(2026, 10, 31), present=False, late=False, on_leave=False, holiday=False,
                weekly_off=[6], has_shift=True, joined=None, pending_invite=False)
    base.update(kw)
    return day_status(d, **base)


def test_absent_rules():
    assert _st(date(2026, 10, 25)) == "weekly_off"  # Sunday
    assert _st(date(2026, 10, 27), holiday=True) == "holiday"
    assert _st(date(2026, 10, 27), has_shift=False) == "no_shift"
    assert _st(date(2026, 10, 27), joined=date(2026, 10, 28)) == "not_joined"
    assert _st(date(2026, 10, 27), pending_invite=True) == "not_joined"
    assert _st(date(2026, 10, 27), on_leave=True) == "leave"
    assert _st(date(2026, 11, 2)) == "future"
    assert _st(date(2026, 10, 27)) == "absent"
    assert _st(date(2026, 10, 27), present=True, late=True) == "late"
