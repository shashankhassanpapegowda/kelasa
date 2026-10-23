# Password auth (iteration 7): login, lockout, change/forgot/reset, admin set password, security
import os
import uuid
import pytest
import requests
from datetime import datetime, timezone, timedelta
from pymongo import MongoClient

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL').rstrip('/')
API = f"{BASE_URL}/api"
db = MongoClient(os.environ.get('MONGO_URL', 'mongodb://localhost:27017'))[os.environ.get('DB_NAME', 'test_database')]

ADMIN = {"Authorization": "Bearer test_session_admin_001"}
SUB = {"Authorization": "Bearer test_session_subadmin_001"}
RAVI_EMAIL, RAVI_PW = "emp1.test@gtgroups.local", "RaviReset@26"


def login(email, pw, headers=None):
    return requests.post(f"{API}/auth/login", json={"email": email, "password": pw}, headers=headers or {})


def no_hash(obj):
    s = str(obj)
    return "password_hash" not in s and "$2b$" not in s


@pytest.fixture(autouse=True)
def clear_attempts():
    db.login_attempts.delete_many({})
    yield
    db.login_attempts.delete_many({})


@pytest.fixture
def temp_emp():
    email = f"test_pw_{uuid.uuid4().hex[:6]}@gtgroups.local"
    r = requests.post(f"{API}/admin/employees", headers=ADMIN, json={
        "name": "TEST_PW Emp", "email": email, "password": "TempPass@123",
        "department": "Field Operations"})
    assert r.status_code == 200, r.text
    emp = r.json()["employee"]
    assert no_hash(r.json())
    yield emp
    db.users.delete_many({"email": email})
    db.user_sessions.delete_many({"user_id": emp["user_id"]})
    db.password_reset_tokens.delete_many({"user_id": emp["user_id"]})


# ---- Login ----
class TestLogin:
    def test_login_success_cookie_and_token(self):
        r = login(RAVI_EMAIL, RAVI_PW)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["user"]["email"] == RAVI_EMAIL and d["user"]["role"] == "employee"
        assert no_hash(d)
        sc = r.headers.get("set-cookie", "").lower()
        assert "session_token=" in sc and "httponly" in sc and "secure" in sc and "samesite=none" in sc
        me = requests.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {d['session_token']}"})
        assert me.status_code == 200 and me.json()["email"] == RAVI_EMAIL and no_hash(me.json())

    def test_login_case_insensitive_email(self):
        assert login(RAVI_EMAIL.upper(), RAVI_PW).status_code == 200

    def test_wrong_password_and_unknown_email_same_msg(self):
        a = login(RAVI_EMAIL, "wrongpass1")
        b = login("nobody_x@gtgroups.local", "wrongpass1")
        c = login("emp2.test@gtgroups.local", "wrongpass1")  # user with no password
        assert a.status_code == b.status_code == c.status_code == 401
        assert a.json()["detail"] == b.json()["detail"] == c.json()["detail"] == "Incorrect email or password"

    def test_lockout_after_5_and_success_clears(self):
        for i in range(4):
            assert login(RAVI_EMAIL, "bad-pass-x").status_code == 401
        # success clears counter
        assert login(RAVI_EMAIL, RAVI_PW).status_code == 200
        assert db.login_attempts.count_documents({}) == 0
        for i in range(5):
            assert login(RAVI_EMAIL, "bad-pass-x").status_code == 401
        r = login(RAVI_EMAIL, RAVI_PW)
        assert r.status_code == 429
        assert "Try again in" in r.json()["detail"] and "minute" in r.json()["detail"]

    def test_cors_credentials(self):
        r = requests.options(f"{API}/auth/login", headers={
            "Origin": BASE_URL, "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type"})
        assert r.headers.get("access-control-allow-origin") in (BASE_URL,)
        assert r.headers.get("access-control-allow-credentials") == "true"


