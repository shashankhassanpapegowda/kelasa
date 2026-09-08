from fastapi import FastAPI, APIRouter, HTTPException, Request, Response, Depends, Query
from fastapi.responses import StreamingResponse
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
import uuid
import math
import base64
import io
import csv
import httpx
import requests
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional
from datetime import datetime, timezone, timedelta, time as dtime
from zoneinfo import ZoneInfo

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

app = FastAPI()
api_router = APIRouter(prefix="/api")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

DEFAULT_TZ = "Asia/Kolkata"
LATE_GRACE_MINUTES = 15

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
    descriptor: List[float]
    image_b64: str

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

class BreakRequest(BaseModel):
    lat: Optional[float] = None
    lng: Optional[float] = None

class RoleUpdate(BaseModel):
    role: str

class ShiftUpdate(BaseModel):
    shift_start: Optional[str] = None  # "HH:MM"
    shift_end: Optional[str] = None    # "HH:MM"
    break_max_minutes: Optional[int] = None
    timezone: Optional[str] = None

class TrackingModeUpdate(BaseModel):
    tracking_mode: str  # "duty_only" | "always_on"

# ---------- Helpers ----------
def now_utc() -> datetime:
    return datetime.now(timezone.utc)

def parse_hhmm(s: str) -> Optional[dtime]:
    if not s or ":" not in s:
        return None
    try:
        h, m = s.split(":", 1)
        return dtime(hour=int(h), minute=int(m))
    except Exception:
        return None

def user_local_now(user: dict) -> datetime:
    tz = ZoneInfo(user.get("timezone") or DEFAULT_TZ)
    return now_utc().astimezone(tz)

def user_local_today(user: dict) -> str:
    return user_local_now(user).date().isoformat()

def to_local(dt_str: str, tz_name: str) -> datetime:
    dt = datetime.fromisoformat(dt_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(ZoneInfo(tz_name or DEFAULT_TZ))

def compute_late_minutes(check_in_iso: str, user: dict) -> Optional[int]:
    """Returns minutes late vs shift_start (after grace). None if no shift configured."""
    shift_start_str = user.get("shift_start")
    if not shift_start_str:
        return None
    shift_t = parse_hhmm(shift_start_str)
    if not shift_t:
        return None
    tz_name = user.get("timezone") or DEFAULT_TZ
    local_in = to_local(check_in_iso, tz_name)
    shift_dt = local_in.replace(hour=shift_t.hour, minute=shift_t.minute, second=0, microsecond=0)
    diff = (local_in - shift_dt).total_seconds() / 60.0
    minutes = int(diff)
    return max(minutes - LATE_GRACE_MINUTES, 0)

def euclidean(a: List[float], b: List[float]) -> float:
    if len(a) != len(b):
        return 9999.0
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))

FACE_MATCH_THRESHOLD = float(os.environ.get("FACE_MATCH_THRESHOLD", "0.55"))

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
            "shift_start": None,
            "shift_end": None,
            "break_max_minutes": 60,
            "timezone": DEFAULT_TZ,
            "tracking_mode": "duty_only",
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
    return {"user": user_doc, "session_token": session_token}

@api_router.get("/auth/me")
async def get_me(user: dict = Depends(get_current_user)):
    u = dict(user)
    u.pop("face_descriptor", None)
    return u

@api_router.post("/auth/logout")
async def logout(request: Request, response: Response):
    token = request.cookies.get("session_token")
    if token:
        await db.user_sessions.delete_one({"session_token": token})
    response.delete_cookie("session_token", path="/")
    return {"ok": True}

# ---------- Face ----------
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
        raise HTTPException(status_code=404, detail="File not found") from None
    return Response(content=data, media_type=content_type)

