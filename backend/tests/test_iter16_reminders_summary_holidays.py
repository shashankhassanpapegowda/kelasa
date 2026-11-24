# Iteration 16: missed-checkout reminder cron, push 'reminders' pref, monthly payroll summary (xlsx/csv), sub-admin holidays
import csv
import io
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
import requests
from openpyxl import load_workbook
from pymongo import MongoClient

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")


def _env(key):
    with open("/app/backend/.env") as f:
        for line in f:
            if line.startswith(key + "="):
                return line.split("=", 1)[1].strip().strip('"')


CRON_SECRET = _env("WEBHOOK_CRON_SECRET")
db = MongoClient(_env("MONGO_URL"))[_env("DB_NAME")]
ADMIN, SUB, EMP = "test_session_admin_001", "test_session_subadmin_001", "test_session_emp_001"
IST = ZoneInfo("Asia/Kolkata")
SUMMARY_HEADERS = ["Days in Month", "Present Days", "Absent Days", "Work Hours (h:mm)", "Work Hours (decimal)"]


def H(tok):
    return {"Authorization": f"Bearer {tok}"}


# ---------- Cron auth ----------
class TestCronAuth:
    def test_no_bearer(self):
        r = requests.post(f"{BASE_URL}/api/cron/checkout-reminders")
        assert r.status_code == 401

    def test_wrong_bearer(self):
        r = requests.post(f"{BASE_URL}/api/cron/checkout-reminders", headers=H("wrong"))
        assert r.status_code == 401

    def test_good_bearer(self):
        r = requests.post(f"{BASE_URL}/api/cron/checkout-reminders", headers=H(CRON_SECRET))
        assert r.status_code == 200
        assert r.json() == {"ok": True, "queued": True}


# ---------- Cron behaviour on throwaway users ----------
@pytest.fixture(scope="module")
def reminder_data():
    now_l = datetime.now(IST)
    tag = uuid.uuid4().hex[:6]
    ended = (now_l - timedelta(minutes=30))
    later = (now_l + timedelta(hours=2))
    if ended.date() != now_l.date() or later.date() != now_l.date():
        pytest.skip("Too close to midnight IST for same-day shift scenarios")
    specs = {
        "ended": ("06:00" if ended.hour >= 7 else "00:01", ended.strftime("%H:%M")),
        "later": ("06:00" if now_l.hour >= 7 else "00:01", later.strftime("%H:%M")),
        "night": ("22:00", "06:00"),
        "noshift": (None, None),
    }
    users, recs = [], {}
    check_in = (now_l - timedelta(minutes=45 if now_l.hour >= 1 else 5))
    for k, (s, e) in specs.items():
        uid = f"TEST_rem_{k}_{tag}"
        db.users.insert_one({"user_id": uid, "email": f"TEST_{k}_{tag}@example.test", "name": f"TEST_{k}",
                             "role": "employee", "shift_start": s, "shift_end": e, "timezone": "Asia/Kolkata",
                             "face_enrolled": True, "created_at": datetime.now(timezone.utc).isoformat()})
        rid = f"att_TEST_{k}_{tag}"
        db.attendance.insert_one({"record_id": rid, "user_id": uid, "date": now_l.date().isoformat(),
                                  "check_in": check_in.astimezone(timezone.utc).isoformat(), "check_out": None,
                                  "status": "on_duty", "breaks": [], "total_break_minutes": 0, "on_break": False})
        users.append(uid)
        recs[k] = rid
    # fake push sub for "ended" user (push will fail silently)
    ep = f"https://fcm.googleapis.com/fcm/send/TEST_{tag}"
    db.push_subscriptions.insert_one({"endpoint": ep, "user_id": users[0], "keys": {"p256dh": "x", "auth": "y"}})
    yield recs
    db.attendance.delete_many({"record_id": {"$in": list(recs.values())}})
    db.users.delete_many({"user_id": {"$in": users}})
    db.push_subscriptions.delete_many({"endpoint": ep})


