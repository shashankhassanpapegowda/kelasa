"""Calendar-month selfie retention (Asia/Kolkata) and photo access permissions.

Cutoff cases are pure. Purge and file-access cases drive the real handlers
with an in-memory stand-in for Mongo, so they do not need a running database.
"""
import asyncio
import inspect
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test_database")
os.environ.setdefault("WEBHOOK_CRON_SECRET", "test-secret")
os.environ.setdefault("VAPID_PUBLIC_KEY", "test-public")
os.environ.setdefault("VAPID_PRIVATE_KEY", "test-private")
os.environ.setdefault("VAPID_SUBJECT", "mailto:test@example.com")

import pytest
from fastapi import HTTPException
from starlette.requests import Request

import selfie_retention
import server

IST = ZoneInfo("Asia/Kolkata")
APP = server.APP_NAME


def ist(y, m, d, hh=0, mm=0, ss=0):
    return datetime(y, m, d, hh, mm, ss, tzinfo=IST)


def utc_iso(dt):
    return dt.astimezone(timezone.utc).isoformat()


def _match(doc, query):
    if not query:
        return True
    for key, expected in query.items():
        if key == "$or":
            if not any(_match(doc, clause) for clause in expected):
                return False
            continue
        if key == "$and":
            if not all(_match(doc, clause) for clause in expected):
                return False
            continue
        value = doc.get(key)
        if isinstance(expected, dict):
            if "$elemMatch" in expected:
                items = value if isinstance(value, list) else []
                if not any(_match(item, expected["$elemMatch"]) for item in items if isinstance(item, dict)):
                    return False
                expected = {k: v for k, v in expected.items() if k != "$elemMatch"}
                if not expected:
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
        self.updates = []

    async def find_one(self, query, projection=None):
        for doc in self.docs:
            if _match(doc, query):
                return dict(doc)
        return None

    def find(self, query, projection=None):
        return _Cursor([d for d in self.docs if _match(d, query)])

    async def update_one(self, query, update):
        self.updates.append((query, update))
        for doc in self.docs:
            if _match(doc, query):
                doc.update(update.get("$set") or {})
                return


class _DB:
    def __init__(self):
        self.attendance = _Collection()
        self.users = _Collection()
        self.user_sessions = _Collection()


def _request(token=None):
    headers = []
    if token:
        headers.append((b"authorization", f"Bearer {token}".encode()))
    scope = {
        "type": "http", "http_version": "1.1", "method": "GET", "scheme": "http",
        "path": "/api/files/x", "raw_path": b"/api/files/x", "query_string": b"",
        "headers": headers, "client": ("127.0.0.1", 1234), "server": ("test", 80),
    }
    return Request(scope)


def _photo(user_id, kind="checkin"):
    return f"{APP}/{kind}/{user_id}/abc.jpg"


