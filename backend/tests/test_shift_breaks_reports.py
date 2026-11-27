"""Backend tests for iteration 3: shift mapping, break flows, late tracking, reports."""
import csv
import io
import os
import time as pytime
import uuid
from datetime import datetime, timezone, timedelta

import pytest
import requests
from pymongo import MongoClient

MONGO_URL = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
DB_NAME = os.environ.get('DB_NAME', 'test_database')


# ---------------- Helpers / seed for late tests (uses UTC timezone so we control "now") ----------------
def _break_json(image):
    return {"lat": 12.97, "lng": 77.59, "accuracy": 15, "image_b64": image}


def _seed_user(db, user_id, email, role, token, tz="UTC", shift_start=None, shift_end=None, break_max=60):
    db.users.delete_many({"user_id": user_id})
    db.user_sessions.delete_many({"session_token": token})
    db.attendance.delete_many({"user_id": user_id})
    db.locations.delete_many({"user_id": user_id})
    now = datetime.now(timezone.utc)
    db.users.insert_one({
        "user_id": user_id,
        "email": email,
        "name": email.split("@")[0],
        "picture": None,
        "role": role,
        "face_enrolled": True,
        "face_descriptor": [0.0] * 128,
        "face_photo_path": None,
        "shift_start": shift_start,
        "shift_end": shift_end,
        "break_max_minutes": break_max,
        "timezone": tz,
        "created_at": now.isoformat(),
    })
    db.user_sessions.insert_one({
        "user_id": user_id,
        "session_token": token,
        "expires_at": (now + timedelta(days=7)).isoformat(),
        "created_at": now.isoformat(),
    })


@pytest.fixture(scope="module")
def late_employee(mongo_db):
    """Employee with UTC timezone & shift_start=00:00 -> any check-in today is way past grace -> late."""
    uid = "TEST_user_late01"
    token = "TEST_session_late_001"
    _seed_user(mongo_db, uid, "TEST_late@gtg.local", "employee", token,
               tz="UTC", shift_start="00:00", shift_end="23:59", break_max=60)
    yield {"user_id": uid, "token": token}
    mongo_db.users.delete_one({"user_id": uid})
    mongo_db.user_sessions.delete_one({"session_token": token})
    mongo_db.attendance.delete_many({"user_id": uid})
    mongo_db.locations.delete_many({"user_id": uid})


@pytest.fixture
def late_client(late_employee):
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {late_employee['token']}", "Content-Type": "application/json"})
    return s


# ---------- Admin shift PATCH ----------
class TestAdminShiftPatch:
    def test_patch_shift_valid(self, admin_client, employee_client, base_url, mongo_db):
        r = admin_client.patch(f"{base_url}/api/admin/employees/TEST_user_emp01/shift",
                               json={"shift_start": "09:00", "shift_end": "18:00", "break_max_minutes": 45})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        emp = body["employee"]
        assert emp["shift_start"] == "09:00"
        assert emp["shift_end"] == "18:00"
        assert emp["break_max_minutes"] == 45
        # verify persisted
        u = mongo_db.users.find_one({"user_id": "TEST_user_emp01"})
        assert u["shift_start"] == "09:00"
        assert u["break_max_minutes"] == 45

    def test_patch_shift_invalid_time_format(self, admin_client, base_url):
        r = admin_client.patch(f"{base_url}/api/admin/employees/TEST_user_emp01/shift",
                               json={"shift_start": "foo"})
        assert r.status_code == 400

    def test_patch_shift_nonexistent_user(self, admin_client, base_url):
        r = admin_client.patch(f"{base_url}/api/admin/employees/NOT_A_USER/shift",
                               json={"shift_start": "10:00"})
        assert r.status_code == 404

    def test_patch_shift_forbidden_for_employee(self, employee_client, base_url):
        r = employee_client.patch(f"{base_url}/api/admin/employees/TEST_user_emp01/shift",
                                  json={"shift_start": "09:00"})
        assert r.status_code == 403

    def test_employees_list_includes_shift_and_on_break(self, admin_client, base_url):
        r = admin_client.get(f"{base_url}/api/admin/employees")
        assert r.status_code == 200
        emps = r.json()["employees"]
        ours = next((e for e in emps if e["user_id"] == "TEST_user_emp01"), None)
        assert ours is not None
        assert "shift_start" in ours
        assert "shift_end" in ours
        assert "break_max_minutes" in ours
        assert "on_break" in ours