class TestCronBehaviour:
    def test_only_ended_shift_flagged_and_once(self, reminder_data):
        r = requests.post(f"{BASE_URL}/api/cron/checkout-reminders", headers=H(CRON_SECRET), json={"run_id": "t1"})
        assert r.status_code == 200
        time.sleep(4)
        flags = {k: db.attendance.find_one({"record_id": rid}) for k, rid in reminder_data.items()}
        assert flags["ended"].get("checkout_reminder_sent") is True
        first_at = flags["ended"]["checkout_reminder_at"]
        for k in ("later", "night", "noshift"):
            assert not flags[k].get("checkout_reminder_sent"), k
        # second call: no resend
        r = requests.post(f"{BASE_URL}/api/cron/checkout-reminders", headers=H(CRON_SECRET))
        assert r.status_code == 200
        time.sleep(4)
        again = db.attendance.find_one({"record_id": reminder_data["ended"]})
        assert again["checkout_reminder_sent"] is True
        assert again["checkout_reminder_at"] == first_at
        for k in ("later", "night", "noshift"):
            assert not db.attendance.find_one({"record_id": reminder_data[k]}).get("checkout_reminder_sent"), k

    def test_invalid_body(self):
        r = requests.post(f"{BASE_URL}/api/cron/checkout-reminders", headers={**H(CRON_SECRET), "Content-Type": "application/json"}, data="[1,2]")
        assert r.status_code == 400


# ---------- Push reminders preference ----------
class TestPushReminders:
    def test_patch_and_status(self):
        ep = f"https://fcm.googleapis.com/fcm/send/TEST_{uuid.uuid4().hex[:8]}"
        try:
            r = requests.post(f"{BASE_URL}/api/push/subscribe", headers=H(EMP), json={"endpoint": ep, "keys": {"p256dh": "x", "auth": "y"}})
            assert r.status_code == 200
            s = requests.get(f"{BASE_URL}/api/push/status", headers=H(EMP), params={"endpoint": ep}).json()
            assert s["reminders"] is True
            r = requests.patch(f"{BASE_URL}/api/push/subscribe", headers=H(EMP), json={"endpoint": ep, "reminders": False})
            assert r.status_code == 200 and r.json()["reminders"] is False
            s = requests.get(f"{BASE_URL}/api/push/status", headers=H(EMP), params={"endpoint": ep}).json()
            assert s["reminders"] is False and s["this_device"] is True
        finally:
            requests.delete(f"{BASE_URL}/api/push/subscribe", headers=H(EMP), params={"endpoint": ep})


# ---------- Payroll summary ----------
def _month():
    return datetime.now(IST).strftime("%Y-%m")


