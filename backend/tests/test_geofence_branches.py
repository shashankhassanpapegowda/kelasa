"""Iteration 8: Branch geofencing, field staff, employee name/email edit."""
import math
import uuid
import pytest
import requests

from conftest import BASE_URL, TINY_JPEG_B64

ADMIN = "test_session_admin_001"
SUB = "test_session_subadmin_001"
EMP_EMAIL = "emp1.test@gtgroups.local"
EMP_PW = "RaviReset@26"
EMP_ID = "user_testemp01"
ANITA = "user_testemp02"
GEO_SITE = "site_ba19694f88"
GEO_LAT, GEO_LNG, GEO_R = 12.9716, 77.5946, 200
DESC = [0.01] * 128
M_PER_DEG = 111194.93


def client(tok):
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {tok}", "Content-Type": "application/json"})
    return s


def lat_at(dist_m):
    return GEO_LAT + dist_m / M_PER_DEG


@pytest.fixture(scope="module")
def admin():
    return client(ADMIN)


@pytest.fixture(scope="module")
def sub():
    return client(SUB)


@pytest.fixture(scope="module")
def emp(mongo_db):
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": EMP_EMAIL, "password": EMP_PW})
    assert r.status_code == 200, r.text
    c = client(r.json()["session_token"])
    yield c
    # teardown: ensure checked out, field_staff false
    mongo_db.users.update_one({"user_id": EMP_ID}, {"$set": {"field_staff": False}})
    mongo_db.attendance.update_many({"user_id": EMP_ID, "check_out": None},
                                    {"$set": {"check_out": "2026-01-01T00:00:00+00:00", "status": "off_duty"}})


def punch(c, kind, lat, lng, acc=10):
    return c.post(f"{BASE_URL}/api/attendance/{kind}", json={
        "lat": lat, "lng": lng, "accuracy": acc, "descriptor": DESC, "image_b64": TINY_JPEG_B64})


@pytest.fixture(scope="module")
def test_branch(admin, mongo_db):
    name = f"TEST_Branch_{uuid.uuid4().hex[:6]}"
    r = admin.post(f"{BASE_URL}/api/admin/org/sites", json={"name": name})
    assert r.status_code == 200, r.text
    site = r.json()["site"]
    yield site
    mongo_db.sites.delete_many({"name": {"$regex": "^TEST_Branch"}})


# ---------- Geofence info ----------
class TestGeofenceInfo:
    def test_geofence_endpoint(self, emp):
        r = emp.get(f"{BASE_URL}/api/attendance/geofence")
        assert r.status_code == 200
        d = r.json()
        assert d["field_staff"] is False
        assert d["tolerance_m"] == 50
        geo = [b for b in d["branches"] if b["unit_id"] == GEO_SITE]
        assert geo and geo[0]["radius_m"] == GEO_R and geo[0]["lat"] == GEO_LAT


