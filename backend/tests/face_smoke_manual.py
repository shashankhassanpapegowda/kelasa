import os, random, uuid, requests, math
from datetime import datetime, timezone
from pymongo import MongoClient

API = os.environ["REACT_APP_BACKEND_URL"].rstrip("/") + "/api"
db = MongoClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))["test_database"]
JPG = "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/wAALCAABAAEBAREA/8QAFAABAAAAAAAAAAAAAAAAAAAACf/EABQQAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQEAAD8AKp//2Q=="

def unit(v):
    n = math.sqrt(sum(x * x for x in v)); return [x / n for x in v]

def near(base, eps):
    return unit([b + random.gauss(0, eps) for b in base])

def mk_user(tag):
    uid = f"user_facetest_{tag}_{uuid.uuid4().hex[:6]}"; tok = f"sess_{uid}"
    db.users.insert_one({"user_id": uid, "email": f"{uid}@example.com", "name": f"Face {tag}", "role": "employee",
                         "field_staff": True, "created_at": datetime.now(timezone.utc).isoformat(), "face_enrolled": False})
    db.user_sessions.insert_one({"session_token": tok, "user_id": uid, "expires_at": datetime(2030, 1, 1, tzinfo=timezone.utc).isoformat(), "created_at": datetime.now(timezone.utc).isoformat()})
    return uid, {"Authorization": f"Bearer {tok}"}

def run():
    random.seed(7)
    a_base, b_base = unit([random.gauss(0, 1) for _ in range(128)]), unit([random.gauss(0, 1) for _ in range(128)])
    scale = 0.35  # descriptor spread
    A, ha = mk_user("a"); B, hb = mk_user("b")
    try:
        r = requests.post(f"{API}/face/enroll", json={"descriptors": [near(a_base, 0.002)], "image_b64": JPG}, headers=ha); print("enroll 1 photo", r.status_code, r.text[:90])
        r = requests.post(f"{API}/face/enroll", json={"descriptors": [near(a_base, 0.003) for _ in range(3)], "image_b64": JPG}, headers=ha); print("enroll A", r.status_code)
        r = requests.post(f"{API}/face/enroll", json={"descriptors": [near(a_base, 0.003) for _ in range(3)], "image_b64": JPG}, headers=ha); print("re-enroll A", r.status_code, r.text[:80])
        r = requests.post(f"{API}/face/enroll", json={"descriptors": [near(a_base, 0.003) for _ in range(3)], "image_b64": JPG}, headers=hb); print("B enrolls A's face", r.status_code, r.text[:90])
        r = requests.post(f"{API}/face/enroll", json={"descriptors": [near(b_base, 0.003) for _ in range(3)], "image_b64": JPG}, headers=hb); print("enroll B", r.status_code)
        geo = {"lat": 12.97, "lng": 77.59, "accuracy": 10, "image_b64": JPG}
        live = {"challenge": "blink", "passed": True}
        r = requests.post(f"{API}/attendance/checkin", json={**geo, "descriptors": [near(a_base, 0.003)] * 2}, headers=ha); print("no liveness", r.status_code, r.text[:80])
        r = requests.post(f"{API}/attendance/checkin", json={**geo, "liveness": live, "descriptors": [near(a_base, 0.003), near(b_base, 0.003)]}, headers=ha); print("swap mid-check", r.status_code, r.text[:80])
        r = requests.post(f"{API}/attendance/checkin", json={**geo, "liveness": live, "descriptors": [near(b_base, 0.003)] * 2}, headers=ha); print("B face on A account", r.status_code, r.text[:90])
        r = requests.post(f"{API}/attendance/checkin", json={**geo, "liveness": live, "descriptors": [near(a_base, 0.003)] * 2}, headers=ha); print("A good", r.status_code, r.json())
        print("learned", len(db.face_profiles.find_one({"user_id": A}).get("learned", [])))
        mid = unit([0.5 * x + 0.5 * y for x, y in zip(a_base, unit([x + 0.6 * random.gauss(0, 1) / 11 for x in a_base]))])
        rec = db.attendance.find_one({"user_id": A}, {"_id": 0}); print("rec fields", {k: rec.get(k) for k in ("check_in_face_distance", "check_in_face_review", "check_in_liveness")})
    finally:
        for u in (A, B):
            db.users.delete_one({"user_id": u}); db.user_sessions.delete_many({"user_id": u}); db.face_profiles.delete_many({"user_id": u})
            db.attendance.delete_many({"user_id": u}); db.locations.delete_many({"user_id": u})

if __name__ == "__main__":
    run()
