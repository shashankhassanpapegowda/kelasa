"""Staff workflow rules: one paid leave day, sandwich LOP, corrections, notices, month summary.

These tests call the same helpers the API and payroll NDP use. They do not need a server.
"""
from datetime import date, timedelta
from decimal import Decimal

from payroll_calc import D
from payroll_ndp import days_paid
from staff_rules import (
    absent_people_for, announcement_push_user_ids, announcement_visible,
    classify_leave_days, correction_window_error, leave_warning_dates, project_month_summary,
    select_announcements,
)

ZERO = Decimal("0")
SHIFT = dict(has_shift=True, shift_start="09:00", shift_end="18:00")


def _paid(year, month, **kwargs):
    return days_paid(year=year, month=month, nwd=D(kwargs.pop("nwd", 30 if month == 6 else 31)),
                     today=kwargs.pop("today", date(year, month, 28)), weekly_off=kwargs.pop("weekly_off", [6]),
                     **SHIFT, **kwargs)


def test_weekly_off_is_not_charged_and_sunday_only_by_default():
    # Mon 1 Jun 2026 through Sun 7. Sunday is the default weekly off.
    result = classify_leave_days("2026-06-01", "2026-06-07", False, off_dates=[date(2026, 6, 7)])
    assert result["days"] == Decimal("6")
    assert result["paid_days"] == Decimal("1")
    assert result["lop_days"] == Decimal("5")
    assert "2026-06-07" in result["skipped_dates"]
    assert "2026-06-01" in result["paid_dates"]


def test_sandwich_off_friday_holiday_charges_one_paid_day_and_keeps_holiday():
    # Thu 4 Jun 2026 leave, Fri 5 holiday. Saturday and Monday elsewhere stay paid leave.
    thursday = classify_leave_days("2026-06-04", "2026-06-04", False, holiday_dates=[date(2026, 6, 5)])
    assert thursday["paid_days"] == Decimal("1")
    assert thursday["lop_days"] == ZERO
    assert thursday["paid_dates"] == ["2026-06-04"]
    ndp = _paid(2026, 6, holidays=["2026-06-05"], leaves=[{
        "start_date": "2026-06-04", "end_date": "2026-06-04", "status": "approved", "paid": True,
        "leave_type": "Leave", "paid_dates": thursday["paid_dates"], "lop_dates": thursday["lop_dates"],
    }], sandwich_enabled=False)
    assert ndp["paid_leave"]["Leave"] == Decimal("1")
    assert ndp["holidays"] == Decimal("1")

    saturday = classify_leave_days("2026-06-13", "2026-06-13", False)
    monday = classify_leave_days("2026-06-15", "2026-06-15", False)
    assert saturday["paid_dates"] == ["2026-06-13"]
    assert monday["paid_dates"] == ["2026-06-15"]
    assert leave_warning_dates(saturday, False) == []
    assert leave_warning_dates(monday, False) == []


def test_sandwich_on_for_one_branch_only_saturday_and_monday_are_lop():
    saturday = date(2026, 6, 13)  # no holiday that week
    monday = date(2026, 6, 15)
    enabled = classify_leave_days(saturday, saturday, False, sandwich_enabled=True)
    other = classify_leave_days(saturday, saturday, False, sandwich_enabled=False)
    assert enabled["paid_days"] == ZERO
    assert enabled["lop_dates"] == ["2026-06-13"]
    assert other["paid_days"] == Decimal("1")
    monday_on = classify_leave_days(monday, monday, False, sandwich_enabled=True)
    assert monday_on["lop_dates"] == ["2026-06-15"]
    assert monday_on["paid_days"] == ZERO

    lop_ndp = _paid(2026, 6, leaves=[{
        "start_date": "2026-06-13", "end_date": "2026-06-13", "status": "approved",
        "leave_type": "Leave", "type_code": "LV", "paid_dates": [], "lop_dates": ["2026-06-13"],
    }], sandwich_enabled=True)
    paid_ndp = _paid(2026, 6, leaves=[{
        "start_date": "2026-06-13", "end_date": "2026-06-13", "status": "approved", "paid": True,
        "leave_type": "Leave", "paid_dates": ["2026-06-13"], "lop_dates": [],
    }], sandwich_enabled=False)
    assert "Leave" not in lop_ndp["paid_leave"]
    assert paid_ndp["paid_leave"]["Leave"] == Decimal("1")
    # The enabled branch does not pay that Saturday; the other branch does.
    assert lop_ndp["ndp"] == paid_ndp["ndp"] - Decimal("1")


