# Iteration 15: Phase 1 payroll fixes (auto-close, absent rules, stats) + Phase 2 (activity, removal archive, ESI, weekly_off)
import os
import uuid
import pytest
import requests
from datetime import datetime, timedelta, timezone, date
from zoneinfo import ZoneInfo
from pymongo import MongoClient

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
IST = ZoneInfo("Asia/Kolkata")
ADMIN = {"Authorization": "Bearer test_session_admin_001"}
db = MongoClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))[os.environ.get("DB_NAME", "test_database")]

CREATED_USERS, CREATED_RECS, CREATED_LEAVES, CREATED_HOLS, CREATED_SESS = [], [], [], [], []


def mk_user(shift=None, pending=False, joined_days_ago=30, dept="TEST_Dept15", site="TEST_Site15"):
    tag = uuid.uuid4().hex[:6]
    body = {"name": f"TEST_Emp15_{tag}", "email": f"test_emp15_{tag}@example.com", "department": dept, "site": site}
    if shift:
        body.update(shift_start=shift[0], shift_end=shift[1])
    r = requests.post(f"{BASE_URL}/api/admin/employees", json=body, headers=ADMIN)
    assert r.status_code == 200, r.text
    uid = r.json()["employee"]["user_id"]
    CREATED_USERS.append(uid)
    created = (datetime.now(timezone.utc) - timedelta(days=joined_days_ago)).isoformat()
    db.users.update_one({"user_id": uid}, {"$set": {"pending_invite": pending, "created_at": created, "face_enrolled": True}})
    return uid, body["name"]


def ins_open(uid, check_in_dt):
    rid = f"rec_test15_{uuid.uuid4().hex[:8]}"
    db.attendance.insert_one({"record_id": rid, "user_id": uid, "date": check_in_dt.astimezone(IST).date().isoformat(),
                              "check_in": check_in_dt.astimezone(timezone.utc).isoformat(), "check_out": None,
                              "status": "on_duty", "breaks": [], "total_break_minutes": 0, "on_break": False,
                              "late_by_minutes": 0})
    CREATED_RECS.append(rid)
    return rid


@pytest.fixture(scope="module", autouse=True)
def cleanup():
    yield
    for uid in CREATED_USERS:
        requests.delete(f"{BASE_URL}/api/admin/employees/{uid}", headers=ADMIN)
        db.removed_users.delete_many({"user_id": uid})
        db.users.delete_many({"user_id": uid})
        db.attendance.delete_many({"user_id": uid})
        db.employee_profiles.delete_many({"user_id": uid})
        db.user_sessions.delete_many({"user_id": uid})
    for rid in CREATED_RECS:
        db.attendance.delete_many({"record_id": rid})
    for lid in CREATED_LEAVES:
        db.leave_requests.delete_many({"leave_id": lid})
    for hid in CREATED_HOLS:
        requests.delete(f"{BASE_URL}/api/admin/holidays/{hid}", headers=ADMIN)


def today_ist():
    return datetime.now(IST).date()


# ---- Auto-close of stale sessions ----
class TestAutoClose:
    def test_no_shift_closes_2359(self):
        uid, _ = mk_user(shift=None)
        y = today_ist() - timedelta(days=1)
        rid = ins_open(uid, datetime(y.year, y.month, y.day, 17, 12, tzinfo=IST))
        r = requests.get(f"{BASE_URL}/api/admin/stats", headers=ADMIN)
        assert r.status_code == 200
        rec = db.attendance.find_one({"record_id": rid})
        assert rec["check_out"] is not None
        out = datetime.fromisoformat(rec["check_out"]).astimezone(IST)
        assert (out.date(), out.hour, out.minute) == (y, 23, 59)
        assert rec["auto_closed"] is True and rec["auto_close_reason"] == "missed checkout"
        assert rec["net_work_minutes"] == 407 and rec["net_work_minutes"] <= 960

    def test_day_shift_closes_at_shift_end(self):
        uid, _ = mk_user(shift=("09:00", "18:00"))
        y = today_ist() - timedelta(days=1)
        rid = ins_open(uid, datetime(y.year, y.month, y.day, 17, 12, tzinfo=IST))
        requests.get(f"{BASE_URL}/api/admin/stats", headers=ADMIN)
        rec = db.attendance.find_one({"record_id": rid})
        out = datetime.fromisoformat(rec["check_out"]).astimezone(IST)
        assert (out.hour, out.minute) == (18, 0)
        assert rec["net_work_minutes"] == 48 and rec["auto_closed"] is True

    def test_night_shift_closes_2359(self):
        uid, _ = mk_user(shift=("20:00", "05:00"))
        y = today_ist() - timedelta(days=1)
        rid = ins_open(uid, datetime(y.year, y.month, y.day, 20, 5, tzinfo=IST))
        requests.get(f"{BASE_URL}/api/admin/stats", headers=ADMIN)
        rec = db.attendance.find_one({"record_id": rid})
        out = datetime.fromisoformat(rec["check_out"]).astimezone(IST)
        assert (out.date(), out.hour, out.minute) == (y, 23, 59)

    def test_reports_show_auto_closed(self):
        y = (today_ist() - timedelta(days=1)).isoformat()
        r = requests.get(f"{BASE_URL}/api/admin/reports", params={"from": y, "to": y, "department": "TEST_Dept15"}, headers=ADMIN)
        assert r.status_code == 200
        rows = [x for x in r.json()["rows"] if x["user_id"] in CREATED_USERS]
        assert len(rows) >= 3
        for row in rows:
            assert row["auto_closed_sessions"] == 1
            assert 0 < row["total_work_minutes"] <= 960

    def test_stats_running_minutes(self):
        now = datetime.now(IST)
        if now.hour < 2:
            pytest.skip("too early in IST day for a 2h-ago same-day record")
        uid, _ = mk_user(shift=None)
        ins_open(uid, now - timedelta(hours=2, minutes=1))
        r = requests.get(f"{BASE_URL}/api/admin/stats", headers=ADMIN)
        assert r.status_code == 200
        assert r.json()["total_work_minutes_today"] >= 120


