import os
import pytest
import requests
from datetime import datetime, timezone, timedelta
from pymongo import MongoClient

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'http://localhost:8000').rstrip('/')
MONGO_URL = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
DB_NAME = os.environ.get('DB_NAME', 'test_database')

# Minimal 1x1 white JPEG (base64). Valid JPEG bytes that object storage can store.
TINY_JPEG_B64 = (
    "/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0a"
    "HBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgNDRgyIRwhMjIyMjIy"
    "MjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjL/wAARCAABAAEDASIA"
    "AhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQA"
    "AAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3"
    "ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWm"
    "p6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEA"
    "AwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSEx"
    "BhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElK"
    "U1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3"
    "uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwD8/wAo"
    "oooA/9k="
)


@pytest.fixture(scope="session")
def tiny_jpeg_b64():
    return TINY_JPEG_B64


@pytest.fixture(scope="session")
def enrolled_descriptor():
    """A consistent 128-dim descriptor used for both seeding and check-in matching."""
    return [0.0] * 128


@pytest.fixture(scope="session")
def mongo_db():
    client = MongoClient(MONGO_URL)
    db = client[DB_NAME]
    yield db
    client.close()


@pytest.fixture(scope="session")
def base_url():
    return BASE_URL


def _make_session(db, user_id, email, name, role, token, face_enrolled=False, descriptor=None):
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
        "face_enrolled": face_enrolled,
        "face_descriptor": descriptor if face_enrolled else None,
        "face_photo_path": None,
        "created_at": now.isoformat(),
    })
    db.user_sessions.insert_one({
        "user_id": user_id,
        "session_token": token,
        "expires_at": (now + timedelta(days=7)).isoformat(),
        "created_at": now.isoformat(),
    })


@pytest.fixture(scope="session")
def admin_token(mongo_db, enrolled_descriptor):
    token = "TEST_session_admin_001"
    _make_session(mongo_db, "TEST_user_admin01", "TEST_admin@gtgroups.local",
                  "Test Admin", "admin", token,
                  face_enrolled=True, descriptor=enrolled_descriptor)
    yield token
    mongo_db.users.delete_one({"user_id": "TEST_user_admin01"})
    mongo_db.user_sessions.delete_one({"session_token": token})
    mongo_db.attendance.delete_many({"user_id": "TEST_user_admin01"})
    mongo_db.locations.delete_many({"user_id": "TEST_user_admin01"})


@pytest.fixture(scope="session")
def employee_token(mongo_db, enrolled_descriptor):
    """Employee with face already enrolled - for attendance flow tests."""
    token = "TEST_session_employee_001"
    _make_session(mongo_db, "TEST_user_emp01", "TEST_emp@gtgroups.local",
                  "Test Employee", "employee", token,
                  face_enrolled=True, descriptor=enrolled_descriptor)
    yield token
    mongo_db.users.delete_one({"user_id": "TEST_user_emp01"})
    mongo_db.user_sessions.delete_one({"session_token": token})
    mongo_db.attendance.delete_many({"user_id": "TEST_user_emp01"})
    mongo_db.locations.delete_many({"user_id": "TEST_user_emp01"})


@pytest.fixture(scope="session")
def unenrolled_employee_token(mongo_db):
    """Employee WITHOUT face enrolled - for testing the 400 face-not-enrolled flow."""
    token = "TEST_session_unenrolled_001"
    _make_session(mongo_db, "TEST_user_emp_noface", "TEST_emp_noface@gtgroups.local",
                  "Test Employee NoFace", "employee", token,
                  face_enrolled=False, descriptor=None)
    yield token
    mongo_db.users.delete_one({"user_id": "TEST_user_emp_noface"})
    mongo_db.user_sessions.delete_one({"session_token": token})


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
def unenrolled_client(unenrolled_employee_token):
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {unenrolled_employee_token}", "Content-Type": "application/json"})
    return s


@pytest.fixture
def anon_client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s
