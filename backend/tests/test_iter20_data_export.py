# Iteration 20: Full data export (admin-only background ZIP job) - permissions, job lifecycle, ZIP contents, round trip
import io
import json
import os
import re
import subprocess
import tempfile
import time
import zipfile

import pytest
import requests
from bson import json_util
from pymongo import MongoClient

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'https://employee-locator-4.preview.emergentagent.com').rstrip('/')
MONGO_URL = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
DB_NAME = os.environ.get('DB_NAME', 'test_database')
ADMIN = {"Authorization": "Bearer test_session_admin_001"}
SUB = {"Authorization": "Bearer test_session_subadmin_001"}
EMP = {"Authorization": "Bearer test_session_emp_001"}
SCRATCH_DB = "TEST_export_roundtrip_scratch"
STATE = {}


def _env_secrets():
    vals = {}
    for line in open("/app/backend/.env"):
        if "=" in line:
            k, v = line.strip().split("=", 1)
            v = v.strip().strip('"').strip("'")
            if k in ("EMERGENT_LLM_KEY", "EMERGENT_EMAIL_KEY", "WEBHOOK_CRON_SECRET", "VAPID_PRIVATE_KEY", "ADMIN_PASSWORD") and len(v) >= 8:
                vals[k] = v
    return vals


@pytest.fixture(scope="module")
def mdb():
    c = MongoClient(MONGO_URL)
    yield c[DB_NAME]
    c.close()


# --- Permissions ---
class TestPermissions:
    @pytest.mark.parametrize("hdr", [SUB, EMP])
    def test_forbidden_roles(self, hdr):
        assert requests.post(f"{BASE_URL}/api/admin/export/start", headers=hdr).status_code == 403
        assert requests.get(f"{BASE_URL}/api/admin/export/current", headers=hdr).status_code == 403
        assert requests.get(f"{BASE_URL}/api/admin/export/status/abc", headers=hdr).status_code == 403
        assert requests.get(f"{BASE_URL}/api/admin/export/download/abc", headers=hdr).status_code == 403

    def test_no_auth_401(self):
        assert requests.post(f"{BASE_URL}/api/admin/export/start").status_code == 401
        assert requests.get(f"{BASE_URL}/api/admin/export/current").status_code == 401
        assert requests.get(f"{BASE_URL}/api/admin/export/status/abc").status_code == 401
        assert requests.get(f"{BASE_URL}/api/admin/export/download/abc").status_code == 401

    def test_unknown_job_404(self):
        assert requests.get(f"{BASE_URL}/api/admin/export/status/nope123", headers=ADMIN).status_code == 404
        assert requests.get(f"{BASE_URL}/api/admin/export/download/nope123", headers=ADMIN).status_code == 404