# ---- Absent rules in reports ----
class TestAbsentRules:
    def _range(self):
        t = today_ist()
        return t - timedelta(days=13), t + timedelta(days=3)

    def _row(self, uid, **extra):
        f, t = self._range()
        r = requests.get(f"{BASE_URL}/api/admin/reports", params={"from": f.isoformat(), "to": t.isoformat(), "employee": uid, **extra}, headers=ADMIN)
        assert r.status_code == 200, r.text
        rows = r.json()["rows"]
        return rows[0] if rows else None

    def _expected(self, skip_dates=(), joined=None):
        f, _ = self._range()
        t = today_ist()
        hol = {h["date"] for h in db.holidays.find({}, {"date": 1})}
        absent = sundays = 0
        d = f
        while d <= t:
            if (joined is None or d >= joined) and d.isoformat() not in skip_dates and d.isoformat() not in hol:
                if d.weekday() == 6:
                    sundays += 1
                else:
                    absent += 1
            d += timedelta(days=1)
        return absent, sundays

    def test_shift_user_absent_excludes_sunday_future(self):
        uid, _ = mk_user(shift=("09:00", "18:00"))
        row = self._row(uid)
        absent, sundays = self._expected()
        assert row["weekly_off_days"] == sundays
        assert row["absent_days"] == absent
        assert row["no_shift_days"] == 0

    def test_no_shift_user_zero_absent(self):
        uid, _ = mk_user(shift=None)
        row = self._row(uid)
        assert row["absent_days"] == 0 and row["no_shift_days"] > 0

    def test_pending_invite_zero_absent(self):
        uid, _ = mk_user(shift=("09:00", "18:00"), pending=True)
        assert self._row(uid)["absent_days"] == 0

    def test_joined_recently(self):
        uid, _ = mk_user(shift=("09:00", "18:00"), joined_days_ago=2)
        joined = datetime.fromisoformat(db.users.find_one({"user_id": uid})["created_at"]).date()
        absent, _ = self._expected(joined=joined)
        assert self._row(uid)["absent_days"] == absent

    def test_profile_doj_used(self):
        uid, _ = mk_user(shift=("09:00", "18:00"), joined_days_ago=60)
        doj = today_ist() - timedelta(days=4)
        db.employee_profiles.update_one({"user_id": uid}, {"$set": {"user_id": uid, "date_of_joining": doj.isoformat()}}, upsert=True)
        absent, _ = self._expected(joined=doj)
        assert self._row(uid)["absent_days"] == absent

    def test_leave_and_holiday_excluded(self):
        uid, _ = mk_user(shift=("09:00", "18:00"))
        f, _ = self._range()
        # pick two past weekdays without existing holidays
        hol = {h["date"] for h in db.holidays.find({}, {"date": 1})}
        days = []
        d = f + timedelta(days=1)
        while len(days) < 2:
            if d.weekday() != 6 and d.isoformat() not in hol:
                days.append(d.isoformat())
            d += timedelta(days=1)
        lid = f"lv_test15_{uuid.uuid4().hex[:6]}"
        db.leave_requests.insert_one({"leave_id": lid, "user_id": uid, "status": "approved", "start_date": days[0], "end_date": days[0],
                                      "days": 1, "type_name": "TEST_CL"})
        CREATED_LEAVES.append(lid)
        r = requests.post(f"{BASE_URL}/api/admin/holidays", json={"date": days[1], "name": "TEST_Hol15"}, headers=ADMIN)
        assert r.status_code == 200, r.text
        CREATED_HOLS.append(r.json()["holiday"]["holiday_id"])
        absent, _ = self._expected(skip_dates=(days[0],))
        row = self._row(uid)
        assert row["absent_days"] == absent
        assert row["leave_days"] == 1

    def test_filters(self):
        f, t = self._range()
        p = {"from": f.isoformat(), "to": t.isoformat()}
        r = requests.get(f"{BASE_URL}/api/admin/reports", params={**p, "branch": "TEST_Site15"}, headers=ADMIN).json()["rows"]
        assert r and all(x["site"] == "TEST_Site15" for x in r)
        r = requests.get(f"{BASE_URL}/api/admin/reports", params={**p, "department": "NoSuchDept"}, headers=ADMIN).json()["rows"]
        assert r == []

    def test_csv_columns(self):
        f, t = self._range()
        r = requests.get(f"{BASE_URL}/api/admin/reports.csv", params={"from": f.isoformat(), "to": t.isoformat(), "department": "TEST_Dept15"}, headers=ADMIN)
        assert r.status_code == 200
        header = r.text.splitlines()[0]
        for col in ("Weekly Off Days", "No Shift Days", "Auto-closed"):
            assert col in header