# ---------- Branch PATCH ----------
class TestBranchPatch:
    @pytest.mark.parametrize("body,code", [
        ({"lat": 12.9, "lng": 77.5, "radius_m": 5}, 400),
        ({"lat": 12.9, "lng": 77.5, "radius_m": 20000}, 400),
        ({"lat": 12.9}, 400),
        ({"lat": 100, "lng": 77.5, "radius_m": 100}, 400),
        ({}, 400),
    ])
    def test_validation(self, admin, test_branch, body, code):
        r = admin.patch(f"{BASE_URL}/api/admin/org/sites/{test_branch['unit_id']}", json=body)
        assert r.status_code == code, r.text

    def test_404(self, admin):
        r = admin.patch(f"{BASE_URL}/api/admin/org/sites/site_nope", json={"name": "x"})
        assert r.status_code == 404

    def test_subadmin_forbidden(self, sub, test_branch):
        r = sub.patch(f"{BASE_URL}/api/admin/org/sites/{test_branch['unit_id']}",
                      json={"lat": 12.9, "lng": 77.5, "radius_m": 100})
        assert r.status_code == 403

    def test_set_and_clear_geofence(self, admin, test_branch):
        u = f"{BASE_URL}/api/admin/org/sites/{test_branch['unit_id']}"
        r = admin.patch(u, json={"lat": 13.5, "lng": 77.0, "radius_m": 300, "address": "Somewhere"})
        assert r.status_code == 200, r.text
        s = r.json()["site"]
        assert s["radius_m"] == 300 and s["lat"] == 13.5 and s["address"] == "Somewhere"
        org = admin.get(f"{BASE_URL}/api/admin/org").json()
        assert any(x["unit_id"] == test_branch["unit_id"] and x["radius_m"] == 300 for x in org["sites"])
        r = admin.patch(u, json={"clear_geofence": True})
        assert r.status_code == 200
        assert r.json()["site"]["lat"] is None and r.json()["site"]["radius_m"] is None

    def test_rename_propagates(self, admin, test_branch, mongo_db):
        uid = f"TEST_user_{uuid.uuid4().hex[:6]}"
        mongo_db.users.insert_one({"user_id": uid, "email": f"{uid.lower()}@x.local", "name": "TEST Tmp",
                                   "role": "sub_admin", "site": test_branch["name"],
                                   "managed_sites": ["Other", test_branch["name"]]})
        try:
            new = test_branch["name"] + "_R"
            r = admin.patch(f"{BASE_URL}/api/admin/org/sites/{test_branch['unit_id']}", json={"name": new})
            assert r.status_code == 200, r.text
            u = mongo_db.users.find_one({"user_id": uid})
            assert u["site"] == new
            assert u["managed_sites"] == ["Other", new]
            # duplicate name
            r = admin.patch(f"{BASE_URL}/api/admin/org/sites/{test_branch['unit_id']}", json={"name": "GeoTest HQ"})
            assert r.status_code == 400
            test_branch["name"] = new
        finally:
            mongo_db.users.delete_one({"user_id": uid})


# ---------- Punch enforcement ----------
class TestPunchEnforcement:
    def test_outside_blocked(self, emp, mongo_db):
        assert not mongo_db.attendance.find_one({"user_id": EMP_ID, "check_out": None}), "Ravi already on duty"
        r = punch(emp, "checkin", lat_at(2000), GEO_LNG)
        assert r.status_code == 403
        assert "outside GeoTest HQ" in r.json()["detail"] or "outside" in r.json()["detail"]

    def test_accuracy_slack_capped(self, emp):
        # 260 m from centre: gap 60 > min(1000,50) -> blocked
        r = punch(emp, "checkin", lat_at(260), GEO_LNG, acc=1000)
        assert r.status_code == 403, r.text

    def test_inside_with_slack_allowed_and_branch_stored(self, emp, mongo_db):
        # 235 m: gap 35 <= min(40,50)
        r = punch(emp, "checkin", lat_at(235), GEO_LNG, acc=40)
        assert r.status_code == 200, r.text
        rec = mongo_db.attendance.find_one({"record_id": r.json()["record_id"]})
        assert rec["check_in_branch"] == "GeoTest HQ"

    def test_checkout_outside_blocked_then_inside_ok(self, emp, mongo_db):
        r = punch(emp, "checkout", lat_at(5000), GEO_LNG)
        assert r.status_code == 403
        assert "punch out" in r.json()["detail"]
        r = punch(emp, "checkout", lat_at(50), GEO_LNG)
        assert r.status_code == 200, r.text
        rec = mongo_db.attendance.find_one({"user_id": EMP_ID}, sort=[("check_in", -1)])
        assert rec["check_out_branch"] == "GeoTest HQ"

    def test_any_branch_circle(self, admin, emp, test_branch, mongo_db):
        u = f"{BASE_URL}/api/admin/org/sites/{test_branch['unit_id']}"
        assert admin.patch(u, json={"lat": 15.0, "lng": 75.0, "radius_m": 100}).status_code == 200
        try:
            r = punch(emp, "checkin", 15.0003, 75.0)
            assert r.status_code == 200, r.text
            rec = mongo_db.attendance.find_one({"record_id": r.json()["record_id"]})
            assert rec["check_in_branch"] == test_branch["name"]
            assert punch(emp, "checkout", 15.0, 75.0).status_code == 200
        finally:
            admin.patch(u, json={"clear_geofence": True})


