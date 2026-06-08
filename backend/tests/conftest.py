import os
import pytest
import requests
from datetime import datetime, timezone, timedelta
from pymongo import MongoClient

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'https://employee-locator-4.preview.emergentagent.com').rstrip('/')
MONGO_URL = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
DB_NAME = os.environ.get('DB_NAME', 'test_database')


@pytest.fixture(scope="session")
def mongo_db():
    client = MongoClient(MONGO_URL)
    db = client[DB_NAME]
    yield db
    client.close()


@pytest.fixture(scope="session")
def base_url():
    return BASE_URL


def _make_session(db, user_id, email, name, role, token):
    db.users.delete_many({"user_id": user_id})
    db.user_sessions.delete_many({"session_token": token})
    db.attendance.delete_many({"user_id": user_id})
    db.locations.delete_many({"user_id": user_id})
    now = datetime.now(timezone.utc)
    db.users.insert_one({
        "user_id": user_id,
        "email": email,
        "name": name,
        "picture": None,
        "role": role,
        "created_at": now.isoformat(),
    })
    db.user_sessions.insert_one({
        "user_id": user_id,
        "session_token": token,
        "expires_at": (now + timedelta(days=7)).isoformat(),
        "created_at": now.isoformat(),
    })


@pytest.fixture(scope="session")
def admin_token(mongo_db):
    token = "TEST_session_admin_001"
    _make_session(mongo_db, "TEST_user_admin01", "TEST_admin@gtgroups.local",
                  "Test Admin", "admin", token)
    yield token
    # cleanup
    mongo_db.users.delete_one({"user_id": "TEST_user_admin01"})
    mongo_db.user_sessions.delete_one({"session_token": token})
    mongo_db.attendance.delete_many({"user_id": "TEST_user_admin01"})
    mongo_db.locations.delete_many({"user_id": "TEST_user_admin01"})


@pytest.fixture(scope="session")
def employee_token(mongo_db):
    token = "TEST_session_employee_001"
    _make_session(mongo_db, "TEST_user_emp01", "TEST_emp@gtgroups.local",
                  "Test Employee", "employee", token)
    yield token
    mongo_db.users.delete_one({"user_id": "TEST_user_emp01"})
    mongo_db.user_sessions.delete_one({"session_token": token})
    mongo_db.attendance.delete_many({"user_id": "TEST_user_emp01"})
    mongo_db.locations.delete_many({"user_id": "TEST_user_emp01"})


@pytest.fixture
def admin_client(admin_token):
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"})
    return s


@pytest.fixture
def employee_client(employee_token):
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {employee_token}", "Content-Type": "application/json"})
    return s


@pytest.fixture
def anon_client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s