# ---------- cutoff: month boundaries and IST ----------
class TestCutoff:
    def test_examples_from_the_rule(self):
        # 15 Dec keeps 1 Nov onward. 1 Jan keeps 1 Dec onward.
        assert selfie_retention.selfie_retention_cutoff(ist(2026, 12, 15, 15), 1) == ist(2026, 11, 1)
        assert selfie_retention.selfie_retention_cutoff(ist(2027, 1, 1), 1) == ist(2026, 12, 1)

    def test_window_slides_at_midnight_ist_not_utc(self):
        # 30 Nov 23:59 IST is still November, so the previous month is October.
        # 00:00 IST on 1 Dec is the first instant of December (18:30 UTC on 30 Nov).
        assert selfie_retention.selfie_retention_cutoff(ist(2026, 11, 30, 23, 59), 1) == ist(2026, 10, 1)
        assert selfie_retention.selfie_retention_cutoff(ist(2026, 12, 1, 0, 0), 1) == ist(2026, 11, 1)
        assert selfie_retention.selfie_retention_cutoff(datetime(2026, 11, 30, 18, 29, tzinfo=timezone.utc), 1) == ist(2026, 10, 1)
        assert selfie_retention.selfie_retention_cutoff(datetime(2026, 11, 30, 18, 30, tzinfo=timezone.utc), 1) == ist(2026, 11, 1)

    def test_cutoff_is_ist_midnight_as_utc(self):
        cutoff = selfie_retention.selfie_retention_cutoff(ist(2026, 12, 15, 12), 1)
        assert cutoff == datetime(2026, 10, 31, 18, 30, tzinfo=timezone.utc)
        assert cutoff.tzinfo == timezone.utc
        jan = selfie_retention.selfie_retention_cutoff(ist(2027, 1, 1, 0, 30), 1)
        assert jan == datetime(2026, 11, 30, 18, 30, tzinfo=timezone.utc)

    def test_same_cutoff_throughout_the_month(self):
        first = selfie_retention.selfie_retention_cutoff(ist(2026, 12, 1), 1)
        last = selfie_retention.selfie_retention_cutoff(ist(2026, 12, 31, 23, 59), 1)
        assert first == last == ist(2026, 11, 1)

    def test_year_wrap_and_leap_february(self):
        assert selfie_retention.selfie_retention_cutoff(ist(2027, 1, 31, 23), 1) == ist(2026, 12, 1)
        assert selfie_retention.selfie_retention_cutoff(ist(2024, 3, 1), 1) == ist(2024, 2, 1)
        assert selfie_retention.selfie_retention_cutoff(ist(2026, 3, 1), 1) == ist(2026, 2, 1)

    def test_retention_months_setting(self, monkeypatch):
        now = ist(2026, 12, 15, 9)
        assert selfie_retention.selfie_retention_cutoff(now, 0) == ist(2026, 12, 1)
        assert selfie_retention.selfie_retention_cutoff(now, 2) == ist(2026, 10, 1)
        assert selfie_retention.selfie_retention_cutoff(ist(2026, 6, 15), 13) == ist(2025, 5, 1)
        assert selfie_retention.selfie_retention_cutoff(now, -4) == ist(2026, 11, 1)

        monkeypatch.delenv("SELFIE_RETENTION_MONTHS", raising=False)
        assert selfie_retention.selfie_retention_months() == 1
        for raw in ("", "nope", "1.5", "-1", "-3"):
            monkeypatch.setenv("SELFIE_RETENTION_MONTHS", raw)
            assert selfie_retention.selfie_retention_months() == 1
        monkeypatch.setenv("SELFIE_RETENTION_MONTHS", "0")
        assert selfie_retention.selfie_retention_months() == 0
        monkeypatch.setenv("SELFIE_RETENTION_MONTHS", " 2 ")
        assert selfie_retention.selfie_retention_months() == 2
        assert selfie_retention.selfie_retention_cutoff(now) == ist(2026, 10, 1)

    def test_taken_before_respects_the_instant(self):
        cutoff = selfie_retention.selfie_retention_cutoff(ist(2026, 12, 15), 1)
        keep = utc_iso(ist(2026, 11, 1))
        drop = utc_iso(ist(2026, 10, 31, 23, 59, 59))
        assert selfie_retention.photo_taken_before(keep, cutoff) is False
        assert selfie_retention.photo_taken_before(drop, cutoff) is True
        # Same instant written with an IST offset is kept.
        assert selfie_retention.photo_taken_before("2026-11-01T00:00:00+05:30", cutoff) is False
        assert selfie_retention.photo_taken_before("2026-10-31T23:59:00+05:30", cutoff) is True
        # Naive timestamps are UTC, matching the rest of the API.
        assert selfie_retention.photo_taken_before("2026-10-31T18:30:00", cutoff) is False
        assert selfie_retention.photo_taken_before("2026-10-31T18:29:59", cutoff) is True
        assert selfie_retention.photo_taken_before(None, cutoff) is False
        assert selfie_retention.photo_taken_before("", cutoff) is False
        assert selfie_retention.photo_taken_before("not-a-timestamp", cutoff) is False

    def test_mongo_string_compare_matches_the_guard(self):
        cutoff = selfie_retention.selfie_retention_cutoff(ist(2026, 12, 15, 12), 1)
        cutoff_iso = cutoff.isoformat()
        samples = [
            ist(2026, 10, 31, 23, 59, 59),
            ist(2026, 11, 1),
            ist(2026, 11, 1, 0, 0, 1),
            ist(2026, 11, 20, 9),
            ist(2026, 12, 1),
            ist(2027, 1, 1),
        ]
        for taken in samples:
            taken_iso = utc_iso(taken)
            assert (taken_iso < cutoff_iso) is selfie_retention.photo_taken_before(taken_iso, cutoff)


