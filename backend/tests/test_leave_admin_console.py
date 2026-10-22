# Leave management + role-scoped admin/sub-admin console regression tests (iteration 5)
import os
import uuid
import pytest
import requests

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'https://employee-locator-4.preview.emergentagent.com').rstrip('/')
API = f"{BASE_URL}/api"
ADMIN = "test_session_admin_001"
SUB = "test_session_subadmin_001"
EMP = "test_session_emp_001"


def h(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def types_by_code(tok=EMP):
    r = requests.get(f"{API}/leave/types", headers=h(tok))
    assert r.status_code == 200
    return {t["code"]: t for t in r.json()["types"]}


# ---- Leave: employee flow ----
class TestEmployeeLeave:
    created = []

    @classmethod
    def teardown_class(cls):
        for lid in cls.created:
            requests.post(f"{API}/leave/{lid}/cancel", headers=h(EMP))

    def test_balance_cards(self):
        r = requests.get(f"{API}/leave/balance", headers=h(EMP))
        assert r.status_code == 200
        b = {x["code"]: x for x in r.json()["balances"]}
        assert b["CL"]["entitled"] == 12
        assert b["SL"]["entitled"] == 6
        assert b["EL"]["policy"] == "monthly" and b["EL"]["entitled"] == 15.0  # 1.5 * 10 months (Oct)
        assert b["LOP"]["entitled"] is None and b["LOP"]["available"] is None

    def test_apply_and_cancel(self):
        t = types_by_code()
        r = requests.post(f"{API}/leave/request", headers=h(EMP), json={
            "type_id": t["SL"]["type_id"], "start_date": "2026-11-10", "end_date": "2026-11-11", "reason": "TEST_flu"})
        assert r.status_code == 200, r.text
        req = r.json()["request"]
        assert req["status"] == "pending" and req["days"] == 2.0
        mine = requests.get(f"{API}/leave/me", headers=h(EMP)).json()["requests"]
        assert any(m["leave_id"] == req["leave_id"] for m in mine)
        bal = {x["code"]: x for x in requests.get(f"{API}/leave/balance", headers=h(EMP)).json()["balances"]}
        assert bal["SL"]["pending"] >= 2
        c = requests.post(f"{API}/leave/{req['leave_id']}/cancel", headers=h(EMP))
        assert c.status_code == 200
        mine = {m["leave_id"]: m for m in requests.get(f"{API}/leave/me", headers=h(EMP)).json()["requests"]}
        assert mine[req["leave_id"]]["status"] == "cancelled"

    def test_exceed_quota_rejected(self):
        t = types_by_code()
        r = requests.post(f"{API}/leave/request", headers=h(EMP), json={
            "type_id": t["SL"]["type_id"], "start_date": "2026-11-01", "end_date": "2026-11-20"})
        assert r.status_code == 400
        assert "left" in r.json()["detail"]

    def test_overlap_rejected(self):
        t = types_by_code()
        r = requests.post(f"{API}/leave/request", headers=h(EMP), json={
            "type_id": t["LOP"]["type_id"], "start_date": "2026-11-24", "end_date": "2026-11-25"})
        assert r.status_code == 200
        self.__class__.created.append(r.json()["request"]["leave_id"])
        r2 = requests.post(f"{API}/leave/request", headers=h(EMP), json={
            "type_id": t["CL"]["type_id"], "start_date": "2026-11-25", "end_date": "2026-11-26"})
        assert r2.status_code == 400
        assert "covering" in r2.json()["detail"]

    def test_invalid_dates(self):
        t = types_by_code()
        r = requests.post(f"{API}/leave/request", headers=h(EMP), json={
            "type_id": t["CL"]["type_id"], "start_date": "2026-11-20", "end_date": "2026-11-18"})
        assert r.status_code == 400
        r = requests.post(f"{API}/leave/request", headers=h(EMP), json={
            "type_id": t["CL"]["type_id"], "start_date": "2026-11-20", "end_date": "2026-11-21", "half_day": True})
        assert r.status_code == 400


# ---- Leave: approval flow (admin + sub-admin) ----
class TestLeaveDecisions:
    def _apply(self, start, end, code="LOP"):
        t = types_by_code()
        r = requests.post(f"{API}/leave/request", headers=h(EMP), json={
            "type_id": t[code]["type_id"], "start_date": start, "end_date": end, "reason": "TEST_"})
        assert r.status_code == 200, r.text
        return r.json()["request"]["leave_id"]

    def test_admin_approve(self):
        lid = self._apply("2026-12-01", "2026-12-01")
        lst = requests.get(f"{API}/admin/leave?status=pending", headers=h(ADMIN)).json()
        assert any(r["leave_id"] == lid for r in lst["requests"])
        r = requests.post(f"{API}/admin/leave/{lid}/decide", headers=h(ADMIN), json={"status": "approved"})
        assert r.status_code == 200
        mine = {m["leave_id"]: m for m in requests.get(f"{API}/leave/me", headers=h(EMP)).json()["requests"]}
        assert mine[lid]["status"] == "approved"
        again = requests.post(f"{API}/admin/leave/{lid}/decide", headers=h(ADMIN), json={"status": "rejected"})
        assert again.status_code == 400
        requests.post(f"{API}/leave/{lid}/cancel", headers=h(EMP))

    def test_sub_admin_reject_with_note(self):
        lid = self._apply("2026-12-03", "2026-12-03")
        lst = requests.get(f"{API}/admin/leave?status=pending", headers=h(SUB)).json()
        assert any(r["leave_id"] == lid for r in lst["requests"])
        r = requests.post(f"{API}/admin/leave/{lid}/decide", headers=h(SUB), json={"status": "rejected", "note": "TEST_busy"})
        assert r.status_code == 200
        mine = {m["leave_id"]: m for m in requests.get(f"{API}/leave/me", headers=h(EMP)).json()["requests"]}
        assert mine[lid]["status"] == "rejected" and mine[lid]["decision_note"] == "TEST_busy"

    def test_employee_cannot_decide(self):
        r = requests.post(f"{API}/admin/leave/lv_seed0001/decide", headers=h(EMP), json={"status": "approved"})
        assert r.status_code == 403

    def test_balances_matrix(self):
        r = requests.get(f"{API}/admin/leave/balances", headers=h(ADMIN))
        assert r.status_code == 200
        d = r.json()
        assert len(d["types"]) >= 4
        assert any(row["user_id"] == "user_testemp01" for row in d["rows"])


# ---- Leave types (admin only) ----
class TestLeaveTypes:
    def test_create_and_retire(self):
        code = f"T{uuid.uuid4().hex[:3].upper()}"
        r = requests.post(f"{API}/admin/leave-types", headers=h(ADMIN), json={
            "name": "TEST_Comp Off", "code": code, "policy": "monthly", "monthly_accrual": 1})
        assert r.status_code == 200
        tid = r.json()["type"]["type_id"]
        assert code in types_by_code()
        d = requests.delete(f"{API}/admin/leave-types/{tid}", headers=h(ADMIN))
        assert d.status_code == 200
        assert code not in types_by_code()

    def test_sub_admin_forbidden(self):
        r = requests.post(f"{API}/admin/leave-types", headers=h(SUB), json={"name": "X", "code": "XX", "policy": "none"})
        assert r.status_code == 403


# ---- Sub-admin scoping & permissions ----
class TestSubAdminScope:
    def test_employees_scoped(self):
        ids = {e["user_id"] for e in requests.get(f"{API}/admin/employees", headers=h(SUB)).json()["employees"]}
        assert "user_testemp01" in ids
        assert "user_testemp02" not in ids
        assert "user_testadmin01" not in ids

    def test_stats_scoped(self):
        s = requests.get(f"{API}/admin/stats", headers=h(SUB)).json()
        a = requests.get(f"{API}/admin/stats", headers=h(ADMIN)).json()
        assert s["total_employees"] < a["total_employees"]
        assert s["total_employees"] == 2  # self + Ravi
        for k in ("on_leave_today", "pending_leave", "late_today"):
            assert k in s

    @pytest.mark.parametrize("method,path", [
        ("post", "/admin/org/departments"), ("get", "/admin/activity"),
        ("post", "/admin/holidays"), ("patch", "/admin/employees/user_testemp01/role"),
        ("patch", "/admin/employees/user_testsub01/scope"),
    ])
    def test_admin_only_403(self, method, path):
        r = getattr(requests, method)(f"{API}{path}", headers=h(SUB), json={"name": "TEST_x", "date": "2026-12-25", "role": "admin"})
        assert r.status_code == 403

    def test_out_of_scope_edit_forbidden(self):
        r = requests.patch(f"{API}/admin/employees/user_testemp02/shift", headers=h(SUB), json={"break_max_minutes": 30})
        assert r.status_code == 403
        r = requests.delete(f"{API}/admin/employees/user_testemp02", headers=h(SUB))
        assert r.status_code == 403

    def test_sub_admin_edit_team_shift(self):
        r = requests.patch(f"{API}/admin/employees/user_testemp01/shift", headers=h(SUB), json={"break_max_minutes": 45})
        assert r.status_code == 200
        assert r.json()["employee"]["break_max_minutes"] == 45
        requests.patch(f"{API}/admin/employees/user_testemp01/shift", headers=h(ADMIN), json={"break_max_minutes": 60})

    def test_sub_admin_add_remove_employee(self):
        email = f"test_sub_{uuid.uuid4().hex[:6]}@example.com"
        r = requests.post(f"{API}/admin/employees", headers=h(SUB), json={"name": "TEST_SubHire", "email": email, "role": "admin"})
        assert r.status_code == 200
        emp = r.json()["employee"]
        assert emp["role"] == "employee" and emp["manager_id"] == "user_testsub01"
        ids = {e["user_id"] for e in requests.get(f"{API}/admin/employees", headers=h(SUB)).json()["employees"]}
        assert emp["user_id"] in ids
        d = requests.delete(f"{API}/admin/employees/{emp['user_id']}", headers=h(SUB))
        assert d.status_code == 200

    def test_employee_blocked_from_admin(self):
        assert requests.get(f"{API}/admin/employees", headers=h(EMP)).status_code == 403


# ---- Admin employee CRUD + org + holidays + notices + activity ----
class TestAdminManagement:
    def test_employee_crud(self):
        email = f"test_emp_{uuid.uuid4().hex[:6]}@example.com"
        r = requests.post(f"{API}/admin/employees", headers=h(ADMIN), json={
            "name": "TEST_NewHire", "email": email, "department": "Field Operations", "site": "Bengaluru HQ",
            "shift_start": "09:00", "shift_end": "18:00"})
        assert r.status_code == 200, r.text
        uid = r.json()["employee"]["user_id"]
        dup = requests.post(f"{API}/admin/employees", headers=h(ADMIN), json={"name": "x", "email": email})
        assert dup.status_code == 400
        a = requests.patch(f"{API}/admin/employees/{uid}/assignment", headers=h(ADMIN), json={
            "designation": "TEST_Driver", "department": "Administration", "manager_id": "user_testsub01"})
        assert a.status_code == 200
        emps = {e["user_id"]: e for e in requests.get(f"{API}/admin/employees", headers=h(ADMIN)).json()["employees"]}
        assert emps[uid]["designation"] == "TEST_Driver" and emps[uid]["pending_invite"] is True
        assert emps[uid]["department"] == "Administration" and emps[uid]["site"] == "Bengaluru HQ"
        d = requests.delete(f"{API}/admin/employees/{uid}", headers=h(ADMIN))
        assert d.status_code == 200
        emps = {e["user_id"] for e in requests.get(f"{API}/admin/employees", headers=h(ADMIN)).json()["employees"]}
        assert uid not in emps

    def test_cannot_delete_self(self):
        r = requests.delete(f"{API}/admin/employees/user_testadmin01", headers=h(ADMIN))
        assert r.status_code == 400

    def test_org_department_site(self):
        n = f"TEST_Dept_{uuid.uuid4().hex[:4]}"
        r = requests.post(f"{API}/admin/org/departments", headers=h(ADMIN), json={"name": n})
        assert r.status_code == 200
        uid = r.json()["department"]["unit_id"]
        s = requests.post(f"{API}/admin/org/sites", headers=h(ADMIN), json={"name": n})
        assert s.status_code == 200
        org = requests.get(f"{API}/admin/org", headers=h(ADMIN)).json()
        assert any(d["name"] == n for d in org["departments"])
        assert requests.delete(f"{API}/admin/org/departments/{uid}", headers=h(ADMIN)).status_code == 200
        assert requests.delete(f"{API}/admin/org/sites/{s.json()['site']['unit_id']}", headers=h(ADMIN)).status_code == 200

    def test_holiday_add_delete(self):
        r = requests.post(f"{API}/admin/holidays", headers=h(ADMIN), json={"date": "2026-12-24", "name": "TEST_Eve"})
        assert r.status_code == 200, r.text
        hid = r.json()["holiday"]["holiday_id"]
        hol = requests.get(f"{API}/holidays", headers=h(EMP)).json()["holidays"]
        assert any(x["holiday_id"] == hid for x in hol)
        assert requests.delete(f"{API}/admin/holidays/{hid}", headers=h(ADMIN)).status_code == 200

    def test_announcement(self):
        r = requests.post(f"{API}/admin/announcements", headers=h(ADMIN), json={"title": "TEST_Notice", "body": "b", "pinned": False})
        assert r.status_code == 200
        aid = r.json()["announcement"]["announcement_id"]
        anns = requests.get(f"{API}/announcements", headers=h(EMP)).json()["announcements"]
        assert any(a["announcement_id"] == aid for a in anns)
        # sub-admin cannot remove admin's notice
        assert requests.delete(f"{API}/admin/announcements/{aid}", headers=h(SUB)).status_code == 403
        assert requests.delete(f"{API}/admin/announcements/{aid}", headers=h(ADMIN)).status_code == 200

    def test_activity_log(self):
        r = requests.get(f"{API}/admin/activity", headers=h(ADMIN))
        assert r.status_code == 200
        actions = {e["action"] for e in r.json()["entries"]}
        for a in ("employee_added", "employee_removed", "holiday_added", "announcement_posted", "leave_approved", "leave_rejected", "shift_updated"):
            assert a in actions, a

    def test_analytics(self):
        r = requests.get(f"{API}/admin/analytics", headers=h(ADMIN))
        assert r.status_code == 200
        assert isinstance(r.json(), dict)

    def test_reports_csv_regression(self):
        r = requests.get(f"{API}/admin/reports.csv?from=2026-10-01&to=2026-10-22", headers=h(ADMIN))
        assert r.status_code == 200
        s = requests.get(f"{API}/admin/reports.csv?from=2026-10-01&to=2026-10-22", headers=h(SUB))
        assert s.status_code == 200
        assert "Anita Shetty" not in s.text
        e = requests.get(f"{API}/admin/reports.csv?from=2026-10-01&to=2026-10-22", headers=h(EMP))
        assert e.status_code == 403
