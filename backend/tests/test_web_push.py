# Web Push (phone alerts): /push/* endpoints + geofence leave/escalation push trigger chain
import base64
import os
import time
from datetime import datetime, timezone, timedelta

import pytest
import requests
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization
from pymongo import MongoClient

from conftest import BASE_URL, TINY_JPEG_B64, MONGO_URL, DB_NAME

ADMIN = {"Authorization": "Bearer test_session_admin_001"}
SUB = {"Authorization": "Bearer test_session_subadmin_001"}
OOS_TOKEN = "TEST_session_oos_sub_001"
OOS = {"Authorization": f"Bearer {OOS_TOKEN}"}
INSIDE = {"lat": 12.9720, "lng": 77.5946, "accuracy": 10}
OUTSIDE = {"lat": 12.99, "lng": 77.5946, "accuracy": 10}

db = MongoClient(MONGO_URL)[DB_NAME]


def b64u(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def fake_sub(tag):
    key = ec.generate_private_key(ec.SECP256R1())
    pub = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return {"endpoint": f"https://fcm.googleapis.com/fcm/send/fakeTEST{tag}{int(time.time()*1000)}",
            "keys": {"p256dh": b64u(pub), "auth": b64u(os.urandom(16))}}


def sub_exists(ep):
    return db.push_subscriptions.count_documents({"endpoint": ep}) == 1


def wait_gone(ep, timeout=15):
    end = time.time() + timeout
    while time.time() < end:
        if not sub_exists(ep):
            return True
        time.sleep(0.5)
    return False


@pytest.fixture(scope="module")
def emp():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": "emp1.test@gtgroups.local", "password": "RaviReset@26"})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['session_token']}"}


@pytest.fixture(scope="module", autouse=True)
def oos_subadmin():
    now = datetime.now(timezone.utc)
    db.users.delete_many({"user_id": "TEST_user_oos_sub"})
    db.user_sessions.delete_many({"session_token": OOS_TOKEN})
    db.users.insert_one({"user_id": "TEST_user_oos_sub", "email": "TEST_oos_sub@gtgroups.local", "name": "TEST OOS Sub",
                         "role": "sub_admin", "face_enrolled": True, "managed_departments": ["Administration"],
                         "managed_sites": [], "department": "Administration", "created_at": now.isoformat()})
    db.user_sessions.insert_one({"user_id": "TEST_user_oos_sub", "session_token": OOS_TOKEN,
                                 "expires_at": (now + timedelta(days=1)).isoformat(), "created_at": now.isoformat()})
    yield
    db.users.delete_many({"user_id": "TEST_user_oos_sub"})
    db.user_sessions.delete_many({"session_token": OOS_TOKEN})
    db.push_subscriptions.delete_many({"endpoint": {"$regex": "fakeTEST"}})


# ---- /push endpoints ----
class TestPushEndpoints:
    def test_public_key_auth(self, emp):
        r = requests.get(f"{BASE_URL}/api/push/public-key", headers=ADMIN)
        assert r.status_code == 200 and len(r.json()["public_key"]) > 60
        assert requests.get(f"{BASE_URL}/api/push/public-key", headers=SUB).status_code == 200
        assert requests.get(f"{BASE_URL}/api/push/public-key", headers=emp).status_code == 403
        assert requests.get(f"{BASE_URL}/api/push/public-key").status_code == 401

    def test_subscribe_validation(self, emp):
        s = fake_sub("v")
        assert requests.post(f"{BASE_URL}/api/push/subscribe", json={**s, "endpoint": "http://x.com/a"}, headers=ADMIN).status_code == 400
        assert requests.post(f"{BASE_URL}/api/push/subscribe", json={"endpoint": s["endpoint"]}, headers=ADMIN).status_code == 422
        assert requests.post(f"{BASE_URL}/api/push/subscribe", json=s, headers=emp).status_code == 403
        assert requests.post(f"{BASE_URL}/api/push/subscribe", json=s).status_code == 401

    def test_test_without_devices(self):
        db.push_subscriptions.delete_many({"user_id": "user_testadmin01"})
        r = requests.post(f"{BASE_URL}/api/push/test", headers=ADMIN)
        assert r.status_code == 400 and "No device is subscribed yet" in r.json()["detail"]

    def test_subscribe_upsert_status_delete(self):
        s = fake_sub("u")
        assert requests.post(f"{BASE_URL}/api/push/subscribe", json=s, headers=ADMIN).json()["ok"] is True
        assert requests.post(f"{BASE_URL}/api/push/subscribe", json=s, headers=ADMIN).status_code == 200
        assert db.push_subscriptions.count_documents({"endpoint": s["endpoint"]}) == 1
        st = requests.get(f"{BASE_URL}/api/push/status", params={"endpoint": s["endpoint"]}, headers=ADMIN).json()
        assert st["devices"] >= 1 and st["this_device"] is True
        st2 = requests.get(f"{BASE_URL}/api/push/status", headers=SUB).json()
        assert st2["this_device"] is False
        # other user cannot delete it
        requests.delete(f"{BASE_URL}/api/push/subscribe", params={"endpoint": s["endpoint"]}, headers=SUB)
        assert sub_exists(s["endpoint"])
        assert requests.delete(f"{BASE_URL}/api/push/subscribe", params={"endpoint": s["endpoint"]}, headers=ADMIN).status_code == 200
        assert not sub_exists(s["endpoint"])

    def test_send_test_dead_endpoint_removed(self):
        s = fake_sub("t")
        requests.post(f"{BASE_URL}/api/push/subscribe", json=s, headers=ADMIN)
        r = requests.post(f"{BASE_URL}/api/push/test", headers=ADMIN)
        assert r.status_code == 200
        d = r.json()
        assert d["sent"] == 0 and d["devices"] == 1
        assert not sub_exists(s["endpoint"])