# ---------- Attendance ----------
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

    active = await db.attendance.find_one(
        {"user_id": user["user_id"], "check_out": None}, {"_id": 0},
        sort=[("check_in", -1)]
    )
    if active:
        raise HTTPException(status_code=400, detail="Already checked in")

    today = user_local_today(user)
    check_in_iso = now_utc().isoformat()
    late_by = compute_late_minutes(check_in_iso, user)
    photo_path = upload_face_image(user["user_id"], payload.image_b64, "checkin")
    record_id = f"att_{uuid.uuid4().hex[:12]}"
    doc = {
        "record_id": record_id,
        "user_id": user["user_id"],
        "date": today,
        "check_in": check_in_iso,
        "check_in_lat": payload.lat,
        "check_in_lng": payload.lng,
        "check_in_accuracy": payload.accuracy,
        "check_in_photo_path": photo_path,
        "check_in_face_distance": round(dist, 4),
        "check_out": None,
        "status": "on_duty",
        "breaks": [],
        "total_break_minutes": 0,
        "on_break": False,
        "late_by_minutes": late_by,
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
        "timestamp": check_in_iso,
    })
    return {"ok": True, "record_id": record_id, "face_distance": round(dist, 4), "late_by_minutes": late_by}

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

    active = await db.attendance.find_one(
        {"user_id": user["user_id"], "check_out": None}, {"_id": 0},
        sort=[("check_in", -1)]
    )
    if not active:
        raise HTTPException(status_code=400, detail="No active check-in")
    if active.get("on_break"):
        raise HTTPException(status_code=400, detail="You are currently on break. End break before checking out.")

    photo_path = upload_face_image(user["user_id"], payload.image_b64, "checkout")
    check_in_dt = datetime.fromisoformat(active["check_in"])
    if check_in_dt.tzinfo is None:
        check_in_dt = check_in_dt.replace(tzinfo=timezone.utc)
    out_dt = now_utc()
    total_minutes = int((out_dt - check_in_dt).total_seconds() // 60)
    break_minutes = int(active.get("total_break_minutes", 0))
    net_minutes = max(total_minutes - break_minutes, 0)
    break_max_raw = user.get("break_max_minutes")
    break_max = int(break_max_raw) if break_max_raw is not None else 60
    over_break = break_minutes > break_max

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
            "duration_minutes": total_minutes,
            "net_work_minutes": net_minutes,
            "over_break": over_break,
        }}
    )
    await db.locations.insert_one({
        "ping_id": f"ping_{uuid.uuid4().hex[:12]}",
        "user_id": user["user_id"],
        "record_id": active["record_id"],
        "date": active["date"],
        "lat": payload.lat,
        "lng": payload.lng,
        "accuracy": payload.accuracy,
        "timestamp": out_dt.isoformat(),
    })
    return {"ok": True, "duration_minutes": total_minutes, "net_work_minutes": net_minutes, "over_break": over_break}

# ---------- Breaks ----------
@api_router.post("/attendance/break/start")
async def break_start(payload: BreakRequest, user: dict = Depends(get_current_user)):
    active = await db.attendance.find_one(
        {"user_id": user["user_id"], "check_out": None}, {"_id": 0},
        sort=[("check_in", -1)]
    )
    if not active:
        raise HTTPException(status_code=400, detail="Not currently on duty")
    if active.get("on_break"):
        raise HTTPException(status_code=400, detail="Already on break")

    break_id = f"brk_{uuid.uuid4().hex[:10]}"
    brk = {
        "break_id": break_id,
        "start": now_utc().isoformat(),
        "end": None,
        "duration_minutes": None,
        "start_lat": payload.lat,
        "start_lng": payload.lng,
        "end_lat": None,
        "end_lng": None,
    }
    await db.attendance.update_one(
        {"record_id": active["record_id"]},
        {"$push": {"breaks": brk}, "$set": {"on_break": True}}
    )
    return {"ok": True, "break_id": break_id}

