"""Iteration 9: Leaving-area alerts + Branch attendance report + punches CSV."""
import csv
import io
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
INSIDE = (12.9720, 77.5946)
OUTSIDE = (12.99, 77.5946)
OUTSIDE2 = (12.995, 77.5946)
DESC = [0.01] * 128


def client(tok):
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {tok}", "Content-Type": "application/json"})
    return s


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
    mongo_db.users.update_one({"user_id": EMP_ID}, {"$set": {"field_staff": False}})
    mongo_db.sites.update_one({"unit_id": GEO_SITE}, {"$set": {"radius_m": 200}})


def punch(c, kind, lat, lng, acc=10):
    return c.post(f"{BASE_URL}/api/attendance/{kind}", json={
        "lat": lat, "lng": lng, "accuracy": acc, "descriptor": DESC, "image_b64": TINY_JPEG_B64})


def ping(c, pt, acc=10):
    return c.post(f"{BASE_URL}/api/location/ping", json={"lat": pt[0], "lng": pt[1], "accuracy": acc})


def active_for(admin_c, uid=EMP_ID):
    r = admin_c.get(f"{BASE_URL}/api/admin/geofence-alerts")
    assert r.status_code == 200, r.text
    d = r.json()
    return [a for a in d["active"] if a["user_id"] == uid], d


def ensure_on_duty(emp, mongo_db):
    rec = mongo_db.attendance.find_one({"user_id": EMP_ID, "check_out": None})
    if not rec:
        r = punch(emp, "checkin", *INSIDE)
        assert r.status_code == 200, r.text
        rec = mongo_db.attendance.find_one({"user_id": EMP_ID, "check_out": None})
    if rec.get("on_break"):
        mongo_db.attendance.update_one({"record_id": rec["record_id"]}, {"$set": {"on_break": False}})
    return rec


