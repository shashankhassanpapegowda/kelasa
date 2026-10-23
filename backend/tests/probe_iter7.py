import os, uuid, requests
from pymongo import MongoClient
B = os.environ['REACT_APP_BACKEND_URL'].rstrip('/') + '/api'
db = MongoClient('mongodb://localhost:27017')['test_database']
A = {"Authorization": "Bearer test_session_admin_001"}
S = {"Authorization": "Bearer test_session_subadmin_001"}
db.login_attempts.delete_many({})
made = []
try:
    # 1. sub-admin resetting an ADMIN in their department
    em = f"test_adm_{uuid.uuid4().hex[:5]}@gtgroups.local"; made.append(em)
    r = requests.post(f"{B}/admin/employees", headers=A, json={"name": "TEST_ScopeAdmin", "email": em, "role": "admin", "department": "Field Operations", "password": "AdminTmp@1"})
    uid = r.json()["employee"]["user_id"]
    r = requests.patch(f"{B}/admin/employees/{uid}/password", headers=S, json={"password": "Hijack@123"})
    print("1. sub-admin sets admin password:", r.status_code, r.text[:100])
    l = requests.post(f"{B}/auth/login", json={"email": em, "password": "Hijack@123"})
    print("   login as admin with sub-set pw:", l.status_code, l.json().get("user", {}).get("role") if l.ok else l.text)

    # 2. must_change_password enforced server-side?
    em2 = f"test_mcp_{uuid.uuid4().hex[:5]}@gtgroups.local"; made.append(em2)
    requests.post(f"{B}/admin/employees", headers=A, json={"name": "TEST_MCP", "email": em2, "password": "TempPass@1"})
    tok = requests.post(f"{B}/auth/login", json={"email": em2, "password": "TempPass@1"}).json()["session_token"]
    h = {"Authorization": f"Bearer {tok}"}
    for p in ("/leave/balances", "/leave/my", "/attendance/today", "/announcements"):
        print(f"2. must_change session GET {p}:", requests.get(f"{B}{p}", headers=h).status_code)

    # 3. X-Forwarded-For spoof
    db.login_attempts.delete_many({})
    codes = [requests.post(f"{B}/auth/login", headers={"X-Forwarded-For": f"10.0.0.{i}"}, json={"email": em2, "password": "bad-bad-1"}).status_code for i in range(8)]
    print("3. spoofed XFF 8 failures codes:", codes, list(db.login_attempts.find({}, {"_id": 0, "identifier": 1, "attempts": 1})))
    db.login_attempts.delete_many({})

    # 4. whitespace password
    r = requests.patch(f"{B}/admin/employees/{uid}/password", headers=A, json={"password": "  Spaced@123  "})
    a = requests.post(f"{B}/auth/login", json={"email": em, "password": "  Spaced@123  "}).status_code
    b = requests.post(f"{B}/auth/login", json={"email": em, "password": "Spaced@123"}).status_code
    print("4. whitespace pw: exact-as-typed login", a, "stripped login", b)

    # 5. change-password other sessions revoked?
    db.login_attempts.delete_many({})
    t1 = requests.post(f"{B}/auth/login", json={"email": em2, "password": "TempPass@1"}).json()["session_token"]
    t2 = requests.post(f"{B}/auth/login", json={"email": em2, "password": "TempPass@1"}).json()["session_token"]
    requests.post(f"{B}/auth/change-password", headers={"Authorization": f"Bearer {t1}"}, json={"current_password": "TempPass@1", "new_password": "Changed@123"})
    print("5. other session after change-password:", requests.get(f"{B}/auth/me", headers={"Authorization": f"Bearer {t2}"}).status_code)

    # 6. logout with bearer-only kills session?
    lo = requests.post(f"{B}/auth/logout", headers={"Authorization": f"Bearer {t1}"})
    print("6. bearer logout then /me:", requests.get(f"{B}/auth/me", headers={"Authorization": f"Bearer {t1}"}).status_code)

    # 7. employee list no hash
    print("7. hash in /admin/employees:", "password_hash" in requests.get(f"{B}/admin/employees", headers=A).text)
finally:
    for e in made:
        u = db.users.find_one({"email": e})
        if u:
            db.user_sessions.delete_many({"user_id": u["user_id"]}); db.users.delete_one({"email": e})
    db.login_attempts.delete_many({})