def test_friday_holiday_sandwich_makes_thursday_friday_saturday_lop():
    hol = date(2026, 6, 5)  # Friday
    span = classify_leave_days("2026-06-04", "2026-06-06", False, holiday_dates=[hol], sandwich_enabled=True)
    assert span["lop_dates"] == ["2026-06-04", "2026-06-05", "2026-06-06"]
    assert span["paid_days"] == ZERO
    warned = leave_warning_dates(span, True)
    assert warned == ["2026-06-04", "2026-06-05", "2026-06-06"]
    off = _paid(2026, 6, holidays=["2026-06-05"], sandwich_enabled=False)
    on = _paid(2026, 6, holidays=["2026-06-05"], sandwich_enabled=True)
    assert off["holidays"] == Decimal("1")
    assert on["holidays"] == ZERO
    assert on["ndp"] == off["ndp"] - Decimal("1")
    # A punch on the holiday stays present.
    punched = _paid(2026, 6, holidays=["2026-06-05"], sandwich_enabled=True, sessions_by_date={
        "2026-06-05": [{"net_work_minutes": 480, "check_out": "2026-06-05T12:30:00+00:00", "late_by_minutes": 0}],
    })
    assert punched["present"] == Decimal("1")
    assert punched["ndp"] == on["ndp"] + Decimal("1")


def test_wednesday_holiday_sandwich_makes_tue_wed_thu_lop():
    hol = date(2026, 6, 10)  # Wednesday
    span = classify_leave_days("2026-06-09", "2026-06-11", False, holiday_dates=[hol], sandwich_enabled=True)
    assert span["lop_dates"] == ["2026-06-09", "2026-06-10", "2026-06-11"]
    assert span["paid_days"] == ZERO
    on = _paid(2026, 6, holidays=["2026-06-10"], sandwich_enabled=True)
    off = _paid(2026, 6, holidays=["2026-06-10"], sandwich_enabled=False)
    assert on["holidays"] == ZERO
    assert off["holidays"] == Decimal("1")
    assert on["ndp"] == off["ndp"] - Decimal("1")


def test_warning_names_lop_dates_only_when_the_branch_opted_in():
    span = classify_leave_days("2026-06-13", "2026-06-15", False, sandwich_enabled=True)  # Sat, Sun, Mon
    # Sunday is not a sandwich weekday and, with no off_dates passed, is a normal candidate.
    # Saturday and Monday are named. The disabled branch names nothing.
    assert "2026-06-13" in leave_warning_dates(span, True)
    assert "2026-06-15" in leave_warning_dates(span, True)
    assert leave_warning_dates(span, False) == []
    quiet = classify_leave_days("2026-06-13", "2026-06-15", False, off_dates=[date(2026, 6, 14)], sandwich_enabled=False)
    assert quiet["paid_days"] == Decimal("1")
    assert leave_warning_dates(quiet, False) == []


def test_days_paid_matches_the_monthly_balance():
    # Three weekdays, no sandwich: one paid, two LOP. NDP counts the same one paid day.
    classified = classify_leave_days("2026-06-02", "2026-06-04", False)
    assert classified["paid_days"] == Decimal("1")
    assert classified["lop_days"] == Decimal("2")
    result = _paid(2026, 6, leaves=[{
        "start_date": "2026-06-02", "end_date": "2026-06-04", "status": "approved",
        "leave_type": "Leave", "type_code": "LV", "half_day": False,
        "paid_dates": classified["paid_dates"], "lop_dates": classified["lop_dates"],
    }])
    assert result["paid_leave"]["Leave"] == classified["paid_days"]
    assert result["unpaid_leave"]["Leave"] == classified["lop_days"]
    summary = project_month_summary("2026-06", result)
    assert summary["ndp"] == float(result["ndp"])
    assert summary["lop"] == float(result["lop"])
    assert summary["paid_leave_days"] == 1
    assert summary["unpaid_leave_days"] == 2
    assert summary["holidays"] == float(result["holidays"])


def test_historical_leave_still_counts_and_scheduled_window_decides_half_day():
    historical = _paid(2026, 10, nwd=31, today=date(2026, 11, 1), holidays=["2026-10-03"], sessions_by_date={
        "2026-10-01": [{"net_work_minutes": 60, "check_out": "2026-10-01T10:00:00+00:00", "late_by_minutes": 0}],
    }, leaves=[{
        "start_date": "2026-10-02", "end_date": "2026-10-02", "status": "approved", "paid": True,
        "leave_type": "Casual Leave", "half_day": False,
    }])
    assert historical["paid_leave"]["Casual Leave"] == Decimal("1")
    assert historical["holidays"] == Decimal("1")
    assert historical["half_days"] == Decimal("1")

    # 90 minutes is a half day on a 09:00–18:00 shift, and a full day on a 09:00–11:00 schedule.
    short = {"2026-06-02": [{"net_work_minutes": 90, "check_out": "2026-06-02T05:00:00+00:00", "late_by_minutes": 0}]}
    legacy = _paid(2026, 6, sessions_by_date=short)
    scheduled = _paid(2026, 6, sessions_by_date=short, day_windows={"2026-06-02": ("09:00", "11:00")})
    assert legacy["half_days"] == Decimal("1")
    assert scheduled["half_days"] == ZERO
    assert scheduled["present"] == Decimal("1")


