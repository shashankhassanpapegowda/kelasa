# Iter19: selfie-only check-in/out, employee calendar, regularization (corrections), regression
import os
import uuid
import requests
import pytest
from datetime import datetime, timezone, timedelta
from pymongo import MongoClient
from conftest import TINY_JPEG_B64

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
API = f"{BASE_URL}/api"
DB = MongoClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))[os.environ.get("DB_NAME", "test_database")]
ADMIN = {"Authorization": "Bearer test_session_admin_001"}
SUB = {"Authorization": "Bearer test_session_subadmin_001"}
RAVI = {"Authorization": "Bearer test_session_emp_001"}
GEO = {"lat": 12.97, "lng": 77.59, "accuracy": 10, "image_b64": TINY_JPEG_B64}
MONTH = "2026-11"


@pytest.fixture(scope="module")
def tmp_user():
    uid = f"user_TEST_{uuid.uuid4().hex[:8]}"
    tok = f"TEST_sess_{uuid.uuid4().hex}"
    DB.users.insert_one({"user_id": uid, "email": f"TEST_{uid}@example.com", "name": "TEST_Iter19 Emp", "role": "employee",
                         "face_enrolled": False, "shift_start": "09:00", "shift_end": "18:00", "break_max_minutes": 60,
                         "timezone": "Asia/Kolkata", "tracking_mode": "duty_only", "department": "Field Operations",
                         "site": "Bengaluru HQ", "manager_id": "user_testsub01", "pending_invite": False,
                         "field_staff": True, "created_at": "2026-10-01T00:00:00+00:00", "must_change_password": False})
    DB.user_sessions.insert_one({"user_id": uid, "session_token": tok,
                                 "expires_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
                                 "created_at": datetime.now(timezone.utc).isoformat()})
    yield {"uid": uid, "h": {"Authorization": f"Bearer {tok}"}}
    for c in ("attendance", "locations", "regularizations", "user_sessions", "geofence_alerts"):
        DB[c].delete_many({"user_id": uid})
    DB.users.delete_one({"user_id": uid})


def day(cal, d):
    return next(x for x in cal["days"] if x["date"] == d)


# ---- Selfie-only check-in/out ----
class TestSelfie:
    def test_checkin_requires_selfie(self, tmp_user):
        r = requests.post(f"{API}/attendance/checkin", json={**GEO, "image_b64": ""}, headers=tmp_user["h"])
        assert r.status_code == 400 and "selfie" in r.json()["detail"].lower()
        r = requests.post(f"{API}/attendance/checkin", json={**GEO, "image_b64": "data:image/jpeg;base64,abc"}, headers=tmp_user["h"])
        assert r.status_code == 400

    def test_checkin_checkout_no_enrolment(self, tmp_user):
        r = requests.post(f"{API}/attendance/checkin", json=GEO, headers=tmp_user["h"])
        assert r.status_code == 200, r.text
        rid = r.json()["record_id"]
        r = requests.post(f"{API}/attendance/checkout", json={**GEO, "image_b64": "x"}, headers=tmp_user["h"])
        assert r.status_code == 400
        r = requests.post(f"{API}/attendance/checkout", json=GEO, headers=tmp_user["h"])
        assert r.status_code == 200, r.text
        rec = DB.attendance.find_one({"record_id": rid})
        assert rec["check_out"] and rec.get("check_in_photo_path") and rec.get("check_out_photo_path")
        assert "face_match" not in rec or rec.get("face_match") is None


