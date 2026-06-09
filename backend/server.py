from fastapi import FastAPI, APIRouter, HTTPException, Request, Response, Depends, Header, Query
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
import uuid
import math
import base64
import httpx
import requests
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional
from datetime import datetime, timezone, timedelta

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

app = FastAPI()
api_router = APIRouter(prefix="/api")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ---------- Object Storage ----------
STORAGE_URL = "https://integrations.emergentagent.com/objstore/api/v1/storage"
EMERGENT_KEY = os.environ.get("EMERGENT_LLM_KEY")
APP_NAME = "gtg-attendance"
storage_key = None

def init_storage():
    global storage_key
    if storage_key:
        return storage_key
    try:
        resp = requests.post(f"{STORAGE_URL}/init", json={"emergent_key": EMERGENT_KEY}, timeout=30)
        resp.raise_for_status()
        storage_key = resp.json()["storage_key"]
        logger.info("Storage initialized")
        return storage_key
    except Exception as e:
        logger.error(f"Storage init failed: {e}")
        return None

def put_object(path: str, data: bytes, content_type: str):
    key = init_storage()
    if not key:
        raise HTTPException(status_code=500, detail="Storage unavailable")
    resp = requests.put(
        f"{STORAGE_URL}/objects/{path}",
        headers={"X-Storage-Key": key, "Content-Type": content_type},
        data=data, timeout=120
    )
    if resp.status_code == 403:
        # session expired, retry once
        global storage_key
        storage_key = None
        key = init_storage()
        resp = requests.put(
            f"{STORAGE_URL}/objects/{path}",
            headers={"X-Storage-Key": key, "Content-Type": content_type},
            data=data, timeout=120
        )
    resp.raise_for_status()
    return resp.json()

def get_object(path: str):
    key = init_storage()
    if not key:
        raise HTTPException(status_code=500, detail="Storage unavailable")
    resp = requests.get(
        f"{STORAGE_URL}/objects/{path}",
        headers={"X-Storage-Key": key}, timeout=60
    )
    if resp.status_code == 403:
        global storage_key
        storage_key = None
        key = init_storage()
        resp = requests.get(
            f"{STORAGE_URL}/objects/{path}",
            headers={"X-Storage-Key": key}, timeout=60
        )
    resp.raise_for_status()
    return resp.content, resp.headers.get("Content-Type", "image/jpeg")

# ---------- Models ----------
class SessionExchange(BaseModel):
    session_id: str

class FaceEnrollRequest(BaseModel):
    descriptor: List[float]  # 128-dim from face-api.js
    image_b64: str  # base64-encoded JPEG

class CheckRequest(BaseModel):
    lat: float
    lng: float
    accuracy: Optional[float] = None
    descriptor: List[float]
    image_b64: str

class LocationPing(BaseModel):
    lat: float
    lng: float
    accuracy: Optional[float] = None

class RoleUpdate(BaseModel):
    role: str

# ---------- Helpers ----------
def now_utc() -> datetime:
    return datetime.now(timezone.utc)

def today_str() -> str:
    return now_utc().date().isoformat()

def euclidean(a: List[float], b: List[float]) -> float:
    if len(a) != len(b):
        return 9999.0
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))

FACE_MATCH_THRESHOLD = 0.55  # face-api.js standard threshold

async def get_current_user(request: Request) -> dict:
    token = request.cookies.get("session_token")
    if not token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    session = await db.user_sessions.find_one({"session_token": token}, {"_id": 0})
    if not session:
        raise HTTPException(status_code=401, detail="Invalid session")

    expires_at = session["expires_at"]
    if isinstance(expires_at, str):
        expires_at = datetime.fromisoformat(expires_at)
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < now_utc():
        raise HTTPException(status_code=401, detail="Session expired")

    user = await db.users.find_one({"user_id": session["user_id"]}, {"_id": 0})
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user

async def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user

def upload_face_image(user_id: str, image_b64: str, kind: str) -> str:
    """Decode base64 JPEG and upload to object storage. Returns storage path."""
    if image_b64.startswith("data:"):
        image_b64 = image_b64.split(",", 1)[1]
    data = base64.b64decode(image_b64)
    path = f"{APP_NAME}/{kind}/{user_id}/{uuid.uuid4().hex}.jpg"
    result = put_object(path, data, "image/jpeg")
    return result["path"]

