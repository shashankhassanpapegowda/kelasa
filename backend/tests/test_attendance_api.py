"""Backend API tests for Attendance + Face Recognition + Location Accuracy."""
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

    def test_face_status_no_auth(self, anon_client, base_url):
        r = anon_client.get(f"{base_url}/api/face/status")
        assert r.status_code == 401

    def test_auth_me_admin_has_face_enrolled_but_no_descriptor(self, admin_client, base_url):
        r = admin_client.get(f"{base_url}/api/auth/me")
        assert r.status_code == 200
        data = r.json()
        assert data["role"] == "admin"
        assert data["face_enrolled"] is True
        assert "face_descriptor" not in data, "descriptor must never be returned"
        assert "_id" not in data


# ---------- Admin RBAC ----------
class TestAdminEndpoints:
    def test_stats_admin(self, admin_client, base_url):
        r = admin_client.get(f"{base_url}/api/admin/stats")
        assert r.status_code == 200
        for k in ("total_employees", "on_duty", "today_checkins", "total_work_minutes_today"):
            assert k in r.json()

    def test_employees_admin_includes_face_fields(self, admin_client, base_url):
        r = admin_client.get(f"{base_url}/api/admin/employees")
        assert r.status_code == 200
        emps = r.json()["employees"]
        assert isinstance(emps, list) and len(emps) > 0
        # descriptor must NEVER leak for any user
        for e in emps:
            assert "face_descriptor" not in e, "descriptor leak in /admin/employees"
            assert "today_minutes" in e
            assert "today_sessions" in e
        # For TEST_ seeded users, face_enrolled and face_photo_path fields must exist
        seeded = [e for e in emps if e["user_id"].startswith("TEST_")]
        assert len(seeded) >= 1
        for e in seeded:
            assert "face_enrolled" in e, "seeded user missing face_enrolled"

    def test_attendance_admin(self, admin_client, base_url):
        r = admin_client.get(f"{base_url}/api/admin/attendance")
        assert r.status_code == 200
        assert "records" in r.json()

    def test_stats_forbidden_for_employee(self, employee_client, base_url):
        r = employee_client.get(f"{base_url}/api/admin/stats")
        assert r.status_code == 403


# ---------- Face Enrollment ----------
class TestFaceEnrollment:
    def test_face_status_unenrolled(self, unenrolled_client, base_url):
        r = unenrolled_client.get(f"{base_url}/api/face/status")
        assert r.status_code == 200
        assert r.json()["enrolled"] is False

    def test_enroll_invalid_descriptor_length(self, unenrolled_client, base_url, tiny_jpeg_b64):
        r = unenrolled_client.post(f"{base_url}/api/face/enroll",
                                   json={"descriptor": [0.0] * 64, "image_b64": tiny_jpeg_b64})
        assert r.status_code == 400

    def test_enroll_success_and_status_updated(self, unenrolled_client, base_url, tiny_jpeg_b64, mongo_db):
        descriptor = [0.1] * 128
        r = unenrolled_client.post(f"{base_url}/api/face/enroll",
                                   json={"descriptor": descriptor, "image_b64": tiny_jpeg_b64})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["photo_path"].endswith(".jpg")

        # Verify /face/status now true
        r2 = unenrolled_client.get(f"{base_url}/api/face/status")
        assert r2.status_code == 200
        assert r2.json()["enrolled"] is True

        # Verify /auth/me reflects face_enrolled and does NOT include descriptor
        r3 = unenrolled_client.get(f"{base_url}/api/auth/me")
        assert r3.status_code == 200
        me = r3.json()
        assert me["face_enrolled"] is True
        assert "face_descriptor" not in me

        # DB has descriptor + photo path
        u = mongo_db.users.find_one({"user_id": "TEST_user_emp_noface"})
        assert u["face_enrolled"] is True
        assert len(u["face_descriptor"]) == 128
        assert u["face_photo_path"] is not None

        # File serving auth: no auth -> 401
        path = body["photo_path"]
        import requests as _r
        anon = _r.get(f"{base_url}/api/files/{path}")
        assert anon.status_code == 401

        # With auth: 200 + image bytes
        good = unenrolled_client.get(f"{base_url}/api/files/{path}")
        assert good.status_code == 200
        assert len(good.content) > 100
        assert good.headers.get("content-type", "").startswith("image/")

    def test_admin_reset_face(self, admin_client, base_url, mongo_db):
        # Reset the just-enrolled employee's face
        r = admin_client.delete(f"{base_url}/api/admin/employees/TEST_user_emp_noface/face")
        assert r.status_code == 200
        u = mongo_db.users.find_one({"user_id": "TEST_user_emp_noface"})
        assert u["face_enrolled"] is False
        assert u["face_descriptor"] is None
        assert u["face_photo_path"] is None