# ---------- Late computation ----------
class TestLateCheckin:
    def test_checkin_after_grace_is_late(self, late_client, base_url, mongo_db, tiny_jpeg_b64, late_employee):
        mongo_db.attendance.delete_many({"user_id": late_employee["user_id"]})
        # tz=UTC, shift_start=00:00 => current minute of day > 15 means late
        now = datetime.now(timezone.utc)
        minute_of_day = now.hour * 60 + now.minute
        r = late_client.post(f"{base_url}/api/attendance/checkin", json={
            "lat": 12.97, "lng": 77.59, "accuracy": 15,
            "descriptor": [0.0] * 128, "image_b64": tiny_jpeg_b64
        })
        assert r.status_code == 200, r.text
        body = r.json()
        if minute_of_day > 15:
            assert body["late_by_minutes"] is not None
            assert body["late_by_minutes"] > 0
            assert body["late_by_minutes"] == minute_of_day - 15 or abs(body["late_by_minutes"] - (minute_of_day - 15)) <= 1
        else:
            assert (body["late_by_minutes"] or 0) == 0

    def test_checkin_no_shift_returns_none_late(self, employee_client, base_url, mongo_db, tiny_jpeg_b64):
        # ensure shift cleared and no active record
        mongo_db.users.update_one({"user_id": "TEST_user_emp01"}, {"$set": {"shift_start": None}})
        mongo_db.attendance.delete_many({"user_id": "TEST_user_emp01"})
        r = employee_client.post(f"{base_url}/api/attendance/checkin", json={
            "lat": 12.97, "lng": 77.59, "accuracy": 15,
            "descriptor": [0.0] * 128, "image_b64": tiny_jpeg_b64
        })
        assert r.status_code == 200
        assert r.json().get("late_by_minutes") is None
        # cleanup
        employee_client.post(f"{base_url}/api/attendance/checkout", json={
            "lat": 12.97, "lng": 77.59, "accuracy": 15,
            "descriptor": [0.0] * 128, "image_b64": tiny_jpeg_b64
        })