# ---------- Auth Routes ----------
@api_router.post("/auth/session")
async def auth_session(payload: SessionExchange, response: Response):
    async with httpx.AsyncClient(timeout=15) as hc:
        r = await hc.get(
            "https://demobackend.emergentagent.com/auth/v1/env/oauth/session-data",
            headers={"X-Session-ID": payload.session_id},
        )
    if r.status_code != 200:
        raise HTTPException(status_code=401, detail="Invalid session_id")
    data = r.json()
    email = data["email"]
    name = data.get("name", email)
    picture = data.get("picture")
    session_token = data["session_token"]

    existing = await db.users.find_one({"email": email}, {"_id": 0})
    if existing:
        user_id = existing["user_id"]
        await db.users.update_one(
            {"user_id": user_id},
            {"$set": {"name": name, "picture": picture}}
        )
    else:
        user_count = await db.users.count_documents({})
        role = "admin" if user_count == 0 else "employee"
        user_id = f"user_{uuid.uuid4().hex[:12]}"
        await db.users.insert_one({
            "user_id": user_id,
            "email": email,
            "name": name,
            "picture": picture,
            "role": role,
            "face_enrolled": False,
            "face_descriptor": None,
            "face_photo_path": None,
            "created_at": now_utc().isoformat(),
        })

    expires_at = now_utc() + timedelta(days=7)
    await db.user_sessions.insert_one({
        "user_id": user_id,
        "session_token": session_token,
        "expires_at": expires_at.isoformat(),
        "created_at": now_utc().isoformat(),
    })

    response.set_cookie(
        key="session_token", value=session_token,
        max_age=7 * 24 * 60 * 60, httponly=True, secure=True, samesite="none", path="/",
    )
    user_doc = await db.users.find_one({"user_id": user_id}, {"_id": 0, "face_descriptor": 0})
    return {"user": user_doc}

@api_router.get("/auth/me")
async def get_me(user: dict = Depends(get_current_user)):
    u = dict(user)
    u.pop("face_descriptor", None)  # never expose descriptor
    return u

@api_router.post("/auth/logout")
async def logout(request: Request, response: Response):
    token = request.cookies.get("session_token")
    if token:
        await db.user_sessions.delete_one({"session_token": token})
    response.delete_cookie("session_token", path="/")
    return {"ok": True}

# ---------- Face Enrollment ----------
@api_router.post("/face/enroll")
async def face_enroll(payload: FaceEnrollRequest, user: dict = Depends(get_current_user)):
    if len(payload.descriptor) != 128:
        raise HTTPException(status_code=400, detail="Invalid face descriptor")
    photo_path = upload_face_image(user["user_id"], payload.image_b64, "enrollment")
    await db.users.update_one(
        {"user_id": user["user_id"]},
        {"$set": {
            "face_enrolled": True,
            "face_descriptor": payload.descriptor,
            "face_photo_path": photo_path,
            "face_enrolled_at": now_utc().isoformat(),
        }}
    )
    return {"ok": True, "photo_path": photo_path}

@api_router.get("/face/status")
async def face_status(user: dict = Depends(get_current_user)):
    return {"enrolled": user.get("face_enrolled", False)}

# ---------- File Serving ----------
@api_router.get("/files/{path:path}")
async def download_file(path: str, request: Request, auth: Optional[str] = Query(None)):
    # Auth check via cookie or token query
    token = request.cookies.get("session_token") or auth
    if not token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    session = await db.user_sessions.find_one({"session_token": token}, {"_id": 0})
    if not session:
        raise HTTPException(status_code=401, detail="Invalid session")
    try:
        data, content_type = get_object(path)
    except Exception:
        raise HTTPException(status_code=404, detail="File not found")
    return Response(content=data, media_type=content_type)

# ---------- Attendance Routes ----------
@api_router.post("/attendance/checkin")
async def check_in(payload: CheckRequest, user: dict = Depends(get_current_user)):
    if not user.get("face_enrolled"):
        raise HTTPException(status_code=400, detail="Face not enrolled. Please complete face enrollment first.")
    if len(payload.descriptor) != 128:
        raise HTTPException(status_code=400, detail="Invalid face data")
    stored_desc = user.get("face_descriptor") or []
    dist = euclidean(payload.descriptor, stored_desc)
    if dist > FACE_MATCH_THRESHOLD:
        raise HTTPException(status_code=403, detail=f"Face does not match enrolled face (score: {dist:.2f}). Please try again.")

    today = today_str()
    active = await db.attendance.find_one(
        {"user_id": user["user_id"], "check_out": None}, {"_id": 0},
        sort=[("check_in", -1)]
    )
    if active:
        raise HTTPException(status_code=400, detail="Already checked in")

    photo_path = upload_face_image(user["user_id"], payload.image_b64, "checkin")
    record_id = f"att_{uuid.uuid4().hex[:12]}"
    doc = {
        "record_id": record_id,
        "user_id": user["user_id"],
        "date": today,
        "check_in": now_utc().isoformat(),
        "check_in_lat": payload.lat,
        "check_in_lng": payload.lng,
        "check_in_accuracy": payload.accuracy,
        "check_in_photo_path": photo_path,
        "check_in_face_distance": round(dist, 4),
        "check_out": None,
        "status": "on_duty",
    }
    await db.attendance.insert_one(doc)
    await db.locations.insert_one({
        "ping_id": f"ping_{uuid.uuid4().hex[:12]}",
        "user_id": user["user_id"],
        "record_id": record_id,
        "date": today,
        "lat": payload.lat,
        "lng": payload.lng,
        "accuracy": payload.accuracy,
        "timestamp": now_utc().isoformat(),
    })
    return {"ok": True, "record_id": record_id, "face_distance": round(dist, 4)}