# ---- Weekly off ----
class TestWeeklyOff:
    def test_set_and_validate(self):
        uid, _ = mk_user(shift=("09:00", "18:00"))
        r = requests.patch(f"{BASE_URL}/api/admin/employees/{uid}/shift", json={"weekly_off": [6, 5]}, headers=ADMIN)
        assert r.status_code == 200 and r.json()["employee"]["weekly_off"] == [5, 6]
        assert db.users.find_one({"user_id": uid})["weekly_off"] == [5, 6]
        for bad in ([7], [-1]):
            r = requests.patch(f"{BASE_URL}/api/admin/employees/{uid}/shift", json={"weekly_off": bad}, headers=ADMIN)
            assert r.status_code == 400


# ---- Activity log ----
class TestActivity:
    def test_filters_and_pagination(self):
        r = requests.get(f"{BASE_URL}/api/admin/activity", params={"page_size": 5}, headers=ADMIN)
        assert r.status_code == 200
        d = r.json()
        assert {"entries", "total", "page", "page_size", "actions"} <= set(d)
        assert len(d["entries"]) <= 5
        r = requests.get(f"{BASE_URL}/api/admin/activity", params={"action": "employee_added"}, headers=ADMIN).json()
        assert r["total"] > 0 and all(e["action"] == "employee_added" for e in r["entries"])
        r = requests.get(f"{BASE_URL}/api/admin/activity", params={"q": "TEST_Emp15"}, headers=ADMIN).json()
        assert r["total"] > 0
        r = requests.get(f"{BASE_URL}/api/admin/activity", params={"person": "Test Admin", "q": "TEST_Emp15"}, headers=ADMIN).json()
        assert r["total"] > 0
        t = today_ist().isoformat()
        r = requests.get(f"{BASE_URL}/api/admin/activity", params={"from": t, "to": t}, headers=ADMIN).json()
        assert r["total"] > 0
        r = requests.get(f"{BASE_URL}/api/admin/activity", params={"from": "2001-01-01", "to": "2001-01-02"}, headers=ADMIN).json()
        assert r["total"] == 0

    def test_sub_admin_forbidden(self):
        r = requests.get(f"{BASE_URL}/api/admin/activity", headers={"Authorization": "Bearer test_session_subadmin_001"})
        assert r.status_code == 403


# ---- Removal archives and keeps records ----
class TestRemoval:
    def test_remove_archives(self):
        uid, _ = mk_user(shift=None)
        y = today_ist() - timedelta(days=2)
        rid = ins_open(uid, datetime(y.year, y.month, y.day, 10, 0, tzinfo=IST))
        r = requests.delete(f"{BASE_URL}/api/admin/employees/{uid}", headers=ADMIN)
        assert r.status_code == 200
        assert db.users.find_one({"user_id": uid}) is None
        arch = db.removed_users.find_one({"user_id": uid})
        assert arch and arch.get("removed_at")
        assert db.attendance.find_one({"record_id": rid}) is not None


# ---- ESI not applicable ----
class TestESI:
    def test_esi_clears_na(self):
        uid, _ = mk_user(shift=None)
        tok = f"test_session_t15_{uuid.uuid4().hex[:8]}"
        db.user_sessions.insert_one({"session_token": tok, "user_id": uid,
                                     "expires_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
                                     "created_at": datetime.now(timezone.utc).isoformat()})
        h = {"Authorization": f"Bearer {tok}"}
        r = requests.put(f"{BASE_URL}/api/profile/me", json={"esi_not_applicable": True}, headers=h)
        assert r.status_code == 200, r.text
        assert r.json().get("esi_not_applicable") is True
        r = requests.put(f"{BASE_URL}/api/profile/me", json={"esi": "1234567890"}, headers=h)
        assert r.status_code == 200, r.text
        assert r.json().get("esi") == "1234567890" and not r.json().get("esi_not_applicable")
        r = requests.put(f"{BASE_URL}/api/profile/me", json={"esi": "123"}, headers=h)
        assert r.status_code == 400
