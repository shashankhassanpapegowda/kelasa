# Iteration 18: face recognition v2 (3-photo enrol, liveness, anti-impersonation, learning, review, selfie purge)
import os, math, random, uuid, time
from datetime import datetime, timezone, timedelta
import pytest, requests
from pymongo import MongoClient

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = BASE_URL + "/api"
db = MongoClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))["test_database"]
ADMIN = {"Authorization": "Bearer test_session_admin_001"}
SUB = {"Authorization": "Bearer test_session_subadmin_001"}
CRON_SECRET = [l.split("=", 1)[1].strip().strip('"') for l in open("/app/backend/.env") if l.startswith("WEBHOOK_CRON_SECRET=")][0]
JPG = "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/wAALCAABAAEBAREA/8QAFAABAAAAAAAAAAAAAAAAAAAACf/EABQQAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQEAAD8AKp//2Q=="
GEO = {"lat": 12.97, "lng": 77.59, "accuracy": 10, "image_b64": JPG}
LIVE = {"challenge": "blink", "passed": True}
rng = random.Random(2026)


def unit(v):
    n = math.sqrt(sum(x * x for x in v)); return [x / n for x in v]

def rand_unit():
    return unit([rng.gauss(0, 1) for _ in range(128)])

def dist(a, b):
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))

def orth(base):
    r = rand_unit(); d = sum(x * y for x, y in zip(r, base))
    return unit([x - d * y for x, y in zip(r, base)])

def at_distance(base, d, direction=None):
    """unit vector exactly at euclidean distance d from base (along an orthogonal direction)"""
    o = direction or orth(base); th = 2 * math.asin(d / 2)
    return unit([math.cos(th) * b + math.sin(th) * x for b, x in zip(base, o)])

def jitter(v, eps=0.002):
    return unit([x + rng.gauss(0, eps) for x in v])

CREATED_USERS, CREATED_RECORDS = [], []

def mk_user(tag, legacy=None):
    uid = f"user_TEST_face_{tag}_{uuid.uuid4().hex[:6]}"; tok = f"sess_{uid}"
    doc = {"user_id": uid, "email": f"{uid}@example.com", "name": f"TEST_Face {tag}", "role": "employee", "field_staff": True,
           "created_at": datetime.now(timezone.utc).isoformat(), "face_enrolled": bool(legacy)}
    if legacy:
        doc["face_descriptor"] = legacy
    db.users.insert_one(doc)
    db.user_sessions.insert_one({"session_token": tok, "user_id": uid, "created_at": datetime.now(timezone.utc).isoformat(),
                                 "expires_at": datetime(2030, 1, 1, tzinfo=timezone.utc).isoformat()})
    CREATED_USERS.append(uid)
    return uid, {"Authorization": f"Bearer {tok}"}

def enroll(h, base):
    return requests.post(f"{API}/face/enroll", json={"descriptors": [jitter(base) for _ in range(3)], "image_b64": JPG}, headers=h)

def check(h, kind, vec, live=LIVE):
    body = {**GEO, "descriptors": [jitter(vec), jitter(vec)]}
    if live is not None:
        body["liveness"] = live
    return requests.post(f"{API}/attendance/{kind}", json=body, headers=h)

def activity(action, target):
    return db.activity_log.find_one({"action": action, "target_name": target}) or db.activity_logs.find_one({"action": action, "target_name": target})


@pytest.fixture(scope="module", autouse=True)
def cleanup():
    yield
    for u in CREATED_USERS:
        db.users.delete_one({"user_id": u}); db.user_sessions.delete_many({"user_id": u}); db.face_profiles.delete_many({"user_id": u})
        db.attendance.delete_many({"user_id": u}); db.locations.delete_many({"user_id": u})
    for r in CREATED_RECORDS:
        db.attendance.delete_one({"record_id": r})


