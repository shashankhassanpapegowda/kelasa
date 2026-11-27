# Iter12: employee web push (leave decision notifications) + per-device silent flag
import os
import sys
import time
from datetime import datetime, timezone, timedelta

import pytest
import requests
from pymongo import MongoClient

from conftest import BASE_URL, TINY_JPEG_B64, MONGO_URL, DB_NAME
from test_web_push import fake_sub, sub_exists, wait_gone

ADMIN = {"Authorization": "Bearer test_session_admin_001"}
SUB = {"Authorization": "Bearer test_session_subadmin_001"}
def paid_leave_id(headers):
    r = requests.get(f"{BASE_URL}/api/leave/types", headers=headers)
    assert r.status_code == 200, r.text
    return next(t["type_id"] for t in r.json()["types"] if t["code"] == "LV")
INSIDE = {"lat": 12.9720, "lng": 77.5946, "accuracy": 10}
OUTSIDE = {"lat": 12.99, "lng": 77.5946, "accuracy": 10}
LOG = "/var/log/supervisor/backend.err.log"
db = MongoClient(MONGO_URL)[DB_NAME]


@pytest.fixture(scope="module")
def emp():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": "emp1.test@gtgroups.local", "password": "RaviReset@26"})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['session_token']}"}


@pytest.fixture(scope="module", autouse=True)
def cleanup():
    yield
    db.push_subscriptions.delete_many({"endpoint": {"$regex": "fakeTEST"}})
    db.leave_requests.delete_many({"reason": {"$regex": "^TEST_iter12"}})


# ---- unit: leave_push_payload ----
class TestLeavePayloadUnit:
    @pytest.fixture(scope="class")
    def server(self):
        sys.path.insert(0, "/app/backend")
        import server as srv
        return srv

    def test_with_note(self, server):
        p = server.leave_push_payload({"type_name": "Casual Leave", "start_date": "2026-12-01", "end_date": "2026-12-02",
                                       "leave_id": "lv_x"}, "rejected", "Busy week", "Boss")
        assert p == {"title": "Leave rejected", "body": "Casual Leave · 01 Dec – 02 Dec\nNote: Busy week",
                     "tag": "leave_lv_x", "url": "/leave"}

    def test_no_note_single_day(self, server):
        p = server.leave_push_payload({"type_name": "Sick Leave", "start_date": "2026-12-01", "end_date": "2026-12-01",
                                       "leave_id": "lv_y"}, "approved", "", "Boss")
        assert p["title"] == "Leave approved" and p["body"] == "Sick Leave · 01 Dec · by Boss"

    def test_no_note_no_by(self, server):
        p = server.leave_push_payload({"type_name": "SL", "start_date": "2026-12-01", "end_date": "2026-12-01",
                                       "leave_id": "lv_z"}, "approved", "", None)
        assert p["body"] == "SL · 01 Dec"


# ---- employee push endpoints + silent ----
class TestEmployeePushEndpoints:
    def test_employee_public_key_and_subscribe(self, emp):
        assert requests.get(f"{BASE_URL}/api/push/public-key", headers=emp).status_code == 200
        s = fake_sub("e1")
        assert requests.post(f"{BASE_URL}/api/push/subscribe", json=s, headers=emp).status_code == 200
        doc = db.push_subscriptions.find_one({"endpoint": s["endpoint"]})
        assert doc["user_id"] == "user_testemp01" and doc["silent"] is False
        st = requests.get(f"{BASE_URL}/api/push/status", params={"endpoint": s["endpoint"]}, headers=emp).json()
        assert st["this_device"] is True and st["silent"] is False

    def test_silent_patch_own_only_and_persist(self, emp):
        s = fake_sub("e2")
        requests.post(f"{BASE_URL}/api/push/subscribe", json=s, headers=emp)
        r = requests.patch(f"{BASE_URL}/api/push/subscribe", json={"endpoint": s["endpoint"], "silent": True}, headers=emp)
        assert r.status_code == 200 and r.json() == {"ok": True, "silent": True}
        st = requests.get(f"{BASE_URL}/api/push/status", params={"endpoint": s["endpoint"]}, headers=emp).json()
        assert st["silent"] is True
        # other user can't touch it
        r2 = requests.patch(f"{BASE_URL}/api/push/subscribe", json={"endpoint": s["endpoint"], "silent": False}, headers=ADMIN)
        assert r2.status_code == 404 and r2.json()["detail"] == "This phone isn't subscribed"
        assert db.push_subscriptions.find_one({"endpoint": s["endpoint"]})["silent"] is True
        # re-subscribe keeps silent
        requests.post(f"{BASE_URL}/api/push/subscribe", json=s, headers=emp)
        assert db.push_subscriptions.find_one({"endpoint": s["endpoint"]})["silent"] is True
        # unknown endpoint -> 404, bad body -> 422, unauth -> 401
        assert requests.patch(f"{BASE_URL}/api/push/subscribe", json={"endpoint": "https://nope", "silent": True}, headers=emp).status_code == 404
        assert requests.patch(f"{BASE_URL}/api/push/subscribe", json={"endpoint": s["endpoint"]}, headers=emp).status_code == 422
        assert requests.patch(f"{BASE_URL}/api/push/subscribe", json={"endpoint": s["endpoint"], "silent": True}).status_code == 401

    def test_status_without_endpoint(self, emp):
        st = requests.get(f"{BASE_URL}/api/push/status", headers=emp).json()
        assert st["this_device"] is False and st["silent"] is False and st["devices"] >= 1

    def test_employee_send_test(self, emp):
        db.push_subscriptions.delete_many({"user_id": "user_testemp01"})
        assert requests.post(f"{BASE_URL}/api/push/test", headers=emp).status_code == 400
        s = fake_sub("e3")
        requests.post(f"{BASE_URL}/api/push/subscribe", json=s, headers=emp)
        r = requests.post(f"{BASE_URL}/api/push/test", headers=emp)
        assert r.status_code == 200 and r.json()["devices"] == 1 and r.json()["sent"] == 0
        assert not sub_exists(s["endpoint"])

    def test_employee_unsubscribe(self, emp):
        s = fake_sub("e4")
        requests.post(f"{BASE_URL}/api/push/subscribe", json=s, headers=emp)
        assert requests.delete(f"{BASE_URL}/api/push/subscribe", params={"endpoint": s["endpoint"]}, headers=emp).status_code == 200
        assert not sub_exists(s["endpoint"])