# ---------- Break flow ----------
class TestBreakFlow:
    def test_break_lifecycle_and_overbreak_and_ping_paused(self, late_client, base_url, mongo_db,
                                                            tiny_jpeg_b64, late_employee):
        uid = late_employee["user_id"]
        mongo_db.attendance.delete_many({"user_id": uid})
        mongo_db.locations.delete_many({"user_id": uid})
        # ensure break_max low so we trigger over_break (avoid 0 due to `or` truthiness bug fallback to 60)
        mongo_db.users.update_one({"user_id": uid}, {"$set": {"break_max_minutes": 1}})

        # check in
        r = late_client.post(f"{base_url}/api/attendance/checkin", json={
            "lat": 12.97, "lng": 77.59, "accuracy": 15,
            "descriptor": [0.0] * 128, "image_b64": tiny_jpeg_b64
        })
        assert r.status_code == 200, r.text
        record_id = r.json()["record_id"]

        # start break #1
        r = late_client.post(f"{base_url}/api/attendance/break/start", json=_break_json(tiny_jpeg_b64))
        assert r.status_code == 200
        assert r.json()["ok"] is True

        # double break start -> 400
        r = late_client.post(f"{base_url}/api/attendance/break/start", json=_break_json(tiny_jpeg_b64))
        assert r.status_code == 400
        assert "already" in r.json()["detail"].lower()

        # active record reflects on_break
        rec = mongo_db.attendance.find_one({"record_id": record_id})
        assert rec["on_break"] is True

        # Ping during break -> ok=False, skipped, no DB write
        before = mongo_db.locations.count_documents({"user_id": uid})
        rp = late_client.post(f"{base_url}/api/location/ping",
                              json={"lat": 12.97, "lng": 77.59, "accuracy": 20})
        assert rp.status_code == 200
        body = rp.json()
        assert body["ok"] is False
        assert body.get("reason") == "on_break"
        after = mongo_db.locations.count_documents({"user_id": uid})
        assert after == before, "ping during break should not be persisted"

        # checkout while on break -> 400
        rc = late_client.post(f"{base_url}/api/attendance/checkout", json={
            "lat": 12.97, "lng": 77.59, "accuracy": 15,
            "descriptor": [0.0] * 128, "image_b64": tiny_jpeg_b64
        })
        assert rc.status_code == 400
        assert "break" in rc.json()["detail"].lower()

        # end break (force duration_minutes>0 by backdating start)
        mongo_db.attendance.update_one(
            {"record_id": record_id},
            {"$set": {"breaks.0.start": (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()}}
        )
        r = late_client.post(f"{base_url}/api/attendance/break/end", json=_break_json(tiny_jpeg_b64))
        assert r.status_code == 200
        b1 = r.json()
        assert b1["duration_minutes"] >= 4
        assert b1["total_break_minutes"] >= 4

        # second break to verify accumulation
        r = late_client.post(f"{base_url}/api/attendance/break/start", json=_break_json(tiny_jpeg_b64))
        assert r.status_code == 200
        # backdate the new break too
        mongo_db.attendance.update_one(
            {"record_id": record_id},
            {"$set": {"breaks.1.start": (datetime.now(timezone.utc) - timedelta(minutes=3)).isoformat()}}
        )
        r = late_client.post(f"{base_url}/api/attendance/break/end", json=_break_json(tiny_jpeg_b64))
        assert r.status_code == 200
        b2 = r.json()
        assert b2["total_break_minutes"] >= b1["total_break_minutes"] + 2

        # also backdate check_in so duration > break total
        mongo_db.attendance.update_one(
            {"record_id": record_id},
            {"$set": {"check_in": (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()}}
        )

        # checkout now succeeds -> net_work_minutes & over_break
        rc = late_client.post(f"{base_url}/api/attendance/checkout", json={
            "lat": 12.97, "lng": 77.59, "accuracy": 15,
            "descriptor": [0.0] * 128, "image_b64": tiny_jpeg_b64
        })
        assert rc.status_code == 200, rc.text
        cdata = rc.json()
        assert "net_work_minutes" in cdata
        assert cdata["net_work_minutes"] == max(cdata["duration_minutes"] - b2["total_break_minutes"], 0)
        assert cdata["over_break"] is True  # break_max=1 and breaks ~ 5+3 mins triggers it

    def test_break_start_not_on_duty(self, employee_client, base_url, mongo_db):
        mongo_db.attendance.delete_many({"user_id": "TEST_user_emp01", "check_out": None})
        r = employee_client.post(f"{base_url}/api/attendance/break/start", json={})
        assert r.status_code == 400

    def test_break_end_when_not_on_break(self, late_client, base_url, mongo_db, tiny_jpeg_b64, late_employee):
        uid = late_employee["user_id"]
        mongo_db.attendance.delete_many({"user_id": uid})
        late_client.post(f"{base_url}/api/attendance/checkin", json={
            "lat": 12.97, "lng": 77.59, "accuracy": 15,
            "descriptor": [0.0] * 128, "image_b64": tiny_jpeg_b64
        })
        r = late_client.post(f"{base_url}/api/attendance/break/end", json={})
        assert r.status_code == 400
        # cleanup
        late_client.post(f"{base_url}/api/attendance/checkout", json={
            "lat": 12.97, "lng": 77.59, "accuracy": 15,
            "descriptor": [0.0] * 128, "image_b64": tiny_jpeg_b64
        })


# ---------- Reports ----------
class TestReports:
    def test_reports_json(self, admin_client, base_url):
        today = datetime.now(timezone.utc).date().isoformat()
        frm = (datetime.now(timezone.utc).date() - timedelta(days=7)).isoformat()
        r = admin_client.get(f"{base_url}/api/admin/reports?from={frm}&to={today}")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["from"] == frm and body["to"] == today
        assert isinstance(body["rows"], list)
        if body["rows"]:
            row = body["rows"][0]
            for k in ("user_id","name","email","present_days","absent_days","late_days",
                       "total_late_minutes","total_work_minutes","total_break_minutes",
                       "over_break_days","sessions"):
                assert k in row, f"missing {k} in report row"

    def test_reports_csv_with_bearer(self, admin_client, base_url):
        today = datetime.now(timezone.utc).date().isoformat()
        frm = (datetime.now(timezone.utc).date() - timedelta(days=7)).isoformat()
        r = admin_client.get(f"{base_url}/api/admin/reports.csv?from={frm}&to={today}")
        assert r.status_code == 200, r.text
        assert "text/csv" in r.headers.get("content-type", "")
        cd = r.headers.get("content-disposition", "")
        assert "attachment" in cd and ".csv" in cd
        text = r.text
        rows = list(csv.reader(io.StringIO(text)))
        assert len(rows) >= 1
        assert rows[0][0] == "Employee"
        assert "Total Work (h:m)" in rows[0]

    def test_reports_csv_with_auth_query_param(self, admin_token, base_url):
        today = datetime.now(timezone.utc).date().isoformat()
        frm = today
        # no cookies, no Authorization header -> use ?auth=
        r = requests.get(f"{base_url}/api/admin/reports.csv?from={frm}&to={today}&auth={admin_token}")
        assert r.status_code == 200, r.text
        assert "text/csv" in r.headers.get("content-type", "")

    def test_reports_csv_unauthorized(self, base_url):
        today = datetime.now(timezone.utc).date().isoformat()
        r = requests.get(f"{base_url}/api/admin/reports.csv?from={today}&to={today}")
        assert r.status_code == 401

    def test_reports_csv_forbidden_for_employee(self, employee_client, base_url):
        today = datetime.now(timezone.utc).date().isoformat()
        r = employee_client.get(f"{base_url}/api/admin/reports.csv?from={today}&to={today}")
        assert r.status_code == 403


# ---------- Stats includes late_today ----------
class TestStats:
    def test_stats_has_late_today(self, admin_client, base_url):
        r = admin_client.get(f"{base_url}/api/admin/stats")
        assert r.status_code == 200
        assert "late_today" in r.json()
        assert isinstance(r.json()["late_today"], int)


# ---------- Break selfies, required GPS, over-break push ----------
# These drive the handlers with an in-memory stand-in, same as selfie retention,
# so they do not need a running API or object storage.
import asyncio

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test_database")
os.environ.setdefault("VAPID_PUBLIC_KEY", "test-public")
os.environ.setdefault("VAPID_PRIVATE_KEY", "test-private")
os.environ.setdefault("VAPID_SUBJECT", "mailto:test@example.com")

from fastapi import HTTPException
from work_timing import DayTiming
from attendance_calc import compute_session
import server

SELFIE = "A" * 240
FROZEN = datetime(2026, 11, 27, 12, 0, tzinfo=timezone.utc)


def _iso(minutes_before=0):
    return (FROZEN - timedelta(minutes=minutes_before)).isoformat()


def _match(doc, query):
    if not query:
        return True
    for key, expected in query.items():
        if key == "$or":
            if not any(_match(doc, clause) for clause in expected):
                return False
            continue
        value = doc.get(key)
        if isinstance(expected, dict):
            if "$elemMatch" in expected:
                items = value if isinstance(value, list) else []
                if not any(_match(item, expected["$elemMatch"]) for item in items if isinstance(item, dict)):
                    return False
                continue
            if "$ne" in expected and value == expected["$ne"]:
                return False
            if "$in" in expected and value not in expected["$in"]:
                return False
            if "$lt" in expected and (value is None or not (value < expected["$lt"])):
                return False
            if any(str(k).startswith("$") for k in expected):
                continue
        elif value != expected:
            return False
    return True


class _Cursor:
    def __init__(self, docs):
        self.docs = docs

    async def to_list(self, limit):
        return [dict(d) for d in self.docs[:limit]]


class _Collection:
    def __init__(self):
        self.docs = []

    async def find_one(self, query, projection=None, sort=None):
        rows = [d for d in self.docs if _match(d, query)]
        if sort:
            for key, direction in reversed(sort):
                rows.sort(key=lambda d: d.get(key) or "", reverse=direction < 0)
        return dict(rows[0]) if rows else None

    def find(self, query, projection=None):
        return _Cursor([d for d in self.docs if _match(d, query)])

    async def update_one(self, query, update):
        for doc in self.docs:
            if _match(doc, query):
                for key, value in (update.get("$set") or {}).items():
                    doc[key] = value
                for key, value in (update.get("$push") or {}).items():
                    doc.setdefault(key, []).append(value)
                return

    async def insert_one(self, doc):
        self.docs.append(dict(doc))


class _DB:
    def __init__(self):
        self._cols = {}

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        if name not in self._cols:
            self._cols[name] = _Collection()
        return self._cols[name]


def _people():
    return [
        {"user_id": "emp", "role": "employee", "name": "Asha Rao", "site": "Bengaluru HQ",
         "department": "Field Operations", "manager_id": "sub_mgr", "timezone": "UTC"},
        {"user_id": "sub_mgr", "role": "sub_admin", "name": "Team Lead", "managed_departments": [], "managed_sites": []},
        {"user_id": "sub_site", "role": "sub_admin", "name": "Branch Lead", "managed_departments": [], "managed_sites": ["Bengaluru HQ"]},
        {"user_id": "sub_other", "role": "sub_admin", "name": "Other", "managed_departments": [], "managed_sites": ["Tumkur Yard"]},
        {"user_id": "sub_quiet", "role": "sub_admin", "name": "Quiet", "managed_departments": ["Field Operations"], "managed_sites": []},
        {"user_id": "admin", "role": "admin", "name": "Boss"},
    ]


def _subs():
    rows = []
    for uid, reminders in (
        ("sub_mgr", True), ("sub_site", True), ("sub_other", True),
        ("sub_quiet", False), ("admin", True), ("emp", True),
    ):
        rows.append({"user_id": uid, "endpoint": f"https://push/{uid}", "keys": {}, "reminders": reminders})
    return rows


def _session(minutes_open=180):
    return {
        "record_id": "att_break",
        "user_id": "emp",
        "date": "2026-11-27",
        "check_in": _iso(minutes_open),
        "check_out": None,
        "on_break": False,
        "breaks": [],
        "total_break_minutes": 0,
        "status": "on_duty",
    }


def _proof(**over):
    body = {"lat": 12.9716, "lng": 77.5946, "accuracy": 18, "image_b64": SELFIE}
    body.update(over)
    return server.BreakRequest(**body)


class TestBreakSelfieRules:
    def setup_method(self):
        self.db = _DB()
        self.db.users.docs = _people()
        self.db.push_subscriptions.docs = _subs()
        self.db.attendance.docs = [_session()]
        self.pushes = []
        self.uploaded = []
        self.geo_calls = []
        self.user = dict(self.db.users.docs[0])

    def _install(self, monkeypatch):
        async def capture(subs, payload):
            self.pushes.append({"users": [s["user_id"] for s in subs], "payload": payload})
            return len(subs)

        def upload(user_id, image_b64, kind):
            self.uploaded.append(kind)
            return f"gtg-attendance/{kind}/{user_id}/{kind}.jpg"

        async def geo(*args, **kwargs):
            self.geo_calls.append(args)
            return "Bengaluru HQ"

        async def timing(user, day):
            return DayTiming(source="default", working=True)

        monkeypatch.setattr(server, "db", self.db)
        monkeypatch.setattr(server, "now_utc", lambda: FROZEN)
        monkeypatch.setattr(server, "push_to_subscriptions", capture)
        monkeypatch.setattr(server, "upload_face_image", upload)
        monkeypatch.setattr(server, "enforce_geofence", geo)
        monkeypatch.setattr(server, "timing_for_user", timing)

    def _rec(self):
        return self.db.attendance.docs[0]

    def _backdate_open(self, minutes):
        self._rec()["breaks"][-1]["start"] = _iso(minutes)

    def test_missing_selfie_or_location_does_not_change_on_break(self, monkeypatch):
        self._install(monkeypatch)

        async def run():
            for payload in (
                server.BreakRequest(lat=12.97, lng=77.59),
                server.BreakRequest(image_b64=SELFIE, lng=77.59),
                server.BreakRequest(image_b64=SELFIE, lat=12.97),
                server.BreakRequest(lat=12.97, lng=77.59, image_b64="short"),
                server.BreakRequest(),
            ):
                with pytest.raises(HTTPException) as exc:
                    await server.break_start(payload, self.user)
                assert exc.value.status_code == 400
            assert self._rec()["on_break"] is False
            assert self._rec()["breaks"] == []
            assert self.uploaded == []

            await server.break_start(_proof(), self.user)
            assert self._rec()["on_break"] is True
            for payload in (
                server.BreakRequest(lat=12.97, lng=77.59),
                server.BreakRequest(image_b64=SELFIE),
                server.BreakRequest(lat=12.97, lng=77.59, image_b64="x"),
            ):
                with pytest.raises(HTTPException) as exc:
                    await server.break_end(payload, self.user)
                assert exc.value.status_code == 400
            brk = self._rec()["breaks"][0]
            assert self._rec()["on_break"] is True
            assert brk["end"] is None and brk["end_photo_path"] is None
            assert self.uploaded == ["break_start"]
            assert self.geo_calls == []

            self.db.attendance.docs = []
            with pytest.raises(HTTPException) as off:
                await server.break_start(_proof(), self.user)
            assert off.value.status_code == 400

        asyncio.run(run())

    def test_start_and_end_store_photo_and_coordinates(self, monkeypatch):
        self._install(monkeypatch)

        async def run():
            started = await server.break_start(_proof(), self.user)
            assert started["ok"] is True
            brk = self._rec()["breaks"][0]
            assert brk["start_photo_path"].endswith("/break_start/emp/break_start.jpg")
            assert brk["start_lat"] == 12.9716 and brk["start_lng"] == 77.5946
            assert brk["start_accuracy"] == 18
            assert self._rec()["on_break"] is True
            self._backdate_open(25)
            ended = await server.break_end(_proof(lat=12.98, lng=77.60, accuracy=22), self.user)
            brk = self._rec()["breaks"][0]
            assert ended["duration_minutes"] == 25
            assert ended["total_break_minutes"] == 25
            assert ended["over_break"] is False
            assert brk["end_photo_path"].endswith("/break_end/emp/break_end.jpg")
            assert brk["end_lat"] == 12.98 and brk["end_lng"] == 77.60
            assert brk["duration_minutes"] == 25
            assert self._rec()["on_break"] is False
            assert self._rec()["total_break_minutes"] == 25
            assert self.geo_calls == []
            assert self.pushes == []

        asyncio.run(run())

    def test_second_start_and_checkout_while_on_break_stay_blocked(self, monkeypatch):
        self._install(monkeypatch)

        async def run():
            await server.break_start(_proof(), self.user)
            with pytest.raises(HTTPException) as again:
                await server.break_start(_proof(), self.user)
            assert again.value.status_code == 400
            assert "already" in again.value.detail.lower()
            assert len(self._rec()["breaks"]) == 1
            assert self._rec()["on_break"] is True

            with pytest.raises(HTTPException) as checkout:
                await server.check_out(server.CheckRequest(lat=1, lng=2, image_b64=SELFIE), self.user)
            assert checkout.value.status_code == 400
            assert "break" in checkout.value.detail.lower()
            assert self._rec()["on_break"] is True
            assert self._rec()["check_out"] is None
            assert self.geo_calls == []

        asyncio.run(run())

    def test_checkout_subtracts_actual_break_minutes_from_net_hours(self, monkeypatch):
        self._install(monkeypatch)
        cin = _iso(180)
        cout = FROZEN.isoformat()

        async def run():
            await server.break_start(_proof(), self.user)
            self._backdate_open(40)
            await server.break_end(_proof(), self.user)
            result = await server.check_out(server.CheckRequest(lat=1, lng=2, accuracy=5, image_b64=SELFIE), self.user)
            stored = self._rec()
            expected = compute_session(cin, cout, 40, None, None)
            assert stored["total_break_minutes"] == 40
            assert result["duration_minutes"] == 180
            assert result["net_work_minutes"] == 140
            assert stored["net_work_minutes"] == expected["net_work_minutes"] == 140
            assert result["net_work_minutes"] == result["duration_minutes"] - stored["total_break_minutes"]
            # The scheduled break figure is not a second deduction. Only actual minutes move net hours.
            same_net = compute_session(cin, cout, 40, "09:00", "18:00")
            assert same_net["net_work_minutes"] == 140

        asyncio.run(run())

    def test_crossing_default_cap_pushes_covering_sub_admins_and_does_not_block(self, monkeypatch):
        self._install(monkeypatch)
        assert "break_max_minutes" not in self.user

        async def run():
            await server.break_start(_proof(), self.user)
            self._backdate_open(30)
            under = await server.break_end(_proof(), self.user)
            assert under["total_break_minutes"] == 30
            assert under["over_break"] is False
            assert self._rec()["over_break"] is False
            assert self.pushes == []

            await server.break_start(_proof(), self.user)
            self._backdate_open(31)
            over = await server.break_end(_proof(), self.user)
            assert over["duration_minutes"] == 31
            assert over["total_break_minutes"] == 61
            assert over["over_break"] is True
            assert self._rec()["on_break"] is False
            assert self._rec()["over_break_notified"] is True
            assert len(self.pushes) == 1
            push = self.pushes[0]
            assert sorted(push["users"]) == ["sub_mgr", "sub_site"]
            payload = push["payload"]
            assert payload["employee_name"] == "Asha Rao"
            assert payload["branch"] == "Bengaluru HQ"
            assert payload["minutes"] == 61
            assert payload["url"] == "/admin#live"
            assert "Asha Rao" in payload["body"] and "Bengaluru HQ" in payload["body"] and "61" in payload["body"]

            await server.break_start(_proof(), self.user)
            assert self._rec()["on_break"] is True
            assert len(self._rec()["breaks"]) == 3
            with pytest.raises(HTTPException) as blocked:
                await server.check_out(server.CheckRequest(lat=1, lng=2, image_b64=SELFIE), self.user)
            assert blocked.value.status_code == 400
            assert self._rec()["on_break"] is True

            self._backdate_open(5)
            again = await server.break_end(_proof(), self.user)
            assert again["over_break"] is True
            assert again["total_break_minutes"] == 66
            assert self._rec()["on_break"] is False
            assert len(self.pushes) == 1

            done = await server.check_out(server.CheckRequest(lat=1, lng=2, image_b64=SELFIE), self.user)
            assert done["over_break"] is True
            assert done["net_work_minutes"] == done["duration_minutes"] - 66
            assert self._rec()["check_out"]
            assert len(self.pushes) == 1

        asyncio.run(run())

    def test_exactly_at_the_cap_does_not_push(self, monkeypatch):
        self._install(monkeypatch)

        async def run():
            await server.break_start(_proof(), self.user)
            self._backdate_open(60)
            ended = await server.break_end(_proof(), self.user)
            assert ended["total_break_minutes"] == 60
            assert ended["over_break"] is False
            assert self.pushes == []
            assert "over_break_notified" not in self._rec()

        asyncio.run(run())

    def test_auto_close_pushes_when_the_open_break_crosses_without_an_end_selfie(self, monkeypatch):
        self._install(monkeypatch)
        close_at = FROZEN
        self.db.attendance.docs = [{
            "record_id": "att_auto",
            "user_id": "emp",
            "check_in": _iso(300),
            "check_out": None,
            "on_break": True,
            "total_break_minutes": 0,
            "breaks": [{
                "break_id": "brk_open",
                "start": _iso(70),
                "end": None,
                "duration_minutes": None,
                "start_photo_path": "gtg-attendance/break_start/emp/start.jpg",
                "start_lat": 12.97,
                "start_lng": 77.59,
            }],
        }]

        async def run():
            await server.close_session(self._rec(), self.user, close_at, "missed checkout", notify=True)
            rec = self._rec()
            brk = rec["breaks"][0]
            assert rec["on_break"] is False and rec["auto_closed"] is True
            assert rec["over_break"] is True and rec["over_break_notified"] is True
            assert brk["end"] == close_at.isoformat()
            assert brk["duration_minutes"] == 70
            assert brk.get("end_photo_path") in (None, "")
            assert brk.get("closed_without_selfie") is True
            assert brk["start_photo_path"].endswith("start.jpg")
            assert rec["net_work_minutes"] == rec["duration_minutes"] - 70
            assert len(self.pushes) == 1
            assert self.pushes[0]["payload"]["minutes"] == 70
            assert sorted(self.pushes[0]["users"]) == ["sub_mgr", "sub_site"]

        asyncio.run(run())

    def test_auto_close_under_the_cap_and_a_second_crossing_do_not_push(self, monkeypatch):
        self._install(monkeypatch)

        async def run():
            self.db.attendance.docs = [{
                "record_id": "att_short",
                "user_id": "emp",
                "check_in": _iso(120),
                "on_break": True,
                "total_break_minutes": 0,
                "breaks": [{"break_id": "b", "start": _iso(20), "end": None, "start_photo_path": "start.jpg"}],
            }]
            await server.close_session(self._rec(), self.user, FROZEN, "missed checkout", notify=True)
            assert self._rec()["over_break"] is False
            assert self._rec()["breaks"][0]["duration_minutes"] == 20
            assert not self._rec()["breaks"][0].get("end_photo_path")
            assert self.pushes == []

            self.db.attendance.docs = [{
                "record_id": "att_again",
                "user_id": "emp",
                "check_in": _iso(200),
                "on_break": True,
                "total_break_minutes": 70,
                "over_break": True,
                "over_break_notified": True,
                "breaks": [
                    {"break_id": "done", "start": _iso(100), "end": _iso(30), "duration_minutes": 70,
                     "end_photo_path": "resume.jpg"},
                    {"break_id": "open", "start": _iso(15), "end": None, "start_photo_path": "start-2.jpg"},
                ],
            }]
            await server.close_session(self._rec(), self.user, FROZEN, "missed checkout", notify=True)
            rec = self._rec()
            assert rec["total_break_minutes"] == 85
            assert rec["over_break"] is True and rec["on_break"] is False
            assert rec["breaks"][0]["end_photo_path"] == "resume.jpg"
            assert not rec["breaks"][0].get("closed_without_selfie")
            assert rec["breaks"][1]["duration_minutes"] == 15
            assert rec["breaks"][1].get("closed_without_selfie") is True
            assert not rec["breaks"][1].get("end_photo_path")
            assert self.pushes == []

        asyncio.run(run())
