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
from datetime import datetime, timezone, timedelta, time as dtime, date as ddate
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

class EmployeeCreate(BaseModel):
    name: str
    email: str
    department: Optional[str] = None
    site: Optional[str] = None
    manager_id: Optional[str] = None
    designation: Optional[str] = None
    phone: Optional[str] = None
    employee_code: Optional[str] = None
    role: str = "employee"
    shift_start: Optional[str] = None
    shift_end: Optional[str] = None
    break_max_minutes: Optional[int] = 60

class AssignmentUpdate(BaseModel):
    department: Optional[str] = None
    site: Optional[str] = None
    manager_id: Optional[str] = None
    designation: Optional[str] = None
    phone: Optional[str] = None
    employee_code: Optional[str] = None

class ScopeUpdate(BaseModel):
    managed_departments: List[str] = []
    managed_sites: List[str] = []

class OrgUnitIn(BaseModel):
    name: str

class LeaveTypeIn(BaseModel):
    name: str
    code: str
    policy: str = "yearly"  # yearly | monthly | none
    annual_quota: float = 0
    monthly_accrual: float = 0
    paid: bool = True
    color: Optional[str] = "#0047FF"

class LeaveRequestIn(BaseModel):
    type_id: str
    start_date: str
    end_date: str
    half_day: bool = False
    reason: Optional[str] = ""

class LeaveDecision(BaseModel):
    status: str  # approved | rejected
    note: Optional[str] = ""

class HolidayIn(BaseModel):
    date: str
    name: str

class AnnouncementIn(BaseModel):
    title: str
    body: str
    pinned: bool = False

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

async def require_manager(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") not in ("admin", "sub_admin"):
        raise HTTPException(status_code=403, detail="Admin access required")
    return user

async def scoped_user_ids(actor: dict):
    """None = unrestricted (full admin). Otherwise the set of user_ids this sub-admin manages."""
    if actor.get("role") == "admin":
        return None
    conds = [{"manager_id": actor["user_id"]}]
    depts = actor.get("managed_departments") or []
    sites = actor.get("managed_sites") or []
    if depts:
        conds.append({"department": {"$in": depts}})
    if sites:
        conds.append({"site": {"$in": sites}})
    docs = await db.users.find({"$or": conds}, {"_id": 0, "user_id": 1}).to_list(5000)
    ids = {d["user_id"] for d in docs}
    ids.add(actor["user_id"])
    return ids

def user_filter(ids):
    return {} if ids is None else {"user_id": {"$in": list(ids)}}

async def ensure_in_scope(actor: dict, target_user_id: str):
    ids = await scoped_user_ids(actor)
    if ids is not None and target_user_id not in ids:
        raise HTTPException(status_code=403, detail="This employee is not in your team")

async def ensure_manages_other(actor: dict, target_user_id: str):
    """Scope check that also stops a sub-admin editing their own record."""
    if actor.get("role") != "admin" and target_user_id == actor["user_id"]:
        raise HTTPException(status_code=403, detail="Only an admin can change your own settings")
    await ensure_in_scope(actor, target_user_id)

async def log_activity(actor: dict, action: str, target_name: str = "", details: str = ""):
    await db.activity_log.insert_one({
        "log_id": f"log_{uuid.uuid4().hex[:12]}",
        "actor_id": actor["user_id"],
        "actor_name": actor.get("name"),
        "actor_role": actor.get("role"),
        "action": action,
        "target_name": target_name,
        "details": details,
        "created_at": now_utc().isoformat(),
    })

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
            {"$set": {"name": name, "picture": picture, "pending_invite": False}}
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
async def admin_stats(user: dict = Depends(require_manager)):
    today = user_local_today(user)
    ids = await scoped_user_ids(user)
    uf = user_filter(ids)
    total_employees = await db.users.count_documents(uf)
    on_duty = await db.attendance.count_documents({"check_out": None, **uf})
    today_checkins = await db.attendance.count_documents({"date": today, **uf})
    pipeline = [
        {"$match": {"date": today, "net_work_minutes": {"$exists": True}, **uf}},
        {"$group": {"_id": None, "total": {"$sum": "$net_work_minutes"}}}
    ]
    cursor = db.attendance.aggregate(pipeline)
    total_minutes = 0
    async for row in cursor:
        total_minutes = row.get("total", 0)
    late_today = await db.attendance.count_documents({"date": today, "late_by_minutes": {"$gt": 0}, **uf})
    leave_q = {"status": "approved", "start_date": {"$lte": today}, "end_date": {"$gte": today}, **uf}
    on_leave_today = await db.leave_requests.count_documents(leave_q)
    pending_leave = await db.leave_requests.count_documents({"status": "pending", **uf})
    return {
        "total_employees": total_employees,
        "on_duty": on_duty,
        "today_checkins": today_checkins,
        "total_work_minutes_today": total_minutes,
        "late_today": late_today,
        "on_leave_today": on_leave_today,
        "pending_leave": pending_leave,
    }

@api_router.get("/admin/employees")
async def admin_employees(user: dict = Depends(require_manager)):
    ids = await scoped_user_ids(user)
    uf = user_filter(ids)
    users = await db.users.find(uf, {"_id": 0, "face_descriptor": 0}).sort("created_at", -1).to_list(1000)
    today = user_local_today(user)
    actives = await db.attendance.find({"check_out": None, **uf}, {"_id": 0}).to_list(1000)
    active_map = {a["user_id"]: a for a in actives}
    today_records = await db.attendance.find({"date": today, **uf}, {"_id": 0}).to_list(5000)
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
        u.setdefault("department", None)
        u.setdefault("site", None)
        u.setdefault("manager_id", None)
        u.setdefault("designation", None)
        u.setdefault("phone", None)
        u.setdefault("employee_code", None)
        u.setdefault("pending_invite", False)
    return {"employees": users}

@api_router.patch("/admin/employees/{user_id}/role")
async def admin_set_role(user_id: str, payload: RoleUpdate, user: dict = Depends(require_admin)):
    if payload.role not in ("admin", "sub_admin", "employee"):
        raise HTTPException(status_code=400, detail="Invalid role")
    if user_id == user["user_id"] and payload.role != "admin":
        raise HTTPException(status_code=400, detail="Cannot demote yourself")
    target = await db.users.find_one({"user_id": user_id}, {"_id": 0, "name": 1})
    res = await db.users.update_one({"user_id": user_id}, {"$set": {"role": payload.role}})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="User not found")
    await log_activity(user, "role_changed", (target or {}).get("name", user_id), f"→ {payload.role}")
    return {"ok": True}