def test_correction_window_is_seven_days_and_blocks_the_future():
    today = date(2026, 11, 27)
    assert correction_window_error(today, today) is None
    assert correction_window_error(today - timedelta(days=7), today) is None
    assert "7 days" in correction_window_error(today - timedelta(days=8), today)
    assert "future" in correction_window_error(today + timedelta(days=1), today)


def test_announcement_branch_targeting_hides_and_skips_other_branches():
    notice = {"audience": "branches", "branches": ["Bengaluru HQ"], "author_id": "admin"}
    company = {"audience": "all", "branches": [], "author_id": "admin"}
    hq = {"role": "employee", "site": "Bengaluru HQ", "user_id": "hq"}
    yard = {"role": "employee", "site": "Tumkur Yard", "user_id": "yard"}
    sub = {"role": "sub_admin", "managed_sites": ["Tumkur Yard"], "user_id": "sub", "site": "Tumkur Yard"}
    admin = {"role": "admin", "user_id": "admin", "site": "Tumkur Yard"}
    assert announcement_visible(notice, hq)
    assert not announcement_visible(notice, yard)
    assert not announcement_visible(notice, sub)
    assert announcement_visible(notice, admin)
    assert announcement_visible(company, yard)
    assert announcement_visible({}, yard)  # older notices are company-wide
    recipients = announcement_push_user_ids(notice, [hq, yard, sub, admin], author_id="admin")
    assert recipients == {"hq"}


def test_legacy_notice_without_audience_is_visible_to_admin_and_everyone():
    # A document created before branch targeting: no audience and no branches keys at all.
    legacy = {
        "announcement_id": "ann_legacy",
        "title": "Office closed Friday",
        "body": "The yard is shut.",
        "pinned": True,
        "author_id": "user_old_admin",
        "author_name": "Admin",
        "created_at": "2026-08-15T04:30:00+00:00",
        "notify_phones": True,
    }
    assert "audience" not in legacy
    assert "branches" not in legacy
    branch_only = {
        "announcement_id": "ann_hq",
        "title": "HQ only",
        "body": "Ignore elsewhere",
        "pinned": False,
        "audience": "branches",
        "branches": ["Bengaluru HQ"],
        "created_at": "2026-11-01T00:00:00+00:00",
    }
    admin = {"role": "admin", "user_id": "admin", "site": "Tumkur Yard"}
    employee = {"role": "employee", "user_id": "yard", "site": "Tumkur Yard"}
    sub = {"role": "sub_admin", "user_id": "sub", "managed_sites": ["Tumkur Yard"], "site": "Tumkur Yard"}
    for viewer in (admin, employee, sub):
        shown = select_announcements([legacy], viewer, limit=20)
        assert [row["announcement_id"] for row in shown] == ["ann_legacy"]
        assert shown[0]["audience"] == "all"
        assert shown[0]["branches"] == []
        assert announcement_visible(legacy, viewer)
    # Admin still sees a branch notice and the legacy company notice. Another branch does not see the branch notice.
    admin_rows = select_announcements([branch_only, legacy], admin, limit=20)
    assert {row["announcement_id"] for row in admin_rows} == {"ann_legacy", "ann_hq"}
    assert admin_rows[0]["announcement_id"] == "ann_legacy"  # pinned legacy notice stays first
    yard_rows = select_announcements([branch_only, legacy], employee, limit=1)
    assert [row["announcement_id"] for row in yard_rows] == ["ann_legacy"]


def test_absent_today_is_branch_isolated():
    people = [
        {"user_id": "a", "name": "Asha", "site": "Bengaluru HQ"},
        {"user_id": "b", "name": "Bala", "site": "Tumkur Yard"},
    ]
    employee = absent_people_for({"role": "employee", "site": "Bengaluru HQ"}, people)
    assert [p["name"] for p in employee] == ["Asha"]
    sub = absent_people_for({"role": "sub_admin", "managed_sites": ["Tumkur Yard"]}, people)
    assert [p["name"] for p in sub] == ["Bala"]
    admin = absent_people_for({"role": "admin"}, people)
    assert {p["name"] for p in admin} == {"Asha", "Bala"}
    # A pending leave is simply not in this list: the endpoint only loads approved leave.