class TestZoneAlerts:
    # Alert lifecycle: create -> update (no dup) -> resolve inside
    def test_lifecycle(self, admin, emp, mongo_db):
        rec = ensure_on_duty(emp, mongo_db)
        assert ping(emp, INSIDE).status_code == 200
        mine, _ = active_for(admin)
        assert mine == [], "inside ping should resolve any open alert"
        r = ping(emp, OUTSIDE, acc=20)
        assert r.status_code == 200 and r.json()["ok"] is True
        mine, _ = active_for(admin)
        assert len(mine) == 1
        a = mine[0]
        for k in ("name", "distance_m", "nearest_branch", "created_at", "last_seen_at"):
            assert k in a
        assert a["name"] == "Ravi Kumar" and a["nearest_branch"] == "GeoTest HQ"
        assert 1800 <= a["distance_m"] <= 1900
        assert a["acknowledged_at"] is None and a["record_id"] == rec["record_id"]
        # live outside_zone
        live = admin.get(f"{BASE_URL}/api/admin/live").json()["employees"]
        me = [e for e in live if e["user_id"] == EMP_ID][0]
        assert me["outside_zone"] is True
        # second outside ping updates same alert
        assert ping(emp, OUTSIDE2).status_code == 200
        mine2, _ = active_for(admin)
        assert len(mine2) == 1 and mine2[0]["alert_id"] == a["alert_id"]
        assert mine2[0]["distance_m"] > a["distance_m"]
        assert mine2[0]["last_seen_at"] >= a["last_seen_at"]
        assert mongo_db.geofence_alerts.count_documents({"record_id": rec["record_id"], "resolved_at": None}) == 1
        # back inside resolves
        assert ping(emp, INSIDE).status_code == 200
        mine3, d = active_for(admin)
        assert mine3 == []
        rec_alert = [x for x in d["recent"] if x["alert_id"] == a["alert_id"]]
        assert rec_alert and rec_alert[0]["resolved_reason"] == "back inside GeoTest HQ"
        live = admin.get(f"{BASE_URL}/api/admin/live").json()["employees"]
        assert [e for e in live if e["user_id"] == EMP_ID][0]["outside_zone"] is False

    # Ack: admin ok, 404 unknown, sub-admin in-scope ok, out-of-scope 403
    def test_ack(self, admin, sub, emp, mongo_db):
        ensure_on_duty(emp, mongo_db)
        ping(emp, OUTSIDE)
        mine, _ = active_for(admin)
        aid = mine[0]["alert_id"]
        r = sub.post(f"{BASE_URL}/api/admin/geofence-alerts/{aid}/ack")
        assert r.status_code == 200, r.text
        doc = mongo_db.geofence_alerts.find_one({"alert_id": aid})
        assert doc["acknowledged_at"] and doc["acknowledged_by"] == "Test SubAdmin"
        assert admin.post(f"{BASE_URL}/api/admin/geofence-alerts/{aid}/ack").status_code == 200
        assert admin.post(f"{BASE_URL}/api/admin/geofence-alerts/gfa_nope000/ack").status_code == 404
        # out-of-scope alert (Anita) inserted directly
        fake = f"gfa_TEST{uuid.uuid4().hex[:8]}"
        mongo_db.geofence_alerts.insert_one({
            "alert_id": fake, "user_id": ANITA, "name": "Anita Shetty", "record_id": "att_TEST_x",
            "date": "2026-01-01", "distance_m": 10, "nearest_branch": "GeoTest HQ",
            "created_at": "2026-01-01T00:00:00+00:00", "last_seen_at": "2026-01-01T00:00:00+00:00",
            "resolved_at": None, "acknowledged_by": None, "acknowledged_at": None})
        try:
            assert sub.post(f"{BASE_URL}/api/admin/geofence-alerts/{fake}/ack").status_code == 403
            sub_list = sub.get(f"{BASE_URL}/api/admin/geofence-alerts").json()["active"]
            assert all(x["user_id"] != ANITA for x in sub_list)
            adm_list = admin.get(f"{BASE_URL}/api/admin/geofence-alerts").json()["active"]
            assert any(x["alert_id"] == fake for x in adm_list)
        finally:
            mongo_db.geofence_alerts.delete_one({"alert_id": fake})

    # Checkout resolves open alerts
    def test_checkout_resolves(self, admin, emp, mongo_db):
        rec = ensure_on_duty(emp, mongo_db)
        ping(emp, OUTSIDE)
        assert len(active_for(admin)[0]) == 1
        r = punch(emp, "checkout", *INSIDE)
        assert r.status_code == 200, r.text
        # the inside checkout didn't ping - alert resolved by checkout
        doc = mongo_db.geofence_alerts.find_one({"record_id": rec["record_id"]}, sort=[("created_at", -1)])
        assert doc["resolved_at"] is not None
        assert doc["resolved_reason"] == "checked out"
        assert active_for(admin)[0] == []

    # Field staff never trigger alerts
    def test_field_staff_no_alert(self, admin, emp, mongo_db):
        mongo_db.users.update_one({"user_id": EMP_ID}, {"$set": {"field_staff": True}})
        try:
            rec = ensure_on_duty(emp, mongo_db)
            assert ping(emp, OUTSIDE).status_code == 200
            assert mongo_db.geofence_alerts.count_documents({"record_id": rec["record_id"], "resolved_at": None}) == 0
        finally:
            mongo_db.users.update_one({"user_id": EMP_ID}, {"$set": {"field_staff": False}})

    # No geofenced branches -> no alerts
    def test_no_geofenced_branches(self, admin, emp, mongo_db):
        rec = ensure_on_duty(emp, mongo_db)
        ping(emp, INSIDE)
        mongo_db.sites.update_one({"unit_id": GEO_SITE}, {"$set": {"radius_m": 0}})
        try:
            assert ping(emp, OUTSIDE).status_code == 200
            assert mongo_db.geofence_alerts.count_documents({"record_id": rec["record_id"], "resolved_at": None}) == 0
        finally:
            mongo_db.sites.update_one({"unit_id": GEO_SITE}, {"$set": {"radius_m": 200}})
        # finish: checkout inside
        assert punch(emp, "checkout", *INSIDE).status_code == 200


