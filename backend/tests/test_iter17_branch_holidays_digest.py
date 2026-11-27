# Iteration 17: branch holidays (add/clash/list/delete/scope), reports + leave day count by branch, missed-checkout digest cron
import os
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
ADMIN = {"Authorization": "Bearer test_session_admin_001"}
SUB = {"Authorization": "Bearer test_session_subadmin_001"}
EMP = {"Authorization": "Bearer test_session_emp_001"}


def _env(key):
    for line in open("/app/backend/.env"):
        if line.startswith(key + "="):
            return line.split("=", 1)[1].strip().strip('"')
    return os.environ.get(key)


MONGO_URL = _env("MONGO_URL")
DB_NAME = _env("DB_NAME")
CRON = _env("WEBHOOK_CRON_SECRET")
db = MongoClient(MONGO_URL)[DB_NAME]
CREATED = []
NOSITE_TOKEN = f"TEST_sess_nosite_{uuid.uuid4().hex[:6]}"
NOSITE_UID = f"TEST_user_nosite_{uuid.uuid4().hex[:6]}"


def leave_type_id():
    r = requests.get(f"{BASE_URL}/api/leave/types", headers=EMP)
    assert r.status_code == 200, r.text
    match = next((t for t in r.json()["types"] if t["code"] == "LV"), None)
    assert match, r.text
    return match["type_id"]


def add(headers, date, name, branches):
    r = requests.post(f"{BASE_URL}/api/admin/holidays", headers=headers, json={"date": date, "name": name, "branches": branches})
    if r.status_code == 200:
        CREATED.append(r.json()["holiday"]["holiday_id"])
    return r


@pytest.fixture(scope="module", autouse=True)
def setup_cleanup():
    db.users.insert_one({"user_id": NOSITE_UID, "email": f"{NOSITE_UID.lower()}@example.test", "name": "TEST_NoSite Sub",
                         "role": "sub_admin", "managed_sites": [], "managed_departments": [], "face_enrolled": True,
                         "created_at": "2026-01-01T00:00:00+00:00"})
    db.user_sessions.insert_one({"user_id": NOSITE_UID, "session_token": NOSITE_TOKEN,
                                 "expires_at": (datetime.utcnow() + timedelta(days=1)).isoformat() + "Z",
                                 "created_at": datetime.utcnow().isoformat() + "Z"})
    yield
    for hid in CREATED:
        db.holidays.delete_one({"holiday_id": hid})
    db.users.delete_one({"user_id": NOSITE_UID})
    db.user_sessions.delete_one({"session_token": NOSITE_TOKEN})


# --- Add permissions ---
class TestAddPermissions:
    def test_admin_company_wide(self):
        r = add(ADMIN, "2027-03-01", "TEST_Company", [])
        assert r.status_code == 200, r.text
        assert r.json()["holiday"]["branches"] == []

    def test_admin_chosen_branches(self):
        r = add(ADMIN, "2027-03-02", "TEST_Two", ["Tumkur Yard", "GeoTest HQ"])
        assert r.status_code == 200, r.text
        assert r.json()["holiday"]["branches"] == ["GeoTest HQ", "Tumkur Yard"]

    def test_admin_unknown_branch(self):
        r = add(ADMIN, "2027-03-03", "TEST_Unknown", ["Nowhere"])
        assert r.status_code == 400 and "Unknown branch" in r.json()["detail"]

    def test_sub_no_branches_400(self):
        assert add(SUB, "2027-03-04", "TEST_SubNone", []).status_code == 400

    def test_sub_other_branch_403(self):
        assert add(SUB, "2027-03-04", "TEST_SubOther", ["Tumkur Yard"]).status_code == 403

    def test_sub_mixed_branch_403(self):
        assert add(SUB, "2027-03-04", "TEST_SubMix", ["Bengaluru HQ", "Tumkur Yard"]).status_code == 403

    def test_sub_own_branch_ok(self):
        r = add(SUB, "2027-03-04", "TEST_SubOwn", ["Bengaluru HQ"])
        assert r.status_code == 200, r.text
        assert r.json()["holiday"]["branches"] == ["Bengaluru HQ"]

    def test_sub_no_managed_sites_403(self):
        r = add({"Authorization": f"Bearer {NOSITE_TOKEN}"}, "2027-03-05", "TEST_NoSite", ["Bengaluru HQ"])
        assert r.status_code == 403, r.text

    def test_employee_403(self):
        assert add(EMP, "2027-03-05", "TEST_Emp", []).status_code == 403


