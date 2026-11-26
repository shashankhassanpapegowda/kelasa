"""Full data export: every Mongo collection (Extended JSON) + every stored photo, zipped."""
import json
import logging
import os
import shutil
import subprocess
import tempfile
import threading
import uuid
import zipfile
from datetime import datetime, timezone
from typing import Callable, Optional

from bson import json_util
from pymongo import MongoClient

logger = logging.getLogger("export")
EXPORT_DIR = os.path.join(tempfile.gettempdir(), "kelasa-exports")
KEEP_SECONDS = 3600
BATCH = 1000
JSON_OPTS = json_util.CANONICAL_JSON_OPTIONS  # relaxed=False: exact type round-trip with mongoimport

_jobs: dict = {}
_lock = threading.Lock()


def _app_version() -> Optional[str]:
    if os.environ.get("APP_VERSION"):
        return os.environ["APP_VERSION"]
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=os.path.dirname(__file__), capture_output=True, text=True, timeout=5)
        return out.stdout.strip() or None
    except Exception:
        return None


def _collect_paths(value, prefix: str, found: set):
    if isinstance(value, str):
        if value.startswith(prefix) and ".." not in value:
            found.add(value)
    elif isinstance(value, dict):
        for v in value.values():
            _collect_paths(v, prefix, found)
    elif isinstance(value, (list, tuple)):
        for v in value:
            _collect_paths(v, prefix, found)


def active_job() -> Optional[dict]:
    with _lock:
        return next((j for j in _jobs.values() if j["status"] == "running"), None)


def latest_job() -> Optional[dict]:
    """The running job, else the newest finished one that can still be downloaded."""
    with _lock:
        live = [j for j in _jobs.values() if j["status"] in ("running", "done")]
        return max(live, key=lambda j: (j["status"] == "running", j["started_at"]), default=None)


def get_job(job_id: str) -> Optional[dict]:
    return _jobs.get(job_id)


def start_export(mongo_url: str, db_name: str, path_prefix: str, fetch: Callable[[str], tuple], started_by: str) -> dict:
    with _lock:
        if any(j["status"] == "running" for j in _jobs.values()):
            raise RuntimeError("An export is already running")
        os.makedirs(EXPORT_DIR, exist_ok=True)
        job_id = uuid.uuid4().hex[:16]
        job = {"job_id": job_id, "status": "running", "progress": 0, "size_bytes": 0, "error": None, "stage": "Starting",
               "started_by": started_by, "started_at": datetime.now(timezone.utc).isoformat(), "finished_at": None,
               "file": os.path.join(EXPORT_DIR, f"{job_id}.zip")}
        _jobs[job_id] = job
    threading.Thread(target=_run, args=(job, mongo_url, db_name, path_prefix, fetch), daemon=True).start()
    return job


def _run(job: dict, mongo_url: str, db_name: str, prefix: str, fetch: Callable[[str], tuple]):
    client = MongoClient(mongo_url)
    try:
        db = client[db_name]
        names = sorted(db.list_collection_names())
        counts, indexes, paths = {}, {}, set()
        with zipfile.ZipFile(job["file"], "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
            for i, name in enumerate(names):
                job["stage"] = f"Exporting {name}"
                n = 0
                with zf.open(f"db/{name}.json", "w", force_zip64=True) as fh:
                    for doc in db[name].find({}, no_cursor_timeout=True).batch_size(BATCH):
                        fh.write(json_util.dumps(doc, json_options=JSON_OPTS).encode("utf-8") + b"\n")
                        _collect_paths(doc, prefix, paths)
                        n += 1
                counts[name] = n
                indexes[name] = db[name].index_information()
                job["progress"] = int(50 * (i + 1) / max(1, len(names)))
            zf.writestr("db/_indexes.json", json_util.dumps(indexes, json_options=JSON_OPTS, indent=2))

            missing, empty, saved = [], [], 0
            ordered = sorted(paths)
            for i, p in enumerate(ordered):
                job["stage"] = f"Copying photos ({i + 1}/{len(ordered)})"
                try:
                    data, _ctype = fetch(p)
                    zf.writestr(f"photos/{p}", data)
                    saved += 1
                    if not data:
                        empty.append(p)
                except Exception as e:
                    missing.append(p)
                    logger.warning(f"Export: photo missing {p}: {e}")
                job["progress"] = 50 + int(49 * (i + 1) / max(1, len(ordered)))

            manifest = {
                "exported_at": datetime.now(timezone.utc).isoformat(),
                "db_name": db_name,
                "app_version": _app_version(),
                "collections": [{"name": k, "count": counts[k]} for k in names],
                "total_documents": sum(counts.values()),
                "photo_count": saved,
                "photos_referenced": len(ordered),
                "missing_photos": missing,
                "empty_photos": empty,
                "format": "db/<collection>.json = one MongoDB Extended JSON (canonical) document per line; "
                          "import with: mongoimport --db <db> --collection <name> --file db/<name>.json",
            }
            zf.writestr("manifest.json", json.dumps(manifest, indent=2))
        job.update(status="done", progress=100, stage="Ready", size_bytes=os.path.getsize(job["file"]),
                   finished_at=datetime.now(timezone.utc).isoformat(), manifest_summary={
                       "collections": len(names), "documents": manifest["total_documents"],
                       "photos": saved, "missing_photos": len(missing)})
        threading.Timer(KEEP_SECONDS, _expire, args=(job,)).start()
    except Exception as e:
        logger.exception("Export failed")
        job.update(status="failed", error=str(e), finished_at=datetime.now(timezone.utc).isoformat())
        _remove(job["file"])
    finally:
        client.close()


def _remove(path: str):
    try:
        os.remove(path)
    except FileNotFoundError:
        pass


def _expire(job: dict):
    _remove(job["file"])
    job.update(status="failed", error="The export file expired (kept for 1 hour). Start a new export.", size_bytes=0)


def cleanup_stale():
    shutil.rmtree(EXPORT_DIR, ignore_errors=True)
