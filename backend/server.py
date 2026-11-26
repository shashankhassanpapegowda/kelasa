from fastapi import FastAPI, APIRouter, HTTPException, Request, Response, Depends, Query, BackgroundTasks
from fastapi.responses import StreamingResponse
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
import uuid
import math
import base64
import binascii
import io
import csv
import httpx
import requests
import bcrypt
import secrets as pysecrets
import hmac
from pymongo.errors import DuplicateKeyError
import re
import ipaddress
from html import escape
from html.parser import HTMLParser
from urllib.parse import urlparse
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict
from typing import List, Literal, Optional
from datetime import datetime, timezone, timedelta, time as dtime, date as ddate
from zoneinfo import ZoneInfo
import json
import asyncio
from pywebpush import webpush, WebPushException
import export_job
from fastapi.responses import FileResponse
from attendance_calc import shift_minutes, compute_session, session_cap, day_status, DEFAULT_WEEKLY_OFF

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
STORAGE_BASE = (os.environ.get("INTEGRATION_PROXY_URL") or "").strip() or "https://integrations.emergentagent.com"
STORAGE_URL = STORAGE_BASE.rstrip("/") + "/objstore/api/v1/storage"
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
class CheckRequest(BaseModel):
    lat: float
    lng: float
    accuracy: Optional[float] = None
    image_b64: str

class RegularizationIn(BaseModel):
    date: str
    check_in: str
    check_out: str
    reason: str

class RegularizationDecision(BaseModel):
    decision: Literal["approved", "rejected"]
    note: Optional[str] = None

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
    weekly_off: Optional[List[int]] = None
    shift_start: Optional[str] = None  # "HH:MM"
    shift_end: Optional[str] = None    # "HH:MM"
    break_max_minutes: Optional[int] = None
    timezone: Optional[str] = None

class TrackingModeUpdate(BaseModel):
    tracking_mode: str  # "duty_only" | "always_on"

class PasswordLogin(BaseModel):
    email: str
    password: str

class PasswordChange(BaseModel):
    current_password: str = ""
    new_password: str

class ForgotPassword(BaseModel):
    email: str

class ResetPassword(BaseModel):
    token: str
    new_password: str

class SetEmployeePassword(BaseModel):
    password: str

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
    password: Optional[str] = None
    shift_start: Optional[str] = None
    shift_end: Optional[str] = None
    break_max_minutes: Optional[int] = 60
    # Captured with the employee, not afterwards.
    uan: Optional[str] = None
    epf_not_applicable: bool = False
    esi: Optional[str] = None
    esi_not_applicable: bool = False
    account_holder: Optional[str] = None
    account_number: Optional[str] = None
    ifsc: Optional[str] = None
    bank_name: Optional[str] = None

class AssignmentUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
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

class BranchUpdate(BaseModel):
    name: Optional[str] = None
    address: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    radius_m: Optional[int] = None
    clear_geofence: bool = False

class PushKeys(BaseModel):
    p256dh: str
    auth: str

class PushSubscriptionIn(BaseModel):
    endpoint: str
    keys: PushKeys

class PushDeviceSettings(BaseModel):
    endpoint: str
    silent: Optional[bool] = None
    leave_updates: Optional[bool] = None
    announcements: Optional[bool] = None
    celebrations: Optional[bool] = None
    reminders: Optional[bool] = None

class WishIn(BaseModel):
    to_user_id: str
    kind: Literal["birthday", "wedding_anniversary", "work_anniversary"]
    message: str

class WishReply(BaseModel):
    message: str

class ProfileUpdate(BaseModel):
    esi_not_applicable: Optional[bool] = None
    epf_not_applicable: Optional[bool] = None
    dob: Optional[str] = None
    wedding_anniversary: Optional[str] = None
    date_of_joining: Optional[str] = None
    uan: Optional[str] = None
    esi: Optional[str] = None

class BankDetailsIn(BaseModel):
    account_holder: str
    account_number: str
    ifsc: str
    bank_name: Optional[str] = None

class AvatarUpload(BaseModel):
    image_b64: str

class BankDecision(BaseModel):
    status: str
    note: Optional[str] = None

class GeofenceSettings(BaseModel):
    escalate_minutes: int

class FieldStaffUpdate(BaseModel):
    field_staff: bool

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
    branches: List[str] = []

class AnnouncementIn(BaseModel):
    title: str
    body: str
    pinned: bool = False
    notify_phones: bool = True

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

def parse_iso(dt_str: str) -> datetime:
    dt = datetime.fromisoformat(dt_str)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

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

def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))

GEOFENCE_ACCURACY_TOLERANCE_M = 50

async def geofenced_branches() -> List[dict]:
    return await db.sites.find({"lat": {"$ne": None}, "lng": {"$ne": None}, "radius_m": {"$gt": 0}}, {"_id": 0}).to_list(500)

async def enforce_geofence(user: dict, lat: float, lng: float, accuracy: Optional[float], action: str) -> Optional[str]:
    """Returns the matched branch name, or raises 403 when outside every branch circle."""
    branches = await geofenced_branches()
    if not branches:
        return None
    inside, nearest, nearest_gap = nearest_branch(branches, lat, lng, accuracy)
    if inside or user.get("field_staff"):
        return inside
    raise HTTPException(status_code=403, detail=(
        f"You are {int(nearest_gap)} m outside {nearest['name']}. "
        f"Move inside a branch area to punch {action}."
    ))

def nearest_branch(branches: List[dict], lat: float, lng: float, accuracy: Optional[float]):
    """(inside_name, nearest_branch, gap_m) — inside_name is None when outside every circle."""
    slack = min(accuracy or 0, GEOFENCE_ACCURACY_TOLERANCE_M)
    nearest, nearest_gap = None, None
    for b in branches:
        gap = haversine_m(lat, lng, b["lat"], b["lng"]) - b["radius_m"]
        if gap <= slack:
            return b["name"], b, gap
        if nearest_gap is None or gap < nearest_gap:
            nearest, nearest_gap = b, gap
    return None, nearest, nearest_gap

async def track_zone(user: dict, record: dict, lat: float, lng: float, accuracy: Optional[float]):
    if user.get("field_staff"):
        return
    branches = await geofenced_branches()
    if not branches:
        return
    inside, nearest, gap = nearest_branch(branches, lat, lng, accuracy)
    open_alert = await db.geofence_alerts.find_one({"record_id": record["record_id"], "resolved_at": None}, {"_id": 0})
    now_iso = now_utc().isoformat()
    if inside and open_alert:
        await resolve_alerts({"alert_id": open_alert["alert_id"]}, now_iso, f"back inside {inside}")
    elif not inside and open_alert:
        updates = {"lat": lat, "lng": lng, "distance_m": int(gap), "nearest_branch": nearest["name"], "last_seen_at": now_iso}
        every = await escalate_minutes()
        minutes = int((now_utc() - parse_iso(open_alert["created_at"])).total_seconds() // 60)
        level = minutes // every
        if level > (open_alert.get("pushed_level") or 0):
            updates["pushed_level"] = level
            spawn_push(user["user_id"], {
                "title": f"{user.get('name')} still outside · {minutes} min",
                "body": f"{int(gap)} m outside {nearest['name']}",
                "tag": open_alert["alert_id"], "url": "/admin#alerts",
            })
        await db.geofence_alerts.update_one({"alert_id": open_alert["alert_id"]}, {"$set": updates})
    elif not inside:
        alert_id = f"gfa_{uuid.uuid4().hex[:12]}"
        spawn_push(user["user_id"], {
            "title": f"{user.get('name')} left the branch area",
            "body": f"{int(gap)} m outside {nearest['name']}",
            "tag": alert_id, "url": "/admin#live",
        })
        await db.geofence_alerts.insert_one({
            "alert_id": alert_id,
            "user_id": user["user_id"], "name": user.get("name"), "record_id": record["record_id"],
            "date": record["date"], "lat": lat, "lng": lng, "accuracy": accuracy,
            "distance_m": int(gap), "nearest_branch": nearest["name"],
            "created_at": now_iso, "last_seen_at": now_iso, "resolved_at": None,
            "acknowledged_by": None, "acknowledged_at": None,
        })

# ---------- Web push ----------
VAPID_PUBLIC_KEY = os.environ["VAPID_PUBLIC_KEY"]
VAPID_PRIVATE_KEY = os.environ["VAPID_PRIVATE_KEY"]
VAPID_SUBJECT = os.environ["VAPID_SUBJECT"]
_push_tasks: set = set()

def _send_webpush(sub: dict, body: str):
    webpush(
        subscription_info={"endpoint": sub["endpoint"], "keys": sub["keys"]},
        data=body, vapid_private_key=VAPID_PRIVATE_KEY,
        vapid_claims={"sub": VAPID_SUBJECT}, ttl=600,
    )

async def push_to_subscriptions(subs: List[dict], payload: dict) -> int:
    sent, dead = 0, []
    for sub in subs:
        body = json.dumps({**payload, "silent": bool(sub.get("silent"))}, separators=(",", ":"))
        try:
            await asyncio.to_thread(_send_webpush, sub, body)
            sent += 1
        except WebPushException as exc:
            code = getattr(exc.response, "status_code", None)
            if code in (404, 410):
                dead.append(sub["endpoint"])
            logger.warning(f"Push failed ({code}) for {sub.get('user_id')}")
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Push error: {exc}")
    if dead:
        await db.push_subscriptions.delete_many({"endpoint": {"$in": dead}})
    return sent

async def push_to_managers_of(employee_id: str, payload: dict):
    subs = await db.push_subscriptions.find({}, {"_id": 0}).to_list(2000)
    if not subs:
        return
    managers = await db.users.find(
        {"user_id": {"$in": list({x["user_id"] for x in subs})}, "role": {"$in": ["admin", "sub_admin"]}}, {"_id": 0}
    ).to_list(500)
    allowed = set()
    for m in managers:
        if m["role"] == "admin":
            allowed.add(m["user_id"])
        else:
            ids = await scoped_user_ids(m)
            if ids is None or employee_id in ids:
                allowed.add(m["user_id"])
    await push_to_subscriptions([x for x in subs if x["user_id"] in allowed], payload)

def _fmt_day(d: str) -> str:
    return ddate.fromisoformat(d).strftime("%d %b")

def leave_push_payload(req: dict, status: str, note: str, by: Optional[str]) -> dict:
    dates = _fmt_day(req["start_date"]) if req["start_date"] == req["end_date"] else f"{_fmt_day(req['start_date'])} – {_fmt_day(req['end_date'])}"
    body = f"{req['type_name']} · {dates}"
    if note:
        body += f"\nNote: {note}"
    elif by:
        body += f" · by {by}"
    return {"title": f"Leave {status}", "body": body, "tag": f"leave_{req['leave_id']}", "url": "/leave"}

async def push_to_user(user_id: str, payload: dict):
    subs = await db.push_subscriptions.find({"user_id": user_id, "leave_updates": {"$ne": False}}, {"_id": 0}).to_list(50)
    if subs:
        await push_to_subscriptions(subs, payload)

def _track(task):
    _push_tasks.add(task)
    task.add_done_callback(_push_tasks.discard)

def spawn_user_push(user_id: str, payload: dict):
    _track(asyncio.create_task(push_to_user(user_id, payload)))

async def push_announcement(doc: dict):
    subs = await db.push_subscriptions.find(
        {"announcements": {"$ne": False}, "user_id": {"$ne": doc["author_id"]}}, {"_id": 0}
    ).to_list(5000)
    body = doc["body"] if len(doc["body"]) <= 180 else doc["body"][:177] + "…"
    sent = await push_to_subscriptions(subs, {
        "title": f"Notice: {doc['title']}", "body": body or f"New notice from {doc.get('author_name') or 'admin'}",
        "tag": doc["announcement_id"], "url": "/",
    })
    await db.announcements.update_one({"announcement_id": doc["announcement_id"]}, {"$set": {"pushed_devices": sent}})

def spawn_push(employee_id: str, payload: dict):
    task = asyncio.create_task(push_to_managers_of(employee_id, payload))
    _push_tasks.add(task)
    task.add_done_callback(_push_tasks.discard)

SELFIE_KEEP_DAYS = 7

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
    user.pop("password_hash", None)
    if user.get("must_change_password") and request.url.path not in (
        "/api/auth/me", "/api/auth/change-password", "/api/auth/logout",
    ):
        raise HTTPException(status_code=403, detail="Set your own password before continuing")
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
    """Scope check that also stops a sub-admin editing their own record or another manager."""
    if actor.get("role") != "admin":
        if target_user_id == actor["user_id"]:
            raise HTTPException(status_code=403, detail="Only an admin can change your own settings")
        target = await db.users.find_one({"user_id": target_user_id}, {"_id": 0, "role": 1})
        if target and target.get("role") in ("admin", "sub_admin"):
            raise HTTPException(status_code=403, detail="Only an admin can manage another admin")
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

def scrub_object(path: str):
    """Storage has no delete API, so overwrite the photo with an empty file."""
    try:
        put_object(path, b"", "image/jpeg")
    except Exception as e:
        logger.warning(f"Could not scrub {path}: {e}")

def upload_face_image(user_id: str, image_b64: str, kind: str) -> str:
    if image_b64.startswith("data:"):
        image_b64 = image_b64.split(",", 1)[1]
    data = base64.b64decode(image_b64)
    path = f"{APP_NAME}/{kind}/{user_id}/{uuid.uuid4().hex}.jpg"
    result = put_object(path, data, "image/jpeg")
    return result["path"]

# ---------- Auth Routes ----------
@api_router.get("/auth/me")
async def get_me(user: dict = Depends(get_current_user)):
    u = dict(user)
    u.pop("face_descriptor", None)
    return u

@api_router.post("/auth/logout")
async def logout(request: Request, response: Response):
    token = request.cookies.get("session_token")
    if not token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
    if token:
        await db.user_sessions.delete_one({"session_token": token})
    response.delete_cookie("session_token", path="/")
    return {"ok": True}

# ---------- Email (Emergent managed Resend) ----------
EMAIL_BASE_URL = "https://integrations.emergentagent.com"
EMAIL_KEY = os.environ.get("EMERGENT_EMAIL_KEY", "")
EMAIL_FROM_NAME = os.environ.get("EMAIL_FROM_NAME", "Kelasa")
EMAIL_REPLY_TO = os.environ.get("EMAIL_REPLY_TO")
APP_PUBLIC_URL = os.environ.get("APP_PUBLIC_URL", "").rstrip("/")

_SHORTENERS = ("bit.ly", "tinyurl.com", "t.co", "is.gd", "cutt.ly", "goo.gl", "rebrand.ly")
_CRED_ASK = ("reply with your password", "reply with the code", "send your password", "cvv",
             "send us your password", "enter your password below", "confirm your card number",
             "your full card number", "seed phrase", "recovery phrase", "verify your card",
             "social security number", "confirm your bank details")
_HOSTISH = re.compile(r"\b(?:https?://)?((?:[a-z0-9-]+\.)+[a-z]{2,})", re.I)

def _host_ok(host: str) -> bool:
    if not host or "xn--" in host:
        return False
    try:
        ipaddress.ip_address(host)
        return False
    except ValueError:
        pass
    return not any(host == s or host.endswith("." + s) for s in _SHORTENERS)

def _same_site(shown: str, real: str) -> bool:
    return shown == real or real.endswith("." + shown) or shown.endswith("." + real)

class _EmailScan(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags, self.urls, self.anchors = set(), [], []
        self._href, self._text = None, []
    def handle_starttag(self, tag, attrs):
        self.tags.add(tag.lower())
        self.urls += [v for k, v in attrs if k.lower() in ("href", "src") and v]
        if tag.lower() == "a":
            self._href = dict((k.lower(), v) for k, v in attrs).get("href")
            self._text = []
    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)
    def handle_endtag(self, tag):
        if tag.lower() == "a" and self._href is not None:
            self.anchors.append((self._href, "".join(self._text)))
            self._href, self._text = None, []

def _assert_safe_email(subject: str, html: str) -> None:
    scan = _EmailScan(); scan.feed(html)
    if scan.tags & {"form", "input", "textarea", "select"}:
        raise ValueError("No forms or input fields in email (G2)")
    body = f"{subject}\n{html}".lower()
    for p in _CRED_ASK:
        if p in body:
            raise ValueError(f"Email asks the recipient for credentials: {p!r} (G2)")
    for url in scan.urls:
        low = url.strip().lower()
        if low.startswith(("mailto:", "tel:", "cid:", "#")):
            continue
        if not low.startswith("https://"):
            raise ValueError(f"Email links/assets must be absolute https: {url!r} (G3)")
        host = urlparse(low).hostname or ""
        if not _host_ok(host) or urlparse(low).username is not None:
            raise ValueError(f"Shortened, numeric-host or credential-bearing URL: {url!r} (G3)")
    for href, text in scan.anchors:
        real = urlparse(href.strip().lower()).hostname or ""
        if not real:
            continue
        for m in _HOSTISH.finditer(text):
            if not _same_site(m.group(1).lower(), real):
                raise ValueError(f"Anchor text {m.group(1)!r} != real link host {real!r} (G3)")

async def send_email(*, to: str, subject: str, html: str, reply_to: Optional[str] = None) -> Optional[str]:
    _assert_safe_email(subject, html)
    if not EMAIL_KEY:
        logger.error("EMERGENT_EMAIL_KEY is not configured; cannot send email")
        raise HTTPException(status_code=503, detail="Email is temporarily unavailable")
    payload = {"to": [to], "subject": subject, "html": html, "from_name": EMAIL_FROM_NAME}
    if reply_to or EMAIL_REPLY_TO:
        payload["contact_email"] = reply_to or EMAIL_REPLY_TO
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{EMAIL_BASE_URL}/api/v1/email/send",
                headers={"X-Email-Key": EMAIL_KEY},
                json=payload,
            )
        resp.raise_for_status()
        return resp.json().get("id")
    except httpx.HTTPStatusError as e:
        try:
            code = e.response.json().get("code", "")
            message = e.response.json().get("message", "")
        except ValueError:
            code, message = "", ""
        if code in ("insufficient_credits", "integration_disabled", "daily_limit_reached"):
            logger.warning(f"Email paused: {code} ({e.response.status_code}): {message}")
            raise HTTPException(status_code=503, detail="Email is temporarily unavailable") from None
        logger.error(f"Email send failed: {e.response.status_code} {e.response.text}")
        raise HTTPException(status_code=502, detail="Failed to send email") from None
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Email send error: {e}")
        raise HTTPException(status_code=500, detail="Failed to send email") from None