class TestPayrollSummary:
    def test_xlsx_admin(self):
        r = requests.get(f"{BASE_URL}/api/admin/reports/payroll-summary", headers=H(ADMIN), params={"month": _month(), "format": "xlsx"})
        assert r.status_code == 200
        assert "spreadsheetml" in r.headers["content-type"]
        assert f"payroll_summary_{_month()}.xlsx" in r.headers["content-disposition"]
        ws = load_workbook(io.BytesIO(r.content)).active
        header = [c.value for c in ws[1]]
        for h in SUMMARY_HEADERS:
            assert h in header
        assert any(h.startswith("Auto-closed Days") for h in header)
        assert ws.max_row >= 3
        emails = [row[1] for row in ws.iter_rows(min_row=2, values_only=True)]
        assert "emp1.test@gtgroups.local" in emails and "emp2.test@gtgroups.local" in emails
        row = next(r_ for r_ in ws.iter_rows(min_row=2, values_only=True) if r_[1] == "emp1.test@gtgroups.local")
        dim = header.index("Days in Month")
        assert row[dim] in (28, 29, 30, 31)
        hm, dec = row[header.index("Work Hours (h:mm)")], row[header.index("Work Hours (decimal)")]
        hh, mm = map(int, hm.split(":"))
        assert abs((hh * 60 + mm) / 60 - dec) < 0.01

    def test_csv_admin(self):
        r = requests.get(f"{BASE_URL}/api/admin/reports/payroll-summary", headers=H(ADMIN), params={"month": _month(), "format": "csv"})
        assert r.status_code == 200
        assert "text/csv" in r.headers["content-type"]
        rows = list(csv.reader(io.StringIO(r.text.lstrip("\ufeff"))))
        for h in SUMMARY_HEADERS:
            assert h in rows[0]
        assert len(rows) >= 3

    def test_subadmin_team_only(self):
        r = requests.get(f"{BASE_URL}/api/admin/reports/payroll-summary", headers=H(SUB), params={"month": _month(), "format": "csv"})
        assert r.status_code == 200
        emails = [row[1] for row in list(csv.reader(io.StringIO(r.text.lstrip("\ufeff"))))[1:]]
        assert "emp1.test@gtgroups.local" in emails
        assert "emp2.test@gtgroups.local" not in emails
        assert "shashank@gtgroups.in" not in emails

    def test_employee_403(self):
        r = requests.get(f"{BASE_URL}/api/admin/reports/payroll-summary", headers=H(EMP), params={"month": _month()})
        assert r.status_code == 403

    def test_no_auth_401(self):
        r = requests.get(f"{BASE_URL}/api/admin/reports/payroll-summary", params={"month": _month()})
        assert r.status_code == 401

    @pytest.mark.parametrize("m", ["2026-13", "2026-00", "abc", "2026-1"])
    def test_invalid_month(self, m):
        r = requests.get(f"{BASE_URL}/api/admin/reports/payroll-summary", headers=H(ADMIN), params={"month": m})
        assert r.status_code in (400, 422)

    def test_invalid_format(self):
        r = requests.get(f"{BASE_URL}/api/admin/reports/payroll-summary", headers=H(ADMIN), params={"month": _month(), "format": "pdf"})
        assert r.status_code == 422

    def test_auth_query_param(self):
        r = requests.get(f"{BASE_URL}/api/admin/reports/payroll-summary", params={"month": _month(), "format": "xlsx", "auth": ADMIN})
        assert r.status_code == 200
        load_workbook(io.BytesIO(r.content))

    def test_december_month(self):
        r = requests.get(f"{BASE_URL}/api/admin/reports/payroll-summary", headers=H(ADMIN), params={"month": "2026-12", "format": "csv"})
        assert r.status_code == 200
        rows = list(csv.reader(io.StringIO(r.text.lstrip("\ufeff"))))
        assert rows[1][rows[0].index("Days in Month")] == "31"


# ---------- Holidays (sub-admin) ----------
class TestHolidays:
    def test_subadmin_add_delete(self):
        date = f"2031-0{1 + int(uuid.uuid4().int % 9)}-1{uuid.uuid4().int % 9}"
        r = requests.post(f"{BASE_URL}/api/admin/holidays", headers=H(SUB), json={"date": date, "name": "TEST_SubHoliday"})
        assert r.status_code == 200, r.text
        hid = r.json()["holiday"]["holiday_id"]
        try:
            lst = requests.get(f"{BASE_URL}/api/holidays", headers=H(SUB), params={"year": 2031}).json()["holidays"]
            assert any(h["holiday_id"] == hid for h in lst)
        finally:
            d = requests.delete(f"{BASE_URL}/api/admin/holidays/{hid}", headers=H(SUB))
        assert d.status_code == 200
        lst = requests.get(f"{BASE_URL}/api/holidays", headers=H(SUB), params={"year": 2031}).json()["holidays"]
        assert not any(h["holiday_id"] == hid for h in lst)

    def test_employee_forbidden(self):
        r = requests.post(f"{BASE_URL}/api/admin/holidays", headers=H(EMP), json={"date": "2031-02-02", "name": "TEST_x"})
        assert r.status_code == 403
        r = requests.delete(f"{BASE_URL}/api/admin/holidays/hol_seed01", headers=H(EMP))
        assert r.status_code == 403