# ---------- Field staff ----------
class TestFieldStaff:
    def test_subadmin_scope(self, sub):
        r = sub.patch(f"{BASE_URL}/api/admin/employees/{ANITA}/field_staff", json={"field_staff": True})
        assert r.status_code == 403

    def test_field_staff_bypass(self, sub, emp, admin, mongo_db):
        r = sub.patch(f"{BASE_URL}/api/admin/employees/{EMP_ID}/field_staff", json={"field_staff": True})
        assert r.status_code == 200, r.text
        try:
            assert emp.get(f"{BASE_URL}/api/attendance/geofence").json()["field_staff"] is True
            emps = admin.get(f"{BASE_URL}/api/admin/employees").json()["employees"]
            assert [e for e in emps if e["user_id"] == EMP_ID][0].get("field_staff") is True
            r = punch(emp, "checkin", 28.6, 77.2)
            assert r.status_code == 200, r.text
            assert punch(emp, "checkout", 28.6, 77.2).status_code == 200
        finally:
            r = admin.patch(f"{BASE_URL}/api/admin/employees/{EMP_ID}/field_staff", json={"field_staff": False})
            assert r.status_code == 200
        assert punch(emp, "checkin", 28.6, 77.2).status_code == 403


# ---------- No geofence anywhere ----------
class TestNoGeofence:
    def test_punch_anywhere_when_none_pinned(self, admin, emp):
        u = f"{BASE_URL}/api/admin/org/sites/{GEO_SITE}"
        assert admin.patch(u, json={"clear_geofence": True}).status_code == 200
        try:
            assert emp.get(f"{BASE_URL}/api/attendance/geofence").json()["branches"] == []
            assert punch(emp, "checkin", 28.6, 77.2).status_code == 200
            assert punch(emp, "checkout", 28.6, 77.2).status_code == 200
        finally:
            r = admin.patch(u, json={"lat": GEO_LAT, "lng": GEO_LNG, "radius_m": GEO_R})
            assert r.status_code == 200


# ---------- Name / email edit ----------
class TestEmployeeEmailEdit:
    def test_invalid_and_duplicate(self, admin):
        u = f"{BASE_URL}/api/admin/employees/{ANITA}/assignment"
        r = admin.patch(u, json={"email": "not-an-email"})
        assert r.status_code == 400 and "valid email" in r.json()["detail"]
        r = admin.patch(u, json={"email": EMP_EMAIL.upper()})
        assert r.status_code == 400 and r.json()["detail"] == "Another employee already uses this email"
        r = admin.patch(u, json={"name": "   "})
        assert r.status_code == 400

    def test_change_email_and_login(self, admin, mongo_db):
        email = f"test_{uuid.uuid4().hex[:6]}@gtgroups.local"
        r = admin.post(f"{BASE_URL}/api/admin/employees",
                       json={"name": "TEST Mailer", "email": email, "password": "TestPass@123"})
        assert r.status_code == 200, r.text
        uid = r.json()["employee"]["user_id"]
        try:
            new_email = "TEST_New_" + email
            r = admin.patch(f"{BASE_URL}/api/admin/employees/{uid}/assignment",
                            json={"name": "TEST Mailer Renamed", "email": new_email})
            assert r.status_code == 200, r.text
            assert r.json()["employee"]["email"] == new_email.lower()
            assert r.json()["employee"]["name"] == "TEST Mailer Renamed"
            r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": new_email, "password": "TestPass@123"})
            assert r.status_code == 200, r.text
            r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": "TestPass@123"})
            assert r.status_code == 401
        finally:
            admin.delete(f"{BASE_URL}/api/admin/employees/{uid}")
            mongo_db.login_attempts.delete_many({})

    def test_subadmin_cannot_edit_out_of_scope(self, sub):
        r = sub.patch(f"{BASE_URL}/api/admin/employees/{ANITA}/assignment", json={"email": "zz@zz.com"})
        assert r.status_code == 403