def _record(record_id, check_in, check_out=None, in_path="in", out_path="out"):
    return {
        "record_id": record_id,
        "user_id": "emp_a",
        "check_in": utc_iso(check_in) if check_in else None,
        "check_out": utc_iso(check_out) if check_out else None,
        "check_in_photo_path": in_path,
        "check_out_photo_path": out_path,
        "face_photo_path": f"{APP}/enrollment/emp_a/face.jpg",
    }


async def _purge(monkeypatch, docs, *, now, months="1"):
    db = _DB()
    db.attendance.docs = docs
    db.users.docs = [{
        "user_id": "emp_a", "role": "employee",
        "face_photo_path": f"{APP}/enrollment/emp_a/face.jpg",
        "avatar_path": f"{APP}/avatars/emp_a/ava.jpg",
    }]
    scrubbed = []
    monkeypatch.setattr(server, "db", db)
    monkeypatch.setattr(server, "scrub_object", lambda path: scrubbed.append(path))
    monkeypatch.setattr(selfie_retention, "_utcnow", lambda: now)
    monkeypatch.setenv("SELFIE_RETENTION_MONTHS", months)
    cleared = await server.run_selfie_purge()
    return cleared, db, scrubbed


class TestPurge:
    def test_startup_schedules_the_calendar_purge(self):
        startup = inspect.getsource(server.startup)
        purge = inspect.getsource(server.run_selfie_purge)
        assert "run_selfie_purge()" in startup
        assert "selfie_retention_cutoff" in purge
        assert "photo_taken_before" in purge
        assert "SELFIE_KEEP_DAYS" not in purge
        assert "timedelta" not in purge
        assert "face_photo_path" not in purge
        assert "avatar_path" not in purge

    def test_calendar_sessions_carry_photo_fields(self):
        for key in ("check_in_photo_path", "check_out_photo_path", "photos_purged_at"):
            assert key in server.SESSION_KEYS
        assert "SESSION_KEYS" in inspect.getsource(server.build_calendar)

    def test_keeps_previous_month_and_deletes_before_it(self, monkeypatch):
        now = ist(2026, 12, 15, 15)
        docs = [
            _record("keep-boundary", ist(2026, 11, 1), ist(2026, 11, 1, 9), "keep-in", "keep-out"),
            _record("drop-boundary", ist(2026, 10, 31, 23, 59, 59), ist(2026, 10, 31, 23, 59, 59), "old-in", "old-out"),
            # Older than 7 days, but still inside November: the new rule must keep it.
            _record("keep-week-plus", ist(2026, 11, 20, 9), ist(2026, 11, 20, 18), "nov-in", "nov-out"),
            _record("keep-today", ist(2026, 12, 15, 9), ist(2026, 12, 15, 18), "today-in", "today-out"),
            # Check-in before the window, check-out inside it. Only the check-in selfie goes.
            _record("split", ist(2026, 10, 31, 22), ist(2026, 11, 1, 6), "split-in", "split-out"),
            _record("no-photos", ist(2026, 8, 1), ist(2026, 8, 1, 9), None, None),
        ]
        cleared, db, scrubbed = asyncio.run(_purge(monkeypatch, docs, now=now))

        by_id = {d["record_id"]: d for d in db.attendance.docs}
        assert cleared == 2
        assert set(scrubbed) == {"old-in", "old-out", "split-in"}
        assert f"{APP}/enrollment/emp_a/face.jpg" not in scrubbed
        assert f"{APP}/avatars/emp_a/ava.jpg" not in scrubbed
        assert db.users.updates == []
        assert db.users.docs[0]["face_photo_path"].endswith("face.jpg")
        assert db.users.docs[0]["avatar_path"].endswith("ava.jpg")

        for rid in ("keep-boundary", "keep-week-plus", "keep-today"):
            assert by_id[rid]["check_in_photo_path"]
            assert by_id[rid]["check_out_photo_path"]
            assert "photos_purged_at" not in by_id[rid]

        dropped = by_id["drop-boundary"]
        assert dropped["check_in_photo_path"] is None
        assert dropped["check_out_photo_path"] is None
        assert dropped["photos_purged_at"]
        # The extra field on the attendance row is not an enrolment photo and is not scrubbed.
        assert dropped["face_photo_path"].endswith("face.jpg")

        split = by_id["split"]
        assert split["check_in_photo_path"] is None
        assert split["check_out_photo_path"] == "split-out"
        assert split["photos_purged_at"]

        untouched = by_id["no-photos"]
        assert untouched["check_in_photo_path"] is None
        assert "photos_purged_at" not in untouched

    def test_new_year_boundary(self, monkeypatch):
        now = ist(2027, 1, 1)
        docs = [
            _record("keep-dec", ist(2026, 12, 1), ist(2026, 12, 1, 18), "dec-in", "dec-out"),
            _record("drop-nov", ist(2026, 11, 30, 23, 59), ist(2026, 11, 30, 23, 59), "nov-in", "nov-out"),
        ]
        cleared, db, scrubbed = asyncio.run(_purge(monkeypatch, docs, now=now))
        by_id = {d["record_id"]: d for d in db.attendance.docs}
        assert cleared == 1
        assert set(scrubbed) == {"nov-in", "nov-out"}
        assert by_id["keep-dec"]["check_in_photo_path"] == "dec-in"
        assert "photos_purged_at" not in by_id["keep-dec"]
        assert by_id["drop-nov"]["check_in_photo_path"] is None
        assert by_id["drop-nov"]["photos_purged_at"]

    def test_env_months_changes_the_window(self, monkeypatch):
        now = ist(2026, 12, 15, 12)
        docs = [
            _record("october", ist(2026, 10, 1), ist(2026, 10, 1, 9), "oct-in", "oct-out"),
            _record("september", ist(2026, 9, 30, 23), ist(2026, 9, 30, 23), "sep-in", "sep-out"),
        ]
        cleared, db, scrubbed = asyncio.run(_purge(monkeypatch, docs, now=now, months="2"))
        by_id = {d["record_id"]: d for d in db.attendance.docs}
        assert cleared == 1
        assert scrubbed == ["sep-in", "sep-out"]
        assert by_id["october"]["check_in_photo_path"] == "oct-in"
        assert by_id["september"]["photos_purged_at"]

    def test_guard_vetoes_a_delete(self, monkeypatch):
        now = ist(2026, 12, 15, 12)
        docs = [_record("looks-old", ist(2026, 1, 1), ist(2026, 1, 1, 9), "keep-me", "keep-me-out")]
        monkeypatch.setattr(selfie_retention, "photo_taken_before", lambda *_a, **_k: False)
        cleared, db, scrubbed = asyncio.run(_purge(monkeypatch, docs, now=now))
        assert cleared == 0
        assert scrubbed == []
        assert db.attendance.docs[0]["check_in_photo_path"] == "keep-me"
        assert db.attendance.updates == []

    def test_break_photos_are_judged_on_their_own_timestamp(self, monkeypatch):
        now = ist(2026, 12, 15, 15)

        def brk(start, end, start_path, end_path):
            return {
                "break_id": "b1",
                "start": utc_iso(start) if start else "2020-not-a-date",
                "end": utc_iso(end) if end else None,
                "start_photo_path": start_path,
                "end_photo_path": end_path,
            }

        docs = [
            {**_record("split-break", ist(2026, 11, 20, 9), ist(2026, 11, 20, 18), "punch-in", "punch-out"),
             "breaks": [brk(ist(2026, 10, 31, 23), ist(2026, 11, 20, 12), "old-start", "new-end")]},
            {**_record("old-breaks", ist(2026, 12, 2, 9), ist(2026, 12, 2, 18), "dec-in", "dec-out"),
             "breaks": [brk(ist(2026, 10, 1, 10), ist(2026, 10, 1, 11), "old-b-start", "old-b-end")]},
            {**_record("old-punch-new-break", ist(2026, 10, 15, 9), ist(2026, 10, 15, 18), "old-punch-in", "old-punch-out"),
             "breaks": [brk(ist(2026, 11, 2, 10), ist(2026, 11, 2, 10, 30), "keep-b-start", "keep-b-end")]},
            {**_record("auto", ist(2026, 9, 1, 9), ist(2026, 9, 1, 18), None, None),
             "auto_closed": True,
             "breaks": [brk(ist(2026, 9, 1, 12), ist(2026, 9, 1, 13), "auto-start", None)]},
            {**_record("fresh-break", ist(2026, 12, 10, 9), ist(2026, 12, 10, 18), None, None),
             "breaks": [brk(ist(2026, 12, 10, 13), ist(2026, 12, 10, 13, 20), "fresh-start", "fresh-end")]},
            {**_record("bad-stamp", ist(2026, 12, 10, 9), ist(2026, 12, 10, 12), "keep-in", "keep-out"),
             "breaks": [{"start": "2020-not-a-date", "start_photo_path": "weird", "end": None, "end_photo_path": None}]},
        ]
        cleared, db, scrubbed = asyncio.run(_purge(monkeypatch, docs, now=now))
        by_id = {d["record_id"]: d for d in db.attendance.docs}

        assert cleared == 4
        assert set(scrubbed) == {
            "old-start", "old-b-start", "old-b-end", "old-punch-in", "old-punch-out", "auto-start",
        }
        assert f"{APP}/enrollment/emp_a/face.jpg" not in scrubbed
        assert f"{APP}/avatars/emp_a/ava.jpg" not in scrubbed
        assert db.users.docs[0]["face_photo_path"].endswith("face.jpg")
        assert db.users.docs[0]["avatar_path"].endswith("ava.jpg")

        split = by_id["split-break"]["breaks"][0]
        assert split["start_photo_path"] is None and split["start_photo_purged"] is True
        assert split["end_photo_path"] == "new-end" and not split.get("end_photo_purged")
        assert by_id["split-break"]["check_in_photo_path"] == "punch-in"
        assert by_id["split-break"]["check_out_photo_path"] == "punch-out"
        assert by_id["split-break"]["photos_purged_at"]

        old = by_id["old-breaks"]
        assert old["check_in_photo_path"] == "dec-in" and old["check_out_photo_path"] == "dec-out"
        assert old["breaks"][0]["start_photo_path"] is None and old["breaks"][0]["end_photo_path"] is None
        assert old["breaks"][0]["start_photo_purged"] is True and old["breaks"][0]["end_photo_purged"] is True

        kept_break = by_id["old-punch-new-break"]
        assert kept_break["check_in_photo_path"] is None and kept_break["check_out_photo_path"] is None
        assert kept_break["breaks"][0]["start_photo_path"] == "keep-b-start"
        assert kept_break["breaks"][0]["end_photo_path"] == "keep-b-end"
        assert not kept_break["breaks"][0].get("start_photo_purged")

        auto = by_id["auto"]["breaks"][0]
        assert auto["start_photo_path"] is None and auto["start_photo_purged"] is True
        assert auto["end_photo_path"] is None and not auto.get("end_photo_purged")

        assert by_id["fresh-break"]["breaks"][0]["start_photo_path"] == "fresh-start"
        assert by_id["fresh-break"]["breaks"][0]["end_photo_path"] == "fresh-end"
        assert "photos_purged_at" not in by_id["fresh-break"]
        assert by_id["bad-stamp"]["breaks"][0]["start_photo_path"] == "weird"
        assert "photos_purged_at" not in by_id["bad-stamp"]

    def test_day_payload_keeps_break_photo_paths_and_purged_markers(self):
        purge = inspect.getsource(server.run_selfie_purge)
        assert "breaks" in server.SESSION_KEYS
        assert "start_photo_path" in purge and "end_photo_path" in purge
        assert "_photo_purged" in purge
        assert "SESSION_KEYS" in inspect.getsource(server.build_calendar)
        rec = {
            "breaks": [{
                "start_photo_path": "break-start.jpg",
                "end_photo_path": None,
                "end_photo_purged": True,
            }],
            "photos_purged_at": "2026-12-15T00:00:00+00:00",
            "check_in_photo_path": "in.jpg",
        }
        session = {k: rec.get(k) for k in server.SESSION_KEYS}
        assert session["breaks"][0]["start_photo_path"] == "break-start.jpg"
        assert session["breaks"][0]["end_photo_purged"] is True
        assert session["photos_purged_at"]
        assert session["check_in_photo_path"] == "in.jpg"