@pytest.fixture(scope="module")
def world():
    A_base = rand_unit()
    dirAB = orth(A_base)
    B_base = at_distance(A_base, 0.8, dirAB)       # far enough to enrol separately
    A, ha = mk_user("A"); B, hb = mk_user("B")
    return dict(A_base=A_base, B_base=B_base, dirAB=dirAB, A=A, ha=ha, B=B, hb=hb)


# --- Enrolment
class TestEnroll:
    def test_fewer_than_3(self, world):
        r = requests.post(f"{API}/face/enroll", json={"descriptors": [jitter(world["A_base"])] * 2, "image_b64": JPG}, headers=world["ha"])
        assert r.status_code == 400, r.text

    def test_inconsistent(self, world):
        a = world["A_base"]
        r = requests.post(f"{API}/face/enroll", json={"descriptors": [a, a, at_distance(a, 0.9)], "image_b64": JPG}, headers=world["ha"])
        assert r.status_code == 400 and "same person" in r.text

    def test_success(self, world):
        r = enroll(world["ha"], world["A_base"]); assert r.status_code == 200, r.text
        prof = db.face_profiles.find_one({"user_id": world["A"]})
        assert len(prof["templates"]) == 3 and prof["learned"] == []
        u = db.users.find_one({"user_id": world["A"]})
        assert u["face_enrolled"] is True and u.get("face_photo_path")

    def test_already_enrolled(self, world):
        assert enroll(world["ha"], world["A_base"]).status_code == 403

    def test_duplicate_face_other_employee(self, world):
        r = enroll(world["hb"], at_distance(world["A_base"], 0.2)); assert r.status_code == 409, r.text
        assert activity("face_enroll_blocked", "TEST_Face B")
        assert not db.face_profiles.find_one({"user_id": world["B"]})

    def test_enroll_B(self, world):
        assert enroll(world["hb"], world["B_base"]).status_code == 200


# --- Check-in / check-out
class TestCheck:
    def test_missing_liveness(self, world):
        r = check(world["ha"], "checkin", world["A_base"], live=None); assert r.status_code == 400 and "Live" in r.text
        r = check(world["ha"], "checkin", world["A_base"], live={"challenge": "blink", "passed": False}); assert r.status_code == 400

    def test_two_faces(self, world):
        body = {**GEO, "liveness": LIVE, "descriptors": [world["A_base"], world["B_base"]]}
        r = requests.post(f"{API}/attendance/checkin", json=body, headers=world["ha"]); assert r.status_code == 400 and "changed" in r.text

    def test_single_frame_rejected(self, world):
        body = {**GEO, "liveness": LIVE, "descriptors": [world["A_base"]]}
        assert requests.post(f"{API}/attendance/checkin", json=body, headers=world["ha"]).status_code == 400

    def test_legacy_descriptor_payload_rejected(self, world):
        body = {**GEO, "liveness": LIVE, "descriptor": world["A_base"]}
        assert requests.post(f"{API}/attendance/checkin", json=body, headers=world["ha"]).status_code in (400, 422)

    def test_non_matching(self, world):
        r = check(world["ha"], "checkin", at_distance(world["A_base"], 0.75)); assert r.status_code == 403 and "doesn't match" in r.text

    def test_closer_to_other_employee(self, world):
        a = world["A_base"]
        p = at_distance(a, 0.5, world["dirAB"])  # 0.5 from A, ~0.32 from B
        assert dist(p, world["B_base"]) < 0.4
        r = check(world["ha"], "checkin", p); assert r.status_code == 403 and "different employee" in r.text
        assert activity("face_blocked", "TEST_Face A")
        assert db.attendance.count_documents({"user_id": world["A"]}) == 0

    def test_borderline_flagged(self, world):
        r = check(world["ha"], "checkin", at_distance(world["A_base"], 0.5)); assert r.status_code == 200, r.text
        j = r.json(); assert j["face_review"] is True and 0.45 < j["face_distance"] <= 0.55
        rec = db.attendance.find_one({"record_id": j["record_id"]})
        assert rec["check_in_face_review"] is True and "borderline" in rec["check_in_face_review_reason"]
        assert rec["check_in_liveness"] == "blink" and isinstance(rec["check_in_face_distance"], float)
        assert db.face_profiles.find_one({"user_id": world["A"]})["learned"] == []   # flagged -> not learned
        world["flag_rec"] = j["record_id"]

    def test_clean_checkout_learns(self, world):
        r = check(world["ha"], "checkout", world["A_base"], live={"challenge": "turn", "passed": True, "low_light": True})
        assert r.status_code == 200, r.text
        rec = db.attendance.find_one({"record_id": world["flag_rec"]})
        assert rec["check_out_face_review"] is False and rec["check_out_liveness"] == "turn" and rec["check_out_low_light"] is True
        assert rec["check_out_face_distance"] <= 0.40
        assert len(db.face_profiles.find_one({"user_id": world["A"]})["learned"]) == 1

    def test_learned_capped_at_10(self, world):
        for _ in range(11):
            assert check(world["ha"], "checkin", world["A_base"]).status_code == 200
            assert check(world["ha"], "checkout", world["A_base"]).status_code == 200
        assert len(db.face_profiles.find_one({"user_id": world["A"]})["learned"]) == 10


