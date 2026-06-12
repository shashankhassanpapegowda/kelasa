"""Backend tests for iteration 3: shift mapping, break flows, late tracking, reports."""
import csv
import io
import os
import time as pytime
import uuid
from datetime import datetime, timezone, timedelta

import pytest
import requests
from pymongo import MongoClient

MONGO_URL = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
DB_NAME = os.environ.get('DB_NAME', 'test_database')


# ---------------- Helpers / seed for late tests (uses UTC timezone so we control "now") ----------------
def _seed_user(db, user_id, email, role, token, tz="UTC", shift_start=None, shift_end=None, break_max=60):
    db.users.delete_many({"user_id": user_id})
    db.user_sessions.delete_many({"session_token": token})
    db.attendance.delete_many({"user_id": user_id})
    db.locations.delete_many({"user_id": user_id})
    now = datetime.now(timezone.utc)
    db.users.insert_one({
        "user_id": user_id,
        "email": email,
        "name": email.split("@")[0],
        "picture": None,
        "role": role,
        "face_enrolled": True,
        "face_descriptor": [0.0] * 128,
        "face_photo_path": None,
        "shift_start": shift_start,
        "shift_end": shift_end,
        "break_max_minutes": break_max,
        "timezone": tz,
        "created_at": now.isoformat(),
    })
    db.user_sessions.insert_one({
        "user_id": user_id,
        "session_token": token,
        "expires_at": (now + timedelta(days=7)).isoformat(),
        "created_at": now.isoformat(),
    })


@pytest.fixture(scope="module")
def late_employee(mongo_db):
    """Employee with UTC timezone & shift_start=00:00 -> any check-in today is way past grace -> late."""
    uid = "TEST_user_late01"
    token = "TEST_session_late_001"
    _seed_user(mongo_db, uid, "TEST_late@gtg.local", "employee", token,
               tz="UTC", shift_start="00:00", shift_end="23:59", break_max=60)
    yield {"user_id": uid, "token": token}
    mongo_db.users.delete_one({"user_id": uid})
    mongo_db.user_sessions.delete_one({"session_token": token})
    mongo_db.attendance.delete_many({"user_id": uid})
    mongo_db.locations.delete_many({"user_id": uid})


@pytest.fixture
def late_client(late_employee):
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {late_employee['token']}", "Content-Type": "application/json"})
    return s


# ---------- Admin shift PATCH ----------
class TestAdminShiftPatch:
    def test_patch_shift_valid(self, admin_client, employee_client, base_url, mongo_db):
        r = admin_client.patch(f"{base_url}/api/admin/employees/TEST_user_emp01/shift",
                               json={"shift_start": "09:00", "shift_end": "18:00", "break_max_minutes": 45})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        emp = body["employee"]
        assert emp["shift_start"] == "09:00"
        assert emp["shift_end"] == "18:00"
        assert emp["break_max_minutes"] == 45
        # verify persisted
        u = mongo_db.users.find_one({"user_id": "TEST_user_emp01"})
        assert u["shift_start"] == "09:00"
        assert u["break_max_minutes"] == 45

    def test_patch_shift_invalid_time_format(self, admin_client, base_url):
        r = admin_client.patch(f"{base_url}/api/admin/employees/TEST_user_emp01/shift",
                               json={"shift_start": "foo"})
        assert r.status_code == 400

    def test_patch_shift_nonexistent_user(self, admin_client, base_url):
        r = admin_client.patch(f"{base_url}/api/admin/employees/NOT_A_USER/shift",
                               json={"shift_start": "10:00"})
        assert r.status_code == 404

    def test_patch_shift_forbidden_for_employee(self, employee_client, base_url):
        r = employee_client.patch(f"{base_url}/api/admin/employees/TEST_user_emp01/shift",
                                  json={"shift_start": "09:00"})
        assert r.status_code == 403

    def test_employees_list_includes_shift_and_on_break(self, admin_client, base_url):
        r = admin_client.get(f"{base_url}/api/admin/employees")
        assert r.status_code == 200
        emps = r.json()["employees"]
        ours = next((e for e in emps if e["user_id"] == "TEST_user_emp01"), None)
        assert ours is not None
        assert "shift_start" in ours
        assert "shift_end" in ours
        assert "break_max_minutes" in ours
        assert "on_break" in ours