# --- Clash rules ---
class TestClash:
    def test_rules(self):
        assert add(ADMIN, "2027-04-01", "TEST_CW", []).status_code == 200
        assert add(ADMIN, "2027-04-01", "TEST_CW2", []).status_code == 400
        assert add(ADMIN, "2027-04-01", "TEST_BrOnCW", ["Tumkur Yard"]).status_code == 400
        assert add(ADMIN, "2027-04-02", "TEST_TY", ["Tumkur Yard"]).status_code == 200
        assert add(ADMIN, "2027-04-02", "TEST_BH", ["Bengaluru HQ"]).status_code == 200  # different branches ok
        r = add(ADMIN, "2027-04-02", "TEST_Overlap", ["Tumkur Yard", "GeoTest HQ"])
        assert r.status_code == 400 and "Tumkur Yard" in r.json()["detail"]
        assert add(ADMIN, "2027-04-02", "TEST_CWonBranch", []).status_code == 400  # company-wide clashes w/ any
        assert add(SUB, "2027-04-02", "TEST_SubDup", ["Bengaluru HQ"]).status_code == 400


# --- List & delete ---
class TestListDelete:
    def test_list_and_delete(self):
        cw = add(ADMIN, "2027-05-03", "TEST_L_CW", []).json()["holiday"]["holiday_id"]
        ty = add(ADMIN, "2027-05-04", "TEST_L_TY", ["Tumkur Yard"]).json()["holiday"]["holiday_id"]
        bh = add(ADMIN, "2027-05-05", "TEST_L_BH", ["Bengaluru HQ"]).json()["holiday"]["holiday_id"]
        mix = add(ADMIN, "2027-05-06", "TEST_L_MIX", ["Bengaluru HQ", "Tumkur Yard"]).json()["holiday"]["holiday_id"]

        def get(h):
            r = requests.get(f"{BASE_URL}/api/holidays?year=2027", headers=h)
            assert r.status_code == 200
            return {x["holiday_id"]: x for x in r.json()["holidays"]}

        a = get(ADMIN)
        assert all(k in a for k in (cw, ty, bh, mix))
        assert all(a[k]["can_edit"] for k in (cw, ty, bh, mix))
        assert a[cw]["branches"] == [] and a[ty]["branches"] == ["Tumkur Yard"]
        s = get(SUB)
        assert all(k in s for k in (cw, ty, bh, mix))
        assert s[bh]["can_edit"] is True
        assert s[cw]["can_edit"] is False and s[ty]["can_edit"] is False and s[mix]["can_edit"] is False
        e = get(EMP)
        assert cw in e and bh in e and mix in e and ty not in e

        for hid in (cw, ty, mix):
            r = requests.delete(f"{BASE_URL}/api/admin/holidays/{hid}", headers=SUB)
            assert r.status_code == 403, (hid, r.text)
        assert requests.delete(f"{BASE_URL}/api/admin/holidays/{bh}", headers=EMP).status_code == 403
        assert requests.delete(f"{BASE_URL}/api/admin/holidays/{bh}", headers=SUB).status_code == 200
        assert bh not in get(ADMIN)
        assert requests.delete(f"{BASE_URL}/api/admin/holidays/{ty}", headers=ADMIN).status_code == 200
        assert requests.delete(f"{BASE_URL}/api/admin/holidays/nope_123", headers=ADMIN).status_code == 404


# --- Reports: branch holidays only for staff of that branch ---
class TestReports:
    def _rows(self, f, t):
        r = requests.get(f"{BASE_URL}/api/admin/reports", headers=ADMIN, params={"from": f, "to": t})
        assert r.status_code == 200, r.text
        data = r.json()
        rows = data.get("rows") or data.get("report") or data.get("employees") or data
        return {x["user_id"]: x for x in rows}

    def test_branch_holiday_report(self):
        f, t = "2026-11-10", "2026-11-11"  # Tue, Wed (past)
        before = self._rows(f, t)
        add(ADMIN, "2026-11-10", "TEST_R_TY", ["Tumkur Yard"])
        add(ADMIN, "2026-11-11", "TEST_R_BH", ["Bengaluru HQ"])
        after = self._rows(f, t)
        ravi_b, ravi_a = before["user_testemp01"], after["user_testemp01"]
        anita_b, anita_a = before["user_testemp02"], after["user_testemp02"]
        print("ravi", ravi_b["holiday_days"], ravi_b["absent_days"], "->", ravi_a["holiday_days"], ravi_a["absent_days"])
        print("anita", anita_b["holiday_days"], anita_b["absent_days"], "->", anita_a["holiday_days"], anita_a["absent_days"])
        assert anita_a["holiday_days"] == anita_b["holiday_days"]
        assert anita_a["absent_days"] == anita_b["absent_days"]
        if "2026-11-11" not in {r["date"] for r in db.attendance.find({"user_id": "user_testemp01", "date": "2026-11-11"})}:
            assert ravi_a["holiday_days"] == ravi_b["holiday_days"] + 1
            assert ravi_a["absent_days"] == ravi_b["absent_days"] - 1