# ---- Calendar ----
class TestCalendar:
    def test_calendar_shape(self, tmp_user):
        r = requests.get(f"{API}/me/calendar", params={"month": MONTH}, headers=tmp_user["h"])
        assert r.status_code == 200
        c = r.json()
        assert len(c["days"]) == 30 and c["month"] == MONTH and "counts" in c and "total_work_minutes" in c
        allowed = {"present", "late", "absent", "leave", "half_day", "weekly_off", "holiday", "punch_error", "today", "future", "not_joined", "no_shift"}
        assert all(d["status"] in allowed for d in c["days"])
        assert day(c, "2026-11-30")["status"] == "future"
        assert sum(c["counts"].values()) == 30

    def test_calendar_bad_month(self):
        assert requests.get(f"{API}/me/calendar", params={"month": "2026-13"}, headers=RAVI).status_code in (400, 422)
        assert requests.get(f"{API}/me/calendar", params={"month": MONTH}).status_code == 401

    def test_calendar_csv_bearer(self):
        r = requests.get(f"{API}/me/calendar.csv", params={"month": MONTH}, headers=RAVI)
        assert r.status_code == 200 and "text/csv" in r.headers.get("content-type", "")
        assert r.text.splitlines()[0].startswith("Date,Status")
        assert len(r.text.strip().splitlines()) == 31

    def test_ravi_regularized_day(self):
        c = requests.get(f"{API}/me/calendar", params={"month": MONTH}, headers=RAVI).json()
        d = day(c, "2026-11-18")
        assert d["regularization"]["status"] == "approved"
        assert d["sessions"] and d["sessions"][0]["regularized"] is True
        assert d["status"] in ("late", "present")

    def test_punch_error_and_half_day(self, tmp_user):
        uid = tmp_user["uid"]
        DB.attendance.insert_many([
            {"record_id": f"att_TEST_{uuid.uuid4().hex[:8]}", "user_id": uid, "date": "2026-11-03",
             "check_in": "2026-11-03T03:30:00+00:00", "check_out": "2026-11-03T12:30:00+00:00", "status": "off_duty",
             "net_work_minutes": 540, "duration_minutes": 540, "auto_closed": True, "auto_close_reason": "missed checkout",
             "breaks": [], "total_break_minutes": 0, "late_by_minutes": 0},
            {"record_id": f"att_TEST_{uuid.uuid4().hex[:8]}", "user_id": uid, "date": "2026-11-04",
             "check_in": "2026-11-04T03:30:00+00:00", "check_out": "2026-11-04T05:30:00+00:00", "status": "off_duty",
             "net_work_minutes": 120, "duration_minutes": 120, "auto_closed": False,
             "breaks": [], "total_break_minutes": 0, "late_by_minutes": 0}])
        c = requests.get(f"{API}/me/calendar", params={"month": MONTH}, headers=tmp_user["h"]).json()
        assert day(c, "2026-11-03")["status"] == "punch_error"
        assert day(c, "2026-11-04")["status"] == "half_day"