@api_router.post("/attendance/checkout")
async def check_out(payload: CheckRequest, user: dict = Depends(get_current_user)):
    if not user.get("face_enrolled"):
        raise HTTPException(status_code=400, detail="Face not enrolled")
    if len(payload.descriptor) != 128:
        raise HTTPException(status_code=400, detail="Invalid face data")
    stored_desc = user.get("face_descriptor") or []
    dist = euclidean(payload.descriptor, stored_desc)
    if dist > FACE_MATCH_THRESHOLD:
        raise HTTPException(status_code=403, detail=f"Face does not match enrolled face (score: {dist:.2f}). Please try again.")

    today = today_str()
    active = await db.attendance.find_one(
        {"user_id": user["user_id"], "check_out": None}, {"_id": 0},
        sort=[("check_in", -1)]
    )
    if not active:
        raise HTTPException(status_code=400, detail="No active check-in")

    photo_path = upload_face_image(user["user_id"], payload.image_b64, "checkout")
    check_in_dt = datetime.fromisoformat(active["check_in"])
    if check_in_dt.tzinfo is None:
        check_in_dt = check_in_dt.replace(tzinfo=timezone.utc)
    out_dt = now_utc()
    minutes = int((out_dt - check_in_dt).total_seconds() // 60)

    await db.attendance.update_one(
        {"record_id": active["record_id"]},
        {"$set": {
            "check_out": out_dt.isoformat(),
            "check_out_lat": payload.lat,
            "check_out_lng": payload.lng,
            "check_out_accuracy": payload.accuracy,
            "check_out_photo_path": photo_path,
            "check_out_face_distance": round(dist, 4),
            "status": "off_duty",
            "duration_minutes": minutes,
        }}
    )
    await db.locations.insert_one({
        "ping_id": f"ping_{uuid.uuid4().hex[:12]}",
        "user_id": user["user_id"],
        "record_id": active["record_id"],
        "date": today,
        "lat": payload.lat,
        "lng": payload.lng,
        "accuracy": payload.accuracy,
        "timestamp": out_dt.isoformat(),
    })
    return {"ok": True, "duration_minutes": minutes}

@api_router.get("/attendance/today")
async def attendance_today(user: dict = Depends(get_current_user)):
    today = today_str()
    active = await db.attendance.find_one(
        {"user_id": user["user_id"], "check_out": None}, {"_id": 0},
        sort=[("check_in", -1)]
    )
    records = await db.attendance.find(
        {"user_id": user["user_id"], "date": today}, {"_id": 0}
    ).sort("check_in", 1).to_list(100)
    return {"active": active, "today_records": records}

@api_router.get("/attendance/me")
async def attendance_history(user: dict = Depends(get_current_user), limit: int = 60):
    records = await db.attendance.find(
        {"user_id": user["user_id"]}, {"_id": 0}
    ).sort("check_in", -1).to_list(limit)
    return {"records": records}

# ---------- Location Routes ----------
@api_router.post("/location/ping")
async def location_ping(payload: LocationPing, user: dict = Depends(get_current_user)):
    today = today_str()
    active = await db.attendance.find_one(
        {"user_id": user["user_id"], "check_out": None}, {"_id": 0},
        sort=[("check_in", -1)]
    )
    if not active:
        raise HTTPException(status_code=400, detail="Not currently on duty")
    # Reject extremely poor accuracy (> 500m) to prevent inflating routes with cell-tower pings
    if payload.accuracy is not None and payload.accuracy > 500:
        return {"ok": False, "skipped": True, "reason": "low_accuracy"}

    await db.locations.insert_one({
        "ping_id": f"ping_{uuid.uuid4().hex[:12]}",
        "user_id": user["user_id"],
        "record_id": active["record_id"],
        "date": today,
        "lat": payload.lat,
        "lng": payload.lng,
        "accuracy": payload.accuracy,
        "timestamp": now_utc().isoformat(),
    })
    return {"ok": True}

@api_router.get("/location/today")
async def location_today(user: dict = Depends(get_current_user), date: Optional[str] = None):
    d = date or today_str()
    pings = await db.locations.find(
        {"user_id": user["user_id"], "date": d}, {"_id": 0}
    ).sort("timestamp", 1).to_list(5000)
    return {"date": d, "pings": pings}

# ---------- Admin Routes ----------
@api_router.get("/admin/stats")
async def admin_stats(user: dict = Depends(require_admin)):
    today = today_str()
    total_employees = await db.users.count_documents({})
    on_duty = await db.attendance.count_documents({"check_out": None})
    today_checkins = await db.attendance.count_documents({"date": today})
    pipeline = [
        {"$match": {"date": today, "duration_minutes": {"$exists": True}}},
        {"$group": {"_id": None, "total": {"$sum": "$duration_minutes"}}}
    ]
    cursor = db.attendance.aggregate(pipeline)
    total_minutes = 0
    async for row in cursor:
        total_minutes = row.get("total", 0)
    return {
        "total_employees": total_employees,
        "on_duty": on_duty,
        "today_checkins": today_checkins,
        "total_work_minutes_today": total_minutes,
    }

@api_router.get("/admin/employees")
async def admin_employees(user: dict = Depends(require_admin)):
    users = await db.users.find({}, {"_id": 0, "face_descriptor": 0}).sort("created_at", -1).to_list(1000)
    today = today_str()
    actives = await db.attendance.find({"check_out": None}, {"_id": 0}).to_list(1000)
    active_map = {a["user_id"]: a for a in actives}
    today_records = await db.attendance.find({"date": today}, {"_id": 0}).to_list(5000)
    today_minutes = {}
    today_counts = {}
    for r in today_records:
        today_counts[r["user_id"]] = today_counts.get(r["user_id"], 0) + 1
        if r.get("duration_minutes"):
            today_minutes[r["user_id"]] = today_minutes.get(r["user_id"], 0) + r["duration_minutes"]
    for u in users:
        u["is_on_duty"] = u["user_id"] in active_map
        u["today_minutes"] = today_minutes.get(u["user_id"], 0)
        u["today_sessions"] = today_counts.get(u["user_id"], 0)
        u.setdefault("face_enrolled", False)
        u.setdefault("face_photo_path", None)
    return {"employees": users}

@api_router.patch("/admin/employees/{user_id}/role")
async def admin_set_role(user_id: str, payload: RoleUpdate, user: dict = Depends(require_admin)):
    if payload.role not in ("admin", "employee"):
        raise HTTPException(status_code=400, detail="Invalid role")
    if user_id == user["user_id"] and payload.role != "admin":
        raise HTTPException(status_code=400, detail="Cannot demote yourself")
    res = await db.users.update_one({"user_id": user_id}, {"$set": {"role": payload.role}})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="User not found")
    return {"ok": True}

