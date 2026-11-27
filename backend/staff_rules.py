"""Shared staff rules for leave, sandwich LOP, notices and corrections.

Pure functions so leave requests, the calendar, month summary and payroll NDP
classify a day the same way. Nothing here touches the database.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Iterable, Optional

PAID_LEAVE_CODE = "LV"
PAID_LEAVE_NAME = "Leave"
PAID_PER_MONTH = Decimal("1")
# Monday = 0 … Saturday = 5. Both are loss-of-pay all year when a branch opts in.
SANDWICH_WEEKDAYS = {0, 5}
CORRECTION_WINDOW_DAYS = 7
HOLIDAY_ONLY_MESSAGE = "Those dates are already company holidays"
WEEKLY_OFF_ONLY_MESSAGE = "Those dates are weekly offs"


def is_sandwich_day(day: date, holiday_dates: Iterable, enabled: bool) -> bool:
    """Unworked days in this set are LOP when the branch toggle is on.

    Any Saturday and any Monday, plus the day before, the day of, and the day
    after each declared holiday that applies to the branch.
    """
    if not enabled:
        return False
    if day.weekday() in SANDWICH_WEEKDAYS:
        return True
    hols = set(holiday_dates or [])
    return (day - timedelta(days=1)) in hols or day in hols or (day + timedelta(days=1)) in hols


def _as_date(value) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def iter_span(start: date, end: date, half_day: bool):
    if half_day:
        yield start
        return
    cur = start
    while cur <= end:
        yield cur
        cur += timedelta(days=1)


def classify_leave_days(
    start,
    end,
    half_day: bool,
    *,
    off_dates: Iterable = (),
    holiday_dates: Iterable = (),
    sandwich_enabled: bool = False,
    already_paid=None,
) -> dict:
    """Split a request into the one monthly paid day, LOP days, and days not charged.

    Weekly offs and ordinary holidays are not charged. Sandwich days (when the
    branch has opted in) are LOP and are not charged to the monthly paid leave.
    Days past the one paid day in a calendar month are LOP too. Nothing is
    rejected here — the caller rejects a span with nothing left to charge.
    `already_paid` is month (YYYY-MM) -> days already taken by other requests.
    """
    start_d, end_d = _as_date(start), _as_date(end)
    portion = Decimal("0.5") if half_day else Decimal("1")
    offs = {_as_date(d) for d in (off_dates or [])}
    hols = {_as_date(d) for d in (holiday_dates or [])}
    used = {}
    for month, taken in (already_paid or {}).items():
        used[str(month)] = Decimal(str(taken))
    paid, lop, skipped = [], [], []
    for day in iter_span(start_d, end_d, half_day):
        if is_sandwich_day(day, hols, sandwich_enabled):
            lop.append(day)
            continue
        if day in offs or day in hols:
            skipped.append(day)
            continue
        month = f"{day.year:04d}-{day.month:02d}"
        taken = used.get(month, Decimal("0"))
        if taken + portion <= PAID_PER_MONTH:
            paid.append(day)
            used[month] = taken + portion
        else:
            lop.append(day)

    def total(days) -> Decimal:
        return portion * len(days)

    return {
        "paid_dates": [d.isoformat() for d in paid],
        "lop_dates": [d.isoformat() for d in lop],
        "skipped_dates": [d.isoformat() for d in skipped],
        "paid_days": total(paid),
        "lop_days": total(lop),
        "days": total(paid) + total(lop),
        "sandwich_enabled": bool(sandwich_enabled),
    }


def empty_span_message(skipped_dates: Iterable[str], holiday_dates: Iterable) -> str:
    """Why a request that charges nothing was refused. Holidays keep the existing wording."""
    hols = {_as_date(d).isoformat() for d in (holiday_dates or [])}
    if any(str(d)[:10] in hols for d in skipped_dates):
        return HOLIDAY_ONLY_MESSAGE
    return WEEKLY_OFF_ONLY_MESSAGE


def leave_warning_dates(classification: dict, sandwich_enabled: bool) -> list:
    """LOP dates to name on the leave form. Hidden entirely when the branch toggle is off."""
    if not sandwich_enabled:
        return []
    return list(classification.get("lop_dates") or [])


def correction_window_error(day: date, today: date, limit: int = CORRECTION_WINDOW_DAYS) -> Optional[str]:
    """None when a correction may be filed. Future days stay forbidden; late filing is refused."""
    if day > today:
        return "You can't correct a future day"
    if (today - day).days > limit:
        return "You can only correct a day within the last 7 days"
    return None


def announcement_branches(doc: dict) -> list:
    """Branch names on a notice. Missing, null, or a non-list is no branches."""
    raw = doc.get("branches") if isinstance(doc, dict) else None
    if isinstance(raw, str):
        text = raw.strip()
        return [text] if text else []
    if not isinstance(raw, (list, tuple)):
        return []
    return [b.strip() for b in raw if isinstance(b, str) and b.strip()]


def normalize_announcement(doc: dict) -> dict:
    """Legacy notices (no audience field) are company-wide. A branch notice with no names is too."""
    out = dict(doc or {})
    branches = announcement_branches(out)
    audience = out.get("audience")
    if audience == "branches" and branches:
        out["audience"] = "branches"
        out["branches"] = branches
    else:
        out["audience"] = "all"
        out["branches"] = []
    created = out.get("created_at")
    if created is not None and not isinstance(created, str) and hasattr(created, "isoformat"):
        out["created_at"] = created.isoformat()
    return out


def announcement_visible(doc: dict, user: dict) -> bool:
    """Who can read a notice. Missing audience is company-wide, same as older documents.

    Admins see every notice. Everyone else sees company-wide notices plus branch
    notices that name their site (or, for a sub-admin, a branch they manage).
    """
    notice = normalize_announcement(doc)
    role = (user or {}).get("role")
    if role == "admin":
        return True
    if notice["audience"] != "branches":
        return True
    branches = set(notice["branches"])
    if role == "sub_admin":
        return bool(set((user or {}).get("managed_sites") or []) & branches)
    return ((user or {}).get("site") or "") in branches


def select_announcements(docs: Iterable[dict], user: dict, limit: int = 20) -> list:
    """Pinned first, then newest. Filter only after the full read so a legacy notice is not dropped."""
    rows = [normalize_announcement(doc) for doc in docs or []]

    def sort_key(doc):
        created = doc.get("created_at") or ""
        if not isinstance(created, str):
            created = str(created)
        return (1 if doc.get("pinned") else 0, created)

    rows.sort(key=sort_key, reverse=True)
    if (user or {}).get("role") == "admin":
        chosen = rows
    else:
        chosen = [doc for doc in rows if announcement_visible(doc, user)]
    try:
        cap = int(limit)
    except (TypeError, ValueError):
        cap = 20
    return chosen[: max(1, min(cap, 100))]


def announcement_push_user_ids(doc: dict, users: Iterable[dict], author_id: Optional[str] = None) -> set:
    """Devices to notify. Company-wide reaches everyone except the author.
    A branch notice reaches that branch, and sub-admins who manage it — not staff elsewhere.
    A notice with no audience is company-wide.
    """
    notice = normalize_announcement(doc)
    company = notice["audience"] != "branches"
    wanted = set(notice["branches"])
    out = set()
    for user in users:
        uid = user.get("user_id")
        if not uid or uid == author_id:
            continue
        if company:
            out.add(uid)
            continue
        if user.get("role") == "sub_admin" and wanted & set(user.get("managed_sites") or []):
            out.add(uid)
        elif user.get("site") in wanted:
            out.add(uid)
    return out


def _num(value) -> float:
    if value is None or value == "":
        return 0.0
    return float(value)


def project_month_summary(month: str, breakdown: dict) -> dict:
    """The staff month card. `breakdown` is the days_paid result (decimals or already frozen strings)."""
    paid = breakdown.get("paid_leave") or {}
    unpaid = breakdown.get("unpaid_leave") or {}
    names = sorted(set(paid) | set(unpaid))
    leave_by_type = [{
        "name": name,
        "paid": _num(paid.get(name, 0)),
        "unpaid": _num(unpaid.get(name, 0)),
    } for name in names]
    present = _num(breakdown.get("present"))
    late = _num(breakdown.get("late"))
    punch = _num(breakdown.get("punch_errors"))
    return {
        "month": month,
        "present": present - late - punch,
        "late": late,
        "half_days": _num(breakdown.get("half_days")),
        "leave_by_type": leave_by_type,
        "paid_leave_days": sum(item["paid"] for item in leave_by_type),
        "unpaid_leave_days": sum(item["unpaid"] for item in leave_by_type),
        "holidays": _num(breakdown.get("holidays")),
        "weekly_offs": _num(breakdown.get("weekly_offs")),
        "absences": _num(breakdown.get("lop")),
        "lop": _num(breakdown.get("lop")),
        "punch_errors": punch,
        "ndp": _num(breakdown.get("ndp")),
        "nwd": _num(breakdown.get("nwd")),
        "net_work_minutes": int(breakdown.get("net_work_minutes") or 0),
        "overtime_minutes": int(breakdown.get("overtime_minutes") or 0),
        "total_break_minutes": int(breakdown.get("total_break_minutes") or 0),
    }


def absent_people_for(viewer: dict, people: Iterable[dict], scoped_ids=None) -> list:
    """Approved-leave names a viewer may see. Grouped later by the caller.

    Admin: every branch. Sub-admin: their managed branches (or their team when
    they have no branches yet). Employee: their own branch only.
    """
    role = viewer.get("role")
    chosen = []
    if role == "admin":
        chosen = list(people)
    elif role == "sub_admin":
        mine = set(viewer.get("managed_sites") or [])
        if mine:
            chosen = [p for p in people if p.get("site") in mine]
        else:
            allowed = set(scoped_ids or [])
            chosen = [p for p in people if p.get("user_id") in allowed]
    else:
        site = viewer.get("site")
        chosen = [p for p in people if site and p.get("site") == site]
    return chosen