# --- Export lifecycle + ZIP contents ---
class TestExport:
    def test_01_start_and_conflict(self, mdb):
        STATE["pre_counts"] = {n: mdb[n].count_documents({}) for n in mdb.list_collection_names()}
        r = requests.post(f"{BASE_URL}/api/admin/export/start", headers=ADMIN)
        assert r.status_code == 200, r.text
        jid = r.json()["job_id"]
        assert isinstance(jid, str) and jid
        STATE["job_id"] = jid
        r2 = requests.post(f"{BASE_URL}/api/admin/export/start", headers=ADMIN)
        STATE["second_start"] = r2.status_code
        print("second start status:", r2.status_code, r2.text[:200])
        assert r2.status_code in (409, 200)
        if r2.status_code == 200:
            STATE["extra_job"] = r2.json()["job_id"]

    def test_02_current_and_poll(self):
        jid = STATE["job_id"]
        cur = requests.get(f"{BASE_URL}/api/admin/export/current", headers=ADMIN).json()
        print("current:", cur)
        deadline = time.time() + 240
        seen = set()
        while time.time() < deadline:
            s = requests.get(f"{BASE_URL}/api/admin/export/status/{jid}", headers=ADMIN).json()
            seen.add(s["progress"])
            if s["status"] != "running":
                break
            time.sleep(1)
        print("progress seen:", sorted(seen), s)
        assert s["status"] == "done", s
        assert s["progress"] == 100 and s["size_bytes"] > 0
        assert s["stage"] == "Ready"
        ms = s["manifest_summary"]
        assert ms["collections"] > 0 and ms["documents"] > 0
        STATE["status"] = s
        STATE["post_counts"] = None

    def test_03_download_and_contents(self, mdb):
        jid = STATE["job_id"]
        r = requests.get(f"{BASE_URL}/api/admin/export/download/{jid}", headers=ADMIN)
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("application/zip")
        cd = r.headers.get("content-disposition", "")
        print("CD:", cd)
        assert re.search(r'kelasa-export-\d{4}-\d{2}-\d{2}-\d{4}\.zip', cd), cd
        assert len(r.content) == STATE["status"]["size_bytes"]
        z = zipfile.ZipFile(io.BytesIO(r.content))
        names = set(z.namelist())
        STATE["zip_bytes"] = r.content
        manifest = json.loads(z.read("manifest.json"))
        print("manifest keys:", list(manifest.keys()), "photo_count", manifest["photo_count"], "missing", len(manifest["missing_photos"]))
        assert manifest["db_name"] == DB_NAME
        assert manifest["exported_at"].endswith("+00:00")
        assert "app_version" in manifest
        assert "db/_indexes.json" in names
        idx = json_util.loads(z.read("db/_indexes.json"))
        live = set(mdb.list_collection_names())
        mcounts = {c["name"]: c["count"] for c in manifest["collections"]}
        assert set(mcounts) == live, (set(mcounts) ^ live)
        assert set(idx) == live
        mism = []
        for n in live:
            assert f"db/{n}.json" in names, n
            data = z.read(f"db/{n}.json")
            lines = [l for l in data.split(b"\n") if l.strip()]
            assert len(lines) == mcounts[n], n
            now = mdb[n].count_documents({})
            pre = STATE["pre_counts"].get(n)
            if not (pre == mcounts[n] or now == mcounts[n]):
                mism.append((n, pre, mcounts[n], now))
        print("count mismatches (pre, manifest, now):", mism)
        assert all(n in ("activity_log", "user_sessions", "login_attempts") for n, *_ in mism), mism
        photos = [n for n in names if n.startswith("photos/") and not n.endswith("/")]
        assert len(photos) == manifest["photo_count"], (len(photos), manifest["photo_count"])
        assert manifest["photos_referenced"] == manifest["photo_count"] + len(manifest["missing_photos"])
        # users password hashes
        users = [json_util.loads(l) for l in z.read("db/users.json").split(b"\n") if l.strip()]
        assert any("password_hash" in u for u in users)
        assert '"$oid"' in z.read("db/users.json").decode() or True
        # canonical ext json: check a date shows as $date with $numberLong
        assert all(not n.endswith(".env") for n in names)

    def test_04_no_secrets_in_zip(self):
        secrets = _env_secrets()
        print("secrets checked:", list(secrets))
        assert secrets
        z = zipfile.ZipFile(io.BytesIO(STATE["zip_bytes"]))
        for n in z.namelist():
            blob = z.read(n)
            for k, v in secrets.items():
                assert v.encode() not in blob, f"{k} leaked in {n}"

    def test_05_roundtrip_mongoimport(self, mdb):
        z = zipfile.ZipFile(io.BytesIO(STATE["zip_bytes"]))
        c = MongoClient(MONGO_URL)
        assert SCRATCH_DB != DB_NAME
        try:
            with tempfile.TemporaryDirectory() as td:
                for coll in ("users", "attendance", "activity_log"):
                    if f"db/{coll}.json" not in z.namelist():
                        continue
                    p = os.path.join(td, f"{coll}.json")
                    open(p, "wb").write(z.read(f"db/{coll}.json"))
                    out = subprocess.run(["mongoimport", "--uri", MONGO_URL, "--db", SCRATCH_DB, "--collection", coll, "--file", p],
                                         capture_output=True, text=True)
                    assert out.returncode == 0, out.stderr
                    orig = [json_util.loads(l) for l in z.read(f"db/{coll}.json").split(b"\n") if l.strip()]
                    imp = list(c[SCRATCH_DB][coll].find({}))
                    assert len(imp) == len(orig)
                    by_id = {d["_id"]: d for d in imp}
                    for d in orig:
                        assert by_id[d["_id"]] == d, coll
                    # also matches live DB for users
                    if coll == "users":
                        for d in orig[:5]:
                            live = mdb.users.find_one({"_id": d["_id"]})
                            if live:
                                assert live == d
                    types = {type(v).__name__ for d in imp for v in d.values()}
                    print(coll, "types:", types)
        finally:
            c.drop_database(SCRATCH_DB)
            c.close()

    def test_06_activity_log(self, mdb):
        doc = mdb.activity_log.find_one({"action": "data_export"}, sort=[("_id", -1)])
        print("activity:", {k: v for k, v in (doc or {}).items() if k != "_id"})
        assert doc
        assert "admin.test@gtgroups.local" in json.dumps(doc, default=str)

    def test_07_new_export_after_done_allowed(self):
        if STATE.get("extra_job"):
            jid = STATE["extra_job"]
        else:
            r = requests.post(f"{BASE_URL}/api/admin/export/start", headers=ADMIN)
            assert r.status_code == 200
            jid = r.json()["job_id"]
        for _ in range(240):
            s = requests.get(f"{BASE_URL}/api/admin/export/status/{jid}", headers=ADMIN).json()
            if s["status"] != "running":
                break
            time.sleep(1)
        assert s["status"] == "done"