# --- Legacy single-descriptor users (migration)
class TestMigration:
    def test_ravi_migrated(self):
        u = db.users.find_one({"user_id": "user_testemp01"}); p = db.face_profiles.find_one({"user_id": "user_testemp01"})
        assert p and p["templates"][0] == u["face_descriptor"]

    def test_legacy_user_can_check_in(self):
        base = rand_unit(); uid, h = mk_user("legacy", legacy=base)
        r = check(h, "checkin", base); assert r.status_code == 200, r.text
        assert check(h, "checkout", base).status_code == 200


# --- Admin reset & face-check review
class TestAdmin:
    def test_face_checks_admin(self, world):
        r = requests.get(f"{API}/admin/face-checks", params={"flagged": "true", "person": world["A"]}, headers=ADMIN)
        assert r.status_code == 200; j = r.json()
        assert j["keep_days"] == 7 and j["pending_review"] >= 1 and j["total"] == 1
        it = j["items"][0]
        assert it["record_id"] == world["flag_rec"] and it["check_in_photo_path"] and it["enrollment_photo_path"] and it["check_out_photo_path"]
        all_ = requests.get(f"{API}/admin/face-checks", params={"person": world["A"], "page_size": 5, "page": 2}, headers=ADMIN).json()
        assert all_["total"] == 12 and len(all_["items"]) == 5
        today = db.attendance.find_one({"record_id": world["flag_rec"]})["date"]
        assert requests.get(f"{API}/admin/face-checks", params={"person": world["A"], "from": "2000-01-01", "to": "2000-01-02"}, headers=ADMIN).json()["total"] == 0
        assert requests.get(f"{API}/admin/face-checks", params={"person": world["A"], "from": today, "to": today}, headers=ADMIN).json()["total"] == 12

    def test_subadmin_scope(self, world):
        r = requests.get(f"{API}/admin/face-checks", params={"person": world["A"]}, headers=SUB)
        assert r.status_code == 200 and r.json()["total"] == 0
        r = requests.post(f"{API}/admin/face-checks/{world['flag_rec']}", json={"kind": "in", "decision": "ok"}, headers=SUB)
        assert r.status_code == 403
        r = requests.get(f"{API}/admin/face-checks", headers={"Authorization": world["ha"]["Authorization"]}); assert r.status_code in (401, 403)

    def test_subadmin_in_scope_review(self):
        rid = f"att_TEST_{uuid.uuid4().hex[:8]}"; CREATED_RECORDS.append(rid)
        t = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        db.attendance.insert_one({"record_id": rid, "user_id": "user_testemp01", "date": t[:10], "check_in": t, "check_out": t,
                                  "status": "off_duty", "check_in_photo_path": "x/checkin/user_testemp01/fake.jpg",
                                  "check_in_face_review": True, "check_in_face_review_reason": "borderline match", "check_in_face_distance": 0.5})
        j = requests.get(f"{API}/admin/face-checks", params={"flagged": "true"}, headers=SUB).json()
        assert any(i["record_id"] == rid for i in j["items"])
        r = requests.post(f"{API}/admin/face-checks/{rid}", json={"kind": "in", "decision": "mismatch", "note": "TEST note"}, headers=SUB)
        assert r.status_code == 200
        rec = db.attendance.find_one({"record_id": rid})
        assert rec["check_in_face_review_status"] == "mismatch" and rec["check_in_face_review_note"] == "TEST note"
        assert activity("face_review_mismatch", "Ravi Kumar")

    def test_admin_review_ok_and_validation(self, world):
        before = requests.get(f"{API}/admin/face-checks", params={"flagged": "true", "person": world["A"]}, headers=ADMIN).json()["pending_review"]
        r = requests.post(f"{API}/admin/face-checks/{world['flag_rec']}", json={"kind": "in", "decision": "ok"}, headers=ADMIN); assert r.status_code == 200
        assert db.attendance.find_one({"record_id": world["flag_rec"]})["check_in_face_review_status"] == "ok"
        after = requests.get(f"{API}/admin/face-checks", params={"flagged": "true", "person": world["A"]}, headers=ADMIN).json()["pending_review"]
        assert after == before - 1
        assert requests.post(f"{API}/admin/face-checks/{world['flag_rec']}", json={"kind": "x", "decision": "ok"}, headers=ADMIN).status_code == 422
        assert requests.post(f"{API}/admin/face-checks/att_nope", json={"kind": "in", "decision": "ok"}, headers=ADMIN).status_code == 404

    def test_reset_face(self, world):
        assert requests.delete(f"{API}/admin/employees/{world['B']}/face", headers=SUB).status_code == 403
        r = requests.delete(f"{API}/admin/employees/{world['B']}/face", headers=ADMIN); assert r.status_code == 200
        assert not db.face_profiles.find_one({"user_id": world["B"]})
        u = db.users.find_one({"user_id": world["B"]})
        assert u["face_enrolled"] is False and u["face_descriptor"] is None and u["face_photo_path"] is None
        assert activity("face_reset", "TEST_Face B")
        assert enroll(world["hb"], world["B_base"]).status_code == 200   # can re-enrol