# ---------- Late computation ----------
class TestLateCheckin:
    def test_checkin_after_grace_is_late(self, late_client, base_url, mongo_db, tiny_jpeg_b64, late_employee):
        mongo_db.attendance.delete_many({"user_id": late_employee["user_id"]})
        # tz=UTC, shift_start=00:00 => current minute of day > 15 means late
        now = datetime.now(timezone.utc)
        minute_of_day = now.hour * 60 + now.minute
        r = late_client.post(f"{base_url}/api/attendance/checkin", json={
            "lat": 12.97, "lng": 77.59, "accuracy": 15,
            "descriptor": [0.0] * 128, "image_b64": tiny_jpeg_b64
        })
        assert r.status_code == 200, r.text
        body = r.json()
        if minute_of_day > 15:
            assert body["late_by_minutes"] is not None
            assert body["late_by_minutes"] > 0
            assert body["late_by_minutes"] == minute_of_day - 15 or abs(body["late_by_minutes"] - (minute_of_day - 15)) <= 1
        else:
            assert (body["late_by_minutes"] or 0) == 0

    def test_checkin_no_shift_returns_none_late(self, employee_client, base_url, mongo_db, tiny_jpeg_b64):
        # ensure shift cleared and no active record
        mongo_db.users.update_one({"user_id": "TEST_user_emp01"}, {"$set": {"shift_start": None}})
        mongo_db.attendance.delete_many({"user_id": "TEST_user_emp01"})
        r = employee_client.post(f"{base_url}/api/attendance/checkin", json={
            "lat": 12.97, "lng": 77.59, "accuracy": 15,
            "descriptor": [0.0] * 128, "image_b64": tiny_jpeg_b64
        })
        assert r.status_code == 200
        assert r.json().get("late_by_minutes") is None
        # cleanup
        employee_client.post(f"{base_url}/api/attendance/checkout", json={
            "lat": 12.97, "lng": 77.59, "accuracy": 15,
            "descriptor": [0.0] * 128, "image_b64": tiny_jpeg_b64
        })