# ---------- Attendance Flow (face + accuracy) ----------
class TestAttendanceFlow:
    def test_checkin_without_face_enrollment(self, unenrolled_client, base_url, tiny_jpeg_b64, mongo_db):
        # reset face status (in case prior test enrolled)
        mongo_db.users.update_one({"user_id": "TEST_user_emp_noface"},
                                  {"$set": {"face_enrolled": False, "face_descriptor": None}})
        r = unenrolled_client.post(f"{base_url}/api/attendance/checkin", json={
            "lat": 12.97, "lng": 77.59, "accuracy": 20,
            "descriptor": [0.0] * 128, "image_b64": tiny_jpeg_b64
        })
        assert r.status_code == 400
        assert "not enrolled" in r.json()["detail"].lower()

    def test_full_checkin_ping_checkout_flow(self, employee_client, base_url, mongo_db,
                                             tiny_jpeg_b64, enrolled_descriptor):
        mongo_db.attendance.delete_many({"user_id": "TEST_user_emp01"})
        mongo_db.locations.delete_many({"user_id": "TEST_user_emp01"})

        # Check-in with matching descriptor
        r = employee_client.post(f"{base_url}/api/attendance/checkin", json={
            "lat": 12.9716, "lng": 77.5946, "accuracy": 15,
            "descriptor": enrolled_descriptor, "image_b64": tiny_jpeg_b64
        })
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert "record_id" in body
        assert body["face_distance"] == 0.0
        record_id = body["record_id"]

        # Confirm photo path persisted in DB
        rec = mongo_db.attendance.find_one({"record_id": record_id})
        assert rec["check_in_photo_path"] is not None
        assert rec["check_in_accuracy"] == 15

        # Double check-in -> 400
        r2 = employee_client.post(f"{base_url}/api/attendance/checkin", json={
            "lat": 12.9716, "lng": 77.5946, "accuracy": 15,
            "descriptor": enrolled_descriptor, "image_b64": tiny_jpeg_b64
        })
        assert r2.status_code == 400

        # Good ping (30m) -> stored
        rp = employee_client.post(f"{base_url}/api/location/ping",
                                  json={"lat": 12.9720, "lng": 77.5950, "accuracy": 30})
        assert rp.status_code == 200
        assert rp.json()["ok"] is True

        # Low-accuracy ping (>500m) -> skipped, not stored
        before = mongo_db.locations.count_documents({"user_id": "TEST_user_emp01"})
        rp_low = employee_client.post(f"{base_url}/api/location/ping",
                                      json={"lat": 12.97, "lng": 77.59, "accuracy": 1500})
        assert rp_low.status_code == 200
        data = rp_low.json()
        assert data["ok"] is False
        assert data.get("skipped") is True or data.get("skipped") == "low_accuracy"
        assert data.get("reason") == "low_accuracy"
        after = mongo_db.locations.count_documents({"user_id": "TEST_user_emp01"})
        assert after == before, "low-accuracy ping was incorrectly persisted"

        # Check-out with matching descriptor
        rc = employee_client.post(f"{base_url}/api/attendance/checkout", json={
            "lat": 12.9725, "lng": 77.5955, "accuracy": 20,
            "descriptor": enrolled_descriptor, "image_b64": tiny_jpeg_b64
        })
        assert rc.status_code == 200, rc.text
        cdata = rc.json()
        assert cdata["ok"] is True
        assert isinstance(cdata["duration_minutes"], int)

        rec2 = mongo_db.attendance.find_one({"record_id": record_id})
        assert rec2["check_out_photo_path"] is not None
        assert rec2["check_out_accuracy"] == 20
        assert rec2["check_out"] is not None

    def test_checkin_mismatched_descriptor(self, employee_client, base_url, mongo_db,
                                            tiny_jpeg_b64):
        mongo_db.attendance.delete_many({"user_id": "TEST_user_emp01"})
        # Far descriptor: enrolled was all 0.0, send all 1.0 -> euclidean = sqrt(128) ~ 11.3 >> 0.55
        bad = [1.0] * 128
        r = employee_client.post(f"{base_url}/api/attendance/checkin", json={
            "lat": 12.97, "lng": 77.59, "accuracy": 15,
            "descriptor": bad, "image_b64": tiny_jpeg_b64
        })
        assert r.status_code == 403
        assert "match" in r.json()["detail"].lower()


# ---------- Admin Inspection (accuracy + photo paths) ----------
class TestAdminInspection:
    def test_admin_attendance_has_photo_and_accuracy(self, admin_client, employee_client,
                                                      base_url, mongo_db, tiny_jpeg_b64,
                                                      enrolled_descriptor):
        # Ensure there's a record
        mongo_db.attendance.delete_many({"user_id": "TEST_user_emp01"})
        employee_client.post(f"{base_url}/api/attendance/checkin", json={
            "lat": 12.9716, "lng": 77.5946, "accuracy": 12,
            "descriptor": enrolled_descriptor, "image_b64": tiny_jpeg_b64
        })
        employee_client.post(f"{base_url}/api/attendance/checkout", json={
            "lat": 12.9720, "lng": 77.5950, "accuracy": 18,
            "descriptor": enrolled_descriptor, "image_b64": tiny_jpeg_b64
        })

        r = admin_client.get(f"{base_url}/api/admin/attendance")
        assert r.status_code == 200
        records = r.json()["records"]
        ours = [x for x in records if x["user_id"] == "TEST_user_emp01"]
        assert len(ours) >= 1
        rec = ours[-1]
        assert rec.get("check_in_photo_path")
        assert rec.get("check_out_photo_path")
        assert rec.get("check_in_accuracy") == 12
        assert rec.get("check_out_accuracy") == 18

    def test_admin_employee_route_includes_accuracy_and_photos(self, admin_client, base_url):
        r = admin_client.get(f"{base_url}/api/admin/employees/TEST_user_emp01/route")
        assert r.status_code == 200
        data = r.json()
        # Pings should carry accuracy
        assert any("accuracy" in p for p in data["pings"])
        # Attendance entries should carry photo paths
        assert any(a.get("check_in_photo_path") for a in data["attendance"])

    def test_location_ping_not_on_duty(self, employee_client, base_url, mongo_db):
        # Ensure no active record
        mongo_db.attendance.delete_many({"user_id": "TEST_user_emp01", "check_out": None})
        r = employee_client.post(f"{base_url}/api/location/ping",
                                 json={"lat": 12.97, "lng": 77.59, "accuracy": 20})
        assert r.status_code == 400