# --- Selfie retention purge
class TestPurge:
    def test_unauthorized(self):
        assert requests.post(f"{API}/cron/selfie-purge").status_code == 401
        assert requests.post(f"{API}/cron/selfie-purge", headers={"Authorization": "Bearer wrong"}).status_code == 401

    def test_purge_old_only(self):
        uid, _ = mk_user("purge")
        old_t = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat(); new_t = datetime.now(timezone.utc).isoformat()
        old_id, new_id = f"att_TEST_old_{uuid.uuid4().hex[:6]}", f"att_TEST_new_{uuid.uuid4().hex[:6]}"
        CREATED_RECORDS.extend([old_id, new_id])
        for rid, t in ((old_id, old_t), (new_id, new_t)):
            db.attendance.insert_one({"record_id": rid, "user_id": uid, "date": t[:10], "check_in": t, "check_out": t, "status": "off_duty",
                                      "check_in_photo_path": f"TEST/checkin/{uid}/{rid}.jpg", "check_out_photo_path": f"TEST/checkout/{uid}/{rid}.jpg"})
        r = requests.post(f"{API}/cron/selfie-purge", headers={"Authorization": f"Bearer {CRON_SECRET}"}, json={})
        assert r.status_code == 200 and r.json().get("ok")
        for _ in range(20):
            if db.attendance.find_one({"record_id": old_id}).get("photos_purged_at"):
                break
            time.sleep(0.5)
        o = db.attendance.find_one({"record_id": old_id}); n = db.attendance.find_one({"record_id": new_id})
        assert o["check_in_photo_path"] is None and o["check_out_photo_path"] is None and o.get("photos_purged_at")
        assert n["check_in_photo_path"] and n["check_out_photo_path"] and not n.get("photos_purged_at")