@api_router.post("/attendance/break/end")
async def break_end(payload: BreakRequest, user: dict = Depends(get_current_user)):
    active = await db.attendance.find_one(
        {"user_id": user["user_id"], "check_out": None}, {"_id": 0},
        sort=[("check_in", -1)]
    )
    if not active:
        raise HTTPException(status_code=400, detail="Not currently on duty")
    if not active.get("on_break"):
        raise HTTPException(status_code=400, detail="Not currently on break")

    breaks = active.get("breaks", [])
    if not breaks:
        raise HTTPException(status_code=400, detail="No active break")
    # find last open break
    last = None
    for i in range(len(breaks) - 1, -1, -1):
        if breaks[i].get("end") is None:
            last = i
            break
    if last is None:
        raise HTTPException(status_code=400, detail="No open break")

    start_dt = datetime.fromisoformat(breaks[last]["start"])
    if start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=timezone.utc)
    end_dt = now_utc()
    mins = int((end_dt - start_dt).total_seconds() // 60)

    breaks[last]["end"] = end_dt.isoformat()
    breaks[last]["end_lat"] = payload.lat
    breaks[last]["end_lng"] = payload.lng
    breaks[last]["duration_minutes"] = mins
    total = sum((b.get("duration_minutes") or 0) for b in breaks)

    await db.attendance.update_one(
        {"record_id": active["record_id"]},
        {"$set": {"breaks": breaks, "on_break": False, "total_break_minutes": total}}
    )
    return {"ok": True, "duration_minutes": mins, "total_break_minutes": total}

@api_router.get("/attendance/today")
async def attendance_today(user: dict = Depends(get_current_user)):
    today = user_local_today(user)
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

# ---------- Location ----------
@api_router.post("/location/ping")
async def location_ping(payload: LocationPing, user: dict = Depends(get_current_user)):
    active = await db.attendance.find_one(
        {"user_id": user["user_id"], "check_out": None}, {"_id": 0},
        sort=[("check_in", -1)]
    )
    if not active:
        raise HTTPException(status_code=400, detail="Not currently on duty")
    if active.get("on_break"):
        return {"ok": False, "skipped": True, "reason": "on_break"}
    if payload.accuracy is not None and payload.accuracy > 500:
        return {"ok": False, "skipped": True, "reason": "low_accuracy"}

    await db.locations.insert_one({
        "ping_id": f"ping_{uuid.uuid4().hex[:12]}",
        "user_id": user["user_id"],
        "record_id": active["record_id"],
        "date": active["date"],
        "lat": payload.lat,
        "lng": payload.lng,
        "accuracy": payload.accuracy,
        "timestamp": now_utc().isoformat(),
    })
    return {"ok": True}

@api_router.get("/location/today")
async def location_today(user: dict = Depends(get_current_user), date: Optional[str] = None):
    d = date or user_local_today(user)
    pings = await db.locations.find(
        {"user_id": user["user_id"], "date": d}, {"_id": 0}
    ).sort("timestamp", 1).to_list(5000)
    return {"date": d, "pings": pings}

# ---------- Admin ----------
@api_router.get("/admin/stats")
async def admin_stats(user: dict = Depends(require_admin)):
    today = user_local_today(user)
    total_employees = await db.users.count_documents({})
    on_duty = await db.attendance.count_documents({"check_out": None})
    today_checkins = await db.attendance.count_documents({"date": today})
    pipeline = [
        {"$match": {"date": today, "net_work_minutes": {"$exists": True}}},
        {"$group": {"_id": None, "total": {"$sum": "$net_work_minutes"}}}
    ]
    cursor = db.attendance.aggregate(pipeline)
    total_minutes = 0
    async for row in cursor:
        total_minutes = row.get("total", 0)
    late_today = await db.attendance.count_documents({"date": today, "late_by_minutes": {"$gt": 0}})
    return {
        "total_employees": total_employees,
        "on_duty": on_duty,
        "today_checkins": today_checkins,
        "total_work_minutes_today": total_minutes,
        "late_today": late_today,
    }

@api_router.get("/admin/employees")
async def admin_employees(user: dict = Depends(require_admin)):
    users = await db.users.find({}, {"_id": 0, "face_descriptor": 0}).sort("created_at", -1).to_list(1000)
    today = user_local_today(user)
    actives = await db.attendance.find({"check_out": None}, {"_id": 0}).to_list(1000)
    active_map = {a["user_id"]: a for a in actives}
    today_records = await db.attendance.find({"date": today}, {"_id": 0}).to_list(5000)
    today_minutes = {}
    today_counts = {}
    for r in today_records:
        today_counts[r["user_id"]] = today_counts.get(r["user_id"], 0) + 1
        if r.get("net_work_minutes"):
            today_minutes[r["user_id"]] = today_minutes.get(r["user_id"], 0) + r["net_work_minutes"]
    for u in users:
        u["is_on_duty"] = u["user_id"] in active_map
        u["on_break"] = bool(active_map.get(u["user_id"], {}).get("on_break"))
        u["today_minutes"] = today_minutes.get(u["user_id"], 0)
        u["today_sessions"] = today_counts.get(u["user_id"], 0)
        u.setdefault("face_enrolled", False)
        u.setdefault("face_photo_path", None)
        u.setdefault("shift_start", None)
        u.setdefault("shift_end", None)
        u.setdefault("break_max_minutes", 60)
        u.setdefault("timezone", DEFAULT_TZ)
        u.setdefault("tracking_mode", "duty_only")
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

@api_router.patch("/admin/employees/{user_id}/shift")
async def admin_set_shift(user_id: str, payload: ShiftUpdate, user: dict = Depends(require_admin)):
    updates = {}
    if payload.shift_start is not None:
        if payload.shift_start == "":
            updates["shift_start"] = None
        elif parse_hhmm(payload.shift_start):
            updates["shift_start"] = payload.shift_start
        else:
            raise HTTPException(status_code=400, detail="Invalid shift_start (use HH:MM)")
    if payload.shift_end is not None:
        if payload.shift_end == "":
            updates["shift_end"] = None
        elif parse_hhmm(payload.shift_end):
            updates["shift_end"] = payload.shift_end
        else:
            raise HTTPException(status_code=400, detail="Invalid shift_end (use HH:MM)")
    if payload.break_max_minutes is not None:
        if payload.break_max_minutes < 0 or payload.break_max_minutes > 600:
            raise HTTPException(status_code=400, detail="break_max_minutes 0-600")
        updates["break_max_minutes"] = payload.break_max_minutes
    if payload.timezone is not None:
        try:
            ZoneInfo(payload.timezone)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid timezone") from None
        updates["timezone"] = payload.timezone
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    res = await db.users.update_one({"user_id": user_id}, {"$set": updates})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="User not found")
    emp = await db.users.find_one({"user_id": user_id}, {"_id": 0, "face_descriptor": 0})
    return {"ok": True, "employee": emp}