# ---- leave decision -> employee push ----
class TestLeaveDecisionPush:
    def _apply(self, emp, start, end):
        r = requests.post(f"{BASE_URL}/api/leave/request", json={"type_id": paid_leave_id(emp), "start_date": start, "end_date": end,
                                                                 "half_day": False, "reason": "TEST_iter12"}, headers=emp)
        assert r.status_code == 200, r.text
        return r.json()["request"]["leave_id"]

    @pytest.mark.parametrize("status,note,start", [("rejected", "Peak season", "2027-03-01"), ("approved", "", "2027-03-08")])
    def test_decide_pushes_to_employee(self, emp, status, note, start):
        end = start[:-2] + f"{int(start[-2:]) + 1:02d}"
        lid = self._apply(emp, start, end)
        db.push_subscriptions.delete_many({"user_id": "user_testemp01"})
        s = fake_sub("L" + status)
        requests.post(f"{BASE_URL}/api/push/subscribe", json=s, headers=emp)
        admin_sub = fake_sub("Ladm")
        requests.post(f"{BASE_URL}/api/push/subscribe", json=admin_sub, headers=ADMIN)
        log_size = os.path.getsize(LOG)
        r = requests.post(f"{BASE_URL}/api/admin/leave/{lid}/decide", json={"status": status, "note": note}, headers=ADMIN)
        assert r.status_code == 200
        assert wait_gone(s["endpoint"]), "employee device not pushed on leave decision"
        time.sleep(1)
        assert sub_exists(admin_sub["endpoint"]), "admin device should not get the employee's leave push"
        with open(LOG) as fh:
            fh.seek(log_size)
            assert "Push failed (410) for user_testemp01" in fh.read()
        req = requests.get(f"{BASE_URL}/api/leave/my", headers=emp)
        if req.status_code == 200:
            pass
        doc = db.leave_requests.find_one({"leave_id": lid})
        assert doc["status"] == status and doc["decision_note"] == note

    def test_decide_without_devices_ok(self, emp):
        db.push_subscriptions.delete_many({"user_id": "user_testemp01"})
        lid = self._apply(emp, "2027-03-15", "2027-03-15")
        r = requests.post(f"{BASE_URL}/api/admin/leave/{lid}/decide", json={"status": "approved"}, headers=SUB)
        assert r.status_code == 200
        assert db.leave_requests.find_one({"leave_id": lid})["status"] == "approved"


# ---- employee device never receives leaving-area alerts ----
class TestEmployeeNoGeofencePush:
    def test_geofence_push_skips_employee_device(self, emp):
        body = {**INSIDE, "descriptor": [0.01] * 128, "image_b64": TINY_JPEG_B64}
        requests.post(f"{BASE_URL}/api/attendance/checkout", json=body, headers=emp)
        r = requests.post(f"{BASE_URL}/api/attendance/checkin", json=body, headers=emp)
        assert r.status_code == 200, r.text
        try:
            db.users.update_one({"user_id": "user_testemp01"}, {"$set": {"field_staff": False}})
            requests.post(f"{BASE_URL}/api/location/ping", json=INSIDE, headers=emp)
            e, a = fake_sub("Gemp"), fake_sub("Gadm")
            requests.post(f"{BASE_URL}/api/push/subscribe", json=e, headers=emp)
            requests.post(f"{BASE_URL}/api/push/subscribe", json=a, headers=ADMIN)
            requests.post(f"{BASE_URL}/api/location/ping", json=OUTSIDE, headers=emp)
            assert wait_gone(a["endpoint"]), "admin not pushed on leaving area"
            time.sleep(2)
            assert sub_exists(e["endpoint"]), "employee device got a leaving-area alert"
        finally:
            requests.post(f"{BASE_URL}/api/attendance/checkout", json=body, headers=emp)
