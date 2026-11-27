# Iteration 6 focused retest: self-decision block, self-edit block, manager cancel scope+log, holiday-aware day count, quota msg, leave-type dup code
import os
import uuid
from datetime import datetime, timezone, timedelta
import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'http://localhost:8000').rstrip('/')
API = f"{BASE_URL}/api"
ADMIN = "test_session_admin_001"
SUB = "test_session_subadmin_001"
EMP = "test_session_emp_001"
ANITA = "TEST_session_anita_iter6"


def h(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def types_by_code(tok=EMP):
    return {t["code"]: t for t in requests.get(f"{API}/leave/types", headers=h(tok)).json()["types"]}


def apply(tok, start, end, code="LV"):
    t = types_by_code(tok)
    return requests.post(f"{API}/leave/request", headers=h(tok), json={
        "type_id": t[code]["type_id"], "start_date": start, "end_date": end, "reason": "TEST_iter6"})


@pytest.fixture(scope="module")
def mdb():
    c = MongoClient(os.environ.get('MONGO_URL', 'mongodb://localhost:27017'))
    db = c[os.environ.get('DB_NAME', 'test_database')]
    now = datetime.now(timezone.utc)
    db.user_sessions.insert_one({"user_id": "user_testemp02", "session_token": ANITA,
                                 "expires_at": (now + timedelta(days=1)).isoformat(), "created_at": now.isoformat()})
    yield db
    db.user_sessions.delete_many({"session_token": ANITA})
    db.leave_requests.delete_many({"reason": "TEST_iter6"})
    db.holidays.delete_many({"name": {"$regex": "^TEST_iter6"}})
    c.close()


# ---- Self-decision block ----
class TestSelfDecision:
    def test_sub_admin_cannot_decide_own(self, mdb):
        r = apply(SUB, "2027-01-05", "2027-01-05")
        assert r.status_code == 200, r.text
        lid = r.json()["request"]["leave_id"]
        d = requests.post(f"{API}/admin/leave/{lid}/decide", headers=h(SUB), json={"status": "approved"})
        assert d.status_code == 403
        assert d.json()["detail"] == "You cannot decide on your own leave request"
        # admin can decide sub-admin's
        a = requests.post(f"{API}/admin/leave/{lid}/decide", headers=h(ADMIN), json={"status": "approved"})
        assert a.status_code == 200

    def test_admin_cannot_decide_own(self, mdb):
        r = apply(ADMIN, "2027-01-07", "2027-01-07")
        assert r.status_code == 200, r.text
        lid = r.json()["request"]["leave_id"]
        d = requests.post(f"{API}/admin/leave/{lid}/decide", headers=h(ADMIN), json={"status": "rejected"})
        assert d.status_code == 403
        lst = {x["leave_id"]: x for x in requests.get(f"{API}/admin/leave?status=pending", headers=h(ADMIN)).json()["requests"]}
        assert lst[lid]["status"] == "pending"

    def test_sub_admin_can_decide_team_member(self, mdb):
        r = apply(EMP, "2027-01-12", "2027-01-12")
        assert r.status_code == 200, r.text
        lid = r.json()["request"]["leave_id"]
        d = requests.post(f"{API}/admin/leave/{lid}/decide", headers=h(SUB), json={"status": "approved"})
        assert d.status_code == 200

    def test_sub_admin_cannot_decide_out_of_scope(self, mdb):
        r = apply(ANITA, "2027-01-14", "2027-01-14")
        assert r.status_code == 200, r.text
        lid = r.json()["request"]["leave_id"]
        d = requests.post(f"{API}/admin/leave/{lid}/decide", headers=h(SUB), json={"status": "approved"})
        assert d.status_code == 403, f"sub-admin decided out-of-scope leave: {d.status_code} {d.text}"


# ---- Self-edit block ----
class TestSelfEdit:
    def test_sub_admin_own_shift_assignment_403(self, mdb):
        r = requests.patch(f"{API}/admin/employees/user_testsub01/shift", headers=h(SUB), json={"break_max_minutes": 90})
        assert r.status_code == 403
        r = requests.patch(f"{API}/admin/employees/user_testsub01/assignment", headers=h(SUB), json={"designation": "TEST_boss"})
        assert r.status_code == 403

    def test_sub_admin_team_edit_ok(self, mdb):
        before = mdb.users.find_one({"user_id": "user_testemp01"}, {"_id": 0, "break_max_minutes": 1, "designation": 1})
        r = requests.patch(f"{API}/admin/employees/user_testemp01/shift", headers=h(SUB), json={"break_max_minutes": 50})
        assert r.status_code == 200 and r.json()["employee"]["break_max_minutes"] == 50
        r = requests.patch(f"{API}/admin/employees/user_testemp01/assignment", headers=h(SUB), json={"designation": "TEST_iter6"})
        assert r.status_code == 200
        mdb.users.update_one({"user_id": "user_testemp01"}, {"$set": {
            "break_max_minutes": before.get("break_max_minutes", 60), "designation": before.get("designation")}})

    def test_admin_own_shift_ok(self, mdb):
        before = mdb.users.find_one({"user_id": "user_testadmin01"}, {"_id": 0, "break_max_minutes": 1})
        r = requests.patch(f"{API}/admin/employees/user_testadmin01/shift", headers=h(ADMIN), json={"break_max_minutes": 55})
        assert r.status_code == 200
        mdb.users.update_one({"user_id": "user_testadmin01"}, {"$set": {"break_max_minutes": before.get("break_max_minutes", 60)}})


# ---- Manager cancel scope + log ----
class TestManagerCancel:
    def test_sub_admin_cannot_cancel_out_of_scope(self, mdb):
        r = apply(ANITA, "2027-02-02", "2027-02-02")
        assert r.status_code == 200, r.text
        lid = r.json()["request"]["leave_id"]
        c = requests.post(f"{API}/leave/{lid}/cancel", headers=h(SUB))
        assert c.status_code == 403
        c = requests.post(f"{API}/leave/{lid}/cancel", headers=h(ADMIN))
        assert c.status_code == 200
        acts = requests.get(f"{API}/admin/activity", headers=h(ADMIN)).json()["entries"]
        assert any(a["action"] == "leave_cancelled" and "2027-02-02" in (a.get("details") or "") for a in acts)

    def test_sub_admin_cancel_team_member(self, mdb):
        r = apply(EMP, "2027-02-04", "2027-02-04")
        lid = r.json()["request"]["leave_id"]
        c = requests.post(f"{API}/leave/{lid}/cancel", headers=h(SUB))
        assert c.status_code == 200

    def test_employee_cancel_own_and_not_others(self, mdb):
        r = apply(EMP, "2027-02-08", "2027-02-08")
        lid = r.json()["request"]["leave_id"]
        o = apply(ANITA, "2027-02-08", "2027-02-08").json()["request"]["leave_id"]
        assert requests.post(f"{API}/leave/{o}/cancel", headers=h(EMP)).status_code == 403
        assert requests.post(f"{API}/leave/{lid}/cancel", headers=h(EMP)).status_code == 200


# ---- Holiday-aware counting ----
class TestHolidayCounting:
    def test_holiday_subtracted(self, mdb):
        hr = requests.post(f"{API}/admin/holidays", headers=h(ADMIN), json={"date": "2027-03-10", "name": "TEST_iter6_hol"})
        assert hr.status_code == 200, hr.text
        hid = hr.json()["holiday"]["holiday_id"]
        try:
            r = apply(EMP, "2027-03-09", "2027-03-11")
            assert r.status_code == 200, r.text
            assert r.json()["request"]["days"] == 2.0
            requests.post(f"{API}/leave/{r.json()['request']['leave_id']}/cancel", headers=h(EMP))
            only = apply(EMP, "2027-03-10", "2027-03-10")
            assert only.status_code == 400
            assert only.json()["detail"] == "Those dates are already company holidays"
        finally:
            requests.delete(f"{API}/admin/holidays/{hid}", headers=h(ADMIN))


# ---- Quota message + leave-type duplicate code ----
class TestMisc:
    def test_days_past_the_monthly_paid_day_are_unpaid(self, mdb):
        # Mon–Fri in a month nothing else uses. One day is paid; the other four are unpaid.
        r = apply(EMP, "2029-02-05", "2029-02-09")
        assert r.status_code == 200, r.text
        req = r.json()["request"]
        assert req["paid_days"] == 1
        assert req["lop_days"] == 4
        assert req["days"] == 5
        requests.post(f"{API}/leave/{req['leave_id']}/cancel", headers=h(EMP))

    def test_patch_leave_type_dup_code(self, mdb):
        code = f"T{uuid.uuid4().hex[:3].upper()}"
        c = requests.post(f"{API}/admin/leave-types", headers=h(ADMIN), json={
            "name": "TEST_iter6_type", "code": code, "policy": "none"})
        assert c.status_code == 200
        tid = c.json()["type"]["type_id"]
        try:
            p = requests.patch(f"{API}/admin/leave-types/{tid}", headers=h(ADMIN), json={
                "name": "TEST_iter6_type", "code": "lv", "policy": "none"})
            assert p.status_code == 400
            ok = requests.patch(f"{API}/admin/leave-types/{tid}", headers=h(ADMIN), json={
                "name": "TEST_iter6_type2", "code": code, "policy": "none"})
            assert ok.status_code == 200
        finally:
            requests.delete(f"{API}/admin/leave-types/{tid}", headers=h(ADMIN))