@api_router.patch("/admin/employees/{user_id}/tracking_mode")
async def admin_set_tracking_mode(user_id: str, payload: TrackingModeUpdate, user: dict = Depends(require_admin)):
    if payload.tracking_mode not in ("duty_only", "always_on"):
        raise HTTPException(status_code=400, detail="tracking_mode must be 'duty_only' or 'always_on'")
    res = await db.users.update_one({"user_id": user_id}, {"$set": {"tracking_mode": payload.tracking_mode}})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="User not found")
    emp = await db.users.find_one({"user_id": user_id}, {"_id": 0, "face_descriptor": 0})
    return {"ok": True, "employee": emp}


@api_router.get("/admin/employees/{user_id}/route")
async def admin_employee_route(user_id: str, date: Optional[str] = None, user: dict = Depends(require_admin)):
    emp = await db.users.find_one({"user_id": user_id}, {"_id": 0, "face_descriptor": 0})
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    d = date or user_local_today(emp)
    pings = await db.locations.find(
        {"user_id": user_id, "date": d}, {"_id": 0}
    ).sort("timestamp", 1).to_list(5000)
    attendance = await db.attendance.find(
        {"user_id": user_id, "date": d}, {"_id": 0}
    ).sort("check_in", 1).to_list(100)
    return {"employee": emp, "date": d, "pings": pings, "attendance": attendance}

@api_router.get("/admin/attendance")
async def admin_attendance(date: Optional[str] = None, user: dict = Depends(require_admin)):
    d = date or user_local_today(user)
    records = await db.attendance.find({"date": d}, {"_id": 0}).sort("check_in", 1).to_list(5000)
    user_ids = list({r["user_id"] for r in records})
    users = await db.users.find({"user_id": {"$in": user_ids}}, {"_id": 0, "face_descriptor": 0}).to_list(1000)
    umap = {u["user_id"]: u for u in users}
    for r in records:
        u = umap.get(r["user_id"], {})
        r["name"] = u.get("name", "")
        r["email"] = u.get("email", "")
        r["picture"] = u.get("picture")
        r["shift_start"] = u.get("shift_start")
        r["shift_end"] = u.get("shift_end")
    return {"date": d, "records": records}