class TestBranchReport:
    def _date(self, mongo_db):
        return mongo_db.attendance.find_one({"user_id": EMP_ID}, sort=[("check_in", -1)])["date"]

    # GET /admin/reports/branches structure + scope
    def test_branch_report(self, admin, sub, mongo_db):
        d = self._date(mongo_db)
        r = admin.get(f"{BASE_URL}/api/admin/reports/branches", params={"from": d, "to": d})
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["from"] == d and isinstance(j["zone_alerts"], int) and j["zone_alerts"] >= 1
        ravi = [p for p in j["punches"] if p["user_id"] == EMP_ID]
        assert ravi
        p = ravi[-1]
        for k in ("record_id", "check_in", "check_out", "check_in_branch", "check_out_branch", "home_branch", "field_staff"):
            assert k in p
        assert len(p["check_in"]) == 5 and p["check_in"][2] == ":"
        assert any(x["check_in_branch"] == "GeoTest HQ" for x in ravi)
        assert p["home_branch"] == "Bengaluru HQ"
        rs = sub.get(f"{BASE_URL}/api/admin/reports/branches", params={"from": d, "to": d})
        assert rs.status_code == 200
        assert all(x["user_id"] != ANITA for x in rs.json()["punches"])
        assert requests.get(f"{BASE_URL}/api/admin/reports/branches", params={"from": d, "to": d}).status_code == 401

    # punches.csv bearer + ?auth=
    def test_punches_csv(self, admin, mongo_db):
        d = self._date(mongo_db)
        r = admin.get(f"{BASE_URL}/api/admin/reports/punches.csv", params={"from": d, "to": d})
        assert r.status_code == 200 and "text/csv" in r.headers["content-type"]
        rows = list(csv.reader(io.StringIO(r.text)))
        assert rows[0] == ["Date", "Employee", "Email", "Home Branch", "Department", "Field Staff",
                           "Punch In", "Punch In Branch", "Punch Out", "Punch Out Branch", "Net Work (min)", "Late (min)"]
        assert any(row[1] == "Ravi Kumar" and row[7] == "GeoTest HQ" for row in rows[1:])
        r2 = requests.get(f"{BASE_URL}/api/admin/reports/punches.csv", params={"from": d, "to": d, "auth": ADMIN})
        assert r2.status_code == 200 and r2.text.startswith("Date,")
        assert requests.get(f"{BASE_URL}/api/admin/reports/punches.csv", params={"from": d, "to": d}).status_code == 401
        emp_tok = "test_session_emp_001"
        assert requests.get(f"{BASE_URL}/api/admin/reports/punches.csv",
                            params={"from": d, "to": d, "auth": emp_tok}).status_code in (401, 403)

    # reports.csv new columns + punch_branches on /admin/reports
    def test_reports_csv_cols(self, admin, mongo_db):
        d = self._date(mongo_db)
        r = admin.get(f"{BASE_URL}/api/admin/reports.csv", params={"from": d, "to": d})
        assert r.status_code == 200
        rows = list(csv.reader(io.StringIO(r.text)))
        assert rows[0][3] == "Home Branch" and rows[0][4] == "Punched At"
        ravi = [x for x in rows[1:] if x[0] == "Ravi Kumar"][0]
        assert "GeoTest HQ" in ravi[4]
        j = admin.get(f"{BASE_URL}/api/admin/reports", params={"from": d, "to": d})
        assert j.status_code == 200, j.text
        body = j.json()
        rws = body["rows"] if isinstance(body, dict) else body
        rr = [x for x in rws if x["user_id"] == EMP_ID][0]
        assert "GeoTest HQ (" in rr["punch_branches"]