# ---- Admin-set password + forced change ----
class TestAdminSetPassword:
    def test_new_employee_temp_password_flow(self, temp_emp):
        assert temp_emp["must_change_password"] is True
        doc = db.users.find_one({"user_id": temp_emp["user_id"]})
        assert doc["password_hash"].startswith("$2b$")
        r = login(temp_emp["email"], "TempPass@123")
        assert r.status_code == 200
        assert r.json()["user"]["must_change_password"] is True
        h = {"Authorization": f"Bearer {r.json()['session_token']}"}
        # directory shows has_password + must_change
        emps = requests.get(f"{API}/admin/employees", headers=ADMIN).json()
        assert no_hash(emps)
        lst = emps if isinstance(emps, list) else emps.get("employees", emps)
        row = next(e for e in lst if e["user_id"] == temp_emp["user_id"])
        assert row["has_password"] is True and row["must_change_password"] is True
        # validation
        assert requests.post(f"{API}/auth/change-password", headers=h, json={"current_password": "nope12345", "new_password": "NewPass@123"}).status_code == 400
        assert requests.post(f"{API}/auth/change-password", headers=h, json={"current_password": "TempPass@123", "new_password": "short"}).status_code == 400
        rr = requests.post(f"{API}/auth/change-password", headers=h, json={"current_password": "TempPass@123", "new_password": "TempPass@123"})
        assert rr.status_code == 400 and "haven't used" in rr.json()["detail"]
        ok = requests.post(f"{API}/auth/change-password", headers=h, json={"current_password": "TempPass@123", "new_password": "NewPass@123"})
        assert ok.status_code == 200
        assert requests.get(f"{API}/auth/me", headers=h).json()["must_change_password"] is False
        assert login(temp_emp["email"], "TempPass@123").status_code == 401
        assert login(temp_emp["email"], "NewPass@123").status_code == 200

    def test_admin_reset_kills_sessions_and_logs(self, temp_emp):
        r = login(temp_emp["email"], "TempPass@123")
        h = {"Authorization": f"Bearer {r.json()['session_token']}"}
        requests.post(f"{API}/auth/change-password", headers=h, json={"current_password": "TempPass@123", "new_password": "NewPass@123"})
        s = requests.patch(f"{API}/admin/employees/{temp_emp['user_id']}/password", headers=ADMIN, json={"password": "Reset@1234"})
        assert s.status_code == 200
        assert requests.get(f"{API}/auth/me", headers=h).status_code == 401
        l = login(temp_emp["email"], "Reset@1234")
        assert l.status_code == 200 and l.json()["user"]["must_change_password"] is True
        assert db.activity_log.find_one({"action": "password_set", "target_name": "TEST_PW Emp"}) is not None
        assert requests.patch(f"{API}/admin/employees/{temp_emp['user_id']}/password", headers=ADMIN, json={"password": "short"}).status_code == 400
        assert requests.patch(f"{API}/admin/employees/user_doesnotexist/password", headers=ADMIN, json={"password": "Reset@1234"}).status_code == 404

    def test_subadmin_scope(self, temp_emp):
        assert requests.patch(f"{API}/admin/employees/user_testsub01/password", headers=SUB, json={"password": "Whatever@1"}).status_code == 403
        assert requests.patch(f"{API}/admin/employees/user_testemp02/password", headers=SUB, json={"password": "Whatever@1"}).status_code == 403
        # in scope (Field Operations)
        assert requests.patch(f"{API}/admin/employees/{temp_emp['user_id']}/password", headers=SUB, json={"password": "SubSet@123"}).status_code == 200

    def test_employee_cannot_set_password(self):
        r = requests.patch(f"{API}/admin/employees/user_testemp02/password", headers={"Authorization": "Bearer test_session_emp_001"}, json={"password": "Whatever@1"})
        assert r.status_code == 403

    def test_no_hash_in_shift_assignment_responses(self):
        for path in ("shift", "assignment"):
            r = requests.get(f"{API}/admin/employees/user_testemp01/{path}", headers=ADMIN)
            if r.status_code == 405:
                continue
            assert no_hash(r.text)


# ---- Forgot / reset ----
class TestForgotReset:
    def test_forgot_unknown_email_ok(self):
        r = requests.post(f"{API}/auth/forgot-password", json={"email": "ghost_zz@gtgroups.local"})
        assert r.status_code == 200 and r.json()["ok"] is True

    def test_forgot_and_reset_flow(self, temp_emp):
        r = requests.post(f"{API}/auth/forgot-password", json={"email": temp_emp["email"]})
        assert r.status_code == 200 and r.json()["ok"] is True
        requests.post(f"{API}/auth/forgot-password", json={"email": temp_emp["email"]})
        toks = list(db.password_reset_tokens.find({"user_id": temp_emp["user_id"], "used": False}))
        assert len(toks) == 1
        t = toks[0]
        exp = t["expires_at"].replace(tzinfo=timezone.utc) - t["created_at"].replace(tzinfo=timezone.utc)
        assert timedelta(minutes=59) < exp <= timedelta(hours=1, seconds=5)
        sess = login(temp_emp["email"], "TempPass@123").json()["session_token"]
        assert requests.post(f"{API}/auth/reset-password", json={"token": t["token"], "new_password": "short"}).status_code == 400
        ok = requests.post(f"{API}/auth/reset-password", json={"token": t["token"], "new_password": "Reset@9876"})
        assert ok.status_code == 200
        assert requests.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {sess}"}).status_code == 401
        l = login(temp_emp["email"], "Reset@9876")
        assert l.status_code == 200 and l.json()["user"]["must_change_password"] is False
        again = requests.post(f"{API}/auth/reset-password", json={"token": t["token"], "new_password": "Reset@5555"})
        assert again.status_code == 400

    def test_reset_unknown_and_expired(self, temp_emp):
        assert requests.post(f"{API}/auth/reset-password", json={"token": "bogus", "new_password": "Reset@9876"}).status_code == 400
        db.password_reset_tokens.insert_one({"token": "TEST_expired_tok", "user_id": temp_emp["user_id"], "used": False,
                                             "created_at": datetime.now(timezone.utc) - timedelta(hours=2),
                                             "expires_at": datetime.now(timezone.utc) - timedelta(minutes=1)})
        r = requests.post(f"{API}/auth/reset-password", json={"token": "TEST_expired_tok", "new_password": "Reset@9876"})
        assert r.status_code == 400 and "expired" in r.json()["detail"].lower()
        db.password_reset_tokens.delete_many({"token": "TEST_expired_tok"})


# ---- Regression ----
class TestRegression:
    @pytest.mark.parametrize("tok,role", [("test_session_admin_001", "admin"), ("test_session_subadmin_001", "sub_admin"), ("test_session_emp_001", "employee")])
    def test_legacy_sessions(self, tok, role):
        r = requests.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {tok}"})
        assert r.status_code == 200 and r.json()["role"] == role and no_hash(r.json())
        r2 = requests.get(f"{API}/auth/me", cookies={"session_token": tok})
        assert r2.status_code == 200
