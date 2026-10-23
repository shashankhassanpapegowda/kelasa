# Iteration 14: morning celebrations cron, ESI not-applicable, payroll CSV, private wishes
import os
import csv
import io
import time
import pytest
import requests
from datetime import datetime, timezone, timedelta
from pymongo import MongoClient

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
API = f"{BASE_URL}/api"


def _secret():
    for line in open("/app/backend/.env"):
        if line.startswith("WEBHOOK_CRON_SECRET="):
            return line.split("=", 1)[1].strip().strip('"')
    raise RuntimeError("no secret")


@pytest.fixture(scope="module")
def db():
    c = MongoClient("mongodb://localhost:27017")
    yield c["test_database"]
    c.close()


def _s(token):
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def admin():
    return _s("test_session_admin_001")


@pytest.fixture(scope="module")
def sub():
    return _s("test_session_subadmin_001")


@pytest.fixture(scope="module")
def ravi():
    return _s("test_session_emp_001")


@pytest.fixture(scope="module")
def anita(db):
    tok = "TEST_session_anita_iter14"
    db.user_sessions.delete_many({"session_token": tok})
    now = datetime.now(timezone.utc)
    db.user_sessions.insert_one({"user_id": "user_testemp02", "session_token": tok,
                                 "expires_at": (now + timedelta(days=1)).isoformat(), "created_at": now.isoformat()})
    yield _s(tok)
    db.user_sessions.delete_many({"session_token": tok})
    db.wishes.delete_many({"from_user_id": "user_testemp02"})


# ---- Cron ----
class TestCron:
    def test_no_auth_401(self):
        r = requests.post(f"{API}/cron/celebrations")
        assert r.status_code == 401

    def test_wrong_bearer_401(self):
        r = requests.post(f"{API}/cron/celebrations", headers={"Authorization": "Bearer nope"})
        assert r.status_code == 401

    def test_rerun_then_duplicate(self, db):
        db.cron_runs.delete_many({"key": {"$regex": "^celebrations-"}})
        h = {"Authorization": f"Bearer {_secret()}", "Content-Type": "application/json"}
        t0 = time.time()
        r = requests.post(f"{API}/cron/celebrations", headers=h, json={"run_id": "TEST_r14"})
        assert r.status_code == 200, r.text
        assert time.time() - t0 < 5
        d = r.json()
        assert d["ok"] is True and d["queued"] == datetime.now(timezone(timedelta(hours=5, minutes=30))).date().isoformat()
        r2 = requests.post(f"{API}/cron/celebrations", headers=h)
        assert r2.json() == {"ok": True, "duplicate": True}
        time.sleep(3)
        run = db.cron_runs.find_one({"key": f"celebrations-{d['queued']}"})
        assert run["status"] in ("done", "nothing_today")
        assert "sent" in run

    def test_cron_no_body_ok(self):
        h = {"Authorization": f"Bearer {_secret()}"}
        r = requests.post(f"{API}/cron/celebrations", headers=h)
        assert r.status_code == 200 and r.json().get("duplicate") is True


# ---- Push prefs ----
class TestPushPrefs:
    EP = "https://fcm.googleapis.com/fcm/send/TEST_iter14_ep"

    def test_celebrations_pref(self, ravi, db):
        r = ravi.post(f"{API}/push/subscribe", json={"endpoint": self.EP, "keys": {"p256dh": "x", "auth": "y"}})
        assert r.status_code == 200
        st = ravi.get(f"{API}/push/status", params={"endpoint": self.EP}).json()
        assert st["celebrations"] is True
        r = ravi.patch(f"{API}/push/subscribe", json={"endpoint": self.EP, "celebrations": False})
        assert r.status_code == 200 and r.json()["celebrations"] is False
        st = ravi.get(f"{API}/push/status", params={"endpoint": self.EP}).json()
        assert st["celebrations"] is False
        db.push_subscriptions.delete_many({"endpoint": self.EP})


# ---- Profile ESI not applicable ----
class TestEsiNA:
    def test_toggle(self, ravi):
        r = ravi.put(f"{API}/profile/me", json={"esi": "1234567890", "esi_not_applicable": False})
        assert r.status_code == 200, r.text
        p = ravi.get(f"{API}/profile/me").json()
        prof = p.get("profile", p)
        assert prof.get("esi") == "1234567890"
        r = ravi.put(f"{API}/profile/me", json={"esi_not_applicable": True})
        assert r.status_code == 200
        p = ravi.get(f"{API}/profile/me").json()
        prof = p.get("profile", p)
        assert prof.get("esi") in (None, "") and prof.get("esi_not_applicable") is True

    def test_bad_esi(self, ravi):
        r = ravi.put(f"{API}/profile/me", json={"esi": "12", "esi_not_applicable": False})
        assert r.status_code == 400
        ravi.put(f"{API}/profile/me", json={"esi_not_applicable": True})


