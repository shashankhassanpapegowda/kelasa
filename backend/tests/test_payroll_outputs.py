"""Payslip rendering, register formulas, sheet import, days paid, and route guards."""
import io
from datetime import date
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openpyxl import Workbook, load_workbook

from payroll_api import router, set_user_loader
from payroll_calc import D, compute_line, default_settings
from payroll_excel import register_workbook
from payroll_import import parse_workbook, structures_from_sheet
from payroll_ndp import days_paid
from payroll_pdf import render_payslip
from payroll_api import sample_payslip


def test_register_formulas_follow_the_october_rules():
    line = compute_line(fixed={"BASIC": 6000, "HRA": 3000, "TA": 1320}, ndp=31, nwd=31, month=10)
    line = {**line, "name": "Full Month", "uan": "100200300400", "account_masked": "XXXXXXXX9012", "esi_charged": True, "pf_charged": True}
    raw = register_workbook([line], default_settings(), branch_name="Gyarahalli Thammayya World Academy (Vijaynagar)",
                            year_month="2026-10", formulas=True)
    wb = load_workbook(io.BytesIO(raw))
    ws = wb.active
    assert ws["A1"].value == "GYARAHALLI THAMMAYYA WORLD ACADEMY (VIJAYNAGAR) SALARY LIST OCTOBER 2026"
    headers = [ws.cell(2, col).value for col in range(1, 24)]
    assert headers[:10] == ["SL NO", "NAME", "A/C NO", "UAN", "NWD", "NDP", "BASIC", "HRA", "TA", "GROSS"]
    assert "SA" not in headers
    assert ws["G3"].value.startswith("=6000/E3*F3") or ws["G3"].value.startswith("=6000.00/E3*F3") or "6000" in ws["G3"].value
    assert ws["L3"].value.startswith("=ROUNDUP")
    assert "ROUNDUP" in ws["V3"].value
    assert ws["S3"].value.startswith("=IF(")
    assert "25000" in ws["S3"].value
    assert ws["W4"].value.startswith("=SUM(")


def test_sample_payslip_lists_ta_and_adjustment_reasons():
    from pypdf import PdfReader
    line = sample_payslip({}, default_settings(), "GT World Academy (Vijaynagar)")
    pdf = render_payslip(line, {"legal_name": "Gyarahalli Thammayya World Academy (Vijaynagar)", "language": "en"})
    assert pdf.startswith(b"%PDF")
    text = "\n".join((page.extract_text() or "") for page in PdfReader(io.BytesIO(pdf)).pages)
    assert "Travel Allowance (TA)" in text
    assert "Incentive" in text
    assert "Advance recovery" in text
    assert "Paid by employer" in text


def test_import_maps_sa_to_ta_and_reads_fixed_from_formula():
    wb = Workbook()
    ws = wb.active
    ws.title = "SEPTEMEBER 26"
    ws["A1"] = "GYARAHALLI THAMMAYYA WORLD ACADEMY (VIJAYNAGAR) SALARY LIST SEPTEMBER 2026"
    headers = ["SL NO", "NAME", "A/C NO", "UAN", "NWD", "NDP", "BASIC", "HRA", "SA", "GROSS", "PT", "DED/ADD"]
    for col, header in enumerate(headers, 1):
        ws.cell(2, col, header)
    ws["A3"] = 1
    ws["B3"] = "Asha"
    ws["C3"] = "\u202d123456789012\u202c"
    ws["D3"] = "100200300400"
    ws["E3"] = 30
    ws["F3"] = 30
    ws["G3"] = "=19000/E3*F3"
    ws["H3"] = 9500
    ws["I3"] = 3979
    ws["J3"] = 32479
    ws["K3"] = 200
    ws["L3"] = -1000
    ws["A4"] = None
    ws["B4"] = "TOTAL"
    ws["J4"] = 32479
    raw = io.BytesIO()
    wb.save(raw)
    parsed = parse_workbook(raw.getvalue())
    sheet = parsed["sheets"][0]
    assert sheet["month"] == "2026-09"
    assert sheet["rows"][0]["TA"] == Decimal("3979.00")
    assert sheet["rows"][0]["account"] == "123456789012"
    assert "BASIC" not in sheet["rows"][0] or sheet["rows"][0]["BASIC"] is None
    structures = structures_from_sheet(sheet)
    assert structures[0]["fixed"]["BASIC"] == "19000.00"
    assert structures[0]["fixed"]["TA"] == "3979.00"
    assert structures[0]["pt_override"] == "branch"