@api_router.patch("/admin/employees/{user_id}/shift")
async def admin_set_shift(user_id: str, payload: ShiftUpdate, user: dict = Depends(require_manager)):
    await ensure_manages_other(user, user_id)
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
    await log_activity(user, "shift_updated", (emp or {}).get("name", user_id), ", ".join(f"{k}={v}" for k, v in updates.items()))
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


@api_router.get("/admin/live")
async def admin_live(user: dict = Depends(require_manager)):
    """All currently on-duty employees with their latest known location."""
    ids = await scoped_user_ids(user)
    actives = await db.attendance.find({"check_out": None, **user_filter(ids)}, {"_id": 0}).to_list(1000)
    result = []
    for a in actives:
        emp = await db.users.find_one(
            {"user_id": a["user_id"]}, {"_id": 0, "face_descriptor": 0}
        )
        if not emp:
            continue
        latest = await db.locations.find_one(
            {"user_id": a["user_id"], "record_id": a["record_id"]},
            {"_id": 0}, sort=[("timestamp", -1)]
        )
        hour_ago = (now_utc() - timedelta(hours=1)).isoformat()
        trail_docs = await db.locations.find(
            {"user_id": a["user_id"], "record_id": a["record_id"], "timestamp": {"$gte": hour_ago}},
            {"_id": 0, "lat": 1, "lng": 1, "timestamp": 1}
        ).sort("timestamp", 1).to_list(2000)
        trail = [{"lat": t["lat"], "lng": t["lng"], "timestamp": t["timestamp"]} for t in trail_docs]
        result.append({
            "user_id": a["user_id"],
            "name": emp.get("name"),
            "email": emp.get("email"),
            "picture": emp.get("picture"),
            "face_photo_path": emp.get("face_photo_path"),
            "on_break": bool(a.get("on_break")),
            "check_in": a.get("check_in"),
            "shift_start": emp.get("shift_start"),
            "shift_end": emp.get("shift_end"),
            "lat": latest.get("lat") if latest else None,
            "lng": latest.get("lng") if latest else None,
            "accuracy": latest.get("accuracy") if latest else None,
            "last_ping": latest.get("timestamp") if latest else None,
            "trail": trail,
        })
    return {"employees": result, "server_time": now_utc().isoformat()}

@api_router.get("/admin/employees/{user_id}/route")
async def admin_employee_route(user_id: str, date: Optional[str] = None, user: dict = Depends(require_manager)):
    await ensure_in_scope(user, user_id)
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
async def admin_attendance(date: Optional[str] = None, user: dict = Depends(require_manager)):
    d = date or user_local_today(user)
    ids = await scoped_user_ids(user)
    records = await db.attendance.find({"date": d, **user_filter(ids)}, {"_id": 0}).sort("check_in", 1).to_list(5000)
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
async def admin_reset_face(user_id: str, user: dict = Depends(require_manager)):
    await ensure_manages_other(user, user_id)
    res = await db.users.update_one(
        {"user_id": user_id},
        {"$set": {"face_enrolled": False, "face_descriptor": None, "face_photo_path": None}}
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="User not found")
    return {"ok": True}

