"""Backend API tests for Attendance & Field Work app."""
import pytest


# ---------- Smoke / Auth ----------
class TestSmokeAndAuth:
    def test_root_api(self, anon_client, base_url):
        r = anon_client.get(f"{base_url}/api/")
        assert r.status_code == 200
        assert r.json().get("status") == "ok"

    def test_auth_me_no_session(self, anon_client, base_url):
        r = anon_client.get(f"{base_url}/api/auth/me")
        assert r.status_code == 401

    def test_auth_session_invalid_id(self, anon_client, base_url):
        r = anon_client.post(f"{base_url}/api/auth/session", json={"session_id": "invalid_xxxxx"})
        assert r.status_code == 401

    def test_auth_me_admin(self, admin_client, base_url):
        r = admin_client.get(f"{base_url}/api/auth/me")
        assert r.status_code == 200
        data = r.json()
        assert data["role"] == "admin"
        assert data["user_id"] == "TEST_user_admin01"
        assert data["email"] == "TEST_admin@gtgroups.local"
        assert "_id" not in data

    def test_auth_me_employee(self, employee_client, base_url):
        r = employee_client.get(f"{base_url}/api/auth/me")
        assert r.status_code == 200
        assert r.json()["role"] == "employee"


# ---------- Admin Authorization ----------
class TestAdminEndpoints:
    def test_stats_admin(self, admin_client, base_url):
        r = admin_client.get(f"{base_url}/api/admin/stats")
        assert r.status_code == 200
        data = r.json()
        for k in ("total_employees", "on_duty", "today_checkins", "total_work_minutes_today"):
            assert k in data

    def test_employees_admin(self, admin_client, base_url):
        r = admin_client.get(f"{base_url}/api/admin/employees")
        assert r.status_code == 200
        data = r.json()
        assert "employees" in data
        assert isinstance(data["employees"], list)

    def test_attendance_admin(self, admin_client, base_url):
        r = admin_client.get(f"{base_url}/api/admin/attendance")
        assert r.status_code == 200
        assert "records" in r.json()

    def test_stats_forbidden_for_employee(self, employee_client, base_url):
        r = employee_client.get(f"{base_url}/api/admin/stats")
        assert r.status_code == 403

    def test_employees_forbidden_for_employee(self, employee_client, base_url):
        r = employee_client.get(f"{base_url}/api/admin/employees")
        assert r.status_code == 403

    def test_attendance_forbidden_for_employee(self, employee_client, base_url):
        r = employee_client.get(f"{base_url}/api/admin/attendance")
        assert r.status_code == 403


# ---------- Attendance flow ----------
class TestAttendanceFlow:
    def test_checkin_then_double_checkin_then_ping_checkout(self, employee_client, base_url, mongo_db):
        # Ensure clean state
        mongo_db.attendance.delete_many({"user_id": "TEST_user_emp01"})
        mongo_db.locations.delete_many({"user_id": "TEST_user_emp01"})

        # Check-in
        r = employee_client.post(f"{base_url}/api/attendance/checkin", json={"lat": 12.9716, "lng": 77.5946})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert "record_id" in body
        record_id = body["record_id"]

        # Second check-in without checkout -> 400
        r2 = employee_client.post(f"{base_url}/api/attendance/checkin", json={"lat": 12.9716, "lng": 77.5946})
        assert r2.status_code == 400

        # Location ping while on duty -> ok
        rp = employee_client.post(f"{base_url}/api/location/ping", json={"lat": 12.9720, "lng": 77.5950, "accuracy": 10})
        assert rp.status_code == 200
        assert rp.json()["ok"] is True

        # Check today: active not null
        rt = employee_client.get(f"{base_url}/api/attendance/today")
        assert rt.status_code == 200
        today_data = rt.json()
        assert today_data["active"] is not None
        assert today_data["active"]["record_id"] == record_id

        # Check-out
        rc = employee_client.post(f"{base_url}/api/attendance/checkout", json={"lat": 12.9725, "lng": 77.5955})
        assert rc.status_code == 200
        cdata = rc.json()
        assert cdata["ok"] is True
        assert "duration_minutes" in cdata
        assert isinstance(cdata["duration_minutes"], int)

        # Location ping while NOT on duty -> 400
        rp2 = employee_client.post(f"{base_url}/api/location/ping", json={"lat": 12.9720, "lng": 77.5950})
        assert rp2.status_code == 400

        # Today after checkout: active is null
        rt2 = employee_client.get(f"{base_url}/api/attendance/today")
        assert rt2.status_code == 200
        td = rt2.json()
        assert td["active"] is None
        assert len(td["today_records"]) >= 1
        assert any(r.get("record_id") == record_id and r.get("check_out") for r in td["today_records"])

        # Location today: should have at least 3 pings (checkin, ping, checkout)
        rl = employee_client.get(f"{base_url}/api/location/today")
        assert rl.status_code == 200
        pings = rl.json()["pings"]
        assert len(pings) >= 3
        # Verify ordered by timestamp
        ts = [p["timestamp"] for p in pings]
        assert ts == sorted(ts)

    def test_checkout_without_checkin(self, employee_client, base_url, mongo_db):
        mongo_db.attendance.delete_many({"user_id": "TEST_user_emp01", "check_out": None})
        # Ensure no active
        r = employee_client.post(f"{base_url}/api/attendance/checkout", json={"lat": 12.9, "lng": 77.5})
        assert r.status_code == 400


# ---------- Admin route/role ----------
class TestAdminRouteAndRole:
    def test_employee_route(self, admin_client, base_url):
        r = admin_client.get(f"{base_url}/api/admin/employees/TEST_user_emp01/route")
        assert r.status_code == 200
        data = r.json()
        assert data["employee"]["user_id"] == "TEST_user_emp01"
        assert "pings" in data
        assert "attendance" in data

    def test_employee_route_not_found(self, admin_client, base_url):
        r = admin_client.get(f"{base_url}/api/admin/employees/nonexistent_user/route")
        assert r.status_code == 404

    def test_role_flip(self, admin_client, base_url, mongo_db):
        # Promote employee to admin
        r = admin_client.patch(f"{base_url}/api/admin/employees/TEST_user_emp01/role", json={"role": "admin"})
        assert r.status_code == 200
        u = mongo_db.users.find_one({"user_id": "TEST_user_emp01"})
        assert u["role"] == "admin"

        # Demote back
        r2 = admin_client.patch(f"{base_url}/api/admin/employees/TEST_user_emp01/role", json={"role": "employee"})
        assert r2.status_code == 200
        u2 = mongo_db.users.find_one({"user_id": "TEST_user_emp01"})
        assert u2["role"] == "employee"

    def test_cannot_demote_self(self, admin_client, base_url):
        r = admin_client.patch(f"{base_url}/api/admin/employees/TEST_user_admin01/role", json={"role": "employee"})
        assert r.status_code == 400

    def test_invalid_role(self, admin_client, base_url):
        r = admin_client.patch(f"{base_url}/api/admin/employees/TEST_user_emp01/role", json={"role": "superuser"})
        assert r.status_code == 400