def test_ndp_uses_phase1_day_status():
    # October 2026: Thu 1 half day worked, Fri 2 paid leave, Sat 3 holiday, Sundays weekly off, rest absent.
    sessions = {"2026-10-01": [{"net_work_minutes": 60, "check_out": "2026-10-01T10:00:00+00:00", "late_by_minutes": 0}]}
    leaves = [{"start_date": "2026-10-02", "end_date": "2026-10-02", "status": "approved", "paid": True,
               "leave_type": "Casual Leave", "half_day": False}]
    result = days_paid(
        year=2026, month=10, nwd=D(31), today=date(2026, 11, 1), weekly_off=[6],
        holidays=["2026-10-03"], sessions_by_date=sessions, leaves=leaves,
        has_shift=True, shift_start="09:00", shift_end="18:00",
    )
    assert result["half_days"] == D("1")
    assert result["paid_leave"]["Casual Leave"] == D("1")
    assert result["holidays"] == D("1")
    assert result["weekly_offs"] == D("4")
    assert result["ndp"] == D("6.5")
    assert result["lop"] == D("24.5")

    joined = days_paid(year=2026, month=10, nwd=D(31), today=date(2026, 11, 1), weekly_off=[6],
                       joining="2026-10-16", has_shift=True, shift_start="09:00", shift_end="18:00")
    assert joined["ndp"] == D(2)
    assert joined["lop"] == D(29)


def _client(role, user_id="user"):
    async def loader(request):
        return {"role": role, "user_id": user_id, "name": role}
    set_user_loader(loader)
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_sub_admin_is_forbidden_on_every_payroll_route():
    client = _client("sub_admin", "sub")
    paths = []
    for route in router.routes:
        path = route.path
        if "{" in path:
            path = (path.replace("{run_id}", "run").replace("{line_id}", "line").replace("{recurring_id}", "rec")
                    .replace("{query_id}", "qry").replace("{fy}", "2026").replace("{branch_id}", "site"))
        paths.append((list(route.methods - {"HEAD"})[0], path))
    assert paths, "payroll routes must be registered"
    for method, path in paths:
        response = client.request(method, path)
        assert response.status_code == 403, f"{method} {path} returned {response.status_code}"


def test_employee_cannot_open_admin_payroll_or_another_payslip():
    client = _client("employee", "A")
    assert client.get("/api/payroll/runs", params={"branch_id": "site"}).status_code == 403
    assert client.put("/api/payroll/settings", json={"branch_id": "b", "effective_month": "2026-10", "settings": {}}).status_code == 403
    assert client.post("/api/payroll/runs/generate", json={"branch_id": "b", "month": "2026-10"}).status_code == 403
    # Own published payslip is allowed through the guard; another employee's line is 403 inside the handler.
    # Without a database the handler cannot load the line, so the guard test stops at admin routes.
    from payroll_auth import authorize_payslip
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as denied:
        authorize_payslip({"role": "employee", "user_id": "A"}, {"user_id": "B", "status": "published"})
    assert denied.value.status_code == 403


def test_anonymous_payroll_request_is_unauthorized():
    set_user_loader(lambda request: None)
    app = FastAPI()
    app.include_router(router)
    response = TestClient(app).get("/api/payroll/defaults")
    assert response.status_code == 401