# ---------- Password authentication ----------
MIN_PASSWORD_LENGTH = 8
MAX_LOGIN_ATTEMPTS = 5
MAX_ACCOUNT_ATTEMPTS = 10
LOCKOUT_MINUTES = 15

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False

def validate_password(password: str) -> str:
    pw = password or ""
    if len(pw) < MIN_PASSWORD_LENGTH:
        raise HTTPException(status_code=400, detail=f"Password must be at least {MIN_PASSWORD_LENGTH} characters")
    return pw

async def issue_session(user_id: str, response: Response) -> str:
    token = pysecrets.token_urlsafe(32)
    await db.user_sessions.insert_one({
        "user_id": user_id,
        "session_token": token,
        "expires_at": (now_utc() + timedelta(days=7)).isoformat(),
        "created_at": now_utc().isoformat(),
    })
    response.set_cookie(
        key="session_token", value=token,
        max_age=7 * 24 * 60 * 60, httponly=True, secure=True, samesite="none", path="/",
    )
    return token

async def check_lockout(identifier: str):
    doc = await db.login_attempts.find_one({"identifier": identifier}, {"_id": 0})
    if not doc:
        return
    locked_until = doc.get("locked_until")
    if locked_until:
        lu = datetime.fromisoformat(locked_until)
        if lu > now_utc():
            mins = max(1, int((lu - now_utc()).total_seconds() // 60) + 1)
            raise HTTPException(status_code=429, detail=f"Too many failed attempts. Try again in {mins} minute(s).")

async def register_failed_attempt(identifier: str, limit: int = MAX_LOGIN_ATTEMPTS):
    doc = await db.login_attempts.find_one({"identifier": identifier}, {"_id": 0})
    attempts = (doc or {}).get("attempts", 0) + 1
    update = {"identifier": identifier, "attempts": attempts, "updated_at": now_utc().isoformat()}
    if attempts >= limit:
        update["locked_until"] = (now_utc() + timedelta(minutes=LOCKOUT_MINUTES)).isoformat()
        update["attempts"] = 0
    await db.login_attempts.update_one({"identifier": identifier}, {"$set": update}, upsert=True)

def client_ip(request: Request) -> str:
    """Last X-Forwarded-For hop is the one added by our own proxy, so it can't be spoofed."""
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        parts = [p.strip() for p in fwd.split(",") if p.strip()]
        if parts:
            return parts[-1]
    return request.client.host if request.client else "unknown"

@api_router.post("/auth/login")
async def password_login(payload: PasswordLogin, request: Request, response: Response):
    email = payload.email.strip().lower()
    ip = client_ip(request)
    identifier = f"{ip}:{email}"
    await check_lockout(identifier)
    await check_lockout(email)

    user = await db.users.find_one({"email": email}, {"_id": 0})
    if not user or not user.get("password_hash") or not verify_password(payload.password, user["password_hash"]):
        await register_failed_attempt(identifier)
        await register_failed_attempt(email, limit=MAX_ACCOUNT_ATTEMPTS)
        raise HTTPException(status_code=401, detail="Incorrect email or password")

    await db.login_attempts.delete_many({"identifier": {"$in": [identifier, email]}})
    token = await issue_session(user["user_id"], response)
    await db.users.update_one({"user_id": user["user_id"]}, {"$set": {"last_login_at": now_utc().isoformat(), "pending_invite": False}})
    user_doc = await db.users.find_one({"user_id": user["user_id"]}, {"_id": 0, "face_descriptor": 0, "password_hash": 0})
    return {"user": user_doc, "session_token": token}

@api_router.post("/auth/change-password")
async def change_password(payload: PasswordChange, request: Request, user: dict = Depends(get_current_user)):
    record = await db.users.find_one({"user_id": user["user_id"]}, {"_id": 0, "password_hash": 1})
    current_hash = (record or {}).get("password_hash")
    if current_hash and not verify_password(payload.current_password, current_hash):
        raise HTTPException(status_code=400, detail="Your current password is incorrect")
    new_pw = validate_password(payload.new_password)
    if current_hash and verify_password(new_pw, current_hash):
        raise HTTPException(status_code=400, detail="Pick a password you haven't used here before")
    await db.users.update_one({"user_id": user["user_id"]}, {"$set": {
        "password_hash": hash_password(new_pw),
        "must_change_password": False,
        "password_set_at": now_utc().isoformat(),
    }})
    current_token = request.cookies.get("session_token")
    if not current_token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            current_token = auth_header[7:]
    await db.user_sessions.delete_many({"user_id": user["user_id"], "session_token": {"$ne": current_token}})
    return {"ok": True}

@api_router.post("/auth/forgot-password")
async def forgot_password(payload: ForgotPassword, background: BackgroundTasks):
    email = payload.email.strip().lower()
    user = await db.users.find_one({"email": email}, {"_id": 0, "user_id": 1, "name": 1, "email": 1})
    if user:
        await db.password_reset_tokens.delete_many({"user_id": user["user_id"], "used": False})
        token = pysecrets.token_urlsafe(32)
        await db.password_reset_tokens.insert_one({
            "token": token,
            "user_id": user["user_id"],
            "used": False,
            "created_at": now_utc(),
            "expires_at": now_utc() + timedelta(hours=1),
        })
        link = f"{APP_PUBLIC_URL}/reset-password?token={token}"
        html = (
            '<table role="presentation" width="100%"><tr><td style="padding:24px;font-family:Arial,sans-serif;color:#111">'
            f'<p style="font-size:15px">Hi {escape(user.get("name") or "there")},</p>'
            f'<p style="font-size:15px">We received a request to reset your {escape(EMAIL_FROM_NAME)} password. '
            'Use the button below within the next hour.</p>'
            f'<p><a href="{escape(link)}" style="display:inline-block;background:#111;color:#fff;'
            'padding:12px 20px;text-decoration:none;font-weight:bold">Reset your password</a></p>'
            '<p style="font-size:13px;color:#555">If you did not ask for this, you can ignore this email — '
            'your current password keeps working.</p>'
            f'<p style="font-size:12px;color:#888">Sent by {escape(EMAIL_FROM_NAME)}. '
            'We never ask for your password or card details by email.</p>'
            '</td></tr></table>'
        )
        async def deliver():
            try:
                await send_email(to=user["email"], subject=f"Reset your {EMAIL_FROM_NAME} password", html=html)
            except HTTPException as e:
                logger.error(f"Password reset email failed for {email}: {e.detail}")
        background.add_task(deliver)
    return {"ok": True, "message": "If that email is registered, a reset link is on its way."}

@api_router.post("/auth/reset-password")
async def reset_password(payload: ResetPassword):
    doc = await db.password_reset_tokens.find_one({"token": payload.token}, {"_id": 0})
    if not doc or doc.get("used"):
        raise HTTPException(status_code=400, detail="This reset link is no longer valid. Request a new one.")
    expires_at = doc["expires_at"]
    if isinstance(expires_at, str):
        expires_at = datetime.fromisoformat(expires_at)
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < now_utc():
        raise HTTPException(status_code=400, detail="This reset link has expired. Request a new one.")
    new_pw = validate_password(payload.new_password)
    await db.users.update_one({"user_id": doc["user_id"]}, {"$set": {
        "password_hash": hash_password(new_pw),
        "must_change_password": False,
        "password_set_at": now_utc().isoformat(),
    }})
    await db.password_reset_tokens.update_one({"token": payload.token}, {"$set": {"used": True}})
    await db.user_sessions.delete_many({"user_id": doc["user_id"]})
    return {"ok": True}

async def seed_admin_password():
    admin_email = (os.environ.get("ADMIN_EMAIL") or "").strip().lower()
    admin_password = os.environ.get("ADMIN_PASSWORD")
    if not admin_email or not admin_password:
        return
    user = await db.users.find_one({"email": admin_email}, {"_id": 0, "user_id": 1, "password_hash": 1})
    if not user:
        user_id = f"user_{uuid.uuid4().hex[:12]}"
        await db.users.insert_one({
            "user_id": user_id, "email": admin_email, "name": "Administrator", "picture": None,
            "role": "admin", "face_enrolled": False, "face_descriptor": None, "face_photo_path": None,
            "shift_start": None, "shift_end": None, "break_max_minutes": 60, "timezone": DEFAULT_TZ,
            "tracking_mode": "duty_only", "password_hash": hash_password(admin_password),
            "must_change_password": False, "pending_invite": False, "created_at": now_utc().isoformat(),
        })
        logger.info(f"Seeded admin account {admin_email}")
    elif not user.get("password_hash"):
        await db.users.update_one({"email": admin_email}, {"$set": {
            "password_hash": hash_password(admin_password),
            "must_change_password": False,
            "role": "admin",
        }})
        logger.info(f"Set initial password for existing admin {admin_email}")

async def ensure_indexes():
    await db.users.create_index("email", unique=True)
    await db.employee_profiles.create_index("user_id", unique=True)
    await db.cron_runs.create_index("key", unique=True)
    await db.wishes.create_index([("to_user_id", 1), ("occasion_date", 1)])
    await db.password_reset_tokens.create_index("expires_at", expireAfterSeconds=0)
    await db.password_reset_tokens.create_index("token", unique=True)
    await db.login_attempts.create_index("identifier", unique=True)

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
    parts = path.split("/")
    if len(parts) < 3 or parts[0] != APP_NAME:
        raise HTTPException(status_code=404, detail="File not found")
    if parts[1] != "avatars" and parts[2] != session["user_id"]:
        viewer = await db.users.find_one({"user_id": session["user_id"]}, {"_id": 0})
        if not viewer or viewer.get("role") not in ("admin", "sub_admin"):
            raise HTTPException(status_code=403, detail="Not allowed")
        if viewer["role"] == "sub_admin":
            await ensure_in_scope(viewer, parts[2])
    try:
        data, content_type = get_object(path)
    except Exception:
        raise HTTPException(status_code=404, detail="File not found") from None
    return Response(content=data, media_type=content_type)

# ---------- Attendance ----------
def require_selfie(image_b64: str):
    raw = (image_b64 or "").split(",", 1)[-1]
    if len(raw) < 200:
        raise HTTPException(status_code=400, detail="Please take a selfie to check in or out.")

@api_router.post("/attendance/checkin")
async def check_in(payload: CheckRequest, user: dict = Depends(get_current_user)):
    require_selfie(payload.image_b64)

    active = await db.attendance.find_one(
        {"user_id": user["user_id"], "check_out": None}, {"_id": 0},
        sort=[("check_in", -1)]
    )
    if active:
        raise HTTPException(status_code=400, detail="Already checked in")
    branch = await enforce_geofence(user, payload.lat, payload.lng, payload.accuracy, "in")

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
        "check_in_branch": branch,
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
    return {"ok": True, "record_id": record_id, "late_by_minutes": late_by}

@api_router.post("/attendance/checkout")
async def check_out(payload: CheckRequest, user: dict = Depends(get_current_user)):
    require_selfie(payload.image_b64)

    active = await db.attendance.find_one(
        {"user_id": user["user_id"], "check_out": None}, {"_id": 0},
        sort=[("check_in", -1)]
    )
    if not active:
        raise HTTPException(status_code=400, detail="No active check-in")
    if active.get("on_break"):
        raise HTTPException(status_code=400, detail="You are currently on break. End break before checking out.")
    branch = await enforce_geofence(user, payload.lat, payload.lng, payload.accuracy, "out")

    photo_path = upload_face_image(user["user_id"], payload.image_b64, "checkout")
    check_in_dt = datetime.fromisoformat(active["check_in"])
    if check_in_dt.tzinfo is None:
        check_in_dt = check_in_dt.replace(tzinfo=timezone.utc)
    out_dt = now_utc()
    tz_name = user.get("timezone") or DEFAULT_TZ
    auto_closed = out_dt > session_cap(active["check_in"], tz_name, None, None)
    if auto_closed:
        out_dt = session_cap(active["check_in"], tz_name, user.get("shift_start"), user.get("shift_end"))
    break_minutes = int(active.get("total_break_minutes", 0))
    calc = compute_session(active["check_in"], out_dt.isoformat(), break_minutes, user.get("shift_start"), user.get("shift_end"))
    total_minutes, net_minutes = calc["duration_minutes"], calc["net_work_minutes"]
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
            "check_out_branch": branch,
            "status": "off_duty",
            "duration_minutes": total_minutes,
            "net_work_minutes": net_minutes,
            "overtime_minutes": calc["overtime_minutes"],
            "over_cap": calc["over_cap"],
            "auto_closed": auto_closed,
            "auto_close_reason": "missed checkout (checked out on a later day)" if auto_closed else None,
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
    await resolve_alerts({"record_id": active["record_id"], "resolved_at": None}, out_dt.isoformat(), "checked out")
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

@api_router.get("/attendance/geofence")
async def my_geofence(user: dict = Depends(get_current_user)):
    branches = await geofenced_branches()
    return {
        "field_staff": bool(user.get("field_staff")),
        "tolerance_m": GEOFENCE_ACCURACY_TOLERANCE_M,
        "branches": [{k: b.get(k) for k in ("unit_id", "name", "address", "lat", "lng", "radius_m")} for b in branches],
    }

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
    await track_zone(user, active, payload.lat, payload.lng, payload.accuracy)
    return {"ok": True}

@api_router.get("/location/today")
async def location_today(user: dict = Depends(get_current_user), date: Optional[str] = None):
    d = date or user_local_today(user)
    pings = await db.locations.find(
        {"user_id": user["user_id"], "date": d}, {"_id": 0}
    ).sort("timestamp", 1).to_list(5000)
    return {"date": d, "pings": pings}

# ---------- Admin ----------
async def close_session(rec: dict, u: dict, close_at: datetime, reason: str, extra: Optional[dict] = None):
    breaks = rec.get("breaks") or []
    total_break = int(rec.get("total_break_minutes") or 0)
    if rec.get("on_break") and breaks and not breaks[-1].get("end"):
        start = parse_iso(breaks[-1]["start"])
        mins = max(0, int((close_at - start).total_seconds() // 60))
        breaks[-1].update({"end": close_at.isoformat(), "duration_minutes": mins})
        total_break = sum((b.get("duration_minutes") or 0) for b in breaks)
    calc = compute_session(rec["check_in"], close_at.isoformat(), total_break, u.get("shift_start"), u.get("shift_end"))
    await db.attendance.update_one({"record_id": rec["record_id"]}, {"$set": {
        "check_out": close_at.isoformat(), "status": "off_duty", "on_break": False, "breaks": breaks,
        "total_break_minutes": total_break, "auto_closed": True, "auto_close_reason": reason,
        "over_break": total_break > int(u.get("break_max_minutes") if u.get("break_max_minutes") is not None else 60),
        **calc, **(extra or {}),
    }})
    await resolve_alerts({"record_id": rec["record_id"], "resolved_at": None}, close_at.isoformat(), "auto-closed")

async def auto_close_stale_sessions():
    now = now_utc()
    opens = await db.attendance.find({"check_out": None}, {"_id": 0}).to_list(5000)
    if not opens:
        return 0
    users = {u["user_id"]: u for u in await db.users.find(
        {"user_id": {"$in": list({o["user_id"] for o in opens})}}, {"_id": 0, "face_descriptor": 0}).to_list(5000)}
    closed = 0
    for rec in opens:
        u = users.get(rec["user_id"], {})
        tz = u.get("timezone") or DEFAULT_TZ
        if now > session_cap(rec["check_in"], tz, None, None):
            await close_session(rec, u, session_cap(rec["check_in"], tz, u.get("shift_start"), u.get("shift_end")), "missed checkout")
            closed += 1
    return closed

async def recalc_attendance_migration():
    key = "recalc_work_hours_v1"
    if await db.migrations.find_one({"key": key}):
        return
    users = {u["user_id"]: u for u in await db.users.find({}, {"_id": 0, "face_descriptor": 0}).to_list(10000)}
    fixed = 0
    async for rec in db.attendance.find({"check_out": {"$ne": None}}, {"_id": 0}):
        u = users.get(rec["user_id"], {})
        tz = u.get("timezone") or DEFAULT_TZ
        day_cap = session_cap(rec["check_in"], tz, None, None)
        if parse_iso(rec["check_out"]) > day_cap:
            await close_session(rec, u, session_cap(rec["check_in"], tz, u.get("shift_start"), u.get("shift_end")),
                                "missed checkout (recalculated)", {"original_check_out": rec["check_out"]})
            fixed += 1
        else:
            calc = compute_session(rec["check_in"], rec["check_out"], rec.get("total_break_minutes") or 0,
                                   u.get("shift_start"), u.get("shift_end"))
            await db.attendance.update_one({"record_id": rec["record_id"]}, {"$set": calc})
    await db.migrations.insert_one({"key": key, "applied_at": now_utc().isoformat(), "reclosed": fixed})
    logger.info(f"Attendance recalculation done, {fixed} sessions re-closed")

async def auto_close_loop():
    while True:
        try:
            await auto_close_stale_sessions()
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"auto-close failed: {exc}")
        await asyncio.sleep(300)

def running_minutes(rec: dict, now: datetime) -> int:
    total = int((now - parse_iso(rec["check_in"])).total_seconds() // 60)
    brk = int(rec.get("total_break_minutes") or 0)
    breaks = rec.get("breaks") or []
    if rec.get("on_break") and breaks and not breaks[-1].get("end"):
        brk += int((now - parse_iso(breaks[-1]["start"])).total_seconds() // 60)
    return max(0, min(total - brk, 16 * 60))

@api_router.get("/admin/stats")
async def admin_stats(user: dict = Depends(require_manager)):
    await auto_close_stale_sessions()
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
        total_minutes = row.get("total", 0) or 0
    now = now_utc()
    for rec in await db.attendance.find({"check_out": None, **uf}, {"_id": 0}).to_list(2000):
        total_minutes += running_minutes(rec, now)
    shift_ids = {u["user_id"] for u in await db.users.find({**uf, "shift_start": {"$nin": [None, ""]}}, {"_id": 0, "user_id": 1}).to_list(5000)}
    late_today = len({r["user_id"] for r in await db.attendance.find(
        {"date": today, "late_by_minutes": {"$gt": 0}, **uf}, {"_id": 0, "user_id": 1}).to_list(5000) if r["user_id"] in shift_ids})
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
        u.setdefault("field_staff", False)
        u.setdefault("manager_id", None)
        u.setdefault("designation", None)
        u.setdefault("phone", None)
        u.setdefault("employee_code", None)
        u.setdefault("pending_invite", False)
        u.setdefault("must_change_password", False)
        u["has_password"] = bool(u.pop("password_hash", None))
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
    if payload.weekly_off is not None:
        if any(d not in range(7) for d in payload.weekly_off):
            raise HTTPException(status_code=400, detail="Weekly off days must be 0 (Mon) to 6 (Sun)")
        updates["weekly_off"] = sorted(set(payload.weekly_off))
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    res = await db.users.update_one({"user_id": user_id}, {"$set": updates})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="User not found")
    emp = await db.users.find_one({"user_id": user_id}, {"_id": 0, "face_descriptor": 0, "password_hash": 0})
    await log_activity(user, "shift_updated", (emp or {}).get("name", user_id), ", ".join(f"{k}={v}" for k, v in updates.items()))
    return {"ok": True, "employee": emp}

@api_router.patch("/admin/employees/{user_id}/tracking_mode")
async def admin_set_tracking_mode(user_id: str, payload: TrackingModeUpdate, user: dict = Depends(require_admin)):
    if payload.tracking_mode not in ("duty_only", "always_on"):
        raise HTTPException(status_code=400, detail="tracking_mode must be 'duty_only' or 'always_on'")
    res = await db.users.update_one({"user_id": user_id}, {"$set": {"tracking_mode": payload.tracking_mode}})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="User not found")
    emp = await db.users.find_one({"user_id": user_id}, {"_id": 0, "face_descriptor": 0, "password_hash": 0})
    return {"ok": True, "employee": emp}


@api_router.get("/admin/live")
async def admin_live(user: dict = Depends(require_manager)):
    """All currently on-duty employees with their latest known location."""
    ids = await scoped_user_ids(user)
    actives = await db.attendance.find({"check_out": None, **user_filter(ids)}, {"_id": 0}).to_list(1000)
    open_alert_records = {
        x["record_id"] for x in await db.geofence_alerts.find(
            {"resolved_at": None, "record_id": {"$in": [a["record_id"] for a in actives]}}, {"_id": 0, "record_id": 1}
        ).to_list(1000)
    }
    result = []
    for a in actives:
        emp = await db.users.find_one(
            {"user_id": a["user_id"]}, {"_id": 0, "face_descriptor": 0, "password_hash": 0}
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
            "outside_zone": a["record_id"] in open_alert_records,
        })
    return {"employees": result, "server_time": now_utc().isoformat()}

@api_router.get("/admin/employees/{user_id}/route")
async def admin_employee_route(user_id: str, date: Optional[str] = None, user: dict = Depends(require_manager)):
    await ensure_in_scope(user, user_id)
    emp = await db.users.find_one({"user_id": user_id}, {"_id": 0, "face_descriptor": 0, "password_hash": 0})
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
    users = await db.users.find({"user_id": {"$in": user_ids}}, {"_id": 0, "face_descriptor": 0, "password_hash": 0}).to_list(1000)
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
    emp = await db.users.find_one({"user_id": user_id}, {"_id": 0, "face_photo_path": 1, "name": 1})
    if not emp:
        raise HTTPException(status_code=404, detail="User not found")
    await db.users.update_one(
        {"user_id": user_id},
        {"$set": {"face_enrolled": False, "face_descriptor": None, "face_photo_path": None}}
    )
    await db.face_profiles.delete_one({"user_id": user_id})
    if emp.get("face_photo_path"):
        await asyncio.to_thread(scrub_object, emp["face_photo_path"])
    await log_activity(user, "face_reset", emp.get("name") or user_id)
    return {"ok": True}

# ---------- Face check review ----------
@api_router.get("/admin/face-checks")
async def admin_face_checks(user: dict = Depends(require_manager), flagged: bool = False, person: Optional[str] = None,
                            from_date: Optional[str] = Query(None, alias="from"), to_date: Optional[str] = Query(None, alias="to"),
                            page: int = Query(1, ge=1), page_size: int = Query(24, ge=1, le=100)):
    ids = await scoped_user_ids(user)
    if person:
        ids = [person] if ids is None or person in ids else []
    q: dict = {**user_filter(ids)}
    if from_date or to_date:
        q["date"] = {k: v for k, v in (("$gte", from_date), ("$lte", to_date)) if v}
    q["$or"] = ([{"check_in_face_review": True}, {"check_out_face_review": True}] if flagged else
                [{"check_in_photo_path": {"$ne": None}}, {"check_out_photo_path": {"$ne": None}},
                 {"check_in_face_review": True}, {"check_out_face_review": True}])
    total = await db.attendance.count_documents(q)
    recs = await db.attendance.find(q, {"_id": 0}).sort("check_in", -1).skip((page - 1) * page_size).limit(page_size).to_list(page_size)
    users = {u["user_id"]: u for u in await db.users.find({"user_id": {"$in": list({r["user_id"] for r in recs})}},
             {"_id": 0, "user_id": 1, "name": 1, "email": 1, "face_photo_path": 1, "avatar_path": 1, "site": 1}).to_list(500)}
    pending = await db.attendance.count_documents({**{k: v for k, v in q.items() if k != "$or"}, "$or": [
        {"check_in_face_review": True, "check_in_face_review_status": None},
        {"check_out_face_review": True, "check_out_face_review_status": None}]})
    rev_ids = {r.get(k) for r in recs for k in ("check_in_face_reviewed_by", "check_out_face_reviewed_by")} - {None}
    reviewers = {x["user_id"]: x.get("name") or x.get("email") for x in await db.users.find(
        {"user_id": {"$in": list(rev_ids)}}, {"_id": 0, "user_id": 1, "name": 1, "email": 1}).to_list(200)}
    items = []
    for r in recs:
        u = users.get(r["user_id"], {})
        items.append({**{k: r.get(k) for k in (
            "record_id", "user_id", "date", "check_in", "check_out", "check_in_photo_path", "check_out_photo_path",
            "check_in_face_distance", "check_out_face_distance", "check_in_face_review", "check_out_face_review",
            "check_in_face_review_reason", "check_out_face_review_reason", "check_in_face_review_status",
            "check_out_face_review_status", "check_in_liveness", "check_out_liveness", "check_in_low_light",
            "check_out_low_light", "check_in_lat", "check_in_lng", "check_out_lat", "check_out_lng",
            "check_in_accuracy", "check_out_accuracy", "photos_purged_at", "check_in_face_review_note",
            "check_out_face_review_note", "check_in_face_reviewed_at", "check_out_face_reviewed_at")},
            "check_in_face_reviewed_by": reviewers.get(r.get("check_in_face_reviewed_by")),
            "check_out_face_reviewed_by": reviewers.get(r.get("check_out_face_reviewed_by")),
            "name": u.get("name") or u.get("email"), "site": u.get("site"), "enrollment_photo_path": u.get("face_photo_path")})
    return {"items": items, "total": total, "page": page, "page_size": page_size, "pending_review": pending,
            "keep_days": SELFIE_KEEP_DAYS}

# ---------- Selfie retention ----------
async def run_selfie_purge() -> int:
    cutoff = (now_utc() - timedelta(days=SELFIE_KEEP_DAYS)).isoformat()
    recs = await db.attendance.find({"check_in": {"$lt": cutoff}, "$or": [
        {"check_in_photo_path": {"$ne": None}}, {"check_out_photo_path": {"$ne": None}}]},
        {"_id": 0, "record_id": 1, "check_in_photo_path": 1, "check_out_photo_path": 1}).to_list(5000)
    for r in recs:
        for k in ("check_in_photo_path", "check_out_photo_path"):
            if r.get(k):
                await asyncio.to_thread(scrub_object, r[k])
        await db.attendance.update_one({"record_id": r["record_id"]}, {"$set": {
            "check_in_photo_path": None, "check_out_photo_path": None, "photos_purged_at": now_utc().isoformat()}})
    if recs:
        logger.info(f"Selfie purge: cleared photos on {len(recs)} attendance records")
    return len(recs)

@api_router.post("/cron/selfie-purge")
async def cron_selfie_purge(request: Request):
    # Cron endpoints must ack 2xx immediately; enqueue/background the actual work.
    if not _cron_authorized(request):
        raise HTTPException(status_code=401, detail="Unauthorized")
    try:
        envelope = await request.json()
    except ValueError:
        envelope = None
    if envelope is not None and not isinstance(envelope, dict):
        raise HTTPException(status_code=400, detail="Invalid body")
    _track(asyncio.create_task(run_selfie_purge()))
    export_job.cleanup_stale()
    return {"ok": True, "queued": True}

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
        raise HTTPException(status_code=400, detail="Branch already exists")
    doc = {"unit_id": f"site_{uuid.uuid4().hex[:10]}", "name": name, "created_at": now_utc().isoformat()}
    await db.sites.insert_one(doc)
    await log_activity(user, "site_added", name)
    return {"ok": True, "site": {k: v for k, v in doc.items() if k != "_id"}}

@api_router.patch("/admin/org/sites/{unit_id}")
async def update_site(unit_id: str, payload: BranchUpdate, user: dict = Depends(require_admin)):
    doc = await db.sites.find_one({"unit_id": unit_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Branch not found")
    updates = {}
    if payload.name is not None:
        name = payload.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="Name required")
        if name != doc["name"]:
            if await db.sites.find_one({"name": name}):
                raise HTTPException(status_code=400, detail="A branch with this name already exists")
            updates["name"] = name
    if payload.address is not None:
        updates["address"] = payload.address.strip() or None
    if payload.clear_geofence:
        updates.update({"lat": None, "lng": None, "radius_m": None})
    elif payload.lat is not None or payload.lng is not None or payload.radius_m is not None:
        if payload.lat is None or payload.lng is None or payload.radius_m is None:
            raise HTTPException(status_code=400, detail="Pin a location and set a radius")
        if not (-90 <= payload.lat <= 90 and -180 <= payload.lng <= 180):
            raise HTTPException(status_code=400, detail="Invalid location")
        if not (10 <= payload.radius_m <= 10000):
            raise HTTPException(status_code=400, detail="Radius must be between 10 and 10000 metres")
        updates.update({"lat": payload.lat, "lng": payload.lng, "radius_m": payload.radius_m})
    if not updates:
        raise HTTPException(status_code=400, detail="No changes")
    await db.sites.update_one({"unit_id": unit_id}, {"$set": updates})
    if "name" in updates:
        await db.users.update_many({"site": doc["name"]}, {"$set": {"site": updates["name"]}})
        await db.users.update_many({"managed_sites": doc["name"]}, {"$set": {"managed_sites.$": updates["name"]}})
        await db.holidays.update_many({"branches": doc["name"]}, {"$set": {"branches.$": updates["name"]}})
    new_doc = await db.sites.find_one({"unit_id": unit_id}, {"_id": 0})
    detail = f"radius {new_doc.get('radius_m')} m" if new_doc.get("radius_m") else "geofence cleared"
    await log_activity(user, "branch_updated", new_doc["name"], detail)
    return {"ok": True, "site": new_doc}

GEOCODE_UA = {"User-Agent": "Kelasa-Attendance/1.0 (branch geofence setup)"}

@api_router.get("/admin/geocode")
async def admin_geocode(q: str, user: dict = Depends(require_admin)):
    q = q.strip()[:200]
    if not q:
        raise HTTPException(status_code=400, detail="Enter a place to search")
    async with httpx.AsyncClient(timeout=10, headers=GEOCODE_UA) as hc:
        try:
            r = await hc.get("https://photon.komoot.io/api/", params={"q": q, "limit": 1})
            feats = r.json().get("features", []) if r.status_code == 200 else []
            if feats:
                lng, lat = feats[0]["geometry"]["coordinates"]
                p = feats[0].get("properties", {})
                label = ", ".join(x for x in (p.get("name"), p.get("street"), p.get("city"), p.get("state"), p.get("country")) if x)
                return {"result": {"lat": lat, "lng": lng, "label": label}}
        except (httpx.HTTPError, ValueError, KeyError):
            pass
        try:
            r = await hc.get("https://nominatim.openstreetmap.org/search", params={"q": q, "format": "json", "limit": 1})
            hits = r.json() if r.status_code == 200 else []
            if hits:
                return {"result": {"lat": float(hits[0]["lat"]), "lng": float(hits[0]["lon"]), "label": hits[0].get("display_name", "")}}
        except (httpx.HTTPError, ValueError, KeyError):
            pass
        try:
            r = await hc.get("https://geocoding-api.open-meteo.com/v1/search", params={"name": q.split(",")[0].strip(), "count": 1})
            hits = r.json().get("results", []) if r.status_code == 200 else []
            if hits:
                h = hits[0]
                label = ", ".join(x for x in (h.get("name"), h.get("admin1"), h.get("country")) if x)
                return {"result": {"lat": h["latitude"], "lng": h["longitude"], "label": label, "approximate": True}}
        except (httpx.HTTPError, ValueError, KeyError):
            pass
    return {"result": None}

@api_router.delete("/admin/org/sites/{unit_id}")
async def delete_site(unit_id: str, user: dict = Depends(require_admin)):
    doc = await db.sites.find_one({"unit_id": unit_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Not found")
    await db.sites.delete_one({"unit_id": unit_id})
    await db.users.update_many({"site": doc["name"]}, {"$set": {"site": None}})
    await db.users.update_many({"managed_sites": doc["name"]}, {"$pull": {"managed_sites": doc["name"]}})
    branch_hols = await db.holidays.find({"branches": doc["name"]}, {"_id": 0, "holiday_id": 1, "branches": 1}).to_list(2000)
    await db.holidays.delete_many({"holiday_id": {"$in": [h["holiday_id"] for h in branch_hols if h["branches"] == [doc["name"]]]}})
    await db.holidays.update_many({"branches": doc["name"]}, {"$pull": {"branches": doc["name"]}})
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
    if payload.password:
        doc["password_hash"] = hash_password(validate_password(payload.password))
        doc["must_change_password"] = True
    payroll = payroll_profile_for_new_employee(payload, user_local_today(user))
    await db.users.insert_one(doc)
    await db.employee_profiles.insert_one({
        "user_id": user_id, "updated_at": now_utc().isoformat(), **payroll,
    })
    await log_activity(user, "employee_added", doc["name"], f"{email} · PF, ESI and bank account saved with the employee")
    return {"ok": True, "employee": {k: v for k, v in doc.items() if k not in ("_id", "face_descriptor", "password_hash")}}

@api_router.patch("/admin/employees/{user_id}/password")
async def admin_set_password(user_id: str, payload: SetEmployeePassword, user: dict = Depends(require_manager)):
    await ensure_manages_other(user, user_id)
    emp = await db.users.find_one({"user_id": user_id}, {"_id": 0, "name": 1})
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    await db.users.update_one({"user_id": user_id}, {"$set": {
        "password_hash": hash_password(validate_password(payload.password)),
        "must_change_password": True,
        "password_set_at": now_utc().isoformat(),
    }})
    await db.user_sessions.delete_many({"user_id": user_id})
    await log_activity(user, "password_set", emp.get("name", user_id), "temporary password issued")
    return {"ok": True}

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
    full = await db.users.find_one({"user_id": user_id}, {"_id": 0})
    await db.removed_users.insert_one({**full, "removed_at": now_utc().isoformat(), "removed_by": user.get("name")})
    await db.users.delete_one({"user_id": user_id})
    await db.user_sessions.delete_many({"user_id": user_id})
    await db.push_subscriptions.delete_many({"user_id": user_id})
    await db.users.update_many({"manager_id": user_id}, {"$set": {"manager_id": None}})
    await log_activity(user, "employee_removed", emp.get("name", user_id))
    return {"ok": True}

@api_router.patch("/admin/employees/{user_id}/assignment")
async def admin_set_assignment(user_id: str, payload: AssignmentUpdate, user: dict = Depends(require_manager)):
    await ensure_manages_other(user, user_id)
    updates = {k: (v or None) for k, v in payload.model_dump(exclude_unset=True).items() if k not in ("name", "email")}
    if payload.name is not None:
        if not payload.name.strip():
            raise HTTPException(status_code=400, detail="Name cannot be empty")
        updates["name"] = payload.name.strip()
    if payload.email is not None:
        email = payload.email.strip().lower()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            raise HTTPException(status_code=400, detail="Enter a valid email address")
        clash = await db.users.find_one({"email": email, "user_id": {"$ne": user_id}}, {"_id": 0, "user_id": 1})
        if clash:
            raise HTTPException(status_code=400, detail="Another employee already uses this email")
        updates["email"] = email
        current = await db.users.find_one({"user_id": user_id}, {"_id": 0, "email": 1})
        if current and current.get("email") != email:
            await db.user_sessions.delete_many({"user_id": user_id})
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    res = await db.users.update_one({"user_id": user_id}, {"$set": updates})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Employee not found")
    emp = await db.users.find_one({"user_id": user_id}, {"_id": 0, "face_descriptor": 0, "password_hash": 0})
    await log_activity(user, "employee_assigned", emp.get("name", user_id), ", ".join(f"{k}={v}" for k, v in updates.items()))
    return {"ok": True, "employee": emp}

@api_router.patch("/admin/employees/{user_id}/field_staff")
async def admin_set_field_staff(user_id: str, payload: FieldStaffUpdate, user: dict = Depends(require_manager)):
    await ensure_manages_other(user, user_id)
    emp = await db.users.find_one({"user_id": user_id}, {"_id": 0, "name": 1})
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    await db.users.update_one({"user_id": user_id}, {"$set": {"field_staff": payload.field_staff}})
    await log_activity(user, "field_staff_changed", emp.get("name", user_id), "can punch anywhere" if payload.field_staff else "branch area only")
    return {"ok": True}

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

def holiday_scope(site: Optional[str]) -> dict:
    """Holidays that apply to someone at `site`: company-wide ones plus their branch's."""
    conds = [{"branches": {"$in": [None, []]}}]
    if site:
        conds.append({"branches": site})
    return {"$or": conds}

def holiday_applies(h: dict, site: Optional[str]) -> bool:
    return not h.get("branches") or (site in h["branches"])

async def count_leave_days(start: str, end: str, half_day: bool, site: Optional[str] = None) -> float:
    """Calendar days minus declared holidays (company-wide or the employee's branch) inside the range."""
    days = count_leave_days_raw(start, end, half_day)
    if half_day:
        return days
    holidays = len(await db.holidays.distinct("date", {"date": {"$gte": start, "$lte": end}, **holiday_scope(site)}))
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
    days = await count_leave_days(payload.start_date, payload.end_date, payload.half_day, user.get("site"))
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
    emps = await db.users.find({"user_id": {"$in": emp_ids}}, {"_id": 0, "face_descriptor": 0, "password_hash": 0}).to_list(1000)
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
    spawn_user_push(req["user_id"], leave_push_payload(req, payload.status, (payload.note or "").strip(), user.get("name")))
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
    q = {"date": {"$gte": f"{y}-01-01", "$lte": f"{y}-12-31"}}
    if user.get("role") not in ("admin", "sub_admin"):
        q.update(holiday_scope(user.get("site")))
    docs = await db.holidays.find(q, {"_id": 0}).sort("date", 1).to_list(400)
    for d in docs:
        d["branches"] = d.get("branches") or []
        d["can_edit"] = can_edit_holiday(user, d)
    return {"year": y, "holidays": docs}

def can_edit_holiday(user: dict, h: dict) -> bool:
    if user.get("role") == "admin":
        return True
    mine = set(user.get("managed_sites") or [])
    return user.get("role") == "sub_admin" and bool(h.get("branches")) and set(h["branches"]) <= mine

@api_router.post("/admin/holidays")
async def add_holiday(payload: HolidayIn, user: dict = Depends(require_manager)):
    try:
        ddate.fromisoformat(payload.date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date") from None
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Give the holiday a name")
    branches = sorted({b.strip() for b in payload.branches if b.strip()})
    known = {s["name"] for s in await db.sites.find({}, {"_id": 0, "name": 1}).to_list(500)}
    if set(branches) - known:
        raise HTTPException(status_code=400, detail=f"Unknown branch: {', '.join(sorted(set(branches) - known))}")
    if user.get("role") != "admin":
        mine = set(user.get("managed_sites") or [])
        if not mine:
            raise HTTPException(status_code=403, detail="You don't manage any branch yet. Ask an admin to assign one.")
        if not branches:
            raise HTTPException(status_code=400, detail="Pick at least one of your branches")
        if set(branches) - mine:
            raise HTTPException(status_code=403, detail="You can only mark holidays for your own branches")
    clash_q = {"date": payload.date}
    if branches:
        clash_q["$or"] = [{"branches": {"$in": [None, []]}}, {"branches": {"$in": branches}}]
    clash = await db.holidays.find_one(clash_q, {"_id": 0})
    if clash:
        where = ", ".join(clash.get("branches") or []) or "the whole company"
        raise HTTPException(status_code=400, detail=f"{clash['name']} is already a holiday on this date for {where}")
    doc = {"holiday_id": f"hol_{uuid.uuid4().hex[:10]}", "date": payload.date, "name": name, "branches": branches,
           "created_by": user["user_id"], "created_at": now_utc().isoformat()}
    await db.holidays.insert_one(doc)
    await log_activity(user, "holiday_added", doc["name"], f"{doc['date']} · {', '.join(branches) or 'whole company'}")
    return {"ok": True, "holiday": {k: v for k, v in doc.items() if k != "_id"}}

@api_router.delete("/admin/holidays/{holiday_id}")
async def delete_holiday(holiday_id: str, user: dict = Depends(require_manager)):
    doc = await db.holidays.find_one({"holiday_id": holiday_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Not found")
    if not can_edit_holiday(user, doc):
        raise HTTPException(status_code=403, detail="You can only remove holidays for your own branches")
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
        "created_at": now_utc().isoformat(), "notify_phones": payload.notify_phones,
    }
    await db.announcements.insert_one(doc)
    if payload.notify_phones:
        _track(asyncio.create_task(push_announcement(dict(doc))))
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
async def admin_activity(
    user: dict = Depends(require_admin),
    action: Optional[str] = None, person: Optional[str] = None, q: Optional[str] = None,
    from_date: Optional[str] = Query(None, alias="from"), to_date: Optional[str] = Query(None, alias="to"),
    page: int = Query(1, ge=1), page_size: int = Query(25, ge=5, le=100),
):
    filt: dict = {}
    if action:
        filt["action"] = action
    if person:
        rx = {"$regex": re.escape(person), "$options": "i"}
        filt["$or"] = [{"actor_name": rx}, {"target_name": rx}]
    if q:
        rx = {"$regex": re.escape(q), "$options": "i"}
        filt.setdefault("$and", []).append({"$or": [{"actor_name": rx}, {"target_name": rx}, {"details": rx}, {"action": rx}]})
    if from_date or to_date:
        rng = {}
        tz = ZoneInfo(user.get("timezone") or DEFAULT_TZ)
        if from_date:
            rng["$gte"] = datetime.combine(ddate.fromisoformat(from_date), dtime(0, 0), tz).astimezone(timezone.utc).isoformat()
        if to_date:
            rng["$lt"] = datetime.combine(ddate.fromisoformat(to_date) + timedelta(days=1), dtime(0, 0), tz).astimezone(timezone.utc).isoformat()
        filt["created_at"] = rng
    total = await db.activity_log.count_documents(filt)
    docs = await db.activity_log.find(filt, {"_id": 0}).sort("created_at", -1).skip((page - 1) * page_size).to_list(page_size)
    actions = sorted(await db.activity_log.distinct("action"))
    return {"entries": docs, "total": total, "page": page, "page_size": page_size, "actions": actions}

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

    shift_users = {u["user_id"] for u in await db.users.find({**uf, "shift_start": {"$nin": [None, ""]}}, {"_id": 0, "user_id": 1}).to_list(5000)}
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
            if (r.get("late_by_minutes") or 0) > 0 and r["user_id"] in shift_users:
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
    await auto_close_stale_sessions()
    uf = user_filter(user_ids)
    users = await db.users.find(uf, {"_id": 0, "face_descriptor": 0, "password_hash": 0}).to_list(1000)
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
        {"date": {"$gte": from_date, "$lte": to_date}}, {"_id": 0, "date": 1, "branches": 1}
    ).to_list(2000)

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

    joined = {p["user_id"]: p.get("date_of_joining") for p in await db.employee_profiles.find(
        {"user_id": {"$in": [u["user_id"] for u in users]}}, {"_id": 0, "user_id": 1, "date_of_joining": 1}).to_list(5000)}
    rows = []
    for u in users:
        recs = by_user.get(u["user_id"], [])
        present_dates = {r["date"] for r in recs}
        leave_dates = leave_dates_by_user.get(u["user_id"], set())
        holiday_dates = {h["date"] for h in holiday_docs if holiday_applies(h, u.get("site"))}
        has_shift = bool(u.get("shift_start"))
        late_dates = {r["date"] for r in recs if has_shift and (r.get("late_by_minutes") or 0) > 0}
        jd = joined.get(u["user_id"]) or (u.get("created_at") or "")[:10] or None
        counts: dict = {}
        today_d = datetime.now(ZoneInfo(u.get("timezone") or DEFAULT_TZ)).date()
        for d in all_dates:
            st = day_status(ddate.fromisoformat(d), today=today_d, present=d in present_dates, late=d in late_dates,
                            on_leave=d in leave_dates, holiday=d in holiday_dates,
                            weekly_off=u.get("weekly_off", DEFAULT_WEEKLY_OFF), has_shift=has_shift,
                            joined=ddate.fromisoformat(jd) if jd else None, pending_invite=bool(u.get("pending_invite")))
            counts[st] = counts.get(st, 0) + 1
        absent_days = counts.get("absent", 0)
        late_days = len(late_dates)
        total_late = sum((r.get("late_by_minutes") or 0) for r in recs)
        total_work = sum((r.get("net_work_minutes") or 0) for r in recs)
        total_break = sum((r.get("total_break_minutes") or 0) for r in recs)
        over_break_days = sum(1 for r in recs if r.get("over_break"))
        punch_counts = {}
        for r in recs:
            key = r.get("check_in_branch") or "Outside / no zone"
            punch_counts[key] = punch_counts.get(key, 0) + 1
        rows.append({
            "punch_branches": ", ".join(f"{k} ({v})" for k, v in sorted(punch_counts.items(), key=lambda x: -x[1])),
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
            "holiday_days": counts.get("holiday", 0),
            "absent_days": absent_days,
            "weekly_off_days": counts.get("weekly_off", 0),
            "no_shift_days": counts.get("no_shift", 0),
            "not_joined_days": counts.get("not_joined", 0),
            "future_days": counts.get("future", 0),
            "overtime_minutes": sum((r.get("overtime_minutes") or 0) for r in recs),
            "auto_closed_sessions": sum(1 for r in recs if r.get("auto_closed")),
            "over_cap_sessions": sum(1 for r in recs if r.get("over_cap")),
            "late_days": late_days,
            "total_late_minutes": total_late,
            "total_work_minutes": total_work,
            "total_break_minutes": total_break,
            "over_break_days": over_break_days,
            "sessions": len(recs),
        })
    rows.sort(key=lambda x: x["name"].lower())
    return rows

def filter_report_rows(rows: List[dict], branch: Optional[str], department: Optional[str], employee: Optional[str]) -> List[dict]:
    return [r for r in rows if (not branch or r.get("site") == branch)
            and (not department or r.get("department") == department) and (not employee or r["user_id"] == employee)]

@api_router.get("/admin/reports")
async def admin_reports(
    from_date: str = Query(..., alias="from"),
    to_date: str = Query(..., alias="to"),
    branch: Optional[str] = None,
    department: Optional[str] = None,
    employee: Optional[str] = None,
    user: dict = Depends(require_manager),
):
    rows = filter_report_rows(await build_report(from_date, to_date, await scoped_user_ids(user)), branch, department, employee)
    return {"from": from_date, "to": to_date, "rows": rows}

@api_router.get("/admin/reports.csv")
async def admin_reports_csv(
    from_date: str = Query(..., alias="from"),
    to_date: str = Query(..., alias="to"),
    request: Request = None,
    auth: Optional[str] = Query(None),
    branch: Optional[str] = None,
    department: Optional[str] = None,
    employee: Optional[str] = None,
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

    rows = filter_report_rows(await build_report(from_date, to_date, await scoped_user_ids(u)), branch, department, employee)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "Employee", "Email", "Department", "Home Branch", "Punched At", "Shift Start", "Shift End", "Break Limit (min)",
        "Present Days", "Leave Days", "Holidays", "Weekly Off Days", "No Shift Days", "Absent Days", "Late Days", "Total Late (min)",
        "Total Work (h:m)", "Total Break (min)", "Over-Break Days", "Sessions", "Auto-closed (missed checkout)",
    ])
    for r in rows:
        hours = (r["total_work_minutes"] or 0) // 60
        mins = (r["total_work_minutes"] or 0) % 60
        writer.writerow([
            r["name"], r["email"], r.get("department") or "", r.get("site") or "", r.get("punch_branches") or "",
            r["shift_start"] or "", r["shift_end"] or "",
            r["break_max_minutes"], r["present_days"], r["leave_days"], r["holiday_days"], r["weekly_off_days"], r["no_shift_days"], r["absent_days"],
            r["late_days"], r["total_late_minutes"],
            f"{hours}h {mins}m",
            r["total_break_minutes"], r["over_break_days"], r["sessions"], r["auto_closed_sessions"],
        ])
    buf.seek(0)
    filename = f"attendance_report_{from_date}_to_{to_date}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )

# ---------- Push subscription endpoints ----------
@api_router.get("/push/public-key")
async def push_public_key(user: dict = Depends(get_current_user)):
    return {"public_key": VAPID_PUBLIC_KEY}

@api_router.get("/push/status")
async def push_status(endpoint: Optional[str] = None, user: dict = Depends(get_current_user)):
    devices = await db.push_subscriptions.count_documents({"user_id": user["user_id"]})
    mine = await db.push_subscriptions.find_one({"endpoint": endpoint, "user_id": user["user_id"]}, {"_id": 0}) if endpoint else None
    mine = mine or {}
    return {
        "devices": devices, "this_device": bool(mine), "silent": bool(mine.get("silent")),
        "leave_updates": mine.get("leave_updates", True) is not False,
        "announcements": mine.get("announcements", True) is not False,
        "celebrations": mine.get("celebrations", True) is not False,
        "reminders": mine.get("reminders", True) is not False,
    }

@api_router.patch("/push/subscribe")
async def push_update_device(payload: PushDeviceSettings, user: dict = Depends(get_current_user)):
    updates = payload.model_dump(exclude={"endpoint"}, exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No changes")
    res = await db.push_subscriptions.update_one(
        {"endpoint": payload.endpoint, "user_id": user["user_id"]}, {"$set": updates}
    )
    if not res.matched_count:
        raise HTTPException(status_code=404, detail="This phone isn't subscribed")
    return {"ok": True, **updates}

@api_router.post("/push/subscribe")
async def push_subscribe(payload: PushSubscriptionIn, request: Request, user: dict = Depends(get_current_user)):
    if not payload.endpoint.startswith("https://"):
        raise HTTPException(status_code=400, detail="Invalid push endpoint")
    now_iso = now_utc().isoformat()
    await db.push_subscriptions.update_one({"endpoint": payload.endpoint}, {
        "$set": {"endpoint": payload.endpoint, "keys": payload.keys.model_dump(), "user_id": user["user_id"],
                 "user_agent": request.headers.get("user-agent", "")[:200], "updated_at": now_iso},
        "$setOnInsert": {"created_at": now_iso, "silent": False},
    }, upsert=True)
    return {"ok": True}

@api_router.delete("/push/subscribe")
async def push_unsubscribe(endpoint: str, user: dict = Depends(get_current_user)):
    await db.push_subscriptions.delete_one({"endpoint": endpoint, "user_id": user["user_id"]})
    return {"ok": True}

@api_router.post("/push/test")
async def push_test(user: dict = Depends(get_current_user)):
    subs = await db.push_subscriptions.find({"user_id": user["user_id"]}, {"_id": 0}).to_list(50)
    if not subs:
        raise HTTPException(status_code=400, detail="No device is subscribed yet")
    manager = user.get("role") in ("admin", "sub_admin")
    sent = await push_to_subscriptions(subs, {
        "title": "Kelasa notifications are on",
        "body": "You'll get a notification when someone leaves a branch area." if manager
                else "You'll get a notification when your leave is approved or rejected.",
        "tag": "kelasa-test", "url": "/admin#alerts" if manager else "/leave",
    })
    return {"ok": True, "sent": sent, "devices": len(subs)}

# ---------- Geofence alerts ----------
DEFAULT_ESCALATE_MINUTES = 30

async def escalate_minutes() -> int:
    doc = await db.settings.find_one({"key": "geofence"}, {"_id": 0})
    return (doc or {}).get("escalate_minutes") or DEFAULT_ESCALATE_MINUTES

async def resolve_alerts(query: dict, resolved_iso: str, reason: str):
    every = await escalate_minutes()
    for a in await db.geofence_alerts.find(query, {"_id": 0}).to_list(100):
        a["resolved_at"] = resolved_iso
        e = enrich_alert(a, every)
        await db.geofence_alerts.update_one({"alert_id": a["alert_id"]}, {"$set": {
            "resolved_at": resolved_iso, "resolved_reason": reason,
            "final_minutes": e["minutes_outside"], "final_level": e["escalation_level"],
        }})

def enrich_alert(a: dict, every: int) -> dict:
    end = parse_iso(a["resolved_at"]) if a.get("resolved_at") else now_utc()
    minutes = a.get("final_minutes")
    if minutes is None:
        minutes = max(0, int((end - parse_iso(a["created_at"])).total_seconds() // 60))
    level = a["final_level"] if a.get("final_level") is not None else minutes // every
    a["minutes_outside"] = minutes
    a["escalation_level"] = level
    a["needs_attention"] = not a.get("resolved_at") and (
        not a.get("acknowledged_at") or (a.get("acknowledged_level") or 0) < level
    )
    return a

@api_router.get("/admin/settings/geofence")
async def get_geofence_settings(user: dict = Depends(require_manager)):
    return {"escalate_minutes": await escalate_minutes()}

@api_router.put("/admin/settings/geofence")
async def put_geofence_settings(payload: GeofenceSettings, user: dict = Depends(require_admin)):
    if not (5 <= payload.escalate_minutes <= 480):
        raise HTTPException(status_code=400, detail="Escalation must be between 5 and 480 minutes")
    await db.settings.update_one({"key": "geofence"}, {"$set": {"escalate_minutes": payload.escalate_minutes}}, upsert=True)
    await log_activity(user, "geofence_settings", "Leaving-area alerts", f"repeat every {payload.escalate_minutes} min")
    return {"escalate_minutes": payload.escalate_minutes}

@api_router.get("/admin/geofence-alerts")
async def admin_geofence_alerts(user: dict = Depends(require_manager)):
    uf = user_filter(await scoped_user_ids(user))
    every = await escalate_minutes()
    active = await db.geofence_alerts.find({"resolved_at": None, **uf}, {"_id": 0}).sort("created_at", -1).to_list(200)
    since = (now_utc() - timedelta(hours=24)).isoformat()
    recent = await db.geofence_alerts.find(
        {"resolved_at": {"$ne": None}, "created_at": {"$gte": since}, **uf}, {"_id": 0}
    ).sort("created_at", -1).to_list(50)
    return {
        "escalate_minutes": every,
        "active": [enrich_alert(a, every) for a in active],
        "recent": [enrich_alert(a, every) for a in recent],
    }

async def alert_history(user: dict, from_date: str, to_date: str) -> dict:
    every = await escalate_minutes()
    docs = await db.geofence_alerts.find(
        {"date": {"$gte": from_date, "$lte": to_date}, **user_filter(await scoped_user_ids(user))}, {"_id": 0}
    ).sort("created_at", -1).to_list(5000)
    return {"from": from_date, "to": to_date, "escalate_minutes": every, "alerts": [enrich_alert(a, every) for a in docs]}

@api_router.get("/admin/geofence-alerts/history")
async def admin_alert_history(
    from_date: str = Query(..., alias="from"),
    to_date: str = Query(..., alias="to"),
    user: dict = Depends(require_manager),
):
    return await alert_history(user, from_date, to_date)

@api_router.get("/admin/geofence-alerts/history.csv")
async def admin_alert_history_csv(
    request: Request,
    from_date: str = Query(..., alias="from"),
    to_date: str = Query(..., alias="to"),
    auth: Optional[str] = Query(None),
):
    u = await manager_from_request(request, auth)
    data = await alert_history(u, from_date, to_date)
    tz = u.get("timezone") or DEFAULT_TZ
    fmt = lambda iso: to_local(iso, tz).strftime("%H:%M") if iso else ""  # noqa: E731
    rows = [[
        a["date"], a.get("name") or "", fmt(a["created_at"]),
        fmt(a.get("resolved_at")) or "Still outside", a.get("resolved_reason") or "",
        a["minutes_outside"], a.get("distance_m") or "", a.get("nearest_branch") or "",
        a["escalation_level"], a.get("acknowledged_by") or "",
    ] for a in data["alerts"]]
    return csv_response([
        "Date", "Employee", "Left At", "Returned At", "How It Ended", "Minutes Outside",
        "Last Distance (m)", "Nearest Branch", "Repeat Alerts", "Acknowledged By",
    ], rows, f"left_area_log_{from_date}_to_{to_date}.csv")

@api_router.post("/admin/geofence-alerts/{alert_id}/ack")
async def admin_ack_geofence_alert(alert_id: str, user: dict = Depends(require_manager)):
    alert = await db.geofence_alerts.find_one({"alert_id": alert_id}, {"_id": 0})
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    await ensure_in_scope(user, alert["user_id"])
    level = enrich_alert(dict(alert), await escalate_minutes())["escalation_level"]
    await db.geofence_alerts.update_one({"alert_id": alert_id}, {"$set": {
        "acknowledged_by": user.get("name"), "acknowledged_at": now_utc().isoformat(), "acknowledged_level": level,
    }})
    return {"ok": True}

# ---------- Branch punch report ----------
async def build_punch_log(from_date: str, to_date: str, user_ids=None) -> List[dict]:
    uf = user_filter(user_ids)
    records = await db.attendance.find(
        {"date": {"$gte": from_date, "$lte": to_date}, **uf}, {"_id": 0}
    ).sort("check_in", 1).to_list(20000)
    users = await db.users.find(
        {"user_id": {"$in": list({r["user_id"] for r in records})}},
        {"_id": 0, "user_id": 1, "name": 1, "email": 1, "site": 1, "department": 1, "timezone": 1, "field_staff": 1},
    ).to_list(5000)
    umap = {u["user_id"]: u for u in users}
    fmt = lambda iso, tz: to_local(iso, tz).strftime("%H:%M") if iso else None  # noqa: E731
    out = []
    for r in records:
        u = umap.get(r["user_id"], {})
        tz = u.get("timezone") or DEFAULT_TZ
        out.append({
            "record_id": r["record_id"], "user_id": r["user_id"],
            "name": u.get("name", ""), "email": u.get("email", ""),
            "home_branch": u.get("site"), "department": u.get("department"),
            "field_staff": bool(u.get("field_staff")), "date": r["date"],
            "check_in": fmt(r.get("check_in"), tz), "check_in_branch": r.get("check_in_branch"),
            "check_out": fmt(r.get("check_out"), tz), "check_out_branch": r.get("check_out_branch"),
            "net_work_minutes": r.get("net_work_minutes"), "late_by_minutes": r.get("late_by_minutes"),
        })
    return out

@api_router.get("/admin/reports/branches")
async def admin_branch_report(
    from_date: str = Query(..., alias="from"),
    to_date: str = Query(..., alias="to"),
    user: dict = Depends(require_manager),
):
    log = await build_punch_log(from_date, to_date, await scoped_user_ids(user))
    alerts = await db.geofence_alerts.count_documents(
        {"date": {"$gte": from_date, "$lte": to_date}, **user_filter(await scoped_user_ids(user))}
    )
    return {"from": from_date, "to": to_date, "punches": log, "zone_alerts": alerts}

async def manager_from_request(request: Request, auth: Optional[str]) -> dict:
    u = await user_from_request(request, auth)
    if u.get("role") not in ("admin", "sub_admin"):
        raise HTTPException(status_code=403, detail="Admin only")
    return u

async def user_from_request(request: Request, auth: Optional[str]) -> dict:
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
    u = await db.users.find_one({"user_id": session["user_id"]}, {"_id": 0})
    if not u:
        raise HTTPException(status_code=401, detail="Invalid session")
    return u

def csv_response(header: List[str], rows: List[list], filename: str) -> StreamingResponse:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(header)
    writer.writerows(rows)
    return StreamingResponse(
        iter([buf.getvalue()]), media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

@api_router.get("/admin/reports/punches.csv")
async def admin_punches_csv(
    request: Request,
    from_date: str = Query(..., alias="from"),
    to_date: str = Query(..., alias="to"),
    auth: Optional[str] = Query(None),
):
    u = await manager_from_request(request, auth)
    log = await build_punch_log(from_date, to_date, await scoped_user_ids(u))
    rows = [[
        p["date"], p["name"], p["email"], p["home_branch"] or "", p["department"] or "",
        "Yes" if p["field_staff"] else "No",
        p["check_in"] or "", p["check_in_branch"] or "Outside / no zone",
        p["check_out"] or "", (p["check_out_branch"] or "Outside / no zone") if p["check_out"] else "",
        p["net_work_minutes"] if p["net_work_minutes"] is not None else "", p["late_by_minutes"] or 0,
    ] for p in log]
    return csv_response([
        "Date", "Employee", "Email", "Home Branch", "Department", "Field Staff",
        "Punch In", "Punch In Branch", "Punch Out", "Punch Out Branch", "Net Work (min)", "Late (min)",
    ], rows, f"branch_punches_{from_date}_to_{to_date}.csv")

# ---------- Employee profile ----------
PROFILE_DATE_FIELDS = ("dob", "wedding_anniversary", "date_of_joining")
PROFILE_LABELS = {"dob": "Date of birth", "wedding_anniversary": "Wedding anniversary", "date_of_joining": "Joining date"}
IFSC_RE = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")

def clean_profile(payload: ProfileUpdate, today_iso: str) -> dict:
    out = {}
    data = payload.model_dump(exclude_unset=True)
    for k in PROFILE_DATE_FIELDS:
        if k in data:
            v = (data[k] or "").strip()
            if v:
                try:
                    d = ddate.fromisoformat(v)
                except ValueError:
                    raise HTTPException(status_code=400, detail=f"Invalid {PROFILE_LABELS[k].lower()}") from None
                if d > ddate.fromisoformat(today_iso):
                    raise HTTPException(status_code=400, detail=f"{PROFILE_LABELS[k]} can't be in the future")
            out[k] = v or None
    if "uan" in data:
        v = re.sub(r"\s", "", data["uan"] or "")
        if v and not re.fullmatch(r"\d{12}", v):
            raise HTTPException(status_code=400, detail="UAN must be 12 digits")
        out["uan"] = v or None
    if "esi" in data:
        v = re.sub(r"\s", "", data["esi"] or "")
        if v and not re.fullmatch(r"\d{10}|\d{17}", v):
            raise HTTPException(status_code=400, detail="ESI number must be 10 or 17 digits")
        out["esi"] = v or None
    if data.get("esi_not_applicable") is not None:
        out["esi_not_applicable"] = bool(data["esi_not_applicable"])
        if out["esi_not_applicable"] and not out.get("esi"):
            out["esi"] = None
    if out.get("esi"):
        out["esi_not_applicable"] = False
    if data.get("epf_not_applicable") is not None:
        out["epf_not_applicable"] = bool(data["epf_not_applicable"])
        if out["epf_not_applicable"] and not out.get("uan"):
            out["uan"] = None
    if out.get("uan"):
        out["epf_not_applicable"] = False
    return out

def payroll_profile_for_new_employee(payload: EmployeeCreate, today_iso: str) -> dict:
    """PF (UAN), ESI and bank account are part of adding an employee."""
    statutory = clean_profile(ProfileUpdate(
        uan=payload.uan, esi=payload.esi,
        epf_not_applicable=payload.epf_not_applicable,
        esi_not_applicable=payload.esi_not_applicable,
    ), today_iso)
    if payload.epf_not_applicable:
        statutory["uan"] = None
        statutory["epf_not_applicable"] = True
    elif not statutory.get("uan"):
        raise HTTPException(status_code=400, detail="Enter the PF UAN, or mark PF as not applicable")
    if payload.esi_not_applicable:
        statutory["esi"] = None
        statutory["esi_not_applicable"] = True
    elif not statutory.get("esi"):
        raise HTTPException(status_code=400, detail="Enter the ESI number, or mark ESI as not applicable")
    holder = (payload.account_holder or payload.name or "").strip()
    if not (payload.bank_name or "").strip():
        raise HTTPException(status_code=400, detail="Bank name is required")
    bank = clean_bank(BankDetailsIn(
        account_holder=holder,
        account_number=payload.account_number or "",
        ifsc=payload.ifsc or "",
        bank_name=payload.bank_name,
    ))
    return {**statutory, "bank": bank}


def clean_bank(payload: BankDetailsIn) -> dict:
    number = re.sub(r"\s", "", payload.account_number)
    ifsc = payload.ifsc.strip().upper()
    holder = payload.account_holder.strip()
    if not holder:
        raise HTTPException(status_code=400, detail="Account holder name required")
    if not re.fullmatch(r"\d{9,18}", number):
        raise HTTPException(status_code=400, detail="Account number must be 9 to 18 digits")
    if not IFSC_RE.fullmatch(ifsc):
        raise HTTPException(status_code=400, detail="IFSC must look like SBIN0001234")
    return {"account_holder": holder, "account_number": number, "ifsc": ifsc, "bank_name": (payload.bank_name or "").strip() or None}

async def load_profile(user_id: str) -> dict:
    prof = await db.employee_profiles.find_one({"user_id": user_id}, {"_id": 0}) or {"user_id": user_id}
    u = await db.users.find_one({"user_id": user_id}, {"_id": 0, "avatar_path": 1, "name": 1, "email": 1, "site": 1, "department": 1})
    pending = await db.bank_change_requests.find_one({"user_id": user_id, "status": "pending"}, {"_id": 0})
    last = await db.bank_change_requests.find_one(
        {"user_id": user_id, "status": {"$ne": "pending"}}, {"_id": 0}, sort=[("decided_at", -1)]
    )
    return {**prof, **(u or {}), "pending_bank": pending, "last_bank_decision": last}

async def ensure_can_view_sensitive(actor: dict, target_id: str):
    if actor.get("role") == "admin":
        return
    if actor.get("role") == "sub_admin":
        await ensure_in_scope(actor, target_id)
        return
    raise HTTPException(status_code=403, detail="Not allowed")

async def save_profile_fields(user_id: str, updates: dict):
    if not updates:
        raise HTTPException(status_code=400, detail="No changes")
    await db.employee_profiles.update_one(
        {"user_id": user_id}, {"$set": {**updates, "updated_at": now_utc().isoformat()}, "$setOnInsert": {"user_id": user_id}}, upsert=True
    )

@api_router.get("/profile/me")
async def my_profile(user: dict = Depends(get_current_user)):
    return await load_profile(user["user_id"])

@api_router.put("/profile/me")
async def update_my_profile(payload: ProfileUpdate, user: dict = Depends(get_current_user)):
    updates = clean_profile(payload, user_local_today(user))
    await save_profile_fields(user["user_id"], updates)
    await log_activity(user, "profile_updated", user.get("name", ""), ", ".join(updates))
    return await load_profile(user["user_id"])

@api_router.post("/profile/me/avatar")
async def upload_avatar(payload: AvatarUpload, user: dict = Depends(get_current_user)):
    raw = payload.image_b64.split(",", 1)[1] if payload.image_b64.startswith("data:") else payload.image_b64
    try:
        data = base64.b64decode(raw, validate=True)
    except (ValueError, binascii.Error):
        raise HTTPException(status_code=400, detail="Invalid image") from None
    if len(data) > 3 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Photo too large (max 3 MB)")
    if data[:3] == b"\xff\xd8\xff":
        ext, ctype = "jpg", "image/jpeg"
    elif data[:8] == b"\x89PNG\r\n\x1a\n":
        ext, ctype = "png", "image/png"
    else:
        raise HTTPException(status_code=400, detail="Use a JPG or PNG photo")
    path = f"{APP_NAME}/avatars/{user['user_id']}/{uuid.uuid4().hex}.{ext}"
    result = await asyncio.to_thread(put_object, path, data, ctype)
    await db.users.update_one({"user_id": user["user_id"]}, {"$set": {"avatar_path": result["path"]}})
    return {"ok": True, "avatar_path": result["path"]}

@api_router.delete("/profile/me/avatar")
async def delete_avatar(user: dict = Depends(get_current_user)):
    await db.users.update_one({"user_id": user["user_id"]}, {"$set": {"avatar_path": None}})
    return {"ok": True}

@api_router.post("/profile/me/bank")
async def request_bank_change(payload: BankDetailsIn, user: dict = Depends(get_current_user)):
    bank = clean_bank(payload)
    now_iso = now_utc().isoformat()
    await db.bank_change_requests.update_many(
        {"user_id": user["user_id"], "status": "pending"}, {"$set": {"status": "superseded", "decided_at": now_iso}}
    )
    req = {
        "request_id": f"bank_{uuid.uuid4().hex[:12]}", "user_id": user["user_id"], "user_name": user.get("name"),
        **bank, "status": "pending", "created_at": now_iso, "decided_at": None, "decided_by": None, "note": None,
    }
    await db.bank_change_requests.insert_one(dict(req))
    await log_activity(user, "bank_change_requested", user.get("name", ""), f"{bank['ifsc']} ••{bank['account_number'][-4:]}")
    admins = [a["user_id"] for a in await db.users.find({"role": "admin"}, {"_id": 0, "user_id": 1}).to_list(50)]
    subs = await db.push_subscriptions.find({"user_id": {"$in": admins}}, {"_id": 0}).to_list(200)
    if subs:
        _track(asyncio.create_task(push_to_subscriptions(subs, {
            "title": "Bank details change request", "body": f"{user.get('name')} submitted new bank details for approval",
            "tag": req["request_id"], "url": "/admin#team",
        })))
    return {"ok": True, "request": req}

@api_router.delete("/profile/me/bank")
async def cancel_bank_change(user: dict = Depends(get_current_user)):
    res = await db.bank_change_requests.update_many(
        {"user_id": user["user_id"], "status": "pending"}, {"$set": {"status": "cancelled", "decided_at": now_utc().isoformat()}}
    )
    if not res.modified_count:
        raise HTTPException(status_code=404, detail="No pending change")
    return {"ok": True}

@api_router.get("/admin/employees/{user_id}/profile")
async def admin_employee_profile(user_id: str, user: dict = Depends(require_manager)):
    await ensure_can_view_sensitive(user, user_id)
    if not await db.users.find_one({"user_id": user_id}, {"_id": 1}):
        raise HTTPException(status_code=404, detail="Employee not found")
    return await load_profile(user_id)

@api_router.put("/admin/employees/{user_id}/profile")
async def admin_update_employee_profile(user_id: str, payload: ProfileUpdate, user: dict = Depends(require_manager)):
    await ensure_manages_other(user, user_id)
    emp = await db.users.find_one({"user_id": user_id}, {"_id": 0, "name": 1})
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    updates = clean_profile(payload, user_local_today(user))
    await save_profile_fields(user_id, updates)
    await log_activity(user, "profile_updated", emp.get("name", user_id), ", ".join(updates))
    return await load_profile(user_id)

@api_router.get("/admin/bank-requests")
async def admin_bank_requests(user: dict = Depends(require_admin)):
    items = await db.bank_change_requests.find({"status": "pending"}, {"_id": 0}).sort("created_at", 1).to_list(500)
    current = {
        p["user_id"]: p.get("bank") for p in await db.employee_profiles.find(
            {"user_id": {"$in": [i["user_id"] for i in items]}}, {"_id": 0, "user_id": 1, "bank": 1}
        ).to_list(500)
    }
    for i in items:
        i["current_bank"] = current.get(i["user_id"])
    return {"requests": items}

@api_router.post("/admin/bank-requests/{request_id}/decide")
async def admin_decide_bank(request_id: str, payload: BankDecision, user: dict = Depends(require_admin)):
    if payload.status not in ("approved", "rejected"):
        raise HTTPException(status_code=400, detail="Status must be approved or rejected")
    req = await db.bank_change_requests.find_one({"request_id": request_id}, {"_id": 0})
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")
    if req["status"] != "pending":
        raise HTTPException(status_code=400, detail="Already decided")
    now_iso = now_utc().isoformat()
    note = (payload.note or "").strip() or None
    await db.bank_change_requests.update_one({"request_id": request_id}, {"$set": {
        "status": payload.status, "decided_at": now_iso, "decided_by": user.get("name"), "note": note,
    }})
    if payload.status == "approved":
        bank = {k: req[k] for k in ("account_holder", "account_number", "ifsc", "bank_name")}
        await save_profile_fields(req["user_id"], {"bank": {**bank, "approved_at": now_iso, "approved_by": user.get("name")}})
    await log_activity(user, f"bank_{payload.status}", req.get("user_name", ""), f"{req['ifsc']} ••{req['account_number'][-4:]}")
    body = f"Account ••{req['account_number'][-4:]} · {req['ifsc']}" + (f"\nNote: {note}" if note else "")
    spawn_user_push(req["user_id"], {"title": f"Bank details {payload.status}", "body": body, "tag": request_id, "url": "/profile"})
    return {"ok": True}

def _this_year_occurrence(d: ddate, year: int) -> ddate:
    try:
        return d.replace(year=year)
    except ValueError:
        return ddate(year, 2, 28)

CELEBRATION_KINDS = {"dob": "birthday", "wedding_anniversary": "wedding_anniversary", "date_of_joining": "work_anniversary"}
KIND_LABEL = {"birthday": "birthday", "wedding_anniversary": "wedding anniversary", "work_anniversary": "work anniversary"}

async def compute_celebrations(today_d: ddate, days: int, back: int = 0) -> List[dict]:
    profiles = await db.employee_profiles.find(
        {"$or": [{f: {"$ne": None}} for f in PROFILE_DATE_FIELDS]}, {"_id": 0, "user_id": 1, **{f: 1 for f in PROFILE_DATE_FIELDS}}
    ).to_list(5000)
    users = {
        u["user_id"]: u for u in await db.users.find(
            {"user_id": {"$in": [p["user_id"] for p in profiles]}},
            {"_id": 0, "user_id": 1, "name": 1, "avatar_path": 1, "site": 1, "department": 1},
        ).to_list(5000)
    }
    start = today_d - timedelta(days=back)
    out = []
    for p in profiles:
        u = users.get(p["user_id"])
        if not u:
            continue
        for field, kind in CELEBRATION_KINDS.items():
            if not p.get(field):
                continue
            orig = ddate.fromisoformat(p[field])
            nxt = _this_year_occurrence(orig, start.year)
            if nxt < start:
                nxt = _this_year_occurrence(orig, start.year + 1)
            away = (nxt - today_d).days
            if away > days:
                continue
            years = nxt.year - orig.year
            if kind != "birthday" and years < 1:
                continue
            out.append({
                "user_id": u["user_id"], "name": u.get("name"), "avatar_path": u.get("avatar_path"),
                "site": u.get("site"), "department": u.get("department"), "kind": kind,
                "date": nxt.isoformat(), "days_away": away, "years": years if kind != "birthday" else None,
            })
    out.sort(key=lambda x: (x["days_away"], x["name"] or ""))
    return out

def local_today_date(user: Optional[dict] = None) -> ddate:
    t = user_local_today(user or {})
    return ddate.fromisoformat(t) if isinstance(t, str) else t

@api_router.get("/celebrations")
async def celebrations(days: int = Query(7, ge=0, le=31), user: dict = Depends(get_current_user)):
    today_d = local_today_date(user)
    items = await compute_celebrations(today_d, days)
    mine_sent = await db.wishes.find(
        {"from_user_id": user["user_id"], "occasion_date": {"$in": list({c["date"] for c in items})}},
        {"_id": 0, "to_user_id": 1, "kind": 1, "occasion_date": 1, "wish_id": 1},
    ).to_list(500)
    sent = {(w["to_user_id"], w["kind"], w["occasion_date"]): w["wish_id"] for w in mine_sent}
    for c in items:
        c["is_me"] = c["user_id"] == user["user_id"]
        c["my_wish_id"] = sent.get((c["user_id"], c["kind"], c["date"]))
        if c["is_me"]:
            c["wish_count"] = await db.wishes.count_documents(
                {"to_user_id": user["user_id"], "kind": c["kind"], "occasion_date": c["date"]}
            )
    return {"today": today_d.isoformat(), "celebrations": items}

# ---------- Wishes (private threads) ----------
WISH_MAX = 500

def _wish_view(w: dict, me: str) -> dict:
    mine_is_to = w["to_user_id"] == me
    w["direction"] = "received" if mine_is_to else "sent"
    w["unread"] = not w.get("read_by_to" if mine_is_to else "read_by_from", False)
    return w

async def push_wish(user_id: str, payload: dict):
    subs = await db.push_subscriptions.find({"user_id": user_id, "celebrations": {"$ne": False}}, {"_id": 0}).to_list(50)
    if subs:
        await push_to_subscriptions(subs, payload)

@api_router.post("/wishes")
async def send_wish(payload: WishIn, user: dict = Depends(get_current_user)):
    msg = payload.message.strip()
    if not msg:
        raise HTTPException(status_code=400, detail="Write a message")
    if len(msg) > WISH_MAX:
        raise HTTPException(status_code=400, detail=f"Keep it under {WISH_MAX} characters")
    if payload.to_user_id == user["user_id"]:
        raise HTTPException(status_code=400, detail="You can't wish yourself")
    today_d = local_today_date(user)
    occasion = next((c for c in await compute_celebrations(today_d, 7, back=3)
                     if c["user_id"] == payload.to_user_id and c["kind"] == payload.kind), None)
    if not occasion:
        raise HTTPException(status_code=400, detail="There's no celebration to wish them for right now")
    existing = await db.wishes.find_one(
        {"from_user_id": user["user_id"], "to_user_id": payload.to_user_id, "kind": payload.kind, "occasion_date": occasion["date"]},
        {"_id": 0},
    )
    if existing:
        raise HTTPException(status_code=400, detail="You already sent a wish — reply in the conversation instead")
    now_iso = now_utc().isoformat()
    doc = {
        "wish_id": f"wish_{uuid.uuid4().hex[:12]}", "to_user_id": payload.to_user_id, "to_name": occasion["name"],
        "from_user_id": user["user_id"], "from_name": user.get("name"), "kind": payload.kind,
        "occasion_date": occasion["date"], "years": occasion.get("years"),
        "messages": [{"from_user_id": user["user_id"], "from_name": user.get("name"), "message": msg, "created_at": now_iso}],
        "created_at": now_iso, "updated_at": now_iso, "read_by_from": True, "read_by_to": False,
    }
    await db.wishes.insert_one(dict(doc))
    _track(asyncio.create_task(push_wish(payload.to_user_id, {
        "title": f"{user.get('name')} sent you a {KIND_LABEL[payload.kind]} wish",
        "body": msg[:180], "tag": doc["wish_id"], "url": "/wishes",
    })))
    return {"ok": True, "wish": _wish_view(doc, user["user_id"])}

@api_router.get("/wishes")
async def my_wishes(user: dict = Depends(get_current_user)):
    me = user["user_id"]
    docs = await db.wishes.find({"$or": [{"to_user_id": me}, {"from_user_id": me}]}, {"_id": 0}).sort("updated_at", -1).to_list(500)
    items = [_wish_view(w, me) for w in docs]
    return {"wishes": items, "unread": sum(1 for w in items if w["unread"])}

@api_router.get("/wishes/unread-count")
async def wishes_unread(user: dict = Depends(get_current_user)):
    me = user["user_id"]
    n = await db.wishes.count_documents({"$or": [
        {"to_user_id": me, "read_by_to": False}, {"from_user_id": me, "read_by_from": False},
    ]})
    return {"unread": n}

async def _wish_for_participant(wish_id: str, me: str) -> dict:
    w = await db.wishes.find_one({"wish_id": wish_id}, {"_id": 0})
    if not w or me not in (w["to_user_id"], w["from_user_id"]):
        raise HTTPException(status_code=404, detail="Conversation not found")
    return w

@api_router.post("/wishes/{wish_id}/read")
async def read_wish(wish_id: str, user: dict = Depends(get_current_user)):
    w = await _wish_for_participant(wish_id, user["user_id"])
    field = "read_by_to" if w["to_user_id"] == user["user_id"] else "read_by_from"
    await db.wishes.update_one({"wish_id": wish_id}, {"$set": {field: True}})
    return {"ok": True}

@api_router.post("/wishes/{wish_id}/reply")
async def reply_wish(wish_id: str, payload: WishReply, user: dict = Depends(get_current_user)):
    msg = payload.message.strip()
    if not msg:
        raise HTTPException(status_code=400, detail="Write a message")
    if len(msg) > WISH_MAX:
        raise HTTPException(status_code=400, detail=f"Keep it under {WISH_MAX} characters")
    w = await _wish_for_participant(wish_id, user["user_id"])
    now_iso = now_utc().isoformat()
    i_am_to = w["to_user_id"] == user["user_id"]
    entry = {"from_user_id": user["user_id"], "from_name": user.get("name"), "message": msg, "created_at": now_iso}
    await db.wishes.update_one({"wish_id": wish_id}, {
        "$push": {"messages": entry},
        "$set": {"updated_at": now_iso, "read_by_to": i_am_to, "read_by_from": not i_am_to},
    })
    other = w["from_user_id"] if i_am_to else w["to_user_id"]
    _track(asyncio.create_task(push_wish(other, {
        "title": f"{user.get('name')} replied", "body": msg[:180], "tag": wish_id, "url": "/wishes",
    })))
    return {"ok": True, "message": entry}

# ---------- Morning celebrations cron ----------
def _cron_authorized(request: Request) -> bool:
    expected = os.environ["WEBHOOK_CRON_SECRET"]
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return False
    return hmac.compare_digest(header[7:].encode(), expected.encode())

def _names(items: List[dict]) -> str:
    parts = []
    for c in items:
        first = (c["name"] or "").split(" ")[0]
        parts.append(f"{first}'s birthday" if c["kind"] == "birthday" else f"{first}'s {c['years']}-yr {KIND_LABEL[c['kind']]}")
    return ", ".join(parts[:-1]) + f" and {parts[-1]}" if len(parts) > 1 else parts[0]

async def run_morning_celebrations(day_key: str):
    today_d = ddate.fromisoformat(day_key)
    items = [c for c in await compute_celebrations(today_d, 0)]
    if not items:
        await db.cron_runs.update_one({"key": f"celebrations-{day_key}"}, {"$set": {"status": "nothing_today", "sent": 0}})
        return
    subs = await db.push_subscriptions.find({"celebrations": {"$ne": False}}, {"_id": 0}).to_list(5000)
    by_user: dict = {}
    for sub in subs:
        by_user.setdefault(sub["user_id"], []).append(sub)
    sent = 0
    for uid, user_subs in by_user.items():
        mine = [c for c in items if c["user_id"] == uid]
        others = [c for c in items if c["user_id"] != uid]
        if mine:
            first = (mine[0]["name"] or "").split(" ")[0]
            occasions = " & ".join(KIND_LABEL[c["kind"]] for c in mine)
            title = f"Happy {occasions}, {first}!"
            body = "Wishing you a wonderful day from all of us." + (f" Also today: {_names(others)}." if others else "")
        else:
            title = "Celebrations today"
            body = f"Today: {_names(others)}. Tap to send a wish."
        sent += await push_to_subscriptions(user_subs, {"title": title, "body": body, "tag": f"celebrations-{day_key}", "url": "/dashboard"})
    await db.cron_runs.update_one({"key": f"celebrations-{day_key}"}, {"$set": {"status": "done", "sent": sent, "celebrations": len(items)}})

@api_router.post("/cron/celebrations")
async def cron_celebrations(request: Request):
    # Cron endpoints must ack 2xx immediately; enqueue/background the actual work.
    if not _cron_authorized(request):
        raise HTTPException(status_code=401, detail="Unauthorized")
    try:
        envelope = await request.json()
    except ValueError:
        envelope = None
    if envelope is not None and not isinstance(envelope, dict):
        raise HTTPException(status_code=400, detail="Invalid body")
    run_id = request.headers.get("X-Webhook-Id") or (envelope or {}).get("run_id") or uuid.uuid4().hex
    day_key = datetime.now(ZoneInfo(DEFAULT_TZ)).date().isoformat()
    try:
        await db.cron_runs.insert_one({"key": f"celebrations-{day_key}", "run_id": run_id, "status": "queued", "created_at": now_utc().isoformat()})
    except DuplicateKeyError:
        return {"ok": True, "duplicate": True}
    _track(asyncio.create_task(run_morning_celebrations(day_key)))
    return {"ok": True, "queued": day_key}

# ---------- Missed check-out reminder cron ----------
async def run_checkout_reminders() -> int:
    since = (now_utc() - timedelta(days=1)).date().isoformat()
    opens = await db.attendance.find({"check_out": None, "checkout_reminder_sent": {"$ne": True}, "date": {"$gte": since}}, {"_id": 0}).to_list(5000)
    if not opens:
        return 0
    users = {u["user_id"]: u for u in await db.users.find(
        {"user_id": {"$in": list({o["user_id"] for o in opens})}}, {"_id": 0, "face_descriptor": 0, "password_hash": 0}).to_list(5000)}
    sent = 0
    for rec in opens:
        u = users.get(rec["user_id"]) or {}
        start, end = parse_hhmm(u.get("shift_start") or ""), parse_hhmm(u.get("shift_end") or "")
        if not start or not end or end <= start:
            continue
        tz = ZoneInfo(u.get("timezone") or DEFAULT_TZ)
        local_in = parse_iso(rec["check_in"]).astimezone(tz)
        shift_end_dt = datetime.combine(local_in.date(), end, tz)
        if local_in >= shift_end_dt or now_utc() < shift_end_dt or now_utc().astimezone(tz).date() != local_in.date():
            continue
        res = await db.attendance.update_one({"record_id": rec["record_id"], "checkout_reminder_sent": {"$ne": True}},
                                             {"$set": {"checkout_reminder_sent": True, "checkout_reminder_at": now_utc().isoformat()}})
        if not res.modified_count:
            continue
        subs = await db.push_subscriptions.find({"user_id": rec["user_id"], "reminders": {"$ne": False}}, {"_id": 0}).to_list(20)
        if subs:
            await push_to_subscriptions(subs, {
                "title": "Forgot to check out?",
                "body": f"Your shift ended at {u['shift_end']}. Tap to check out now — otherwise your hours will be counted only up to {u['shift_end']}.",
                "tag": f"checkout_{rec['record_id']}", "url": "/dashboard",
            })
            sent += 1
    return sent

@api_router.post("/cron/checkout-reminders")
async def cron_checkout_reminders(request: Request):
    # Cron endpoints must ack 2xx immediately; enqueue/background the actual work.
    if not _cron_authorized(request):
        raise HTTPException(status_code=401, detail="Unauthorized")
    try:
        envelope = await request.json()
    except ValueError:
        envelope = None
    if envelope is not None and not isinstance(envelope, dict):
        raise HTTPException(status_code=400, detail="Invalid body")
    _track(asyncio.create_task(run_checkout_reminders()))
    return {"ok": True, "queued": True}

# ---------- Morning missed check-out digest (managers) ----------
def _name_list(names: List[str], limit: int = 4) -> str:
    shown = names[:limit]
    rest = len(names) - len(shown)
    return ", ".join(shown) + (f" and {rest} more" if rest else "")

async def run_missed_checkout_digest(day_key: str):
    await auto_close_stale_sessions()
    yday = (ddate.fromisoformat(day_key) - timedelta(days=1)).isoformat()
    recs = await db.attendance.find({"date": yday, "$or": [
        {"check_out": None}, {"auto_closed": True, "auto_close_reason": {"$regex": "^missed checkout"}}]},
        {"_id": 0, "user_id": 1}).to_list(5000)
    missed = {r["user_id"] for r in recs}
    names = {u["user_id"]: u.get("name") or u.get("email") for u in await db.users.find(
        {"user_id": {"$in": list(missed)}}, {"_id": 0, "user_id": 1, "name": 1, "email": 1}).to_list(5000)}
    subs = await db.push_subscriptions.find({"reminders": {"$ne": False}}, {"_id": 0}).to_list(5000)
    managers = {m["user_id"]: m for m in await db.users.find(
        {"user_id": {"$in": list({x["user_id"] for x in subs})}, "role": {"$in": ["admin", "sub_admin"]}}, {"_id": 0}).to_list(500)}
    label = ddate.fromisoformat(yday).strftime("%a %d %b")
    sent = 0
    for mid, m in managers.items():
        ids = await scoped_user_ids(m)
        team = sorted(names[u] for u in missed if u in names and (ids is None or u in ids) and u != mid)
        if team:
            title = f"{len(team)} missed check-out {label}"
            body = f"{_name_list(team)} didn't check out. Their hours were counted only up to shift end or 23:59."
        else:
            title = f"All clear for {label}"
            body = "Everyone in your team checked out yesterday."
        sent += await push_to_subscriptions([x for x in subs if x["user_id"] == mid],
                                            {"title": title, "body": body, "tag": f"missed-digest-{yday}", "url": "/reports"})
    await db.cron_runs.update_one({"key": f"missed-digest-{day_key}"}, {"$set": {"status": "done", "sent": sent, "missed": len(missed)}})

@api_router.post("/cron/missed-checkout-digest")
async def cron_missed_checkout_digest(request: Request):
    # Cron endpoints must ack 2xx immediately; enqueue/background the actual work.
    if not _cron_authorized(request):
        raise HTTPException(status_code=401, detail="Unauthorized")
    try:
        envelope = await request.json()
    except ValueError:
        envelope = None
    if envelope is not None and not isinstance(envelope, dict):
        raise HTTPException(status_code=400, detail="Invalid body")
    run_id = request.headers.get("X-Webhook-Id") or (envelope or {}).get("run_id") or uuid.uuid4().hex
    day_key = datetime.now(ZoneInfo(DEFAULT_TZ)).date().isoformat()
    try:
        await db.cron_runs.insert_one({"key": f"missed-digest-{day_key}", "run_id": run_id, "status": "queued", "created_at": now_utc().isoformat()})
    except DuplicateKeyError:
        return {"ok": True, "duplicate": True}
    _track(asyncio.create_task(run_missed_checkout_digest(day_key)))
    return {"ok": True, "queued": day_key}

# ---------- Employee calendar ----------
def _month_bounds(month: str):
    y, m = map(int, month.split("-"))
    if not 1 <= m <= 12:
        raise HTTPException(status_code=400, detail="Invalid month")
    first = ddate(y, m, 1)
    return first, ddate(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)

SESSION_KEYS = ("record_id", "check_in", "check_out", "net_work_minutes", "duration_minutes", "total_break_minutes",
                "breaks", "late_by_minutes", "auto_closed", "auto_close_reason", "over_cap", "over_break", "regularized",
                "check_in_branch", "check_out_branch", "status")

async def build_calendar(u: dict, month: str) -> dict:
    await auto_close_stale_sessions()
    first, last = _month_bounds(month)
    f, t = first.isoformat(), last.isoformat()
    uid = u["user_id"]
    recs = await db.attendance.find({"user_id": uid, "date": {"$gte": f, "$lte": t}}, {"_id": 0}).sort("check_in", 1).to_list(2000)
    by_date: dict = {}
    for r in recs:
        if not r.get("superseded_by"):
            by_date.setdefault(r["date"], []).append({k: r.get(k) for k in SESSION_KEYS})
    hols = {h["date"]: h["name"] for h in await db.holidays.find(
        {"date": {"$gte": f, "$lte": t}, **holiday_scope(u.get("site"))}, {"_id": 0, "date": 1, "name": 1}).to_list(200)}
    leave_by_date: dict = {}
    for lv in await db.leave_requests.find({"user_id": uid, "status": "approved", "start_date": {"$lte": t}, "end_date": {"$gte": f}}, {"_id": 0}).to_list(500):
        cur = max(ddate.fromisoformat(lv["start_date"]), first)
        while cur <= min(ddate.fromisoformat(lv["end_date"]), last):
            leave_by_date[cur.isoformat()] = lv
            cur += timedelta(days=1)
    regs = {r["date"]: r for r in await db.regularizations.find(
        {"user_id": uid, "date": {"$gte": f, "$lte": t}}, {"_id": 0}).sort("created_at", 1).to_list(500)}
    prof = await db.employee_profiles.find_one({"user_id": uid}, {"_id": 0, "date_of_joining": 1}) or {}
    jd = prof.get("date_of_joining") or (u.get("created_at") or "")[:10] or None
    has_shift = bool(u.get("shift_start"))
    half = (shift_minutes(u.get("shift_start"), u.get("shift_end")) or 0) / 2
    today_d = local_today_date(u)
    days, counts = [], {}
    cur = first
    while cur <= last:
        d = cur.isoformat()
        sess = by_date.get(d, [])
        lv = leave_by_date.get(d)
        net = sum((x.get("net_work_minutes") or 0) for x in sess)
        open_now = any(not x.get("check_out") for x in sess)
        status = day_status(cur, today=today_d, present=bool(sess),
                            late=has_shift and any((x.get("late_by_minutes") or 0) > 0 for x in sess),
                            on_leave=bool(lv), holiday=d in hols, weekly_off=u.get("weekly_off", DEFAULT_WEEKLY_OFF),
                            has_shift=has_shift, joined=ddate.fromisoformat(jd) if jd else None,
                            pending_invite=bool(u.get("pending_invite")))
        if sess and any((x.get("auto_closed") and not x.get("regularized")) or x.get("over_cap") for x in sess):
            status = "punch_error"
        elif sess and not open_now and half and net < half and cur != today_d:
            status = "half_day"
        elif lv and lv.get("half_day"):
            status = "half_day"
        elif cur == today_d and not sess and status == "absent":
            status = "today"
        counts[status] = counts.get(status, 0) + 1
        days.append({"date": d, "status": status, "sessions": sess, "net_work_minutes": net,
                     "holiday": hols.get(d), "leave": {"leave_type": lv.get("leave_type"), "half_day": lv.get("half_day")} if lv else None,
                     "regularization": regs.get(d)})
        cur += timedelta(days=1)
    return {"month": month, "today": today_d.isoformat(), "days": days, "counts": counts,
            "total_work_minutes": sum(x["net_work_minutes"] for x in days),
            "shift": {"start": u.get("shift_start"), "end": u.get("shift_end")}}

@api_router.get("/me/calendar")
async def my_calendar(month: str = Query(..., pattern=r"^\d{4}-\d{2}$"), user: dict = Depends(get_current_user)):
    return await build_calendar(user, month)

@api_router.get("/me/calendar.csv")
async def my_calendar_csv(request: Request, month: str = Query(..., pattern=r"^\d{4}-\d{2}$"), auth: Optional[str] = Query(None)):
    user = await user_from_request(request, auth)
    cal = await build_calendar(user, month)
    tz = ZoneInfo(user.get("timezone") or DEFAULT_TZ)
    fmt = lambda iso: parse_iso(iso).astimezone(tz).strftime("%H:%M") if iso else ""
    rows = [[d["date"], d["status"].replace("_", " ").title(),
             " | ".join(f"{fmt(x['check_in'])}-{fmt(x['check_out'])}" for x in d["sessions"]),
             _hm(d["net_work_minutes"]), sum((x.get("total_break_minutes") or 0) for x in d["sessions"]),
             d["holiday"] or (d["leave"] or {}).get("leave_type") or ""] for d in cal["days"]]
    return csv_response(["Date", "Status", "Sessions", "Work (h:mm)", "Break (min)", "Holiday / Leave"], rows, f"my_attendance_{month}.csv")

# ---------- Attendance correction (regularization) ----------
def _local_iso(day: str, hhmm: str, tz_name: str) -> str:
    t = parse_hhmm(hhmm)
    if not t:
        raise HTTPException(status_code=400, detail="Use HH:MM times")
    return datetime.combine(ddate.fromisoformat(day), t, ZoneInfo(tz_name)).astimezone(timezone.utc).isoformat()

async def _reg_with_names(items: List[dict]) -> List[dict]:
    ids = {i["user_id"] for i in items} | {i.get("decided_by") for i in items if i.get("decided_by")}
    names = {u["user_id"]: u.get("name") or u.get("email") for u in await db.users.find(
        {"user_id": {"$in": list(ids)}}, {"_id": 0, "user_id": 1, "name": 1, "email": 1}).to_list(1000)}
    return [{**i, "name": names.get(i["user_id"]), "decided_by_name": names.get(i.get("decided_by"))} for i in items]

@api_router.post("/regularizations")
async def create_regularization(payload: RegularizationIn, user: dict = Depends(get_current_user)):
    try:
        day = ddate.fromisoformat(payload.date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date") from None
    if day > local_today_date(user):
        raise HTTPException(status_code=400, detail="You can't correct a future day")
    tz = user.get("timezone") or DEFAULT_TZ
    cin, cout = _local_iso(payload.date, payload.check_in, tz), _local_iso(payload.date, payload.check_out, tz)
    if cout <= cin:
        raise HTTPException(status_code=400, detail="Check-out must be after check-in on the same day")
    if parse_iso(cout) > now_utc():
        raise HTTPException(status_code=400, detail="Check-out time can't be in the future")
    if len(payload.reason.strip()) < 5:
        raise HTTPException(status_code=400, detail="Please explain the reason (at least a few words)")
    if await db.regularizations.find_one({"user_id": user["user_id"], "date": payload.date, "status": "pending"}):
        raise HTTPException(status_code=400, detail="You already have a pending correction for this day")
    doc = {"request_id": f"reg_{uuid.uuid4().hex[:10]}", "user_id": user["user_id"], "date": payload.date,
           "check_in": payload.check_in, "check_out": payload.check_out, "reason": payload.reason.strip(),
           "status": "pending", "created_at": now_utc().isoformat()}
    await db.regularizations.insert_one(doc)
    await log_activity(user, "regularization_requested", user.get("name") or user["user_id"],
                       f"{payload.date} {payload.check_in}-{payload.check_out}")
    doc.pop("_id", None)
    return {"ok": True, "request": doc}

@api_router.get("/regularizations/mine")
async def my_regularizations(user: dict = Depends(get_current_user)):
    items = await db.regularizations.find({"user_id": user["user_id"]}, {"_id": 0}).sort("created_at", -1).to_list(100)
    return {"items": await _reg_with_names(items)}

@api_router.post("/regularizations/{request_id}/cancel")
async def cancel_regularization(request_id: str, user: dict = Depends(get_current_user)):
    res = await db.regularizations.update_one({"request_id": request_id, "user_id": user["user_id"], "status": "pending"},
                                              {"$set": {"status": "cancelled", "decided_at": now_utc().isoformat()}})
    if not res.modified_count:
        raise HTTPException(status_code=404, detail="No pending request to cancel")
    return {"ok": True}

@api_router.get("/admin/regularizations")
async def admin_regularizations(status: Optional[str] = "pending", user: dict = Depends(require_manager)):
    q = {**user_filter(await scoped_user_ids(user))}
    if status and status != "all":
        q["status"] = status
    items = await db.regularizations.find(q, {"_id": 0}).sort("created_at", -1).to_list(500)
    return {"items": await _reg_with_names(items)}

async def apply_regularization(reg: dict, emp: dict):
    tz = emp.get("timezone") or DEFAULT_TZ
    cin, cout = _local_iso(reg["date"], reg["check_in"], tz), _local_iso(reg["date"], reg["check_out"], tz)
    day_recs = await db.attendance.find({"user_id": emp["user_id"], "date": reg["date"]}, {"_id": 0}).sort("check_in", 1).to_list(50)
    rec = day_recs[0] if day_recs else None
    breaks = sum(int(r.get("total_break_minutes") or 0) for r in day_recs)
    calc = compute_session(cin, cout, breaks, emp.get("shift_start"), emp.get("shift_end"))
    fields = {"check_in": cin, "check_out": cout, "status": "off_duty", "on_break": False, "auto_closed": False,
              "auto_close_reason": None, "regularized": True, "regularization_id": reg["request_id"],
              "late_by_minutes": compute_late_minutes(cin, emp),
              "over_break": breaks > int(emp.get("break_max_minutes") if emp.get("break_max_minutes") is not None else 60), **calc}
    if rec:
        keep = {} if rec.get("regularized") else {"original_check_in": rec.get("check_in"), "original_check_out": rec.get("check_out")}
        await db.attendance.update_one({"record_id": rec["record_id"]}, {"$set": {**fields, **keep}})
        await resolve_alerts({"record_id": rec["record_id"], "resolved_at": None}, cout, "regularized")
    else:
        await db.attendance.insert_one({"record_id": f"att_{uuid.uuid4().hex[:12]}", "user_id": emp["user_id"], "date": reg["date"],
                                        "breaks": [], "total_break_minutes": 0, "check_in_branch": None, **fields})
    # The corrected span covers the whole day, so other sessions that day stop counting (originals are kept).
    for r in day_recs[1:]:
        keep = {} if r.get("superseded_by") else {"original_net_work_minutes": r.get("net_work_minutes"),
                                                 "original_auto_closed": r.get("auto_closed"), "original_over_cap": r.get("over_cap")}
        await db.attendance.update_one({"record_id": r["record_id"]}, {"$set": {
            **keep, "superseded_by": reg["request_id"], "net_work_minutes": 0, "overtime_minutes": 0,
            "auto_closed": False, "over_cap": False, "late_by_minutes": 0}})

@api_router.post("/admin/regularizations/{request_id}/decide")
async def decide_regularization(request_id: str, payload: RegularizationDecision, user: dict = Depends(require_manager)):
    reg = await db.regularizations.find_one({"request_id": request_id}, {"_id": 0})
    if not reg:
        raise HTTPException(status_code=404, detail="Not found")
    await ensure_manages_other(user, reg["user_id"])
    note = (payload.note or "").strip()
    if payload.decision == "rejected" and not note:
        raise HTTPException(status_code=400, detail="Add a note explaining why it was rejected")
    if payload.decision == "approved" and await db.attendance.find_one({"user_id": reg["user_id"], "date": reg["date"], "check_out": None}):
        raise HTTPException(status_code=400, detail="This employee is still checked in for that day. Approve after they check out.")
    res = await db.regularizations.update_one({"request_id": request_id, "status": "pending"}, {"$set": {
        "status": payload.decision, "manager_note": note or None, "decided_by": user["user_id"], "decided_at": now_utc().isoformat()}})
    if not res.modified_count:
        raise HTTPException(status_code=400, detail="This request was already decided")
    emp = await db.users.find_one({"user_id": reg["user_id"]}, {"_id": 0, "password_hash": 0, "face_descriptor": 0})
    if payload.decision == "approved":
        await apply_regularization(reg, emp)
    await log_activity(user, f"regularization_{payload.decision}", emp.get("name") or reg["user_id"],
                       f"{reg['date']} {reg['check_in']}-{reg['check_out']}" + (f" · {note}" if note else ""))
    nice = ddate.fromisoformat(reg["date"]).strftime("%d %b")
    _track(asyncio.create_task(push_to_user(reg["user_id"], {
        "title": f"Correction {payload.decision} for {nice}",
        "body": note or (f"Your times {reg['check_in']}–{reg['check_out']} were applied." if payload.decision == "approved" else ""),
        "tag": f"reg_{request_id}", "url": "/calendar"})))
    return {"ok": True}

# ---------- Full data export (admin only) ----------
def _export_filename(job: dict) -> str:
    return f"kelasa-export-{parse_iso(job['started_at']).astimezone(ZoneInfo(DEFAULT_TZ)).strftime('%Y-%m-%d-%H%M')}.zip"

def _export_view(job: dict) -> dict:
    return {**{k: job.get(k) for k in ("job_id", "status", "progress", "size_bytes", "error", "stage", "started_at",
                                       "finished_at", "manifest_summary")}, "filename": _export_filename(job)}

@api_router.post("/admin/export/start")
async def export_start(user: dict = Depends(require_admin)):
    try:
        job = export_job.start_export(os.environ["MONGO_URL"], os.environ["DB_NAME"], f"{APP_NAME}/", get_object, user.get("email"))
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e)) from None
    await log_activity(user, "data_export", user.get("email") or user["user_id"], f"Full data export started at {job['started_at']}")
    return {"job_id": job["job_id"]}

@api_router.get("/admin/export/current")
async def export_current(user: dict = Depends(require_admin)):
    job = export_job.latest_job()
    return {"job": _export_view(job) if job else None}

@api_router.get("/admin/export/status/{job_id}")
async def export_status(job_id: str, user: dict = Depends(require_admin)):
    job = export_job.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Export not found")
    return _export_view(job)

@api_router.get("/admin/export/download/{job_id}")
async def export_download(job_id: str, user: dict = Depends(require_admin)):
    job = export_job.get_job(job_id)
    if not job or job["status"] != "done" or not os.path.exists(job["file"]):
        raise HTTPException(status_code=404, detail="Export file not available")
    return FileResponse(job["file"], media_type="application/zip", filename=_export_filename(job))

# ---------- Monthly payroll summary ----------
def _hm(m: int) -> str:
    return f"{(m or 0) // 60}:{(m or 0) % 60:02d}"

@api_router.get("/admin/reports/payroll-summary")
async def payroll_summary(request: Request, month: str = Query(..., pattern=r"^\d{4}-\d{2}$"),
                          format: Literal["xlsx", "csv"] = "xlsx", auth: Optional[str] = Query(None)):
    u = await manager_from_request(request, auth)
    y, m = map(int, month.split("-"))
    if not 1 <= m <= 12:
        raise HTTPException(status_code=400, detail="Invalid month")
    first = ddate(y, m, 1)
    last = (ddate(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1))
    rows = await build_report(first.isoformat(), last.isoformat(), await scoped_user_ids(u))
    header = ["Employee", "Email", "Department", "Branch", "Days in Month", "Present Days", "Leave Days", "Holidays",
              "Weekly Offs", "No Shift Days", "Not Yet Joined", "Upcoming Days", "Absent Days", "Late Days", "Work Hours (h:mm)", "Work Hours (decimal)",
              "Auto-closed Days (missed checkout)", "Sessions over 16h"]
    data = [[r["name"], r["email"], r.get("department") or "", r.get("site") or "", (last - first).days + 1,
             r["present_days"], r["leave_days"], r["holiday_days"], r["weekly_off_days"], r["no_shift_days"],
             r["not_joined_days"], r["future_days"], r["absent_days"], r["late_days"], _hm(r["total_work_minutes"]), round((r["total_work_minutes"] or 0) / 60, 2),
             r["auto_closed_sessions"], r["over_cap_sessions"]] for r in rows]
    await log_activity(u, "payroll_summary_export", f"Payroll summary {month}", f"{len(data)} employees, {format}")
    fname = f"payroll_summary_{month}"
    if format == "csv":
        return csv_response(header, data, f"{fname}.csv")
    from openpyxl import Workbook
    from openpyxl.styles import Font
    wb = Workbook()
    ws = wb.active
    ws.title = first.strftime("%b %Y")
    ws.append(header)
    for c in ws[1]:
        c.font = Font(bold=True)
    for row in data:
        ws.append(row)
    for i, h in enumerate(header, 1):
        ws.column_dimensions[ws.cell(1, i).column_letter].width = max(12, len(h) + 2)
    ws.freeze_panes = "B2"
    out = io.BytesIO()
    wb.save(out)
    return StreamingResponse(iter([out.getvalue()]),
                             media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             headers={"Content-Disposition": f'attachment; filename="{fname}.xlsx"'})

# ---------- Payroll details export ----------
@api_router.get("/admin/reports/payroll-details.csv")
async def payroll_details_csv(request: Request, auth: Optional[str] = Query(None)):
    u = await manager_from_request(request, auth)
    ids = await scoped_user_ids(u)
    users = await db.users.find(
        user_filter(ids),
        {"_id": 0, "user_id": 1, "name": 1, "email": 1, "site": 1, "department": 1, "role": 1},
    ).sort("name", 1).to_list(5000)
    profiles = {p["user_id"]: p for p in await db.employee_profiles.find(
        {"user_id": {"$in": [x["user_id"] for x in users]}}, {"_id": 0}).to_list(5000)}
    pending = {r["user_id"] for r in await db.bank_change_requests.find({"status": "pending"}, {"_id": 0, "user_id": 1}).to_list(5000)}
    rows = []
    for x in users:
        p = profiles.get(x["user_id"], {})
        bank = p.get("bank") or {}
        esi = "Not applicable" if p.get("esi_not_applicable") else (p.get("esi") or "")
        rows.append([
            x["user_id"], x.get("name", ""), x.get("email", ""), x.get("site") or "", x.get("department") or "",
            p.get("date_of_joining") or "", bank.get("account_holder", ""),
            bank.get("account_number", ""), bank.get("ifsc", ""), bank.get("bank_name") or "",
            "Not applicable" if p.get("epf_not_applicable") else (p.get("uan") or ""), esi,
            "Change pending approval" if x["user_id"] in pending else ("Approved" if bank else "Missing"),
        ])
    await log_activity(u, "payroll_export", "Payroll details", f"{len(rows)} employees")
    return csv_response([
        "Employee ID", "Name", "Email", "Branch", "Department", "Joining Date", "Account Holder",
        "Account Number", "IFSC", "Bank Name", "EPF UAN", "ESI Number", "Bank Status",
    ], rows, f"payroll_details_{local_today_date(u).isoformat()}.csv")

@api_router.get("/")
async def root():
    return {"message": "Kelasa API", "status": "ok"}

app.include_router(api_router)
from payroll_api import router as payroll_router, configure_payroll
configure_payroll(
    get_current_user=get_current_user, database=db, log_activity=log_activity,
    push_user=spawn_user_push, put_object=put_object, get_object=get_object,
)
app.include_router(payroll_router)

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
    await ensure_indexes()
    await recalc_attendance_migration()
    _track(asyncio.create_task(run_selfie_purge()))
    _track(asyncio.create_task(auto_close_loop()))
    await seed_admin_password()
    await seed_leave_types()
    from payroll_api import ensure_payroll_indexes
    await ensure_payroll_indexes(db)

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