# --- Leave day count ---
class TestLeaveCount:
    def test_leave_excludes_only_applicable(self):
        add(ADMIN, "2027-06-08", "TEST_LV_TY", ["Tumkur Yard"])
        add(ADMIN, "2027-06-09", "TEST_LV_BH", ["Bengaluru HQ"])
        r = requests.post(f"{BASE_URL}/api/leave/request", headers=EMP, json={
            "type_id": leave_type_id(), "start_date": "2027-06-07", "end_date": "2027-06-10", "reason": "TEST_branch holiday"})
        assert r.status_code == 200, r.text
        body = r.json()
        req = body.get("request") or body.get("leave") or body
        lid = req.get("leave_id")
        try:
            doc = db.leave_requests.find_one({"leave_id": lid})
            assert doc["days"] == 3, doc["days"]  # 4 days minus only the Bengaluru HQ holiday
        finally:
            db.leave_requests.delete_one({"leave_id": lid})

    def test_leave_all_branch_holiday_rejected(self):
        add(ADMIN, "2027-06-15", "TEST_LV_BH2", ["Bengaluru HQ"])
        r = requests.post(f"{BASE_URL}/api/leave/request", headers=EMP, json={
            "type_id": leave_type_id(), "start_date": "2027-06-15", "end_date": "2027-06-15"})
        assert r.status_code == 400


# --- Missed checkout digest cron ---
class TestDigestCron:
    def test_auth(self):
        u = f"{BASE_URL}/api/cron/missed-checkout-digest"
        assert requests.post(u).status_code == 401
        assert requests.post(u, headers={"Authorization": "Bearer wrong"}).status_code == 401

    def test_run_and_dupe(self):
        import time
        today = datetime.now(ZoneInfo("Asia/Kolkata")).date()
        yday = (today - timedelta(days=1)).isoformat()
        key = f"missed-digest-{today.isoformat()}"
        uid = f"TEST_user_digest_{uuid.uuid4().hex[:6]}"
        rid = f"TEST_att_{uuid.uuid4().hex[:8]}"
        db.users.insert_one({"user_id": uid, "name": "TEST_Digest Emp", "email": f"{uid.lower()}@example.test",
                             "role": "employee", "site": "Bengaluru HQ", "created_at": "2026-01-01T00:00:00+00:00"})
        db.attendance.insert_one({"record_id": rid, "user_id": uid, "date": yday, "check_in": f"{yday}T04:00:00+00:00",
                                  "check_out": f"{yday}T12:30:00+00:00", "auto_closed": True,
                                  "auto_close_reason": "missed checkout", "status": "off_duty", "breaks": []})
        db.cron_runs.delete_one({"key": key})
        try:
            h = {"Authorization": f"Bearer {CRON}"}
            u = f"{BASE_URL}/api/cron/missed-checkout-digest"
            r1 = requests.post(u, headers=h)
            assert r1.status_code == 200 and r1.json() == {"ok": True, "queued": today.isoformat()}, r1.text
            r2 = requests.post(u, headers=h)
            assert r2.status_code == 200 and r2.json() == {"ok": True, "duplicate": True}
            doc = None
            for _ in range(20):
                doc = db.cron_runs.find_one({"key": key})
                if doc and doc.get("status") == "done":
                    break
                time.sleep(0.5)
            assert doc["status"] == "done", doc
            assert doc["missed"] >= 1, doc
            r3 = requests.post(u, headers=h, json=[1])
            assert r3.status_code == 400
        finally:
            db.attendance.delete_one({"record_id": rid})
            db.users.delete_one({"user_id": uid})
