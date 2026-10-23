# Iteration 10: Alert history + long-absence escalation tests
import csv
import io
import uuid
from datetime import datetime, timezone, timedelta

import pytest
import requests
from pymongo import MongoClient

from conftest import BASE_URL, MONGO_URL, DB_NAME

ADMIN = {"Authorization": "Bearer test_session_admin_001"}
SUB = {"Authorization": "Bearer test_session_subadmin_001"}
EMP = {"Authorization": "Bearer test_session_emp_001"}
db = MongoClient(MONGO_URL)[DB_NAME]
TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%d")


def iso_ago(minutes):
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()


@pytest.fixture(scope="module", autouse=True)
def restore_settings():
    yield
    requests.put(f"{BASE_URL}/api/admin/settings/geofence", json={"escalate_minutes": 30}, headers=ADMIN)
    db.geofence_alerts.delete_many({"alert_id": {"$regex": "^TEST_"}})


def make_alert(user_id="user_testemp01", name="Ravi Kumar", ago=95, resolved_ago=None, date=TODAY, **extra):
    aid = f"TEST_{uuid.uuid4().hex[:10]}"
    doc = {
        "alert_id": aid, "user_id": user_id, "name": name, "date": date,
        "lat": 12.99, "lng": 77.5946, "accuracy": 10, "distance_m": 2000, "nearest_branch": "GeoTest HQ",
        "created_at": iso_ago(ago), "last_seen_at": iso_ago(1),
        "resolved_at": iso_ago(resolved_ago) if resolved_ago is not None else None,
        "resolved_reason": "back inside GeoTest HQ" if resolved_ago is not None else None,
    }
    doc.update(extra)
    db.geofence_alerts.insert_one(dict(doc))
    return aid


def find_active(headers, aid):
    r = requests.get(f"{BASE_URL}/api/admin/geofence-alerts", headers=headers)
    assert r.status_code == 200
    return r.json(), next((a for a in r.json()["active"] if a["alert_id"] == aid), None)


# --- settings ---
class TestSettings:
    def test_get_default_and_sub_admin_can_read(self):
        r = requests.get(f"{BASE_URL}/api/admin/settings/geofence", headers=SUB)
        assert r.status_code == 200 and r.json()["escalate_minutes"] == 30

    def test_employee_forbidden(self):
        assert requests.get(f"{BASE_URL}/api/admin/settings/geofence", headers=EMP).status_code == 403

    def test_put_admin_only(self):
        r = requests.put(f"{BASE_URL}/api/admin/settings/geofence", json={"escalate_minutes": 45}, headers=SUB)
        assert r.status_code == 403

    @pytest.mark.parametrize("val,code", [(4, 400), (481, 400), (0, 400), (-5, 400), ("abc", 422), (5, 200), (480, 200)])
    def test_put_validation(self, val, code):
        r = requests.put(f"{BASE_URL}/api/admin/settings/geofence", json={"escalate_minutes": val}, headers=ADMIN)
        assert r.status_code == code, r.text
        if code == 200:
            assert requests.get(f"{BASE_URL}/api/admin/settings/geofence", headers=ADMIN).json()["escalate_minutes"] == val

    def test_put_persist_45_then_restore(self):
        r = requests.put(f"{BASE_URL}/api/admin/settings/geofence", json={"escalate_minutes": 45}, headers=ADMIN)
        assert r.status_code == 200 and r.json()["escalate_minutes"] == 45
        assert requests.get(f"{BASE_URL}/api/admin/geofence-alerts", headers=ADMIN).json()["escalate_minutes"] == 45
        requests.put(f"{BASE_URL}/api/admin/settings/geofence", json={"escalate_minutes": 30}, headers=ADMIN)


# --- escalation / ack ---
class TestEscalation:
    def test_enrich_fields_and_reack_cycle(self):
        requests.put(f"{BASE_URL}/api/admin/settings/geofence", json={"escalate_minutes": 30}, headers=ADMIN)
        aid = make_alert(ago=65)
        _, a = find_active(ADMIN, aid)
        assert a is not None
        assert 65 <= a["minutes_outside"] <= 66
        assert a["escalation_level"] == 2
        assert a["needs_attention"] is True
        # ack
        r = requests.post(f"{BASE_URL}/api/admin/geofence-alerts/{aid}/ack", headers=ADMIN)
        assert r.status_code == 200
        stored = db.geofence_alerts.find_one({"alert_id": aid})
        assert stored["acknowledged_level"] == 2 and stored["acknowledged_by"]
        _, a = find_active(ADMIN, aid)
        assert a["needs_attention"] is False
        # backdate to 95 min -> level 3 -> re-alert
        db.geofence_alerts.update_one({"alert_id": aid}, {"$set": {"created_at": iso_ago(95)}})
        _, a = find_active(ADMIN, aid)
        assert a["escalation_level"] == 3 and a["needs_attention"] is True
        # ack again at level 3
        requests.post(f"{BASE_URL}/api/admin/geofence-alerts/{aid}/ack", headers=ADMIN)
        _, a = find_active(ADMIN, aid)
        assert a["needs_attention"] is False
        assert db.geofence_alerts.find_one({"alert_id": aid})["acknowledged_level"] == 3

    def test_level0_ack_then_level1_realerts(self):
        aid = make_alert(ago=10)
        _, a = find_active(ADMIN, aid)
        assert a["escalation_level"] == 0 and a["needs_attention"] is True
        requests.post(f"{BASE_URL}/api/admin/geofence-alerts/{aid}/ack", headers=ADMIN)
        _, a = find_active(ADMIN, aid)
        assert a["needs_attention"] is False
        db.geofence_alerts.update_one({"alert_id": aid}, {"$set": {"created_at": iso_ago(31)}})
        _, a = find_active(ADMIN, aid)
        assert a["escalation_level"] == 1 and a["needs_attention"] is True

    def test_setting_change_affects_level(self):
        aid = make_alert(ago=50)
        requests.put(f"{BASE_URL}/api/admin/settings/geofence", json={"escalate_minutes": 10}, headers=ADMIN)
        _, a = find_active(ADMIN, aid)
        assert a["escalation_level"] == 5
        requests.put(f"{BASE_URL}/api/admin/settings/geofence", json={"escalate_minutes": 30}, headers=ADMIN)
        _, a = find_active(ADMIN, aid)
        assert a["escalation_level"] == 1

    def test_resolved_not_needs_attention(self):
        aid = make_alert(ago=100, resolved_ago=20)
        r = requests.get(f"{BASE_URL}/api/admin/geofence-alerts", headers=ADMIN).json()
        rec = next(a for a in r["recent"] if a["alert_id"] == aid)
        assert rec["needs_attention"] is False and 79 <= rec["minutes_outside"] <= 81

    def test_ack_404(self):
        assert requests.post(f"{BASE_URL}/api/admin/geofence-alerts/nope_x/ack", headers=ADMIN).status_code == 404


