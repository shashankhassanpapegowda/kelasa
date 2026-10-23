# Iter13: Employee profile (dates, UAN/ESI, avatar, bank change approval) + celebrations
import os
import base64
import copy
from datetime import date, timedelta
import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")

ADMIN = "test_session_admin_001"
SUB = "test_session_subadmin_001"
EMP = "test_session_emp_001"
RAVI = "user_testemp01"
ANITA = "user_testemp02"
ADMIN_ID = "user_testadmin01"

PNG_1x1 = base64.b64encode(base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)).decode()


def c(token):
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module", autouse=True)
def snapshot():
    db = MongoClient(MONGO_URL)[DB_NAME]
    prof = db.employee_profiles.find_one({"user_id": RAVI})
    user = db.users.find_one({"user_id": RAVI}, {"avatar_path": 1})
    existing = {r["request_id"] for r in db.bank_change_requests.find({}, {"request_id": 1})}
    yield db
    # restore
    db.bank_change_requests.delete_many({"request_id": {"$nin": list(existing)}})
    if prof:
        db.employee_profiles.replace_one({"user_id": RAVI}, prof, upsert=True)
    db.users.update_one({"user_id": RAVI}, {"$set": {"avatar_path": user.get("avatar_path")}})


# ---- profile/me ----
class TestProfileMe:
    def test_get_profile_merged(self):
        r = c(EMP).get(f"{BASE_URL}/api/profile/me")
        assert r.status_code == 200
        d = r.json()
        assert "_id" not in d
        assert d["name"] and d["email"] == "emp1.test@gtgroups.local"
        assert "pending_bank" in d and "last_bank_decision" in d
        assert d.get("uan") == "100123456789"

    def test_unauth(self):
        r = requests.get(f"{BASE_URL}/api/profile/me")
        assert r.status_code == 401

    def test_future_dob_rejected(self):
        fut = (date.today() + timedelta(days=5)).isoformat()
        r = c(EMP).put(f"{BASE_URL}/api/profile/me", json={"dob": fut})
        assert r.status_code == 400
        assert r.json()["detail"] == "Date of birth can't be in the future"

    def test_invalid_date(self):
        r = c(EMP).put(f"{BASE_URL}/api/profile/me", json={"wedding_anniversary": "2020-13-40"})
        assert r.status_code == 400

    @pytest.mark.parametrize("uan,ok", [("1001 2345 6789", True), ("12345", False), ("abcdefghijkl", False)])
    def test_uan(self, uan, ok):
        r = c(EMP).put(f"{BASE_URL}/api/profile/me", json={"uan": uan})
        if ok:
            assert r.status_code == 200 and r.json()["uan"] == "100123456789"
        else:
            assert r.status_code == 400 and "UAN" in r.json()["detail"]

    @pytest.mark.parametrize("esi,ok", [("3112345678", True), ("12345678901234567", True), ("123456789012", False)])
    def test_esi(self, esi, ok):
        r = c(EMP).put(f"{BASE_URL}/api/profile/me", json={"esi": esi})
        assert r.status_code == (200 if ok else 400)
        if ok:
            assert c(EMP).get(f"{BASE_URL}/api/profile/me").json()["esi"] == esi

    def test_empty_update(self):
        r = c(EMP).put(f"{BASE_URL}/api/profile/me", json={})
        assert r.status_code == 400

    def test_restore_esi(self):
        r = c(EMP).put(f"{BASE_URL}/api/profile/me", json={"esi": "3112345678"})
        assert r.status_code == 200