# ---------- who can fetch a selfie ----------
def _seed_people():
    db = _DB()
    db.users.docs = [
        {"user_id": "emp_a", "role": "employee", "department": "Field Operations", "site": "Bengaluru HQ", "manager_id": "sub_mgr"},
        {"user_id": "emp_b", "role": "employee", "department": "Sales", "site": "Other Yard"},
        {"user_id": "admin", "role": "admin"},
        {"user_id": "sub_in", "role": "sub_admin", "managed_departments": ["Field Operations"], "managed_sites": []},
        {"user_id": "sub_out", "role": "sub_admin", "managed_departments": ["Administration"], "managed_sites": ["Tumkur Yard"]},
        {"user_id": "sub_mgr", "role": "sub_admin", "managed_departments": [], "managed_sites": []},
    ]
    db.user_sessions.docs = [
        {"user_id": uid, "session_token": f"tok_{uid}"}
        for uid in ("emp_a", "emp_b", "admin", "sub_in", "sub_out", "sub_mgr")
    ]
    return db


async def _fetch(path, token):
    return await server.download_file(path, _request(token), None)


class TestPhotoAccess:
    def test_permissions(self, monkeypatch):
        db = _seed_people()
        fetched = []

        def get_object(path):
            fetched.append(path)
            return b"\xff\xd8\xff-selfie", "image/jpeg"

        monkeypatch.setattr(server, "db", db)
        monkeypatch.setattr(server, "get_object", get_object)

        async def run():
            checkin = _photo("emp_a", "checkin")
            checkout = _photo("emp_a", "checkout")
            enrolled = _photo("emp_a", "enrollment")
            avatar = _photo("emp_a", "avatars")

            with pytest.raises(HTTPException) as anon:
                await _fetch(checkin, None)
            assert anon.value.status_code == 401
            assert fetched == []

            own_in = await _fetch(checkin, "tok_emp_a")
            own_out = await _fetch(checkout, "tok_emp_a")
            assert own_in.status_code == 200 and own_in.body == b"\xff\xd8\xff-selfie"
            assert own_out.status_code == 200
            assert own_in.media_type == "image/jpeg"
            assert fetched == [checkin, checkout]

            break_start = _photo("emp_a", "break_start")
            break_end = _photo("emp_a", "break_end")
            assert (await _fetch(break_start, "tok_emp_a")).status_code == 200
            assert (await _fetch(break_end, "tok_sub_in")).status_code == 200
            assert (await _fetch(break_start, "tok_sub_mgr")).status_code == 200
            with pytest.raises(HTTPException) as other_break:
                await _fetch(break_end, "tok_emp_b")
            assert other_break.value.status_code == 403
            with pytest.raises(HTTPException) as outside_break:
                await _fetch(break_start, "tok_sub_out")
            assert outside_break.value.status_code == 403

            with pytest.raises(HTTPException) as other:
                await _fetch(checkin, "tok_emp_b")
            assert other.value.status_code == 403
            with pytest.raises(HTTPException) as other_out:
                await _fetch(checkout, "tok_emp_b")
            assert other_out.value.status_code == 403

            admin_resp = await _fetch(checkin, "tok_admin")
            assert admin_resp.status_code == 200
            assert (await _fetch(checkout, "tok_admin")).status_code == 200
            assert (await _fetch(_photo("emp_b", "checkin"), "tok_admin")).status_code == 200

            # Sub-admin keeps today's scope: in-team selfies and enrolment photos, not the rest.
            assert (await _fetch(checkin, "tok_sub_in")).status_code == 200
            assert (await _fetch(enrolled, "tok_sub_in")).status_code == 200
            assert (await _fetch(checkin, "tok_sub_mgr")).status_code == 200
            with pytest.raises(HTTPException) as outside:
                await _fetch(checkin, "tok_sub_out")
            assert outside.value.status_code == 403
            with pytest.raises(HTTPException) as outside_face:
                await _fetch(enrolled, "tok_sub_out")
            assert outside_face.value.status_code == 403
            with pytest.raises(HTTPException) as sales:
                await _fetch(_photo("emp_b", "checkout"), "tok_sub_in")
            assert sales.value.status_code == 403

            # Avatars stay readable by any signed-in user, including someone outside the team.
            assert (await _fetch(avatar, "tok_emp_b")).status_code == 200
            assert (await _fetch(avatar, "tok_sub_out")).status_code == 200

            with pytest.raises(HTTPException) as other_face:
                await _fetch(enrolled, "tok_emp_b")
            assert other_face.value.status_code == 403

            with pytest.raises(HTTPException) as missing:
                await _fetch("other-app/checkin/emp_a/abc.jpg", "tok_admin")
            assert missing.value.status_code == 404
            assert all(path.startswith(f"{APP}/") for path in fetched)

        asyncio.run(run())

    def test_employee_calendar_is_scoped_to_the_signed_in_user(self):
        src = inspect.getsource(server.build_calendar)
        assert 'uid = u["user_id"]' in src
        assert '{"user_id": uid' in src