# ---- Payroll CSV ----
class TestPayrollCsv:
    COLS = ["Employee ID", "Name", "Email", "Branch", "Department", "Joining Date", "Account Holder",
            "Account Number", "IFSC", "Bank Name", "EPF UAN", "ESI Number", "Bank Status"]

    def _rows(self, s):
        r = s.get(f"{API}/admin/reports/payroll-details.csv")
        assert r.status_code == 200, r.text
        assert "text/csv" in r.headers.get("content-type", "")
        rows = list(csv.reader(io.StringIO(r.content.decode("utf-8-sig"))))
        return rows

    def test_admin_all(self, admin):
        rows = self._rows(admin)
        assert rows[0] == self.COLS
        ids = {r[0] for r in rows[1:]}
        assert {"user_testemp01", "user_testemp02"} <= ids
        ravi = next(r for r in rows[1:] if r[0] == "user_testemp01")
        assert ravi[8] == "SBIN0001234" and ravi[10] == "100123456789"
        assert ravi[11] == "Not applicable" and ravi[12] in ("Approved", "Change pending approval")
        anita = next(r for r in rows[1:] if r[0] == "user_testemp02")
        assert anita[12] == "Missing"

    def test_subadmin_scope(self, sub):
        rows = self._rows(sub)
        ids = {r[0] for r in rows[1:]}
        assert "user_testemp01" in ids and "user_testemp02" not in ids

    def test_employee_403(self, ravi):
        r = ravi.get(f"{API}/admin/reports/payroll-details.csv")
        assert r.status_code == 403

    def test_query_auth(self):
        r = requests.get(f"{API}/admin/reports/payroll-details.csv", params={"auth": "test_session_admin_001"})
        assert r.status_code == 200


# ---- Wishes ----
class TestWishes:
    def test_celebrations_fields(self, ravi, admin):
        d = ravi.get(f"{API}/celebrations").json()
        mine = [c for c in d["celebrations"] if c["is_me"]]
        assert mine and all("wish_count" in c for c in mine)
        bday = next(c for c in mine if c["kind"] == "birthday" and c["days_away"] == 0)
        assert bday["wish_count"] >= 1
        a = admin.get(f"{API}/celebrations").json()
        rb = next(c for c in a["celebrations"] if c["user_id"] == "user_testemp01" and c["kind"] == "birthday")
        assert rb["my_wish_id"] == "wish_45f86dc310d1"
        assert "wish_count" not in rb

    def test_self_wish(self, ravi):
        r = ravi.post(f"{API}/wishes", json={"to_user_id": "user_testemp01", "kind": "birthday", "message": "me"})
        assert r.status_code == 400 and "yourself" in r.json()["detail"]

    def test_no_celebration(self, ravi):
        r = ravi.post(f"{API}/wishes", json={"to_user_id": "user_testemp02", "kind": "birthday", "message": "hi"})
        assert r.status_code == 400 and "no celebration" in r.json()["detail"]

    def test_bad_kind(self, anita):
        r = anita.post(f"{API}/wishes", json={"to_user_id": "user_testemp01", "kind": "xyz", "message": "hi"})
        assert r.status_code == 422

    def test_too_long_and_empty(self, anita):
        r = anita.post(f"{API}/wishes", json={"to_user_id": "user_testemp01", "kind": "birthday", "message": "a" * 501})
        assert r.status_code == 400
        r = anita.post(f"{API}/wishes", json={"to_user_id": "user_testemp01", "kind": "birthday", "message": "   "})
        assert r.status_code == 400

    def test_duplicate_admin(self, admin):
        r = admin.post(f"{API}/wishes", json={"to_user_id": "user_testemp01", "kind": "birthday", "message": "again"})
        assert r.status_code == 400 and "already" in r.json()["detail"]

    def test_full_flow(self, anita, ravi, admin, sub):
        before = ravi.get(f"{API}/wishes/unread-count").json()["unread"]
        r = anita.post(f"{API}/wishes", json={"to_user_id": "user_testemp01", "kind": "work_anniversary", "message": "Congrats Ravi!"})
        assert r.status_code == 200, r.text
        w = r.json()["wish"]
        assert w["direction"] == "sent" and w["unread"] is False and w["years"] == 4
        wid = w["wish_id"]
        # upcoming wedding anniversary (+3 days) allowed
        r = anita.post(f"{API}/wishes", json={"to_user_id": "user_testemp01", "kind": "wedding_anniversary", "message": "Early congrats"})
        assert r.status_code == 200, r.text
        wid2 = r.json()["wish"]["wish_id"]
        assert ravi.get(f"{API}/wishes/unread-count").json()["unread"] == before + 2
        lst = ravi.get(f"{API}/wishes").json()
        t = next(x for x in lst["wishes"] if x["wish_id"] == wid)
        assert t["direction"] == "received" and t["unread"] is True
        # privacy
        assert all(x["wish_id"] not in (wid, wid2) for x in admin.get(f"{API}/wishes").json()["wishes"])
        assert admin.post(f"{API}/wishes/{wid}/reply", json={"message": "hijack"}).status_code == 404
        assert sub.post(f"{API}/wishes/{wid}/read").status_code == 404
        # read
        assert ravi.post(f"{API}/wishes/{wid}/read").status_code == 200
        assert ravi.get(f"{API}/wishes/unread-count").json()["unread"] == before + 1
        # reply -> other party unread
        r = ravi.post(f"{API}/wishes/{wid}/reply", json={"message": "Thanks Anita"})
        assert r.status_code == 200
        al = anita.get(f"{API}/wishes").json()
        t = next(x for x in al["wishes"] if x["wish_id"] == wid)
        assert t["unread"] is True and len(t["messages"]) == 2 and t["messages"][-1]["message"] == "Thanks Anita"
        assert anita.get(f"{API}/wishes/unread-count").json()["unread"] >= 1
        # celebrations my_wish_id for anita
        c = anita.get(f"{API}/celebrations").json()["celebrations"]
        wa = next(x for x in c if x["user_id"] == "user_testemp01" and x["kind"] == "work_anniversary")
        assert wa["my_wish_id"] == wid
        ravi.post(f"{API}/wishes/{wid2}/read")

    def test_reply_unknown_404(self, ravi):
        assert ravi.post(f"{API}/wishes/wish_nope/reply", json={"message": "x"}).status_code == 404