# ---- avatar ----
class TestAvatar:
    def test_reject_non_image(self):
        r = c(EMP).post(f"{BASE_URL}/api/profile/me/avatar",
                        json={"image_b64": "data:text/plain;base64," + base64.b64encode(b"hello world").decode()})
        assert r.status_code == 400 and r.json()["detail"] == "Use a JPG or PNG photo"

    def test_reject_too_large(self):
        big = b"\xff\xd8\xff" + b"0" * (3 * 1024 * 1024 + 10)
        r = c(EMP).post(f"{BASE_URL}/api/profile/me/avatar", json={"image_b64": base64.b64encode(big).decode()})
        assert r.status_code in (400, 413)

    def test_invalid_b64(self):
        r = c(EMP).post(f"{BASE_URL}/api/profile/me/avatar", json={"image_b64": "!!!notb64"})
        assert r.status_code == 400

    def test_upload_png_then_fetch_and_delete(self):
        s = c(EMP)
        r = s.post(f"{BASE_URL}/api/profile/me/avatar", json={"image_b64": "data:image/png;base64," + PNG_1x1})
        assert r.status_code == 200, r.text
        path = r.json()["avatar_path"]
        assert "avatars/" + RAVI in path
        me = s.get(f"{BASE_URL}/api/auth/me").json()
        me_user = me.get("user", me)
        assert me_user.get("avatar_path") == path
        f = s.get(f"{BASE_URL}/api/files/{path}")
        assert f.status_code == 200 and len(f.content) > 10
        d = s.delete(f"{BASE_URL}/api/profile/me/avatar")
        assert d.status_code == 200
        assert s.get(f"{BASE_URL}/api/profile/me").json().get("avatar_path") is None


# ---- bank change ----
class TestBank:
    def test_validation(self):
        s = c(EMP)
        bad = [
            {"account_holder": "Ravi", "account_number": "1234", "ifsc": "SBIN0001234"},
            {"account_holder": "Ravi", "account_number": "123456789012", "ifsc": "SBIN1001234"},
            {"account_holder": "  ", "account_number": "123456789012", "ifsc": "SBIN0001234"},
        ]
        for b in bad:
            assert s.post(f"{BASE_URL}/api/profile/me/bank", json=b).status_code == 400

    def test_request_supersede_withdraw(self, snapshot):
        s = c(EMP)
        before = s.get(f"{BASE_URL}/api/profile/me").json().get("bank")
        r1 = s.post(f"{BASE_URL}/api/profile/me/bank", json={"account_holder": "Ravi Kumar", "account_number": "111122223333", "ifsc": "hdfc0001111"})
        assert r1.status_code == 200
        assert r1.json()["request"]["ifsc"] == "HDFC0001111"
        r2 = s.post(f"{BASE_URL}/api/profile/me/bank", json={"account_holder": "Ravi Kumar", "account_number": "4444 5555 6666", "ifsc": "ICIC0002222", "bank_name": "ICICI"})
        assert r2.status_code == 200
        assert snapshot.bank_change_requests.find_one({"request_id": r1.json()["request"]["request_id"]})["status"] == "superseded"
        p = s.get(f"{BASE_URL}/api/profile/me").json()
        assert p["pending_bank"]["account_number"] == "444455556666"
        assert p.get("bank") == before
        assert s.delete(f"{BASE_URL}/api/profile/me/bank").status_code == 200
        assert s.delete(f"{BASE_URL}/api/profile/me/bank").status_code == 404
        assert s.get(f"{BASE_URL}/api/profile/me").json()["pending_bank"] is None

    def test_admin_list_and_approve(self):
        s = c(EMP)
        rid = s.post(f"{BASE_URL}/api/profile/me/bank", json={"account_holder": "Ravi Kumar", "account_number": "999988887777", "ifsc": "UTIB0003333"}).json()["request"]["request_id"]
        assert c(SUB).get(f"{BASE_URL}/api/admin/bank-requests").status_code == 403
        assert c(EMP).get(f"{BASE_URL}/api/admin/bank-requests").status_code == 403
        lst = c(ADMIN).get(f"{BASE_URL}/api/admin/bank-requests").json()["requests"]
        item = next(i for i in lst if i["request_id"] == rid)
        assert "current_bank" in item
        assert c(SUB).post(f"{BASE_URL}/api/admin/bank-requests/{rid}/decide", json={"status": "approved"}).status_code == 403
        assert c(ADMIN).post(f"{BASE_URL}/api/admin/bank-requests/{rid}/decide", json={"status": "maybe"}).status_code == 400
        r = c(ADMIN).post(f"{BASE_URL}/api/admin/bank-requests/{rid}/decide", json={"status": "approved", "note": "ok"})
        assert r.status_code == 200
        again = c(ADMIN).post(f"{BASE_URL}/api/admin/bank-requests/{rid}/decide", json={"status": "rejected"})
        assert again.status_code == 400 and again.json()["detail"] == "Already decided"
        p = s.get(f"{BASE_URL}/api/profile/me").json()
        assert p["bank"]["account_number"] == "999988887777" and p["bank"]["approved_by"]
        assert p["last_bank_decision"]["status"] == "approved"

    def test_reject_keeps_bank(self):
        s = c(EMP)
        before = s.get(f"{BASE_URL}/api/profile/me").json()["bank"]
        rid = s.post(f"{BASE_URL}/api/profile/me/bank", json={"account_holder": "X", "account_number": "121212121212", "ifsc": "SBIN0009999"}).json()["request"]["request_id"]
        r = c(ADMIN).post(f"{BASE_URL}/api/admin/bank-requests/{rid}/decide", json={"status": "rejected", "note": "wrong ifsc"})
        assert r.status_code == 200
        p = s.get(f"{BASE_URL}/api/profile/me").json()
        assert p["bank"]["account_number"] == before["account_number"]
        assert p["last_bank_decision"]["status"] == "rejected" and p["last_bank_decision"]["note"] == "wrong ifsc"

    def test_decide_404(self):
        assert c(ADMIN).post(f"{BASE_URL}/api/admin/bank-requests/bank_nope/decide", json={"status": "approved"}).status_code == 404