@api_router.get("/admin/employees/{user_id}/route")
async def admin_employee_route(user_id: str, date: Optional[str] = None, user: dict = Depends(require_admin)):
    d = date or today_str()
    emp = await db.users.find_one({"user_id": user_id}, {"_id": 0, "face_descriptor": 0})
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    pings = await db.locations.find(
        {"user_id": user_id, "date": d}, {"_id": 0}
    ).sort("timestamp", 1).to_list(5000)
    attendance = await db.attendance.find(
        {"user_id": user_id, "date": d}, {"_id": 0}
    ).sort("check_in", 1).to_list(100)
    return {"employee": emp, "date": d, "pings": pings, "attendance": attendance}

@api_router.get("/admin/attendance")
async def admin_attendance(date: Optional[str] = None, user: dict = Depends(require_admin)):
    d = date or today_str()
    records = await db.attendance.find({"date": d}, {"_id": 0}).sort("check_in", 1).to_list(5000)
    user_ids = list({r["user_id"] for r in records})
    users = await db.users.find({"user_id": {"$in": user_ids}}, {"_id": 0, "face_descriptor": 0}).to_list(1000)
    umap = {u["user_id"]: u for u in users}
    for r in records:
        u = umap.get(r["user_id"], {})
        r["name"] = u.get("name", "")
        r["email"] = u.get("email", "")
        r["picture"] = u.get("picture")
    return {"date": d, "records": records}

@api_router.delete("/admin/employees/{user_id}/face")
async def admin_reset_face(user_id: str, user: dict = Depends(require_admin)):
    """Reset an employee's face enrollment so they can re-enroll."""
    res = await db.users.update_one(
        {"user_id": user_id},
        {"$set": {"face_enrolled": False, "face_descriptor": None, "face_photo_path": None}}
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="User not found")
    return {"ok": True}

@api_router.get("/")
async def root():
    return {"message": "Attendance & Field Work API", "status": "ok"}

app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup():
    init_storage()

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