# ---------- Organisation ----------
@api_router.get("/admin/org")
async def admin_org(user: dict = Depends(require_manager)):
    depts = await db.departments.find({}, {"_id": 0}).sort("name", 1).to_list(500)
    sites = await db.sites.find({}, {"_id": 0}).sort("name", 1).to_list(500)
    managers = await db.users.find(
        {"role": {"$in": ["admin", "sub_admin"]}}, {"_id": 0, "user_id": 1, "name": 1, "role": 1, "managed_departments": 1, "managed_sites": 1}
    ).sort("name", 1).to_list(500)
    return {"departments": depts, "sites": sites, "managers": managers}

@api_router.post("/admin/org/departments")
async def add_department(payload: OrgUnitIn, user: dict = Depends(require_admin)):
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name required")
    if await db.departments.find_one({"name": name}):
        raise HTTPException(status_code=400, detail="Department already exists")
    doc = {"unit_id": f"dept_{uuid.uuid4().hex[:10]}", "name": name, "created_at": now_utc().isoformat()}
    await db.departments.insert_one(doc)
    await log_activity(user, "department_added", name)
    return {"ok": True, "department": {k: v for k, v in doc.items() if k != "_id"}}

@api_router.delete("/admin/org/departments/{unit_id}")
async def delete_department(unit_id: str, user: dict = Depends(require_admin)):
    doc = await db.departments.find_one({"unit_id": unit_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Not found")
    await db.departments.delete_one({"unit_id": unit_id})
    await db.users.update_many({"department": doc["name"]}, {"$set": {"department": None}})
    await log_activity(user, "department_removed", doc["name"])
    return {"ok": True}

@api_router.post("/admin/org/sites")
async def add_site(payload: OrgUnitIn, user: dict = Depends(require_admin)):
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name required")
    if await db.sites.find_one({"name": name}):
        raise HTTPException(status_code=400, detail="Site already exists")
    doc = {"unit_id": f"site_{uuid.uuid4().hex[:10]}", "name": name, "created_at": now_utc().isoformat()}
    await db.sites.insert_one(doc)
    await log_activity(user, "site_added", name)
    return {"ok": True, "site": {k: v for k, v in doc.items() if k != "_id"}}

@api_router.delete("/admin/org/sites/{unit_id}")
async def delete_site(unit_id: str, user: dict = Depends(require_admin)):
    doc = await db.sites.find_one({"unit_id": unit_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Not found")
    await db.sites.delete_one({"unit_id": unit_id})
    await db.users.update_many({"site": doc["name"]}, {"$set": {"site": None}})
    await log_activity(user, "site_removed", doc["name"])
    return {"ok": True}

# ---------- Employee management ----------
@api_router.post("/admin/employees")
async def admin_create_employee(payload: EmployeeCreate, user: dict = Depends(require_manager)):
    email = payload.email.strip().lower()
    if "@" not in email:
        raise HTTPException(status_code=400, detail="Valid email required")
    if await db.users.find_one({"email": email}):
        raise HTTPException(status_code=400, detail="An employee with this email already exists")
    role = payload.role if payload.role in ("admin", "sub_admin", "employee") else "employee"
    if user.get("role") != "admin":
        role = "employee"
    user_id = f"user_{uuid.uuid4().hex[:12]}"
    doc = {
        "user_id": user_id,
        "email": email,
        "name": payload.name.strip() or email,
        "picture": None,
        "role": role,
        "face_enrolled": False,
        "face_descriptor": None,
        "face_photo_path": None,
        "shift_start": payload.shift_start or None,
        "shift_end": payload.shift_end or None,
        "break_max_minutes": payload.break_max_minutes if payload.break_max_minutes is not None else 60,
        "timezone": DEFAULT_TZ,
        "tracking_mode": "duty_only",
        "department": payload.department or None,
        "site": payload.site or None,
        "manager_id": payload.manager_id or (None if user.get("role") == "admin" else user["user_id"]),
        "designation": payload.designation or None,
        "phone": payload.phone or None,
        "employee_code": payload.employee_code or None,
        "pending_invite": True,
        "created_at": now_utc().isoformat(),
        "created_by": user["user_id"],
    }
    await db.users.insert_one(doc)
    await log_activity(user, "employee_added", doc["name"], email)
    return {"ok": True, "employee": {k: v for k, v in doc.items() if k not in ("_id", "face_descriptor")}}

@api_router.delete("/admin/employees/{user_id}")
async def admin_delete_employee(user_id: str, user: dict = Depends(require_manager)):
    await ensure_in_scope(user, user_id)
    if user_id == user["user_id"]:
        raise HTTPException(status_code=400, detail="You cannot remove your own account")
    emp = await db.users.find_one({"user_id": user_id}, {"_id": 0, "name": 1, "role": 1})
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    if emp.get("role") == "admin" and user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Only an admin can remove another admin")
    await db.users.delete_one({"user_id": user_id})
    await db.user_sessions.delete_many({"user_id": user_id})
    await db.attendance.delete_many({"user_id": user_id})
    await db.locations.delete_many({"user_id": user_id})
    await db.leave_requests.delete_many({"user_id": user_id})
    await db.users.update_many({"manager_id": user_id}, {"$set": {"manager_id": None}})
    await log_activity(user, "employee_removed", emp.get("name", user_id))
    return {"ok": True}

@api_router.patch("/admin/employees/{user_id}/assignment")
async def admin_set_assignment(user_id: str, payload: AssignmentUpdate, user: dict = Depends(require_manager)):
    await ensure_manages_other(user, user_id)
    updates = {k: (v or None) for k, v in payload.model_dump(exclude_unset=True).items()}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    res = await db.users.update_one({"user_id": user_id}, {"$set": updates})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Employee not found")
    emp = await db.users.find_one({"user_id": user_id}, {"_id": 0, "face_descriptor": 0})
    await log_activity(user, "employee_assigned", emp.get("name", user_id), ", ".join(f"{k}={v}" for k, v in updates.items()))
    return {"ok": True, "employee": emp}

@api_router.patch("/admin/employees/{user_id}/scope")
async def admin_set_scope(user_id: str, payload: ScopeUpdate, user: dict = Depends(require_admin)):
    emp = await db.users.find_one({"user_id": user_id}, {"_id": 0, "name": 1, "role": 1})
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    await db.users.update_one({"user_id": user_id}, {"$set": {
        "managed_departments": payload.managed_departments,
        "managed_sites": payload.managed_sites,
    }})
    await log_activity(user, "scope_updated", emp.get("name", user_id),
                       f"departments={payload.managed_departments}, sites={payload.managed_sites}")
    return {"ok": True}

# ---------- Leave ----------
DEFAULT_LEAVE_TYPES = [
    {"code": "CL", "name": "Casual Leave", "policy": "yearly", "annual_quota": 12, "monthly_accrual": 0, "paid": True, "color": "#0047FF"},
    {"code": "SL", "name": "Sick Leave", "policy": "yearly", "annual_quota": 6, "monthly_accrual": 0, "paid": True, "color": "#FF3B30"},
    {"code": "EL", "name": "Earned Leave", "policy": "monthly", "annual_quota": 0, "monthly_accrual": 1.5, "paid": True, "color": "#00A86B"},
    {"code": "LOP", "name": "Unpaid Leave", "policy": "none", "annual_quota": 0, "monthly_accrual": 0, "paid": False, "color": "#52525B"},
]

async def seed_leave_types():
    if await db.leave_types.count_documents({}) == 0:
        for t in DEFAULT_LEAVE_TYPES:
            await db.leave_types.insert_one({
                "type_id": f"lt_{uuid.uuid4().hex[:10]}", "active": True,
                "created_at": now_utc().isoformat(), **t,
            })
        logger.info("Seeded default leave types")

def count_leave_days_raw(start: str, end: str, half_day: bool) -> float:
    try:
        d1 = ddate.fromisoformat(start)
        d2 = ddate.fromisoformat(end)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid dates (use YYYY-MM-DD)") from None
    if d2 < d1:
        raise HTTPException(status_code=400, detail="End date is before start date")
    n = (d2 - d1).days + 1
    if n > 60:
        raise HTTPException(status_code=400, detail="Leave cannot exceed 60 days")
    if half_day:
        if n != 1:
            raise HTTPException(status_code=400, detail="Half-day applies to a single date only")
        return 0.5
    return float(n)

async def count_leave_days(start: str, end: str, half_day: bool) -> float:
    """Calendar days minus any declared company holidays inside the range."""
    days = count_leave_days_raw(start, end, half_day)
    if half_day:
        return days
    holidays = await db.holidays.count_documents({"date": {"$gte": start, "$lte": end}})
    net = days - holidays
    if net <= 0:
        raise HTTPException(status_code=400, detail="Those dates are already company holidays")
    return float(net)

def fmt_days(n: float) -> str:
    return str(int(n)) if float(n).is_integer() else str(n)

async def leave_balances_for(user_id: str, year: int, ltypes=None) -> List[dict]:
    if ltypes is None:
        ltypes = await db.leave_types.find({"active": True}, {"_id": 0}).to_list(100)
    reqs = await db.leave_requests.find(
        {"user_id": user_id, "year": year, "status": {"$in": ["approved", "pending"]}}, {"_id": 0}
    ).to_list(2000)
    now_local = datetime.now(ZoneInfo(DEFAULT_TZ))
    months = 12 if now_local.year > year else (0 if now_local.year < year else now_local.month)
    out = []
    for t in ltypes:
        used = sum(r["days"] for r in reqs if r["type_id"] == t["type_id"] and r["status"] == "approved")
        pending = sum(r["days"] for r in reqs if r["type_id"] == t["type_id"] and r["status"] == "pending")
        if t["policy"] == "yearly":
            entitled = float(t.get("annual_quota") or 0)
        elif t["policy"] == "monthly":
            entitled = round(float(t.get("monthly_accrual") or 0) * months, 1)
        else:
            entitled = None
        out.append({
            "type_id": t["type_id"], "name": t["name"], "code": t["code"], "policy": t["policy"],
            "color": t.get("color"), "paid": t.get("paid", True),
            "entitled": entitled, "used": used, "pending": pending,
            "available": None if entitled is None else round(entitled - used - pending, 1),
        })
    return out

@api_router.get("/leave/types")
async def leave_types(user: dict = Depends(get_current_user)):
    types = await db.leave_types.find({"active": True}, {"_id": 0}).to_list(100)
    return {"types": types}

@api_router.get("/leave/balance")
async def my_leave_balance(user: dict = Depends(get_current_user), year: Optional[int] = None):
    y = year or datetime.now(ZoneInfo(DEFAULT_TZ)).year
    return {"year": y, "balances": await leave_balances_for(user["user_id"], y)}

@api_router.get("/leave/me")
async def my_leave_requests(user: dict = Depends(get_current_user), limit: int = 100):
    reqs = await db.leave_requests.find({"user_id": user["user_id"]}, {"_id": 0}).sort("created_at", -1).to_list(limit)
    return {"requests": reqs}

@api_router.post("/leave/request")
async def create_leave_request(payload: LeaveRequestIn, user: dict = Depends(get_current_user)):
    ltype = await db.leave_types.find_one({"type_id": payload.type_id, "active": True}, {"_id": 0})
    if not ltype:
        raise HTTPException(status_code=400, detail="Invalid leave type")
    days = await count_leave_days(payload.start_date, payload.end_date, payload.half_day)
    overlap = await db.leave_requests.find_one({
        "user_id": user["user_id"],
        "status": {"$in": ["approved", "pending"]},
        "start_date": {"$lte": payload.end_date},
        "end_date": {"$gte": payload.start_date},
    }, {"_id": 0})
    if overlap:
        raise HTTPException(status_code=400, detail="You already have a leave request covering these dates")
    year = ddate.fromisoformat(payload.start_date).year
    if ltype["policy"] != "none":
        balances = await leave_balances_for(user["user_id"], year)
        bal = next((b for b in balances if b["type_id"] == ltype["type_id"]), None)
        if bal and bal["available"] is not None and days > bal["available"]:
            raise HTTPException(status_code=400, detail=f"Only {fmt_days(bal['available'])} day(s) of {ltype['name']} left")
    doc = {
        "leave_id": f"lv_{uuid.uuid4().hex[:12]}",
        "user_id": user["user_id"],
        "user_name": user.get("name"),
        "type_id": ltype["type_id"],
        "type_name": ltype["name"],
        "type_code": ltype["code"],
        "start_date": payload.start_date,
        "end_date": payload.end_date,
        "half_day": payload.half_day,
        "days": days,
        "year": year,
        "reason": (payload.reason or "").strip(),
        "status": "pending",
        "decided_by": None,
        "decided_by_name": None,
        "decision_note": None,
        "decided_at": None,
        "created_at": now_utc().isoformat(),
    }
    await db.leave_requests.insert_one(doc)
    return {"ok": True, "request": {k: v for k, v in doc.items() if k != "_id"}}

@api_router.post("/leave/{leave_id}/cancel")
async def cancel_leave_request(leave_id: str, user: dict = Depends(get_current_user)):
    req = await db.leave_requests.find_one({"leave_id": leave_id}, {"_id": 0})
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")
    if req["user_id"] != user["user_id"]:
        if user.get("role") not in ("admin", "sub_admin"):
            raise HTTPException(status_code=403, detail="Not allowed")
        await ensure_in_scope(user, req["user_id"])
    if req["status"] not in ("pending", "approved"):
        raise HTTPException(status_code=400, detail="Already closed")
    await db.leave_requests.update_one({"leave_id": leave_id}, {"$set": {
        "status": "cancelled",
        "cancelled_by": user["user_id"],
        "cancelled_by_name": user.get("name"),
        "decided_at": now_utc().isoformat(),
    }})
    if req["user_id"] != user["user_id"]:
        await log_activity(user, "leave_cancelled", req.get("user_name", req["user_id"]),
                           f"{req['type_name']} {req['start_date']}→{req['end_date']}")
    return {"ok": True}

@api_router.get("/admin/leave")
async def admin_leave_list(
    status: Optional[str] = None,
    user: dict = Depends(require_manager),
):
    ids = await scoped_user_ids(user)
    q = dict(user_filter(ids))
    if status and status != "all":
        q["status"] = status
    reqs = await db.leave_requests.find(q, {"_id": 0}).sort("created_at", -1).to_list(1000)
    emp_ids = list({r["user_id"] for r in reqs})
    emps = await db.users.find({"user_id": {"$in": emp_ids}}, {"_id": 0, "face_descriptor": 0}).to_list(1000)
    emap = {e["user_id"]: e for e in emps}
    for r in reqs:
        e = emap.get(r["user_id"], {})
        r["user_name"] = e.get("name", r.get("user_name"))
        r["email"] = e.get("email")
        r["picture"] = e.get("picture")
        r["department"] = e.get("department")
        r["site"] = e.get("site")
    pending = sum(1 for r in reqs if r["status"] == "pending" and r["user_id"] != user["user_id"])
    return {"requests": reqs, "pending_count": pending}

@api_router.post("/admin/leave/{leave_id}/decide")
async def admin_decide_leave(leave_id: str, payload: LeaveDecision, user: dict = Depends(require_manager)):
    if payload.status not in ("approved", "rejected"):
        raise HTTPException(status_code=400, detail="status must be approved or rejected")
    req = await db.leave_requests.find_one({"leave_id": leave_id}, {"_id": 0})
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")
    if req["status"] != "pending":
        raise HTTPException(status_code=400, detail="This request has already been decided")
    if req["user_id"] == user["user_id"]:
        raise HTTPException(status_code=403, detail="You cannot decide on your own leave request")
    # NOTE: deliberate product choice — any admin or sub-admin can decide anyone's leave.
    await db.leave_requests.update_one({"leave_id": leave_id}, {"$set": {
        "status": payload.status,
        "decided_by": user["user_id"],
        "decided_by_name": user.get("name"),
        "decision_note": (payload.note or "").strip(),
        "decided_at": now_utc().isoformat(),
    }})
    await log_activity(user, f"leave_{payload.status}", req.get("user_name", req["user_id"]),
                       f"{req['type_name']} {req['start_date']}→{req['end_date']} ({req['days']}d)")
    return {"ok": True}

@api_router.get("/admin/leave/balances")
async def admin_leave_balances(user: dict = Depends(require_manager), year: Optional[int] = None):
    y = year or datetime.now(ZoneInfo(DEFAULT_TZ)).year
    ids = await scoped_user_ids(user)
    emps = await db.users.find(user_filter(ids), {"_id": 0, "user_id": 1, "name": 1, "email": 1, "department": 1}).sort("name", 1).to_list(1000)
    ltypes = await db.leave_types.find({"active": True}, {"_id": 0}).to_list(100)
    rows = []
    for e in emps:
        rows.append({**e, "balances": await leave_balances_for(e["user_id"], y, ltypes)})
    return {"year": y, "rows": rows, "types": ltypes}

@api_router.post("/admin/leave-types")
async def create_leave_type(payload: LeaveTypeIn, user: dict = Depends(require_admin)):
    if payload.policy not in ("yearly", "monthly", "none"):
        raise HTTPException(status_code=400, detail="policy must be yearly, monthly or none")
    code = payload.code.strip().upper()
    if await db.leave_types.find_one({"code": code, "active": True}):
        raise HTTPException(status_code=400, detail="A leave type with this code already exists")
    doc = {
        "type_id": f"lt_{uuid.uuid4().hex[:10]}",
        "name": payload.name.strip(), "code": code, "policy": payload.policy,
        "annual_quota": payload.annual_quota, "monthly_accrual": payload.monthly_accrual,
        "paid": payload.paid, "color": payload.color or "#0047FF",
        "active": True, "created_at": now_utc().isoformat(),
    }
    await db.leave_types.insert_one(doc)
    await log_activity(user, "leave_type_added", doc["name"], f"{payload.policy}")
    return {"ok": True, "type": {k: v for k, v in doc.items() if k != "_id"}}

@api_router.patch("/admin/leave-types/{type_id}")
async def update_leave_type(type_id: str, payload: LeaveTypeIn, user: dict = Depends(require_admin)):
    if payload.policy not in ("yearly", "monthly", "none"):
        raise HTTPException(status_code=400, detail="policy must be yearly, monthly or none")
    code = payload.code.strip().upper()
    clash = await db.leave_types.find_one({"code": code, "active": True, "type_id": {"$ne": type_id}})
    if clash:
        raise HTTPException(status_code=400, detail="A leave type with this code already exists")
    res = await db.leave_types.update_one({"type_id": type_id}, {"$set": {
        "name": payload.name.strip(), "code": code, "policy": payload.policy,
        "annual_quota": payload.annual_quota, "monthly_accrual": payload.monthly_accrual,
        "paid": payload.paid, "color": payload.color or "#0047FF",
    }})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Leave type not found")
    await log_activity(user, "leave_type_updated", payload.name)
    return {"ok": True}

@api_router.delete("/admin/leave-types/{type_id}")
async def delete_leave_type(type_id: str, user: dict = Depends(require_admin)):
    t = await db.leave_types.find_one({"type_id": type_id}, {"_id": 0})
    if not t:
        raise HTTPException(status_code=404, detail="Leave type not found")
    await db.leave_types.update_one({"type_id": type_id}, {"$set": {"active": False}})
    await log_activity(user, "leave_type_removed", t["name"])
    return {"ok": True}

# ---------- Holiday calendar ----------
@api_router.get("/holidays")
async def list_holidays(user: dict = Depends(get_current_user), year: Optional[int] = None):
    y = year or datetime.now(ZoneInfo(DEFAULT_TZ)).year
    docs = await db.holidays.find(
        {"date": {"$gte": f"{y}-01-01", "$lte": f"{y}-12-31"}}, {"_id": 0}
    ).sort("date", 1).to_list(400)
    return {"year": y, "holidays": docs}

@api_router.post("/admin/holidays")
async def add_holiday(payload: HolidayIn, user: dict = Depends(require_admin)):
    try:
        ddate.fromisoformat(payload.date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date") from None
    if await db.holidays.find_one({"date": payload.date}):
        raise HTTPException(status_code=400, detail="A holiday already exists on this date")
    doc = {"holiday_id": f"hol_{uuid.uuid4().hex[:10]}", "date": payload.date,
           "name": payload.name.strip(), "created_at": now_utc().isoformat()}
    await db.holidays.insert_one(doc)
    await log_activity(user, "holiday_added", doc["name"], doc["date"])
    return {"ok": True, "holiday": {k: v for k, v in doc.items() if k != "_id"}}

@api_router.delete("/admin/holidays/{holiday_id}")
async def delete_holiday(holiday_id: str, user: dict = Depends(require_admin)):
    doc = await db.holidays.find_one({"holiday_id": holiday_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Not found")
    await db.holidays.delete_one({"holiday_id": holiday_id})
    await log_activity(user, "holiday_removed", doc["name"], doc["date"])
    return {"ok": True}

# ---------- Announcements ----------
@api_router.get("/announcements")
async def list_announcements(user: dict = Depends(get_current_user), limit: int = 20):
    docs = await db.announcements.find({}, {"_id": 0}).sort([("pinned", -1), ("created_at", -1)]).to_list(limit)
    return {"announcements": docs}

@api_router.post("/admin/announcements")
async def add_announcement(payload: AnnouncementIn, user: dict = Depends(require_manager)):
    if not payload.title.strip():
        raise HTTPException(status_code=400, detail="Title required")
    doc = {
        "announcement_id": f"ann_{uuid.uuid4().hex[:10]}",
        "title": payload.title.strip(), "body": payload.body.strip(),
        "pinned": payload.pinned, "author_id": user["user_id"], "author_name": user.get("name"),
        "created_at": now_utc().isoformat(),
    }
    await db.announcements.insert_one(doc)
    await log_activity(user, "announcement_posted", doc["title"])
    return {"ok": True, "announcement": {k: v for k, v in doc.items() if k != "_id"}}

@api_router.delete("/admin/announcements/{announcement_id}")
async def delete_announcement(announcement_id: str, user: dict = Depends(require_manager)):
    doc = await db.announcements.find_one({"announcement_id": announcement_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Not found")
    if user.get("role") != "admin" and doc.get("author_id") != user["user_id"]:
        raise HTTPException(status_code=403, detail="You can only remove your own notices")
    await db.announcements.delete_one({"announcement_id": announcement_id})
    await log_activity(user, "announcement_removed", doc["title"])
    return {"ok": True}

# ---------- Activity log ----------
@api_router.get("/admin/activity")
async def admin_activity(user: dict = Depends(require_admin), limit: int = 200):
    docs = await db.activity_log.find({}, {"_id": 0}).sort("created_at", -1).to_list(limit)
    return {"entries": docs}

# ---------- Analytics ----------
@api_router.get("/admin/analytics")
async def admin_analytics(days: int = 14, user: dict = Depends(require_manager)):
    days = max(3, min(days, 90))
    ids = await scoped_user_ids(user)
    uf = user_filter(ids)
    today_local = datetime.now(ZoneInfo(user.get("timezone") or DEFAULT_TZ)).date()
    start = today_local - timedelta(days=days - 1)
    from_s, to_s = start.isoformat(), today_local.isoformat()

    records = await db.attendance.find(
        {"date": {"$gte": from_s, "$lte": to_s}, **uf}, {"_id": 0}
    ).to_list(20000)
    leaves = await db.leave_requests.find(
        {"status": "approved", "start_date": {"$lte": to_s}, "end_date": {"$gte": from_s}, **uf}, {"_id": 0}
    ).to_list(5000)
    headcount = await db.users.count_documents(uf)

    daily = {}
    for i in range(days):
        d = (start + timedelta(days=i)).isoformat()
        daily[d] = {"date": d, "present": 0, "late": 0, "on_leave": 0, "work_hours": 0.0}
    seen = set()
    for r in records:
        row = daily.get(r["date"])
        if not row:
            continue
        key = (r["date"], r["user_id"])
        if key not in seen:
            seen.add(key)
            row["present"] += 1
            if (r.get("late_by_minutes") or 0) > 0:
                row["late"] += 1
        row["work_hours"] += round((r.get("net_work_minutes") or 0) / 60.0, 2)
    for lv in leaves:
        s = max(ddate.fromisoformat(lv["start_date"]), start)
        e = min(ddate.fromisoformat(lv["end_date"]), today_local)
        cur = s
        while cur <= e:
            row = daily.get(cur.isoformat())
            if row:
                row["on_leave"] += 1
            cur += timedelta(days=1)
    for row in daily.values():
        row["work_hours"] = round(row["work_hours"], 1)

    leave_by_type = {}
    for lv in leaves:
        leave_by_type[lv["type_name"]] = leave_by_type.get(lv["type_name"], 0) + lv["days"]

    dept_rows = await db.users.find(uf, {"_id": 0, "department": 1}).to_list(2000)
    dept_counts = {}
    for d in dept_rows:
        key = d.get("department") or "Unassigned"
        dept_counts[key] = dept_counts.get(key, 0) + 1

    return {
        "from": from_s, "to": to_s, "headcount": headcount,
        "daily": list(daily.values()),
        "leave_by_type": [{"name": k, "days": v} for k, v in sorted(leave_by_type.items(), key=lambda x: -x[1])],
        "departments": [{"name": k, "count": v} for k, v in sorted(dept_counts.items(), key=lambda x: -x[1])],
    }

# ---------- Reports ----------
async def build_report(from_date: str, to_date: str, user_ids=None) -> List[dict]:
    """Build per-employee aggregated report for date range (inclusive)."""
    uf = user_filter(user_ids)
    users = await db.users.find(uf, {"_id": 0, "face_descriptor": 0}).to_list(1000)
    # All records in range
    records = await db.attendance.find(
        {"date": {"$gte": from_date, "$lte": to_date}, **uf}, {"_id": 0}
    ).to_list(20000)
    by_user = {}
    for r in records:
        by_user.setdefault(r["user_id"], []).append(r)

    # Generate date list
    d_from = datetime.fromisoformat(from_date).date()
    d_to = datetime.fromisoformat(to_date).date()
    total_days = (d_to - d_from).days + 1
    all_dates = {(d_from + timedelta(days=i)).isoformat() for i in range(total_days)}

    holiday_docs = await db.holidays.find(
        {"date": {"$gte": from_date, "$lte": to_date}}, {"_id": 0, "date": 1}
    ).to_list(500)
    holiday_dates = {h["date"] for h in holiday_docs}

    leaves = await db.leave_requests.find(
        {"status": "approved", "start_date": {"$lte": to_date}, "end_date": {"$gte": from_date}, **uf}, {"_id": 0}
    ).to_list(20000)
    leave_dates_by_user = {}
    for lv in leaves:
        s = max(datetime.fromisoformat(lv["start_date"]).date(), d_from)
        e = min(datetime.fromisoformat(lv["end_date"]).date(), d_to)
        cur = s
        while cur <= e:
            leave_dates_by_user.setdefault(lv["user_id"], set()).add(cur.isoformat())
            cur += timedelta(days=1)

    rows = []
    for u in users:
        recs = by_user.get(u["user_id"], [])
        present_dates = {r["date"] for r in recs}
        leave_dates = leave_dates_by_user.get(u["user_id"], set())
        absent_days = len(all_dates - present_dates - leave_dates - holiday_dates)
        late_days = sum(1 for r in recs if (r.get("late_by_minutes") or 0) > 0)
        total_late = sum((r.get("late_by_minutes") or 0) for r in recs)
        total_work = sum((r.get("net_work_minutes") or 0) for r in recs)
        total_break = sum((r.get("total_break_minutes") or 0) for r in recs)
        over_break_days = sum(1 for r in recs if r.get("over_break"))
        rows.append({
            "user_id": u["user_id"],
            "name": u.get("name", ""),
            "email": u.get("email", ""),
            "department": u.get("department"),
            "site": u.get("site"),
            "shift_start": u.get("shift_start"),
            "shift_end": u.get("shift_end"),
            "break_max_minutes": u.get("break_max_minutes", 60),
            "present_days": len(present_dates),
            "leave_days": len(leave_dates),
            "holiday_days": len(holiday_dates),
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
    user: dict = Depends(require_manager),
):
    rows = await build_report(from_date, to_date, await scoped_user_ids(user))
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
    if not u or u.get("role") not in ("admin", "sub_admin"):
        raise HTTPException(status_code=403, detail="Admin only")

    rows = await build_report(from_date, to_date, await scoped_user_ids(u))
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "Employee", "Email", "Department", "Site", "Shift Start", "Shift End", "Break Limit (min)",
        "Present Days", "Leave Days", "Holidays", "Absent Days", "Late Days", "Total Late (min)",
        "Total Work (h:m)", "Total Break (min)", "Over-Break Days", "Sessions",
    ])
    for r in rows:
        hours = (r["total_work_minutes"] or 0) // 60
        mins = (r["total_work_minutes"] or 0) % 60
        writer.writerow([
            r["name"], r["email"], r.get("department") or "", r.get("site") or "",
            r["shift_start"] or "", r["shift_end"] or "",
            r["break_max_minutes"], r["present_days"], r["leave_days"], r["holiday_days"], r["absent_days"],
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
    await seed_leave_types()

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