# --- history ---
class TestHistory:
    def test_history_range_and_fields(self):
        aid_in = make_alert(ago=200, resolved_ago=150, date="2026-09-10", acknowledged_by="Test Admin")
        aid_out = make_alert(ago=200, resolved_ago=150, date="2026-08-01")
        r = requests.get(f"{BASE_URL}/api/admin/geofence-alerts/history", params={"from": "2026-09-01", "to": "2026-09-30"}, headers=ADMIN)
        assert r.status_code == 200
        d = r.json()
        assert d["from"] == "2026-09-01" and d["to"] == "2026-09-30" and d["escalate_minutes"] == 30
        ids = [a["alert_id"] for a in d["alerts"]]
        assert aid_in in ids and aid_out not in ids
        a = next(a for a in d["alerts"] if a["alert_id"] == aid_in)
        assert a["minutes_outside"] == 50 and a["escalation_level"] == 1
        assert a["resolved_reason"] == "back inside GeoTest HQ" and a["acknowledged_by"] == "Test Admin"
        assert "_id" not in a
        assert all("2026-09-01" <= x["date"] <= "2026-09-30" for x in d["alerts"])

    def test_history_sub_admin_scoped(self):
        aid_anita = make_alert(user_id="user_testemp02", name="Anita Shetty", ago=60, resolved_ago=30, date="2026-09-11")
        aid_ravi = make_alert(ago=60, resolved_ago=30, date="2026-09-11")
        d = requests.get(f"{BASE_URL}/api/admin/geofence-alerts/history", params={"from": "2026-09-11", "to": "2026-09-11"}, headers=SUB).json()
        ids = [a["alert_id"] for a in d["alerts"]]
        assert aid_ravi in ids and aid_anita not in ids
        d2 = requests.get(f"{BASE_URL}/api/admin/geofence-alerts/history", params={"from": "2026-09-11", "to": "2026-09-11"}, headers=ADMIN).json()
        assert aid_anita in [a["alert_id"] for a in d2["alerts"]]

    def test_history_auth(self):
        assert requests.get(f"{BASE_URL}/api/admin/geofence-alerts/history", params={"from": TODAY, "to": TODAY}, headers=EMP).status_code == 403
        assert requests.get(f"{BASE_URL}/api/admin/geofence-alerts/history", params={"from": TODAY, "to": TODAY}).status_code == 401
        assert requests.get(f"{BASE_URL}/api/admin/geofence-alerts/history", headers=ADMIN).status_code == 422

    def test_history_csv(self):
        aid = make_alert(ago=200, resolved_ago=150, date="2026-09-12", acknowledged_by="Test Admin")
        r = requests.get(f"{BASE_URL}/api/admin/geofence-alerts/history.csv", params={"from": "2026-09-12", "to": "2026-09-12"}, headers=ADMIN)
        assert r.status_code == 200 and "text/csv" in r.headers["content-type"]
        assert "left_area_log_2026-09-12_to_2026-09-12.csv" in r.headers.get("content-disposition", "")
        rows = list(csv.reader(io.StringIO(r.text)))
        assert rows[0] == ["Date", "Employee", "Left At", "Returned At", "How It Ended", "Minutes Outside",
                           "Last Distance (m)", "Nearest Branch", "Repeat Alerts", "Acknowledged By"]
        row = next(x for x in rows[1:] if x[0] == "2026-09-12" and x[9] == "Test Admin")
        assert row[1] == "Ravi Kumar" and row[5] == "50" and row[7] == "GeoTest HQ" and row[8] == "1"

    def test_history_csv_still_outside_and_auth_param(self):
        r = requests.get(f"{BASE_URL}/api/admin/geofence-alerts/history.csv", params={"from": TODAY, "to": TODAY, "auth": "test_session_admin_001"})
        assert r.status_code == 200
        assert requests.get(f"{BASE_URL}/api/admin/geofence-alerts/history.csv", params={"from": TODAY, "to": TODAY}).status_code == 401
        assert requests.get(f"{BASE_URL}/api/admin/geofence-alerts/history.csv", params={"from": TODAY, "to": TODAY, "auth": "test_session_emp_001"}).status_code == 403

    def test_history_csv_sub_admin_scoped(self):
        make_alert(user_id="user_testemp02", name="Anita Shetty", ago=60, resolved_ago=30, date="2026-09-13")
        r = requests.get(f"{BASE_URL}/api/admin/geofence-alerts/history.csv", params={"from": "2026-09-13", "to": "2026-09-13"}, headers=SUB)
        assert r.status_code == 200 and "Anita" not in r.text