@api_router.delete("/admin/employees/{user_id}/face")
async def admin_reset_face(user_id: str, user: dict = Depends(require_admin)):
    res = await db.users.update_one(
        {"user_id": user_id},
        {"$set": {"face_enrolled": False, "face_descriptor": None, "face_photo_path": None}}
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="User not found")
    return {"ok": True}

# ---------- Reports ----------
async def build_report(from_date: str, to_date: str) -> List[dict]:
    """Build per-employee aggregated report for date range (inclusive)."""
    users = await db.users.find({}, {"_id": 0, "face_descriptor": 0}).to_list(1000)
    # All records in range
    records = await db.attendance.find(
        {"date": {"$gte": from_date, "$lte": to_date}}, {"_id": 0}
    ).to_list(20000)
    by_user = {}
    for r in records:
        by_user.setdefault(r["user_id"], []).append(r)

    # Generate date list
    d_from = datetime.fromisoformat(from_date).date()
    d_to = datetime.fromisoformat(to_date).date()
    total_days = (d_to - d_from).days + 1
    all_dates = {(d_from + timedelta(days=i)).isoformat() for i in range(total_days)}

    rows = []
    for u in users:
        recs = by_user.get(u["user_id"], [])
        present_dates = {r["date"] for r in recs}
        absent_days = len(all_dates - present_dates)
        late_days = sum(1 for r in recs if (r.get("late_by_minutes") or 0) > 0)
        total_late = sum((r.get("late_by_minutes") or 0) for r in recs)
        total_work = sum((r.get("net_work_minutes") or 0) for r in recs)
        total_break = sum((r.get("total_break_minutes") or 0) for r in recs)
        over_break_days = sum(1 for r in recs if r.get("over_break"))
        rows.append({
            "user_id": u["user_id"],
            "name": u.get("name", ""),
            "email": u.get("email", ""),
            "shift_start": u.get("shift_start"),
            "shift_end": u.get("shift_end"),
            "break_max_minutes": u.get("break_max_minutes", 60),
            "present_days": len(present_dates),
            "absent_days": absent_days,
            "late_days": late_days,
            "total_late_minutes": total_late,
            "total_work_minutes": total_work,
            "total_break_minutes": total_break,
            "over_break_days": over_break_days,
            "sessions": len(recs),
        })
    rows.sort(key=lambda x: x["name"].lower())
    return rows

@api_router.get("/admin/reports")
async def admin_reports(
    from_date: str = Query(..., alias="from"),
    to_date: str = Query(..., alias="to"),
    user: dict = Depends(require_admin),
):
    rows = await build_report(from_date, to_date)
    return {"from": from_date, "to": to_date, "rows": rows}

@api_router.get("/admin/reports.csv")
async def admin_reports_csv(
    from_date: str = Query(..., alias="from"),
    to_date: str = Query(..., alias="to"),
    request: Request = None,
    auth: Optional[str] = Query(None),
):
    # Manual auth so we can support browser download with ?auth= token
    token = request.cookies.get("session_token") if request else None
    if not token:
        token = auth
    if not token and request:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    session = await db.user_sessions.find_one({"session_token": token}, {"_id": 0})
    if not session:
        raise HTTPException(status_code=401, detail="Invalid session")
    u = await db.users.find_one({"user_id": session["user_id"]}, {"_id": 0})
    if not u or u.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin only")

    rows = await build_report(from_date, to_date)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "Employee", "Email", "Shift Start", "Shift End", "Break Limit (min)",
        "Present Days", "Absent Days", "Late Days", "Total Late (min)",
        "Total Work (h:m)", "Total Break (min)", "Over-Break Days", "Sessions",
    ])
    for r in rows:
        hours = (r["total_work_minutes"] or 0) // 60
        mins = (r["total_work_minutes"] or 0) % 60
        writer.writerow([
            r["name"], r["email"], r["shift_start"] or "", r["shift_end"] or "",
            r["break_max_minutes"], r["present_days"], r["absent_days"],
            r["late_days"], r["total_late_minutes"],
            f"{hours}h {mins}m", r["total_break_minutes"], r["over_break_days"], r["sessions"],
        ])
    buf.seek(0)
    filename = f"attendance_report_{from_date}_to_{to_date}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )

@api_router.get("/")
async def root():
    return {"message": "Kelasa API", "status": "ok"}

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