# ---------- Break flow ----------
class TestBreakFlow:
    def test_break_lifecycle_and_overbreak_and_ping_paused(self, late_client, base_url, mongo_db,
                                                            tiny_jpeg_b64, late_employee):
        uid = late_employee["user_id"]
        mongo_db.attendance.delete_many({"user_id": uid})
        mongo_db.locations.delete_many({"user_id": uid})
        # ensure break_max low so we trigger over_break (avoid 0 due to `or` truthiness bug fallback to 60)
        mongo_db.users.update_one({"user_id": uid}, {"$set": {"break_max_minutes": 1}})

        # check in
        r = late_client.post(f"{base_url}/api/attendance/checkin", json={
            "lat": 12.97, "lng": 77.59, "accuracy": 15,
            "descriptor": [0.0] * 128, "image_b64": tiny_jpeg_b64
        })
        assert r.status_code == 200, r.text
        record_id = r.json()["record_id"]

        # start break #1
        r = late_client.post(f"{base_url}/api/attendance/break/start", json={"lat": 12.97, "lng": 77.59})
        assert r.status_code == 200
        assert r.json()["ok"] is True

        # double break start -> 400
        r = late_client.post(f"{base_url}/api/attendance/break/start", json={})
        assert r.status_code == 400
        assert "already" in r.json()["detail"].lower()

        # active record reflects on_break
        rec = mongo_db.attendance.find_one({"record_id": record_id})
        assert rec["on_break"] is True

        # Ping during break -> ok=False, skipped, no DB write
        before = mongo_db.locations.count_documents({"user_id": uid})
        rp = late_client.post(f"{base_url}/api/location/ping",
                              json={"lat": 12.97, "lng": 77.59, "accuracy": 20})
        assert rp.status_code == 200
        body = rp.json()
        assert body["ok"] is False
        assert body.get("reason") == "on_break"
        after = mongo_db.locations.count_documents({"user_id": uid})
        assert after == before, "ping during break should not be persisted"

        # checkout while on break -> 400
        rc = late_client.post(f"{base_url}/api/attendance/checkout", json={
            "lat": 12.97, "lng": 77.59, "accuracy": 15,
            "descriptor": [0.0] * 128, "image_b64": tiny_jpeg_b64
        })
        assert rc.status_code == 400
        assert "break" in rc.json()["detail"].lower()

        # end break (force duration_minutes>0 by backdating start)
        mongo_db.attendance.update_one(
            {"record_id": record_id},
            {"$set": {"breaks.0.start": (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()}}
        )
        r = late_client.post(f"{base_url}/api/attendance/break/end", json={"lat": 12.97, "lng": 77.59})
        assert r.status_code == 200
        b1 = r.json()
        assert b1["duration_minutes"] >= 4
        assert b1["total_break_minutes"] >= 4

        # second break to verify accumulation
        r = late_client.post(f"{base_url}/api/attendance/break/start", json={})
        assert r.status_code == 200
        # backdate the new break too
        mongo_db.attendance.update_one(
            {"record_id": record_id},
            {"$set": {"breaks.1.start": (datetime.now(timezone.utc) - timedelta(minutes=3)).isoformat()}}
        )
        r = late_client.post(f"{base_url}/api/attendance/break/end", json={})
        assert r.status_code == 200
        b2 = r.json()
        assert b2["total_break_minutes"] >= b1["total_break_minutes"] + 2

        # also backdate check_in so duration > break total
        mongo_db.attendance.update_one(
            {"record_id": record_id},
            {"$set": {"check_in": (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()}}
        )

        # checkout now succeeds -> net_work_minutes & over_break
        rc = late_client.post(f"{base_url}/api/attendance/checkout", json={
            "lat": 12.97, "lng": 77.59, "accuracy": 15,
            "descriptor": [0.0] * 128, "image_b64": tiny_jpeg_b64
        })
        assert rc.status_code == 200, rc.text
        cdata = rc.json()
        assert "net_work_minutes" in cdata
        assert cdata["net_work_minutes"] == max(cdata["duration_minutes"] - b2["total_break_minutes"], 0)
        assert cdata["over_break"] is True  # break_max=1 and breaks ~ 5+3 mins triggers it

    def test_break_start_not_on_duty(self, employee_client, base_url, mongo_db):
        mongo_db.attendance.delete_many({"user_id": "TEST_user_emp01", "check_out": None})
        r = employee_client.post(f"{base_url}/api/attendance/break/start", json={})
        assert r.status_code == 400

    def test_break_end_when_not_on_break(self, late_client, base_url, mongo_db, tiny_jpeg_b64, late_employee):
        uid = late_employee["user_id"]
        mongo_db.attendance.delete_many({"user_id": uid})
        late_client.post(f"{base_url}/api/attendance/checkin", json={
            "lat": 12.97, "lng": 77.59, "accuracy": 15,
            "descriptor": [0.0] * 128, "image_b64": tiny_jpeg_b64
        })
        r = late_client.post(f"{base_url}/api/attendance/break/end", json={})
        assert r.status_code == 400
        # cleanup
        late_client.post(f"{base_url}/api/attendance/checkout", json={
            "lat": 12.97, "lng": 77.59, "accuracy": 15,
            "descriptor": [0.0] * 128, "image_b64": tiny_jpeg_b64
        })


# ---------- Reports ----------
class TestReports:
    def test_reports_json(self, admin_client, base_url):
        today = datetime.now(timezone.utc).date().isoformat()
        frm = (datetime.now(timezone.utc).date() - timedelta(days=7)).isoformat()
        r = admin_client.get(f"{base_url}/api/admin/reports?from={frm}&to={today}")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["from"] == frm and body["to"] == today
        assert isinstance(body["rows"], list)
        if body["rows"]:
            row = body["rows"][0]
            for k in ("user_id","name","email","present_days","absent_days","late_days",
                       "total_late_minutes","total_work_minutes","total_break_minutes",
                       "over_break_days","sessions"):
                assert k in row, f"missing {k} in report row"

    def test_reports_csv_with_bearer(self, admin_client, base_url):
        today = datetime.now(timezone.utc).date().isoformat()
        frm = (datetime.now(timezone.utc).date() - timedelta(days=7)).isoformat()
        r = admin_client.get(f"{base_url}/api/admin/reports.csv?from={frm}&to={today}")
        assert r.status_code == 200, r.text
        assert "text/csv" in r.headers.get("content-type", "")
        cd = r.headers.get("content-disposition", "")
        assert "attachment" in cd and ".csv" in cd
        text = r.text
        rows = list(csv.reader(io.StringIO(text)))
        assert len(rows) >= 1
        assert rows[0][0] == "Employee"
        assert "Total Work (h:m)" in rows[0]

    def test_reports_csv_with_auth_query_param(self, admin_token, base_url):
        today = datetime.now(timezone.utc).date().isoformat()
        frm = today
        # no cookies, no Authorization header -> use ?auth=
        r = requests.get(f"{base_url}/api/admin/reports.csv?from={frm}&to={today}&auth={admin_token}")
        assert r.status_code == 200, r.text
        assert "text/csv" in r.headers.get("content-type", "")

    def test_reports_csv_unauthorized(self, base_url):
        today = datetime.now(timezone.utc).date().isoformat()
        r = requests.get(f"{base_url}/api/admin/reports.csv?from={today}&to={today}")
        assert r.status_code == 401

    def test_reports_csv_forbidden_for_employee(self, employee_client, base_url):
        today = datetime.now(timezone.utc).date().isoformat()
        r = employee_client.get(f"{base_url}/api/admin/reports.csv?from={today}&to={today}")
        assert r.status_code == 403


# ---------- Stats includes late_today ----------
class TestStats:
    def test_stats_has_late_today(self, admin_client, base_url):
        r = admin_client.get(f"{base_url}/api/admin/stats")
        assert r.status_code == 200
        assert "late_today" in r.json()
        assert isinstance(r.json()["late_today"], int)