# ---- trigger chain via location pings ----
class TestPushTriggerChain:
    def _subscribe_all(self):
        subs = {"admin": fake_sub("a"), "sub": fake_sub("s"), "oos": fake_sub("o")}
        for k, h in (("admin", ADMIN), ("sub", SUB), ("oos", OOS)):
            r = requests.post(f"{BASE_URL}/api/push/subscribe", json=subs[k], headers=h)
            assert r.status_code == 200, r.text
        return subs

    def test_full_chain(self, emp):
        body = {**INSIDE, "descriptor": [0.01] * 128, "image_b64": TINY_JPEG_B64}
        requests.post(f"{BASE_URL}/api/attendance/checkout", json=body, headers=emp)
        r = requests.post(f"{BASE_URL}/api/attendance/checkin", json=body, headers=emp)
        assert r.status_code == 200, r.text
        try:
            assert requests.post(f"{BASE_URL}/api/location/ping", json=INSIDE, headers=emp).status_code == 200
            subs = self._subscribe_all()

            # field staff: no alert, no push
            db.users.update_one({"user_id": "user_testemp01"}, {"$set": {"field_staff": True}})
            assert requests.post(f"{BASE_URL}/api/location/ping", json=OUTSIDE, headers=emp).status_code == 200
            time.sleep(4)
            assert all(sub_exists(s["endpoint"]) for s in subs.values()), "field staff ping pushed"
            assert db.geofence_alerts.count_documents({"user_id": "user_testemp01", "resolved_at": None}) == 0
            db.users.update_one({"user_id": "user_testemp01"}, {"$set": {"field_staff": False}})

            # first leave -> push to admin + in-scope sub, not out-of-scope
            assert requests.post(f"{BASE_URL}/api/location/ping", json=OUTSIDE, headers=emp).status_code == 200
            assert wait_gone(subs["admin"]["endpoint"]), "admin not pushed on leave"
            assert wait_gone(subs["sub"]["endpoint"]), "in-scope sub-admin not pushed on leave"
            time.sleep(2)
            assert sub_exists(subs["oos"]["endpoint"]), "out-of-scope sub-admin pushed"
            alert = db.geofence_alerts.find_one({"user_id": "user_testemp01", "resolved_at": None})
            assert alert is not None and not alert.get("pushed_level")

            # same interval ping -> no re-push
            subs2 = self._subscribe_all()
            requests.post(f"{BASE_URL}/api/location/ping", json=OUTSIDE, headers=emp)
            time.sleep(4)
            assert sub_exists(subs2["admin"]["endpoint"]), "re-pushed within same interval"

            # backdate 31 min -> escalation push level 1
            db.geofence_alerts.update_one({"alert_id": alert["alert_id"]},
                                          {"$set": {"created_at": (datetime.now(timezone.utc) - timedelta(minutes=31)).isoformat()}})
            requests.post(f"{BASE_URL}/api/location/ping", json=OUTSIDE, headers=emp)
            assert wait_gone(subs2["admin"]["endpoint"]), "no escalation push"
            assert wait_gone(subs2["sub"]["endpoint"]), "no escalation push to sub"
            assert db.geofence_alerts.find_one({"alert_id": alert["alert_id"]})["pushed_level"] == 1

            # another ping same level -> no push
            subs3 = self._subscribe_all()
            requests.post(f"{BASE_URL}/api/location/ping", json=OUTSIDE, headers=emp)
            time.sleep(4)
            assert sub_exists(subs3["admin"]["endpoint"]), "re-pushed at same level"
        finally:
            db.users.update_one({"user_id": "user_testemp01"}, {"$set": {"field_staff": False}})
            requests.post(f"{BASE_URL}/api/attendance/checkout", json=body, headers=emp)
            db.push_subscriptions.delete_many({"endpoint": {"$regex": "fakeTEST"}})
