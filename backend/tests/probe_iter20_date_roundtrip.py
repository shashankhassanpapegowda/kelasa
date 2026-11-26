# Iteration 20 probe: canonical Extended JSON (as written by export_job) round-trips BSON dates/ObjectId/int64 via mongoimport
import os, subprocess, tempfile
from datetime import datetime, timezone
from bson import ObjectId, Int64, json_util
from pymongo import MongoClient
from export_job import JSON_OPTS

URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
SCR = "TEST_export_date_scratch"
doc = {"_id": ObjectId(), "d": datetime(2026, 1, 2, 3, 4, 5, 678000, tzinfo=timezone.utc).replace(tzinfo=None),
       "i": 5, "l": Int64(5), "f": 5.0, "nested": {"d": datetime(2025, 5, 5)}}
c = MongoClient(URL)
try:
    with tempfile.NamedTemporaryFile("wb", suffix=".json", delete=False) as fh:
        fh.write(json_util.dumps(doc, json_options=JSON_OPTS).encode() + b"\n")
    r = subprocess.run(["mongoimport", "--uri", URL, "--db", SCR, "--collection", "x", "--file", fh.name], capture_output=True, text=True)
    print("rc", r.returncode, r.stderr.strip().splitlines()[-1:])
    got = c[SCR].x.find_one()
    print("equal:", got == doc, {k: type(v).__name__ for k, v in got.items()})
finally:
    c.drop_database(SCR)