# ---- admin view/edit employee profile ----
class TestAdminProfile:
    def test_admin_any(self):
        r = c(ADMIN).get(f"{BASE_URL}/api/admin/employees/{ANITA}/profile")
        assert r.status_code == 200 and r.json()["user_id"] == ANITA

    def test_sub_in_scope(self):
        r = c(SUB).get(f"{BASE_URL}/api/admin/employees/{RAVI}/profile")
        assert r.status_code == 200 and r.json()["uan"] == "100123456789"

    def test_sub_out_of_scope(self):
        r = c(SUB).get(f"{BASE_URL}/api/admin/employees/{ANITA}/profile")
        assert r.status_code == 403 and r.json()["detail"] == "This employee is not in your team"
        r = c(SUB).get(f"{BASE_URL}/api/admin/employees/{ADMIN_ID}/profile")
        assert r.status_code == 403

    def test_employee_forbidden(self):
        assert c(EMP).get(f"{BASE_URL}/api/admin/employees/{RAVI}/profile").status_code == 403

    def test_404(self):
        assert c(ADMIN).get(f"{BASE_URL}/api/admin/employees/user_nope/profile").status_code == 404

    def test_manager_edit_personal_not_bank(self):
        r = c(SUB).put(f"{BASE_URL}/api/admin/employees/{RAVI}/profile", json={"esi": "3112345679"})
        assert r.status_code == 200 and r.json()["esi"] == "3112345679"
        r = c(ADMIN).put(f"{BASE_URL}/api/admin/employees/{RAVI}/profile", json={"esi": "3112345678", "bank": {"account_number": "1"}})
        assert r.status_code == 200
        assert r.json()["bank"]["account_number"] != "1"
        assert c(SUB).put(f"{BASE_URL}/api/admin/employees/{ANITA}/profile", json={"esi": "3112345678"}).status_code == 403


# ---- celebrations ----
class TestCelebrations:
    def test_celebrations_shape(self):
        for tok in (EMP, ADMIN, SUB):
            r = c(tok).get(f"{BASE_URL}/api/celebrations")
            assert r.status_code == 200
        d = c(EMP).get(f"{BASE_URL}/api/celebrations").json()
        items = d["celebrations"]
        mine = [i for i in items if i["user_id"] == RAVI]
        kinds = {i["kind"]: i for i in mine}
        assert kinds["birthday"]["days_away"] == 0 and kinds["birthday"]["years"] is None
        assert kinds["birthday"]["is_me"] is True
        assert kinds["work_anniversary"]["years"] >= 1
        assert kinds["wedding_anniversary"]["days_away"] == 3
        assert all(0 <= i["days_away"] <= 7 for i in items)
        assert [i["days_away"] for i in items] == sorted(i["days_away"] for i in items)
        # no birth year leak in birthday record
        assert "1994" not in str(kinds["birthday"])
        assert c(ADMIN).get(f"{BASE_URL}/api/celebrations").json()["celebrations"][0]["is_me"] in (True, False)

    def test_unauth(self):
        assert requests.get(f"{BASE_URL}/api/celebrations").status_code == 401