# ---- Regularization ----
class TestRegularization:
    def test_validation(self, tmp_user):
        h = tmp_user["h"]
        p = lambda **k: requests.post(f"{API}/regularizations", json={"date": "2026-11-05", "check_in": "09:00", "check_out": "18:00", "reason": "Forgot to punch in", **k}, headers=h)
        assert p(date="2026-12-20").status_code == 400
        assert p(check_out="08:00").status_code == 400
        assert p(check_out="09:00").status_code == 400
        assert p(reason="no").status_code == 400
        assert p(check_in="9am").status_code == 400
        r = p()
        assert r.status_code == 200, r.text
        rid = r.json()["request"]["request_id"]
        assert p().status_code == 400  # duplicate pending
        mine = requests.get(f"{API}/regularizations/mine", headers=h).json()["items"]
        assert any(i["request_id"] == rid and i["status"] == "pending" for i in mine)
        assert requests.post(f"{API}/regularizations/{rid}/cancel", headers=h).status_code == 200
        assert requests.post(f"{API}/regularizations/{rid}/cancel", headers=h).status_code == 404
        assert p().status_code == 200  # can re-request after cancel

    def test_employee_cannot_decide_or_list(self, tmp_user):
        assert requests.get(f"{API}/admin/regularizations", headers=tmp_user["h"]).status_code == 403

    def test_subadmin_scope_and_decide(self, tmp_user):
        h = tmp_user["h"]
        r = requests.post(f"{API}/regularizations", json={"date": "2026-11-03", "check_in": "09:30", "check_out": "18:00", "reason": "Missed check out at site"}, headers=h)
        assert r.status_code == 200
        rid = r.json()["request"]["request_id"]
        items = requests.get(f"{API}/admin/regularizations", params={"status": "pending"}, headers=SUB).json()["items"]
        assert any(i["request_id"] == rid and i["name"] == "TEST_Iter19 Emp" for i in items)
        assert all(DB.users.find_one({"user_id": i["user_id"]}).get("department") != "Administration" or i["user_id"] == "user_testsub01"
                   for i in requests.get(f"{API}/admin/regularizations", params={"status": "all"}, headers=SUB).json()["items"])
        # reject without note
        r = requests.post(f"{API}/admin/regularizations/{rid}/decide", json={"decision": "rejected"}, headers=SUB)
        assert r.status_code == 400
        r = requests.post(f"{API}/admin/regularizations/{rid}/decide", json={"decision": "rejected", "note": "  "}, headers=SUB)
        assert r.status_code == 400
        old = DB.attendance.find_one({"user_id": tmp_user["uid"], "date": "2026-11-03"})
        r = requests.post(f"{API}/admin/regularizations/{rid}/decide", json={"decision": "approved", "note": "ok"}, headers=SUB)
        assert r.status_code == 200, r.text
        assert requests.post(f"{API}/admin/regularizations/{rid}/decide", json={"decision": "approved"}, headers=SUB).status_code == 400
        rec = DB.attendance.find_one({"user_id": tmp_user["uid"], "date": "2026-11-03"})
        assert rec["regularized"] is True and rec["auto_closed"] is False
        assert rec["original_check_in"] == old["check_in"] and rec["original_check_out"] == old["check_out"]
        assert rec["check_in"].startswith("2026-11-03T04:00") and rec["net_work_minutes"] == 510
        assert rec["late_by_minutes"] == 15  # 15 min grace
        c = requests.get(f"{API}/me/calendar", params={"month": MONTH}, headers=h).json()
        d = day(c, "2026-11-03")
        assert d["status"] == "late" and d["regularization"]["status"] == "approved"
        logs = list(DB.activity_log.find({"action": {"$in": ["regularization_requested", "regularization_approved"]}, "target_name": "TEST_Iter19 Emp"})) \
            if "activity_log" in DB.list_collection_names() else []
        assert len(logs) >= 2, "activity log entries missing (check collection name)"

    def test_approve_creates_record_and_reject(self, tmp_user):
        h = tmp_user["h"]
        rid = requests.post(f"{API}/regularizations", json={"date": "2026-11-06", "check_in": "09:00", "check_out": "12:00", "reason": "Phone died, no punch"}, headers=h).json()["request"]["request_id"]
        assert requests.post(f"{API}/admin/regularizations/{rid}/decide", json={"decision": "approved"}, headers=ADMIN).status_code == 200
        rec = DB.attendance.find_one({"user_id": tmp_user["uid"], "date": "2026-11-06"})
        assert rec and rec["regularized"] and rec["net_work_minutes"] == 180
        c = requests.get(f"{API}/me/calendar", params={"month": MONTH}, headers=h).json()
        assert day(c, "2026-11-06")["status"] == "half_day"
        rid2 = requests.post(f"{API}/regularizations", json={"date": "2026-11-09", "check_in": "09:00", "check_out": "18:00", "reason": "Was on site visit"}, headers=h).json()["request"]["request_id"]
        r = requests.post(f"{API}/admin/regularizations/{rid2}/decide", json={"decision": "rejected", "note": "No proof"}, headers=ADMIN)
        assert r.status_code == 200
        assert DB.attendance.find_one({"user_id": tmp_user["uid"], "date": "2026-11-09"}) is None
        rej = requests.get(f"{API}/admin/regularizations", params={"status": "rejected"}, headers=ADMIN).json()["items"]
        assert any(i["request_id"] == rid2 and i["manager_note"] == "No proof" for i in rej)

    def test_subadmin_cannot_decide_own(self):
        r = requests.post(f"{API}/regularizations", json={"date": "2026-11-02", "check_in": "09:00", "check_out": "18:00", "reason": "TEST_ sub own request"}, headers=SUB)
        assert r.status_code == 200, r.text
        rid = r.json()["request"]["request_id"]
        try:
            assert requests.post(f"{API}/admin/regularizations/{rid}/decide", json={"decision": "approved"}, headers=SUB).status_code == 403
        finally:
            DB.regularizations.delete_one({"request_id": rid})

    def test_decide_404(self):
        assert requests.post(f"{API}/admin/regularizations/reg_nope/decide", json={"decision": "approved"}, headers=ADMIN).status_code == 404


# ---- Regression ----
class TestRegression:
    def test_reports_csv_employee_forbidden(self):
        r = requests.get(f"{API}/admin/reports.csv", params={"from": "2026-11-01", "to": "2026-11-26"}, headers=RAVI)
        assert r.status_code == 403
        r = requests.get(f"{API}/admin/reports.csv", params={"from": "2026-11-01", "to": "2026-11-26", "auth": "test_session_emp_001"})
        assert r.status_code == 403

    def test_manager_reports(self):
        assert requests.get(f"{API}/admin/reports.csv", params={"from": "2026-11-01", "to": "2026-11-26"}, headers=SUB).status_code == 200
        assert requests.get(f"{API}/admin/reports", params={"from": "2026-11-01", "to": "2026-11-26"}, headers=ADMIN).status_code == 200
        assert requests.get(f"{API}/admin/reports/payroll-summary", params={"month": MONTH, "format": "csv"}, headers=ADMIN).status_code == 200

    def test_face_endpoints_gone_or_harmless(self):
        r = requests.get(f"{API}/auth/me", headers=RAVI)
        assert r.status_code == 200
        assert "face_descriptor" not in r.json()
