"""Payroll HTTP API.

Every route is guarded before the handler runs. Administrators have full
access. Sub-admins are refused with 403, including reads. Employees can open
only their own published payslips.
"""
from __future__ import annotations

import base64
import csv
import io
import logging
import os
import uuid
import zipfile
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from fastapi.routing import APIRoute
from pydantic import BaseModel, Field

from payroll_auth import authorize_payslip, require_own_payslip_access, require_payroll_admin
from payroll_calc import (
    D, apply_employee_flags, compute_line, days_in_month, default_register_columns,
    default_settings, freeze, mask_account,
    month_label, normalize_settings, professional_tax, q2, recurring_active,
    structure_from_ctc, ytd_from_lines,
)
from payroll_crypto import decrypt_json, encrypt_json
from payroll_excel import adjustment_rows, bank_rows, register_workbook
from payroll_import import compare_totals, parse_workbook, structures_from_sheet
from payroll_ndp import days_paid
from payroll_pdf import default_template, render_payslip

logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")

_deps = {
    "get_current_user": None,
    "db": None,
    "log_activity": None,
    "push_user": None,
    "put_object": None,
    "get_object": None,
}


def configure_payroll(*, get_current_user, database, log_activity=None, push_user=None, put_object=None, get_object=None):
    _deps.update(get_current_user=get_current_user, db=database, log_activity=log_activity,
                 push_user=push_user, put_object=put_object, get_object=get_object)


def set_user_loader(loader):
    """Tests inject a user without a database session."""
    _deps["get_current_user"] = loader


async def ensure_payroll_indexes(database=None):
    db = database if database is not None else _deps["db"]
    if db is None:
        return
    await db.payroll_settings.create_index([("branch_id", 1), ("effective_month", 1), ("version", 1)])
    await db.salary_structures.create_index([("user_id", 1), ("effective_from", 1), ("version", 1)])
    await db.payroll_runs.create_index([("branch_id", 1), ("month", 1), ("version", 1)], unique=True)
    await db.payroll_lines.create_index([("run_id", 1), ("user_id", 1)], unique=True)
    await db.payroll_lines.create_index([("user_id", 1), ("month", 1), ("status", 1)])
    await db.payslip_templates.create_index([("branch_id", 1), ("version", 1)])
    await db.payslip_queries.create_index([("user_id", 1), ("created_at", 1)])
    await db.payroll_recurring.create_index([("user_id", 1), ("branch_id", 1)])


async def load_payroll_user(request: Request) -> dict:
    loader = _deps.get("get_current_user")
    if loader is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user = loader(request)
    if hasattr(user, "__await__"):
        user = await user
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


class PayrollRoute(APIRoute):
    def get_route_handler(self):
        inner = super().get_route_handler()

        async def handler(request: Request):
            user = await load_payroll_user(request)
            path = request.url.path
            if "/payroll" in path:
                require_payroll_admin(user)
            elif path.startswith("/api/me/payslips") or path.startswith("/api/me/salary"):
                require_own_payslip_access(user)
            else:
                require_payroll_admin(user)
            request.state.user = user
            return await inner(request)

        return handler


router = APIRouter(route_class=PayrollRoute)


def _db():
    db = _deps.get("db")
    if db is None:
        raise HTTPException(status_code=500, detail="Payroll storage is not configured")
    return db


def _now() -> str:
    return datetime.now(ZoneInfo("UTC")).isoformat()


def _month_parts(month: str) -> tuple:
    try:
        year, mon = (int(p) for p in month.split("-"))
    except ValueError:
        raise HTTPException(status_code=400, detail="Month must be YYYY-MM") from None
    if not 1 <= mon <= 12:
        raise HTTPException(status_code=400, detail="Month must be YYYY-MM")
    return year, mon


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


async def _log(actor: dict, action: str, target: str, details: str):
    fn = _deps.get("log_activity")
    if fn:
        await fn(actor, action, target, details)


def _storage_root() -> Path:
    return Path(os.environ.get("KELASA_STORAGE_DIR") or Path(__file__).resolve().parent / "var" / "storage")


def store_bytes(path: str, data: bytes, content_type: str) -> str:
    """Prefer the app storage helper. Fall back to local disk when it is unavailable."""
    put = _deps.get("put_object")
    if put:
        try:
            put(path, data, content_type)
            return path
        except Exception as exc:
            logger.warning("Storage helper failed for %s (%s); writing locally", path, exc)
    dest = _storage_root() / path
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return str(dest)


def read_bytes(path: str) -> Optional[bytes]:
    get = _deps.get("get_object")
    if get and not path.startswith("/"):
        try:
            data, _ctype = get(path)
            return data
        except Exception:
            pass
    local = _storage_root() / path
    if local.exists():
        return local.read_bytes()
    return None


def holiday_applies(holiday: dict, site: Optional[str]) -> bool:
    branches = holiday.get("branches") or []
    return not branches or bool(site and site in branches)


class SettingsIn(BaseModel):
    branch_id: str
    effective_month: str
    settings: dict


class CopySettingsIn(BaseModel):
    from_branch_id: str
    to_branch_id: str
    effective_month: str


class StructureIn(BaseModel):
    user_id: str
    branch_id: str
    effective_from: str
    fixed: dict
    monthly_ctc: Optional[str] = None
    esi_applicable: bool = True
    pf_applicable: bool = True
    pt_override: str = "branch"
    pt_amount: Optional[str] = None
    employee_share_deducted: Optional[bool] = None
    pt_deducted: Optional[bool] = None
    notes: str = ""


class CtcPreviewIn(BaseModel):
    monthly_ctc: str
    esi_applicable: bool = True
    branch_id: Optional[str] = None
    month: Optional[str] = None


class GenerateIn(BaseModel):
    branch_id: str
    month: str


class LinePatch(BaseModel):
    ndp: Optional[str] = None
    ndp_reason: Optional[str] = None
    adjustments: Optional[list] = None
    esi_applicable: Optional[bool] = None
    pf_applicable: Optional[bool] = None
    pt_override: Optional[str] = None
    pt_amount: Optional[str] = None
    employee_share_deducted: Optional[bool] = None
    pt_deducted: Optional[bool] = None


class RecurringIn(BaseModel):
    user_id: str
    branch_id: str
    type: str
    amount: str
    label: str
    category: Optional[str] = None
    start_month: str
    months: int = Field(gt=0)


class TemplateIn(BaseModel):
    branch_id: str
    template: dict


class DuplicateTemplateIn(BaseModel):
    from_branch_id: str
    to_branch_id: str


class TemplatePreviewIn(BaseModel):
    branch_id: str
    template: dict = {}


class ImportPreviewIn(BaseModel):
    branch_id: str
    file_b64: str
    sheets: Optional[list] = None


class ImportMatch(BaseModel):
    sl: str
    action: str
    user_id: Optional[str] = None


class ImportCommitIn(BaseModel):
    branch_id: str
    month: str
    sheet: str
    file_b64: str
    matches: list[ImportMatch]


class StructuresFromSheetIn(BaseModel):
    branch_id: str
    sheet: str
    file_b64: str
    effective_from: str
    matches: list[ImportMatch]


class QueryIn(BaseModel):
    message: str


class ReplyIn(BaseModel):
    message: str


def _clean_components(components: list) -> list:
    if not components:
        raise HTTPException(status_code=400, detail="Add at least one earning component")
    seen = set()
    cleaned = []
    for raw in components:
        code = (raw.get("code") or "").strip().upper()
        name = (raw.get("name") or "").strip()
        if not code or not name:
            raise HTTPException(status_code=400, detail="Each earning needs a name and a short code")
        if code in seen:
            raise HTTPException(status_code=400, detail=f"Duplicate earning code {code}")
        seen.add(code)
        cleaned.append({
            "code": code, "name": name,
            "payslip_label": (raw.get("payslip_label") or name).strip(),
            "show_on_payslip": bool(raw.get("show_on_payslip", True)),
            "prorate": bool(raw.get("prorate", True)),
            "esi_base": bool(raw.get("esi_base", False)),
            "pf_base": bool(raw.get("pf_base", False)),
        })
    return cleaned


def _prepare_settings(payload: dict) -> dict:
    settings = normalize_settings(payload)
    settings["earning_components"] = _clean_components(settings["earning_components"])
    if settings.get("register_columns") == []:
        settings["register_columns"] = None
    return settings


async def _branch(branch_id: str) -> dict:
    doc = await _db().sites.find_one({"unit_id": branch_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Branch not found")
    return doc


async def _settings_for(branch_id: str, month: str) -> dict:
    rows = await _db().payroll_settings.find(
        {"branch_id": branch_id, "effective_month": {"$lte": month}}, {"_id": 0}
    ).sort([("effective_month", -1), ("version", -1)]).to_list(1)
    if not rows:
        return {"settings_id": None, "version": 0, "effective_month": month, "settings": default_settings()}
    return rows[0]


async def _template_for(branch_id: str, version: Optional[int] = None) -> dict:
    query = {"branch_id": branch_id}
    if version is not None:
        query["version"] = version
    rows = await _db().payslip_templates.find(query, {"_id": 0}).sort("version", -1).to_list(1)
    if not rows:
        base = default_template()
        return {"template_id": None, "version": 0, "template": base}
    return rows[0]


def _decode_file(file_b64: str) -> bytes:
    raw = file_b64.split(",", 1)[1] if "," in file_b64 and file_b64.strip().startswith("data:") else file_b64
    try:
        return base64.b64decode(raw, validate=True)
    except Exception:
        raise HTTPException(status_code=400, detail="The upload is not a valid file") from None


def _structure_view(doc: dict) -> dict:
    body = decrypt_json(doc.get("enc") or "")
    return {k: doc.get(k) for k in ("structure_id", "user_id", "branch_id", "effective_from", "version", "created_at", "created_by")} | body


async def _latest_structure(user_id: str, as_of: str) -> Optional[dict]:
    rows = await _db().salary_structures.find(
        {"user_id": user_id, "effective_from": {"$lte": as_of}}, {"_id": 0}
    ).sort([("effective_from", -1), ("version", -1)]).to_list(1)
    return _structure_view(rows[0]) if rows else None


def _line_view(doc: dict, *, reveal_account: bool = False) -> dict:
    snap = decrypt_json(doc.get("enc") or "")
    result = snap.get("result") or {}
    employee = snap.get("employee") or {}
    inputs = snap.get("inputs") or {}
    account = employee.get("account_number") or ""
    view = {
        "line_id": doc.get("line_id"),
        "run_id": doc.get("run_id"),
        "user_id": doc.get("user_id"),
        "branch_id": doc.get("branch_id"),
        "month": doc.get("month"),
        "status": doc.get("status"),
        "version": doc.get("version"),
        "superseded": bool(doc.get("superseded")),
        "imported": bool(doc.get("imported")),
        "name": employee.get("name") or doc.get("employee_name"),
        "employee_code": employee.get("employee_code"),
        "designation": employee.get("designation"),
        "department": employee.get("department"),
        "branch_name": employee.get("branch_name"),
        "date_of_joining": employee.get("date_of_joining"),
        "pan": employee.get("pan"),
        "uan": employee.get("uan"),
        "esi_number": employee.get("esi_number"),
        "bank_name": employee.get("bank_name"),
        "ifsc": employee.get("ifsc"),
        "account_masked": mask_account(account),
        "attendance": snap.get("attendance") or {},
        "warnings": snap.get("warnings") or [],
        "inputs": inputs,
        "ndp_overridden": bool(inputs.get("ndp_overridden")),
        "ndp_reason": inputs.get("ndp_reason") or "",
        "component_labels": snap.get("component_labels") or {},
    }
    for key in ("nwd", "ndp", "earnings", "fixed", "gross", "e_esi", "e_esi_r", "esi", "esi_r",
                "e_pf", "e_pf_r", "pf", "pf_r", "pt", "ded_add", "final", "atc", "ctc",
                "pf_base", "esi_base", "overridden", "deduct_pf_esi", "deduct_pt",
                "esi_applicable", "pf_applicable", "pt_override", "pt_amount", "adjustments"):
        if key in result:
            view[key] = result[key]
    if reveal_account:
        view["account_number"] = account
    return view


async def _run_lines(run_id: str, *, reveal_account: bool = False) -> list:
    docs = await _db().payroll_lines.find({"run_id": run_id}, {"_id": 0}).to_list(5000)
    views = [_line_view(doc, reveal_account=reveal_account) for doc in docs]
    views.sort(key=lambda row: (row.get("name") or "").lower())
    return views


async def _run(run_id: str) -> dict:
    doc = await _db().payroll_runs.find_one({"run_id": run_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Payroll run not found")
    return doc


def _recompute(inputs: dict, settings: dict, month_number: int) -> dict:
    tuned = apply_employee_flags(settings, pt_deducted=inputs.get("pt_deducted"))
    try:
        result = compute_line(
            fixed=inputs.get("fixed") or {},
            ndp=inputs.get("ndp"),
            nwd=inputs.get("nwd"),
            adjustments=inputs.get("adjustments") or [],
            esi_applicable=inputs.get("esi_applicable", True),
            pf_applicable=inputs.get("pf_applicable", True),
            pt_override=inputs.get("pt_override") or "branch",
            pt_amount=inputs.get("pt_amount"),
            employee_share_deducted=inputs.get("employee_share_deducted"),
            settings=tuned,
            month=month_number,
            ndp_overridden=bool(inputs.get("ndp_overridden")),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return freeze(result)


def _warnings_for(result: dict, employee: dict, inputs: dict, previous_atc) -> list:
    from payroll_calc import line_warnings
    bank = (employee.get("account_number") or "").strip()
    return line_warnings(
        {**result, "adjustments": inputs.get("adjustments") or []},
        previous_atc=previous_atc,
        has_bank=bool(bank),
        has_uan=bool(employee.get("uan")) or bool(employee.get("epf_not_applicable")),
        has_esi_number=bool(employee.get("esi_number")) or bool(employee.get("esi_not_applicable")),
        pf_on=bool(result.get("pf_charged", result.get("pf_applicable"))),
        esi_on=bool(result.get("esi_charged", result.get("esi_applicable"))),
    )


async def _previous_atc(user_id: str, month: str):
    year, mon = _month_parts(month)
    if mon == 1:
        prev = f"{year - 1}-12"
    else:
        prev = f"{year:04d}-{mon - 1:02d}"
    rows = await _db().payroll_lines.find(
        {"user_id": user_id, "month": prev, "status": "published", "superseded": {"$ne": True}}, {"_id": 0}
    ).sort("version", -1).to_list(1)
    if not rows:
        return None
    snap = decrypt_json(rows[0].get("enc") or "")
    return (snap.get("result") or {}).get("atc")


async def _attendance_for(user: dict, profile: dict, month: str, nwd: Decimal) -> dict:
    year, mon = _month_parts(month)
    first = date(year, mon, 1)
    last = date(year, mon, days_in_month(year, mon))
    f, t = first.isoformat(), last.isoformat()
    uid = user["user_id"]
    records = await _db().attendance.find({"user_id": uid, "date": {"$gte": f, "$lte": t}}, {"_id": 0}).to_list(2000)
    by_date = {}
    for rec in records:
        if rec.get("superseded_by"):
            continue
        by_date.setdefault(rec["date"], []).append(rec)
    holidays = []
    for holiday in await _db().holidays.find({"date": {"$gte": f, "$lte": t}}, {"_id": 0}).to_list(500):
        if holiday_applies(holiday, user.get("site")):
            holidays.append(holiday["date"])
    leaves = await _db().leave_requests.find(
        {"user_id": uid, "status": "approved", "start_date": {"$lte": t}, "end_date": {"$gte": f}}, {"_id": 0}
    ).to_list(500)
    types = {item["type_id"]: item for item in await _db().leave_types.find({}, {"_id": 0}).to_list(200)}
    for leave in leaves:
        kind = types.get(leave.get("type_id")) or {}
        leave["paid"] = kind.get("paid", True)
        leave["leave_type"] = leave.get("type_name") or kind.get("name")
    today = datetime.now(IST).date()
    breakdown = days_paid(
        year=year, month=mon, nwd=nwd, today=today,
        joining=profile.get("date_of_joining"),
        exit_date=profile.get("date_of_exit") or user.get("exit_date"),
        weekly_off=user.get("weekly_off") or [6],
        holidays=holidays, sessions_by_date=by_date, leaves=leaves,
        has_shift=bool(user.get("shift_start")), pending_invite=bool(user.get("pending_invite")),
        shift_start=user.get("shift_start"), shift_end=user.get("shift_end"),
    )
    return freeze(breakdown)


def _active_in_month(user: dict, profile: dict, month: str) -> bool:
    year, mon = _month_parts(month)
    first = date(year, mon, 1)
    last = date(year, mon, days_in_month(year, mon))
    joining = (profile.get("date_of_joining") or "")[:10]
    exited = (profile.get("date_of_exit") or user.get("exit_date") or "")[:10]
    if joining and joining > last.isoformat():
        return False
    if exited and exited < first.isoformat():
        return False
    return True


async def _recurring_for(user_id: str, branch_id: str, month: str) -> list:
    docs = await _db().payroll_recurring.find({"user_id": user_id, "branch_id": branch_id}, {"_id": 0}).to_list(100)
    items = []
    for doc in docs:
        body = decrypt_json(doc.get("enc") or "")
        if recurring_active(body, month):
            items.append({
                "type": body.get("type"), "amount": body.get("amount"), "label": body.get("label"),
                "category": body.get("category"), "recurring_id": doc.get("recurring_id"),
            })
    return items


def _employee_blob(user: dict, profile: dict, branch: dict) -> dict:
    bank = profile.get("bank") or {}
    return {
        "name": user.get("name"),
        "employee_code": user.get("employee_code"),
        "designation": user.get("designation"),
        "department": user.get("department"),
        "branch_name": branch.get("name"),
        "date_of_joining": profile.get("date_of_joining"),
        "pan": profile.get("pan"),
        "uan": None if profile.get("epf_not_applicable") else profile.get("uan"),
        "esi_number": None if profile.get("esi_not_applicable") else profile.get("esi"),
        "epf_not_applicable": bool(profile.get("epf_not_applicable")),
        "esi_not_applicable": bool(profile.get("esi_not_applicable")),
        "bank_name": bank.get("bank_name"),
        "account_number": bank.get("account_number"),
        "ifsc": bank.get("ifsc"),
    }


@router.get("/api/payroll/defaults")
async def payroll_defaults(request: Request):
    return {"settings": default_settings(), "template": default_template(), "register_columns": default_register_columns()}


@router.get("/api/payroll/settings")
async def get_settings(request: Request, branch_id: str, month: Optional[str] = None):
    await _branch(branch_id)
    current = await _settings_for(branch_id, month or datetime.now(IST).strftime("%Y-%m"))
    history = await _db().payroll_settings.find({"branch_id": branch_id}, {"_id": 0, "settings": 0}).sort("version", -1).to_list(50)
    return {"current": current, "history": history}


@router.put("/api/payroll/settings")
async def save_settings(payload: SettingsIn, request: Request):
    _month_parts(payload.effective_month)
    branch = await _branch(payload.branch_id)
    settings = _prepare_settings(payload.settings)
    version = await _db().payroll_settings.count_documents({"branch_id": payload.branch_id}) + 1
    doc = {
        "settings_id": _id("pset"), "branch_id": payload.branch_id, "effective_month": payload.effective_month,
        "version": version, "settings": settings, "created_at": _now(), "created_by": request.state.user["user_id"],
    }
    await _db().payroll_settings.insert_one(doc)
    doc.pop("_id", None)
    await _log(request.state.user, "payroll_settings_saved", branch["name"],
               f"Saved payroll settings version {version} effective {payload.effective_month}")
    return doc


@router.post("/api/payroll/settings/copy")
async def copy_settings(payload: CopySettingsIn, request: Request):
    _month_parts(payload.effective_month)
    source = await _settings_for(payload.from_branch_id, payload.effective_month)
    target = await _branch(payload.to_branch_id)
    saved = await save_settings(SettingsIn(
        branch_id=payload.to_branch_id, effective_month=payload.effective_month, settings=source["settings"]
    ), request)
    await _log(request.state.user, "payroll_settings_copied", target["name"],
               f"Copied payroll settings from branch {payload.from_branch_id}")
    return saved


@router.get("/api/payroll/structures")
async def list_structures(request: Request, branch_id: str):
    await _branch(branch_id)
    docs = await _db().salary_structures.find({"branch_id": branch_id}, {"_id": 0}).sort("effective_from", -1).to_list(5000)
    return {"structures": [_structure_view(doc) for doc in docs]}


@router.post("/api/payroll/structures")
async def save_structure(payload: StructureIn, request: Request):
    if payload.pt_override not in ("branch", "fixed", "none"):
        raise HTTPException(status_code=400, detail="PT override must be branch, fixed or none")
    user = await _db().users.find_one({"user_id": payload.user_id}, {"_id": 0, "name": 1})
    if not user:
        raise HTTPException(status_code=404, detail="Employee not found")
    version = await _db().salary_structures.count_documents({"user_id": payload.user_id}) + 1
    body = {
        "fixed": {str(k).upper(): str(q2(v)) for k, v in (payload.fixed or {}).items()},
        "monthly_ctc": None if payload.monthly_ctc in (None, "") else str(q2(payload.monthly_ctc)),
        "esi_applicable": payload.esi_applicable, "pf_applicable": payload.pf_applicable,
        "pt_override": payload.pt_override, "pt_amount": payload.pt_amount,
        "employee_share_deducted": payload.employee_share_deducted, "pt_deducted": payload.pt_deducted,
        "notes": payload.notes or "",
    }
    doc = {
        "structure_id": _id("sal"), "user_id": payload.user_id, "branch_id": payload.branch_id,
        "effective_from": payload.effective_from, "version": version, "created_at": _now(),
        "created_by": request.state.user["user_id"], "enc": encrypt_json(body),
    }
    await _db().salary_structures.insert_one(doc)
    await _log(request.state.user, "salary_structure_saved", user.get("name") or payload.user_id,
               f"Saved salary structure version {version} effective {payload.effective_from}")
    doc.pop("_id", None)
    return _structure_view(doc)


@router.post("/api/payroll/structures/preview-ctc")
async def preview_ctc(payload: CtcPreviewIn, request: Request):
    settings = default_settings()
    month_number = None
    if payload.branch_id and payload.month:
        _month_parts(payload.month)
        settings = (await _settings_for(payload.branch_id, payload.month))["settings"]
        month_number = int(payload.month.split("-")[1])
    try:
        built = structure_from_ctc(payload.monthly_ctc, esi_applicable=payload.esi_applicable, settings=settings, month=month_number)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return freeze(built)


@router.get("/api/payroll/runs")
async def list_runs(request: Request, branch_id: str, month: Optional[str] = None):
    query = {"branch_id": branch_id}
    if month:
        _month_parts(month)
        query["month"] = month
    docs = await _db().payroll_runs.find(query, {"_id": 0, "settings": 0}).sort([("month", -1), ("version", -1)]).to_list(200)
    return {"runs": docs}


@router.post("/api/payroll/runs/generate")
async def generate_run(payload: GenerateIn, request: Request):
    year, mon = _month_parts(payload.month)
    branch = await _branch(payload.branch_id)
    existing = await _db().payroll_runs.find(
        {"branch_id": payload.branch_id, "month": payload.month}, {"_id": 0}
    ).sort("version", -1).to_list(1)
    if existing:
        if existing[0]["status"] == "draft":
            lines = await _run_lines(existing[0]["run_id"])
            return {"run": existing[0], "lines": lines, "missing_structure": [], "missing_bank": [], "existing": True}
        raise HTTPException(status_code=409, detail="This month already has a payroll run. Revise a published run to make a new version.")
    pack = await _settings_for(payload.branch_id, payload.month)
    settings = normalize_settings(pack["settings"])
    template = await _template_for(payload.branch_id)
    as_of = date(year, mon, days_in_month(year, mon)).isoformat()
    users = await _db().users.find({"site": branch["name"]}, {"_id": 0, "password_hash": 0, "face_descriptor": 0}).to_list(5000)
    profiles = {p["user_id"]: p for p in await _db().employee_profiles.find(
        {"user_id": {"$in": [u["user_id"] for u in users]}}, {"_id": 0}).to_list(5000)}
    run = {
        "run_id": _id("prun"), "branch_id": payload.branch_id, "branch_name": branch["name"],
        "display_name": (settings.get("profile") or {}).get("display_name") or branch["name"],
        "month": payload.month, "status": "draft", "version": 1, "imported": False, "superseded": False,
        "settings": settings, "settings_id": pack.get("settings_id"), "settings_version": pack.get("version"),
        "template_id": template.get("template_id"), "template_version": template.get("version") or 0,
        "created_at": _now(), "created_by": request.state.user["user_id"],
    }
    missing_structure, missing_bank, line_docs = [], [], []
    for user in sorted(users, key=lambda item: (item.get("name") or "").lower()):
        profile = profiles.get(user["user_id"]) or {}
        if not _active_in_month(user, profile, payload.month):
            continue
        structure = await _latest_structure(user["user_id"], as_of)
        employee = _employee_blob(user, profile, branch)
        if not employee.get("account_number"):
            missing_bank.append({"user_id": user["user_id"], "name": user.get("name")})
        if not structure or structure.get("branch_id") not in (None, payload.branch_id):
            missing_structure.append({"user_id": user["user_id"], "name": user.get("name")})
            continue
        nwd = D(days_in_month(year, mon))
        if settings.get("proration") != "calendar":
            from payroll_calc import nwd_for
            nwd = nwd_for(year, mon, settings, user.get("weekly_off") or [6])
        attendance = await _attendance_for(user, profile, payload.month, nwd)
        adjustments = await _recurring_for(user["user_id"], payload.branch_id, payload.month)
        inputs = {
            "fixed": structure.get("fixed") or {},
            "ndp": attendance["ndp"], "nwd": str(nwd), "ndp_overridden": False, "ndp_reason": "",
            "adjustments": adjustments,
            "esi_applicable": structure.get("esi_applicable", True),
            "pf_applicable": structure.get("pf_applicable", True),
            "pt_override": structure.get("pt_override") or "branch",
            "pt_amount": structure.get("pt_amount"),
            "employee_share_deducted": structure.get("employee_share_deducted"),
            "pt_deducted": structure.get("pt_deducted"),
            "calculated_ndp": attendance["ndp"],
        }
        result = _recompute(inputs, settings, mon)
        previous = await _previous_atc(user["user_id"], payload.month)
        warnings = _warnings_for(result, employee, inputs, previous)
        labels = {c["code"]: c.get("payslip_label") or c["name"] for c in settings["earning_components"]}
        snap = {"inputs": inputs, "result": result, "employee": employee, "attendance": attendance,
                "warnings": warnings, "component_labels": labels, "structure_id": structure.get("structure_id")}
        line_docs.append({
            "line_id": _id("pline"), "run_id": run["run_id"], "user_id": user["user_id"],
            "branch_id": payload.branch_id, "month": payload.month, "version": 1, "status": "draft",
            "superseded": False, "imported": False, "employee_name": user.get("name"),
            "enc": encrypt_json(snap),
        })
    await _db().payroll_runs.insert_one(dict(run))
    if line_docs:
        await _db().payroll_lines.insert_many(line_docs)
    await _log(request.state.user, "payroll_generated", branch["name"],
               f"Generated the {month_label(payload.month)} draft payroll for {branch['name']} ({len(line_docs)} employees)")
    run.pop("_id", None)
    return {"run": run, "lines": await _run_lines(run["run_id"]), "missing_structure": missing_structure, "missing_bank": missing_bank}


@router.get("/api/payroll/runs/{run_id}")
async def get_run(run_id: str, request: Request):
    run = await _run(run_id)
    public = {k: v for k, v in run.items() if k != "settings"}
    public["register_columns"] = (run.get("settings") or {}).get("register_columns") or default_register_columns((run.get("settings") or {}).get("earning_components"))
    return {"run": public, "lines": await _run_lines(run_id)}


async def _draft_line(run_id: str, line_id: str) -> tuple:
    run = await _run(run_id)
    if run["status"] != "draft":
        raise HTTPException(status_code=400, detail="Only a draft payroll can be edited")
    doc = await _db().payroll_lines.find_one({"run_id": run_id, "line_id": line_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Payroll line not found")
    return run, doc


@router.patch("/api/payroll/runs/{run_id}/lines/{line_id}")
async def patch_line(run_id: str, line_id: str, payload: LinePatch, request: Request):
    run, doc = await _draft_line(run_id, line_id)
    snap = decrypt_json(doc.get("enc") or "")
    inputs = dict(snap.get("inputs") or {})
    data = payload.model_dump(exclude_unset=True)
    if "ndp" in data:
        reason = (data.get("ndp_reason") or inputs.get("ndp_reason") or "").strip()
        calculated = str(inputs.get("calculated_ndp") or "")
        if str(data["ndp"]) != calculated and not reason:
            raise HTTPException(status_code=400, detail="Overriding days paid needs a reason")
        inputs["ndp"] = str(data["ndp"])
        inputs["ndp_overridden"] = str(data["ndp"]) != calculated
        inputs["ndp_reason"] = reason
    if "adjustments" in data:
        for entry in data["adjustments"] or []:
            if not (entry.get("label") or entry.get("reason") or "").strip():
                raise HTTPException(status_code=400, detail="Each deduction or addition needs a reason")
            if entry.get("type") not in ("deduction", "addition"):
                raise HTTPException(status_code=400, detail="Adjustment type must be deduction or addition")
        inputs["adjustments"] = data["adjustments"]
    for key in ("esi_applicable", "pf_applicable", "pt_override", "pt_amount", "employee_share_deducted", "pt_deducted"):
        if key in data:
            inputs[key] = data[key]
    month_number = int(run["month"].split("-")[1])
    result = _recompute(inputs, run["settings"], month_number)
    previous = await _previous_atc(doc["user_id"], run["month"])
    snap["inputs"] = inputs
    snap["result"] = result
    snap["warnings"] = _warnings_for(result, snap.get("employee") or {}, inputs, previous)
    await _db().payroll_lines.update_one({"line_id": line_id}, {"$set": {"enc": encrypt_json(snap)}})
    name = (snap.get("employee") or {}).get("name") or doc.get("employee_name")
    if "ndp" in data and inputs.get("ndp_overridden"):
        await _log(request.state.user, "payroll_ndp_override", name,
                   f"Set days paid to {inputs['ndp']} for {month_label(run['month'])}. Reason: {inputs.get('ndp_reason')}")
    if "adjustments" in data:
        await _log(request.state.user, "payroll_adjustment", name,
                   f"Updated deductions and additions for {month_label(run['month'])}")
    doc["enc"] = encrypt_json(snap)
    return _line_view(doc)


async def _set_status(run_id: str, status: str, request: Request, extra: Optional[dict] = None):
    run = await _run(run_id)
    updates = {"status": status, **(extra or {})}
    await _db().payroll_runs.update_one({"run_id": run_id}, {"$set": updates})
    await _db().payroll_lines.update_many({"run_id": run_id}, {"$set": {"status": status}})
    run.update(updates)
    return run


@router.post("/api/payroll/runs/{run_id}/approve")
async def approve_run(run_id: str, request: Request):
    run = await _run(run_id)
    if run["status"] != "draft":
        raise HTTPException(status_code=400, detail="Only a draft can be approved")
    run = await _set_status(run_id, "approved", request, {"approved_at": _now(), "approved_by": request.state.user["user_id"]})
    await _log(request.state.user, "payroll_approved", run.get("branch_name") or "",
               f"Approved the {month_label(run['month'])} payroll for {run.get('branch_name')}")
    return {"ok": True, "status": "approved"}


@router.post("/api/payroll/runs/{run_id}/publish")
async def publish_run(run_id: str, request: Request):
    run = await _run(run_id)
    if run["status"] != "approved":
        raise HTTPException(status_code=400, detail="Approve the payroll before publishing it")
    template = await _template_for(run["branch_id"])
    run = await _set_status(run_id, "published", request, {
        "published_at": _now(), "published_by": request.state.user["user_id"],
        "template_id": template.get("template_id"), "template_version": template.get("version") or 0,
    })
    lines = await _run_lines(run_id)
    push = _deps.get("push_user")
    label = month_label(run["month"])
    if push:
        for line in lines:
            push(line["user_id"], {
                "title": f"Your payslip for {label} is ready.",
                "body": f"Your payslip for {label} is ready.",
                "tag": f"payslip-{run['month']}", "url": "/salary",
            })
    await _log(request.state.user, "payroll_published", run.get("branch_name") or "",
               f"Published the {label} payroll for {run.get('branch_name')} and notified {len(lines)} employees")
    return {"ok": True, "status": "published", "notified": len(lines)}


@router.post("/api/payroll/runs/{run_id}/revise")
async def revise_run(run_id: str, request: Request):
    run = await _run(run_id)
    if run["status"] != "published":
        raise HTTPException(status_code=400, detail="Only a published payroll can be revised")
    version = int(run["version"]) + 1
    new_run = {k: v for k, v in run.items() if k not in ("_id", "published_at", "published_by", "approved_at", "approved_by")}
    new_run.update({
        "run_id": _id("prun"), "version": version, "status": "draft", "superseded": False,
        "created_at": _now(), "created_by": request.state.user["user_id"], "revised_from": run_id,
    })
    await _db().payroll_runs.update_one({"run_id": run_id}, {"$set": {"superseded": True}})
    await _db().payroll_lines.update_many({"run_id": run_id}, {"$set": {"superseded": True}})
    old_lines = await _db().payroll_lines.find({"run_id": run_id}, {"_id": 0}).to_list(5000)
    copies = []
    for doc in old_lines:
        snap = decrypt_json(doc.get("enc") or "")
        if not run.get("imported"):
            snap["result"] = _recompute(snap.get("inputs") or {}, run["settings"], int(run["month"].split("-")[1]))
        copies.append({
            **{k: doc.get(k) for k in ("user_id", "branch_id", "month", "employee_name", "imported")},
            "line_id": _id("pline"), "run_id": new_run["run_id"], "version": version, "status": "draft",
            "superseded": False, "enc": encrypt_json(snap),
        })
    await _db().payroll_runs.insert_one(dict(new_run))
    if copies:
        await _db().payroll_lines.insert_many(copies)
    await _log(request.state.user, "payroll_revised", run.get("branch_name") or "",
               f"Revised the {month_label(run['month'])} payroll. Version {version} is the new draft and version {run['version']} is superseded")
    new_run.pop("_id", None)
    return {"run": {k: v for k, v in new_run.items() if k != "settings"}, "lines": await _run_lines(new_run["run_id"])}


@router.post("/api/payroll/runs/{run_id}/notify")
async def resend_notifications(run_id: str, request: Request):
    run = await _run(run_id)
    if run["status"] != "published":
        raise HTTPException(status_code=400, detail="Notifications go out when a payroll is published")
    lines = await _run_lines(run_id)
    push = _deps.get("push_user")
    label = month_label(run["month"])
    sent = 0
    if push:
        for line in lines:
            if line.get("superseded"):
                continue
            push(line["user_id"], {"title": f"Your payslip for {label} is ready.", "body": f"Your payslip for {label} is ready.",
                                   "tag": f"payslip-{run['month']}", "url": "/salary"})
            sent += 1
    await _log(request.state.user, "payroll_notified", run.get("branch_name") or "", f"Re-sent {label} payslip notifications to {sent} employees")
    return {"ok": True, "notified": sent}


@router.post("/api/payroll/runs/{run_id}/refresh-ndp")
async def refresh_ndp(run_id: str, request: Request):
    run = await _run(run_id)
    if run["status"] != "draft":
        raise HTTPException(status_code=400, detail="Only a draft payroll can be edited")
    branch = await _branch(run["branch_id"])
    changed = 0
    docs = await _db().payroll_lines.find({"run_id": run_id}, {"_id": 0}).to_list(5000)
    for doc in docs:
        snap = decrypt_json(doc.get("enc") or "")
        inputs = snap.get("inputs") or {}
        if inputs.get("ndp_overridden"):
            continue
        user = await _db().users.find_one({"user_id": doc["user_id"]}, {"_id": 0, "password_hash": 0, "face_descriptor": 0})
        profile = await _db().employee_profiles.find_one({"user_id": doc["user_id"]}, {"_id": 0}) or {}
        if not user:
            continue
        attendance = await _attendance_for(user, profile, run["month"], D(inputs.get("nwd") or 0))
        inputs["ndp"] = attendance["ndp"]
        inputs["calculated_ndp"] = attendance["ndp"]
        snap["inputs"] = inputs
        snap["attendance"] = attendance
        snap["result"] = _recompute(inputs, run["settings"], int(run["month"].split("-")[1]))
        snap["warnings"] = _warnings_for(snap["result"], snap.get("employee") or {}, inputs, await _previous_atc(doc["user_id"], run["month"]))
        await _db().payroll_lines.update_one({"line_id": doc["line_id"]}, {"$set": {"enc": encrypt_json(snap)}})
        changed += 1
    await _log(request.state.user, "payroll_ndp_refreshed", branch["name"], f"Refreshed days paid from attendance for {changed} employees")
    return {"ok": True, "updated": changed, "lines": await _run_lines(run_id)}


def _export_lines(lines: list) -> list:
    exported = []
    for line in lines:
        item = dict(line)
        item["account_number"] = line.get("account_masked")
        exported.append(item)
    return exported


@router.get("/api/payroll/runs/{run_id}/export")
async def export_run(run_id: str, request: Request, kind: str = "register"):
    run = await _run(run_id)
    reveal = kind == "bank"
    lines = await _run_lines(run_id, reveal_account=reveal)
    settings = run.get("settings") or default_settings()
    label = month_label(run["month"])
    branch = run.get("display_name") or run.get("branch_name") or "Branch"
    if kind in ("register", "values"):
        formulas = kind == "register" and not run.get("imported")
        data = register_workbook(_export_lines(lines) if not reveal else lines, settings, branch_name=branch,
                                 year_month=run["month"], formulas=formulas)
        filename = f"{branch}-{run['month']}-register.xlsx"
        media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    elif kind == "bank":
        header, rows = bank_rows(lines, settings)
        data, filename, media = _csv_bytes(header, rows), f"{branch}-{run['month']}-bank.csv", "text/csv"
    elif kind == "adjustments":
        header, rows = adjustment_rows(lines)
        data, filename, media = _csv_bytes(header, rows), f"{branch}-{run['month']}-ded-add.csv", "text/csv"
    elif kind in ("pf", "esi", "pt"):
        data, filename, media = _statutory_csv(kind, lines, run["month"])
    else:
        raise HTTPException(status_code=400, detail="Unknown export")
    await _log(request.state.user, "payroll_exported", branch, f"Downloaded the {label} {kind} export")
    return Response(content=data, media_type=media, headers={"Content-Disposition": f'attachment; filename="{filename}"'})


def _csv_bytes(header, rows) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(header)
    writer.writerows(rows)
    return buf.getvalue().encode("utf-8")


def _statutory_csv(kind: str, lines: list, month: str):
    if kind == "pf":
        header = ["UAN", "Name", "PF wages", "Employee share", "Employer share", "NCP days"]
        rows = []
        for line in lines:
            lop = (line.get("attendance") or {}).get("lop")
            if lop is None:
                lop = str(D(line.get("nwd") or 0) - D(line.get("ndp") or 0))
            rows.append([line.get("uan") or "", line.get("name") or "", line.get("pf_base") or 0, line.get("pf_r") or 0, line.get("e_pf_r") or 0, lop])
        return _csv_bytes(header, rows), f"pf-{month}.csv", "text/csv"
    if kind == "esi":
        header = ["ESI number", "Name", "Days paid", "ESI wages", "Employee share", "Employer share"]
        rows = [[line.get("esi_number") or "", line.get("name") or "", line.get("ndp") or 0, line.get("esi_base") or 0, line.get("esi_r") or 0, line.get("e_esi_r") or 0] for line in lines]
        return _csv_bytes(header, rows), f"esi-{month}.csv", "text/csv"
    header = ["Name", "Gross", "Professional tax"]
    rows = [[line.get("name") or "", line.get("gross") or 0, line.get("pt") or 0] for line in lines]
    return _csv_bytes(header, rows), f"pt-{month}.csv", "text/csv"


async def _render_line_pdf(run: dict, line: dict) -> bytes:
    template_doc = await _template_for(run["branch_id"], run.get("template_version") or None)
    template = template_doc.get("template") or default_template()
    if template.get("logo_path"):
        template["logo_bytes"] = read_bytes(template["logo_path"])
    if not template.get("legal_name"):
        template["legal_name"] = (run.get("settings") or {}).get("profile", {}).get("legal_name") or run.get("display_name") or ""
    address = (run.get("settings") or {}).get("profile", {}).get("address")
    if address and not template.get("address_lines"):
        template["address_lines"] = [row.strip() for row in str(address).splitlines() if row.strip()]
    history = await _db().payroll_lines.find(
        {"user_id": line["user_id"], "status": "published"}, {"_id": 0}
    ).to_list(200)
    published = []
    for doc in history:
        view = _line_view(doc)
        if view.get("superseded"):
            continue
        published.append(view)
    if line.get("status") == "published" and not any(item.get("line_id") == line.get("line_id") for item in published):
        published.append(line)
    ytd = freeze(ytd_from_lines(published, line["month"]))
    printable = dict(line)
    printable["legal_name"] = template.get("legal_name")
    return render_payslip(printable, template, ytd=ytd)


@router.get("/api/payroll/runs/{run_id}/lines/{line_id}.pdf")
async def admin_payslip_pdf(run_id: str, line_id: str, request: Request):
    run = await _run(run_id)
    doc = await _db().payroll_lines.find_one({"run_id": run_id, "line_id": line_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Payslip not found")
    line = _line_view(doc)
    pdf = await _render_line_pdf(run, line)
    await _log(request.state.user, "payslip_downloaded", line.get("name") or "",
               f"Downloaded {line.get('name')}'s payslip for {month_label(run['month'])}")
    filename = _pdf_name(line)
    return Response(content=pdf, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{filename}"'})


def _pdf_name(line: dict) -> str:
    code = line.get("employee_code") or line.get("user_id") or "employee"
    name = "".join(ch if ch.isalnum() else "_" for ch in (line.get("name") or "employee"))
    return f"{code}_{name}_{line.get('month')}.pdf"


@router.get("/api/payroll/runs/{run_id}/payslips.zip")
async def payslips_zip(run_id: str, request: Request):
    run = await _run(run_id)
    lines = await _run_lines(run_id)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
        for line in lines:
            archive.writestr(_pdf_name(line), await _render_line_pdf(run, line))
    await _log(request.state.user, "payslips_zip", run.get("branch_name") or "",
               f"Downloaded all {month_label(run['month'])} payslips for {run.get('branch_name')}")
    filename = f"{run.get('branch_name') or 'branch'}_{run['month']}_payslips.zip"
    return Response(content=buf.getvalue(), media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/api/payroll/templates")
async def get_template(request: Request, branch_id: str):
    await _branch(branch_id)
    current = await _template_for(branch_id)
    history = await _db().payslip_templates.find({"branch_id": branch_id}, {"_id": 0, "template": 0}).sort("version", -1).to_list(20)
    return {"current": current, "history": history}


@router.put("/api/payroll/templates")
async def save_template(payload: TemplateIn, request: Request):
    branch = await _branch(payload.branch_id)
    version = await _db().payslip_templates.count_documents({"branch_id": payload.branch_id}) + 1
    template = {**default_template(), **(payload.template or {})}
    doc = {"template_id": _id("ptpl"), "branch_id": payload.branch_id, "version": version,
           "template": template, "created_at": _now(), "created_by": request.state.user["user_id"]}
    await _db().payslip_templates.insert_one(doc)
    doc.pop("_id", None)
    await _log(request.state.user, "payslip_template_saved", branch["name"], f"Saved payslip template version {version}")
    return doc


@router.post("/api/payroll/templates/duplicate")
async def duplicate_template(payload: DuplicateTemplateIn, request: Request):
    source = await _template_for(payload.from_branch_id)
    return await save_template(TemplateIn(branch_id=payload.to_branch_id, template=source.get("template") or default_template()), request)


@router.post("/api/payroll/templates/preview.pdf")
async def preview_pdf_draft(payload: TemplatePreviewIn, request: Request):
    """Sample PDF from the template on screen, before it is saved."""
    branch = await _branch(payload.branch_id)
    template = {**default_template(), **(payload.template or {})}
    settings = (await _settings_for(payload.branch_id, "2026-10"))["settings"]
    if not template.get("legal_name"):
        template["legal_name"] = (settings.get("profile") or {}).get("legal_name") or branch["name"]
    line = sample_payslip(template, settings, branch["name"])
    pdf = render_payslip(line, template, ytd={"gross": line["gross"], "pf_ee": line["pf_r"], "pf_er": line["e_pf_r"],
                                              "esi_ee": line["esi_r"], "esi_er": line["e_esi_r"], "pt": line["pt"], "net": line["atc"]})
    return Response(content=pdf, media_type="application/pdf", headers={"Content-Disposition": 'attachment; filename="sample-payslip.pdf"'})


@router.get("/api/payroll/templates/preview.pdf")
async def preview_pdf(request: Request, branch_id: str):
    branch = await _branch(branch_id)
    template_doc = await _template_for(branch_id)
    template = template_doc.get("template") or default_template()
    settings_doc = await _settings_for(branch_id, "2026-10")
    if not template.get("legal_name"):
        template["legal_name"] = (settings_doc["settings"].get("profile") or {}).get("legal_name") or branch["name"]
    line = sample_payslip(template, settings_doc["settings"], branch["name"])
    pdf = render_payslip(line, template, ytd={"gross": line["gross"], "pf_ee": line["pf_r"], "pf_er": line["e_pf_r"],
                                              "esi_ee": line["esi_r"], "esi_er": line["e_esi_r"], "pt": line["pt"], "net": line["atc"]})
    return Response(content=pdf, media_type="application/pdf", headers={"Content-Disposition": 'attachment; filename="sample-payslip.pdf"'})


def sample_payslip(template: dict, settings: dict, branch_name: str) -> dict:
    """A real calculation (October rules) so the preview lists TA and each DED/ADD reason."""
    result = compute_line(
        fixed={"BASIC": 5750, "HRA": 2875, "TA": 1264}, ndp=31, nwd=31, month=10, settings=settings,
        adjustments=[
            {"type": "addition", "amount": "1000", "label": "Incentive", "category": "Incentive"},
            {"type": "deduction", "amount": "250", "label": "Advance recovery", "category": "Advance recovery"},
        ],
    )
    frozen = freeze(result)
    labels = {c["code"]: c.get("payslip_label") or c["name"] for c in normalize_settings(settings)["earning_components"]}
    return {
        **frozen, "month": "2026-10", "name": "Sample Employee", "employee_code": "GT001",
        "designation": "Teacher", "department": "Academics", "branch_name": branch_name,
        "date_of_joining": "2024-06-01", "pan": "ABCDE1234F", "uan": "100200300400", "esi_number": "1234567890",
        "bank_name": "State Bank of India", "account_masked": "XXXXXXXX9012", "ifsc": "SBIN0001234",
        "component_labels": labels, "legal_name": template.get("legal_name") or branch_name,
        "attendance": {"nwd": "31", "present": "26", "half_days": "0", "paid_leave": {"Casual Leave": "1"},
                       "holidays": "1", "weekly_offs": "4", "lop": "0"},
        "status": "published",
    }


@router.get("/api/payroll/templates/preview")
async def preview_json(request: Request, branch_id: str):
    branch = await _branch(branch_id)
    template = (await _template_for(branch_id)).get("template") or default_template()
    settings = (await _settings_for(branch_id, "2026-10"))["settings"]
    return {"line": sample_payslip(template, settings, branch["name"]), "template": template}


@router.post("/api/payroll/recurring")
async def add_recurring(payload: RecurringIn, request: Request):
    if payload.type not in ("deduction", "addition"):
        raise HTTPException(status_code=400, detail="Adjustment type must be deduction or addition")
    if not payload.label.strip():
        raise HTTPException(status_code=400, detail="Each deduction or addition needs a reason")
    _month_parts(payload.start_month)
    user = await _db().users.find_one({"user_id": payload.user_id}, {"_id": 0, "name": 1})
    if not user:
        raise HTTPException(status_code=404, detail="Employee not found")
    body = {"type": payload.type, "amount": str(q2(payload.amount)), "label": payload.label.strip(),
            "category": payload.category, "start_month": payload.start_month, "months": payload.months}
    doc = {"recurring_id": _id("prec"), "user_id": payload.user_id, "branch_id": payload.branch_id,
           "created_at": _now(), "created_by": request.state.user["user_id"], "enc": encrypt_json(body)}
    await _db().payroll_recurring.insert_one(doc)
    await _log(request.state.user, "payroll_recurring_added", user.get("name") or payload.user_id,
               f"Added a recurring {payload.type} of ₹{body['amount']} ({body['label']}) for {payload.months} months from {payload.start_month}")
    doc.pop("_id", None)
    return {"recurring_id": doc["recurring_id"], **body}


@router.delete("/api/payroll/recurring/{recurring_id}")
async def delete_recurring(recurring_id: str, request: Request):
    """Stopping a recurring item keeps the months already paid. The schedule itself is retained and marked ended."""
    doc = await _db().payroll_recurring.find_one({"recurring_id": recurring_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Not found")
    body = decrypt_json(doc.get("enc") or "")
    body["months"] = 0
    await _db().payroll_recurring.update_one({"recurring_id": recurring_id}, {"$set": {"enc": encrypt_json(body), "ended": True}})
    await _log(request.state.user, "payroll_recurring_ended", doc.get("user_id") or "", f"Stopped recurring item {body.get('label') or recurring_id}")
    return {"ok": True}


def _match_rows(rows: list, users: list, profiles: dict) -> tuple:
    by_uan, by_account, by_name = {}, {}, {}
    for user in users:
        profile = profiles.get(user["user_id"]) or {}
        uan = strip_key(profile.get("uan"))
        if uan:
            by_uan[uan] = user
        account = strip_key((profile.get("bank") or {}).get("account_number"))
        if account:
            by_account[account] = user
        by_name.setdefault((user.get("name") or "").strip().lower(), []).append(user)
    matched, unmatched = [], []
    for row in rows:
        user, how = None, None
        if strip_key(row.get("uan")) and strip_key(row.get("uan")) in by_uan:
            user, how = by_uan[strip_key(row.get("uan"))], "uan"
        elif strip_key(row.get("account")) and strip_key(row.get("account")) in by_account:
            user, how = by_account[strip_key(row.get("account"))], "account"
        else:
            hits = by_name.get((row.get("name") or "").strip().lower(), [])
            if len(hits) == 1:
                user, how = hits[0], "name"
        entry = {"sl": row.get("sl"), "name": row.get("name"), "uan": row.get("uan"), "account": row.get("account"),
                 "gross": _s(row.get("gross")), "pt": _s(row.get("pt")), "ndp": _s(row.get("ndp"))}
        if user:
            matched.append({**entry, "user_id": user["user_id"], "matched_name": user.get("name"), "match": how})
        else:
            unmatched.append(entry)
    return matched, unmatched


def strip_key(value) -> str:
    from payroll_calc import strip_hidden
    return strip_hidden(value)


def _s(value):
    return None if value is None else str(value)


@router.post("/api/payroll/import/preview")
async def import_preview(payload: ImportPreviewIn, request: Request):
    branch = await _branch(payload.branch_id)
    parsed = parse_workbook(_decode_file(payload.file_b64), payload.sheets)
    users = await _db().users.find({"site": branch["name"]}, {"_id": 0, "user_id": 1, "name": 1}).to_list(5000)
    profiles = {p["user_id"]: p for p in await _db().employee_profiles.find(
        {"user_id": {"$in": [u["user_id"] for u in users]}}, {"_id": 0}).to_list(5000)}
    settings = (await _settings_for(payload.branch_id, "2026-10"))["settings"]
    sheets = []
    for sheet in parsed["sheets"]:
        matched, unmatched = _match_rows(sheet["rows"], users, profiles)
        for row in sheet["rows"]:
            gross = row.get("gross")
            if gross is not None:
                row["rule_pt"] = str(professional_tax(gross, gross, settings, month=int((sheet.get("month") or "2026-10").split("-")[1])))
                row["sheet_pt"] = _s(row.get("pt"))
        sheets.append({
            "sheet": sheet["sheet"], "title": sheet["title"], "month": sheet["month"],
            "matched": matched, "unmatched": unmatched, "row_count": len(sheet["rows"]),
            "summary": compare_totals(sheet["rows"], sheet.get("sheet_totals")),
            "rows": [{**{k: _s(v) if k not in ("sl", "name", "uan", "account", "formulas") else v for k, v in row.items()}} for row in sheet["rows"]],
        })
    return {"sheets": sheets}


@router.post("/api/payroll/import/commit")
async def import_commit(payload: ImportCommitIn, request: Request):
    _month_parts(payload.month)
    branch = await _branch(payload.branch_id)
    if await _db().payroll_runs.find_one({"branch_id": payload.branch_id, "month": payload.month}):
        raise HTTPException(status_code=409, detail="This month already has a payroll run and history is never deleted")
    parsed = parse_workbook(_decode_file(payload.file_b64), [payload.sheet])
    sheet = parsed["sheets"][0] if parsed["sheets"] else None
    if not sheet:
        raise HTTPException(status_code=400, detail="Sheet not found")
    if sheet.get("month") and sheet["month"] != payload.month:
        raise HTTPException(status_code=400, detail="That sheet does not match the selected month")
    by_sl = {str(row.get("sl")): row for row in sheet["rows"]}
    run = {
        "run_id": _id("prun"), "branch_id": payload.branch_id, "branch_name": branch["name"],
        "display_name": branch["name"], "month": payload.month, "status": "published", "version": 1,
        "imported": True, "superseded": False, "settings": default_settings(), "template_version": 0,
        "created_at": _now(), "created_by": request.state.user["user_id"], "published_at": _now(),
    }
    lines = []
    for match in payload.matches:
        if match.action == "skip":
            continue
        row = by_sl.get(str(match.sl))
        if not row:
            continue
        user_id = match.user_id
        if match.action == "create":
            user_id = await _create_imported_employee(row, branch, request.state.user)
        elif not user_id:
            raise HTTPException(status_code=400, detail=f"Choose an employee for SL {match.sl}")
        snap = _imported_snapshot(row, branch, user_id)
        user = await _db().users.find_one({"user_id": user_id}, {"_id": 0, "name": 1})
        lines.append({
            "line_id": _id("pline"), "run_id": run["run_id"], "user_id": user_id, "branch_id": payload.branch_id,
            "month": payload.month, "version": 1, "status": "published", "superseded": False, "imported": True,
            "employee_name": (user or {}).get("name") or row.get("name"), "enc": encrypt_json(snap),
        })
    await _db().payroll_runs.insert_one(dict(run))
    if lines:
        await _db().payroll_lines.insert_many(lines)
    summary = compare_totals(sheet["rows"], sheet.get("sheet_totals"))
    await _log(request.state.user, "payroll_imported", branch["name"],
               f"Imported {month_label(payload.month)} from {payload.sheet} ({len(lines)} employees, values kept as on the sheet)")
    run.pop("_id", None)
    return {"run": {k: v for k, v in run.items() if k != "settings"}, "summary": summary, "lines": len(lines)}


async def _create_imported_employee(row: dict, branch: dict, actor: dict) -> str:
    user_id = _id("user")
    email = f"import_{uuid.uuid4().hex[:10]}@imported.kelasa.local"
    await _db().users.insert_one({
        "user_id": user_id, "email": email, "name": row.get("name") or "Imported employee", "picture": None,
        "role": "employee", "site": branch["name"], "pending_invite": True, "face_enrolled": False,
        "created_at": _now(), "timezone": "Asia/Kolkata", "weekly_off": [6],
    })
    bank = None
    if row.get("account"):
        bank = {"account_holder": row.get("name") or "", "account_number": row.get("account"), "ifsc": "", "bank_name": None}
    await _db().employee_profiles.insert_one({
        "user_id": user_id, "uan": row.get("uan") or None, "bank": bank, "updated_at": _now(),
    })
    await _log(actor, "employee_added", row.get("name") or user_id, "Created from a salary-sheet import")
    return user_id


def _imported_snapshot(row: dict, branch: dict, user_id: str) -> dict:
    def money(key):
        value = row.get(key)
        return "0" if value is None else str(value)
    earnings = {code: money(code) for code in ("BASIC", "HRA", "TA") if row.get(code) is not None}
    ded = D(row.get("ded_add") or 0)
    adjustments = []
    if ded != 0:
        adjustments.append({
            "type": "addition" if ded > 0 else "deduction",
            "amount": str(abs(ded)), "label": "Imported", "category": "Other",
        })
    result = {
        "nwd": money("nwd"), "ndp": money("ndp"), "earnings": earnings, "fixed": dict(earnings),
        "gross": money("gross"), "e_esi": money("e_esi"), "e_esi_r": money("e_esi_r"),
        "esi": money("esi"), "esi_r": money("esi_r"), "e_pf": money("e_pf"), "e_pf_r": money("e_pf_r"),
        "pf": money("pf"), "pf_r": money("pf_r"), "pt": money("pt"), "ded_add": money("ded_add"),
        "final": money("final"), "atc": money("atc"), "ctc": money("ctc"),
        "adjustments": adjustments, "overridden": [], "deduct_pf_esi": False, "deduct_pt": False,
        "esi_applicable": True, "pf_applicable": True, "pt_override": "branch",
    }
    employee = {"name": row.get("name"), "branch_name": branch["name"], "uan": row.get("uan"),
                "account_number": row.get("account"), "employee_code": row.get("sl")}
    return {"inputs": {"adjustments": adjustments}, "result": result, "employee": employee,
            "attendance": {"lop": str(D(result["nwd"]) - D(result["ndp"]))}, "warnings": [],
            "component_labels": {"BASIC": "Basic", "HRA": "HRA", "TA": "Travel Allowance (TA)"}, "imported": True}


@router.post("/api/payroll/import/structures")
async def import_structures(payload: StructuresFromSheetIn, request: Request):
    branch = await _branch(payload.branch_id)
    parsed = parse_workbook(_decode_file(payload.file_b64), [payload.sheet])
    sheet = parsed["sheets"][0]
    built = {str(row["sl"]): row for row in structures_from_sheet(sheet)}
    created = []
    for match in payload.matches:
        if match.action == "skip" or not match.user_id:
            continue
        row = built.get(str(match.sl))
        if not row:
            continue
        saved = await save_structure(StructureIn(
            user_id=match.user_id, branch_id=payload.branch_id, effective_from=payload.effective_from,
            fixed=row["fixed"], esi_applicable=row["esi_applicable"], pf_applicable=True, pt_override="branch",
        ), request)
        created.append(saved["structure_id"])
    await _log(request.state.user, "salary_structures_imported", branch["name"],
               f"Created {len(created)} salary structures from {payload.sheet}. PT uses the branch rule.")
    return {"created": created}


@router.get("/api/payroll/queries")
async def list_queries(request: Request):
    docs = await _db().payslip_queries.find({}, {"_id": 0}).sort("created_at", -1).to_list(200)
    return {"queries": [_query_view(doc) for doc in docs]}


@router.post("/api/payroll/queries/{query_id}/reply")
async def reply_query(query_id: str, payload: ReplyIn, request: Request):
    doc = await _db().payslip_queries.find_one({"query_id": query_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Query not found")
    body = decrypt_json(doc.get("enc") or "")
    body["reply"] = payload.message.strip()
    body["replied_at"] = _now()
    body["replied_by"] = request.state.user.get("name")
    await _db().payslip_queries.update_one({"query_id": query_id}, {"$set": {"enc": encrypt_json(body), "status": "replied"}})
    await _log(request.state.user, "payslip_query_replied", body.get("employee_name") or "", f"Replied to a payslip query for {body.get('month')}")
    doc["enc"] = encrypt_json(body)
    doc["status"] = "replied"
    return _query_view(doc)


def _query_view(doc: dict) -> dict:
    body = decrypt_json(doc.get("enc") or "")
    return {"query_id": doc.get("query_id"), "user_id": doc.get("user_id"), "line_id": doc.get("line_id"),
            "status": doc.get("status"), "created_at": doc.get("created_at"), **body}


@router.get("/api/me/payslips")
async def my_payslips(request: Request):
    user = request.state.user
    if user.get("role") != "employee" and user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Payroll is limited to administrators")
    docs = await _db().payroll_lines.find(
        {"user_id": user["user_id"], "status": "published"}, {"_id": 0}
    ).sort([("month", -1), ("version", -1)]).to_list(200)
    return {"payslips": [_employee_payslip(doc) for doc in docs], "structure": await _own_structure(user["user_id"])}


def _employee_payslip(doc: dict) -> dict:
    line = authorize_payslip({"role": "employee", "user_id": doc["user_id"]}, {**doc, "user_id": doc["user_id"], "status": doc.get("status")})
    view = _line_view(doc)
    return {k: view.get(k) for k in ("line_id", "month", "ndp", "atc", "version", "superseded", "imported", "gross")}


async def _own_structure(user_id: str) -> Optional[dict]:
    today = datetime.now(IST).date().isoformat()
    structure = await _latest_structure(user_id, today)
    if not structure:
        return None
    return {"effective_from": structure.get("effective_from"), "fixed": structure.get("fixed"),
            "monthly_ctc": structure.get("monthly_ctc"), "esi_applicable": structure.get("esi_applicable"),
            "pf_applicable": structure.get("pf_applicable")}


@router.get("/api/me/salary-structure")
async def my_structure(request: Request):
    return {"structure": await _own_structure(request.state.user["user_id"])}


@router.get("/api/me/payslips/{line_id}")
async def my_payslip(line_id: str, request: Request):
    doc = await _owned_published(line_id, request.state.user)
    return _line_view(doc)


@router.get("/api/me/payslips/{line_id}.pdf")
async def my_payslip_pdf(line_id: str, request: Request):
    doc = await _owned_published(line_id, request.state.user)
    run = await _run(doc["run_id"])
    line = _line_view(doc)
    pdf = await _render_line_pdf(run, line)
    return Response(content=pdf, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{_pdf_name(line)}"'})


@router.get("/api/me/payslips/financial-year/{fy}.zip")
async def my_year_zip(fy: str, request: Request):
    try:
        start = int(fy)
    except ValueError:
        raise HTTPException(status_code=400, detail="Use the financial year start, such as 2026") from None
    months = []
    y, m = start, 4
    for _ in range(12):
        months.append(f"{y:04d}-{m:02d}")
        m += 1
        if m == 13:
            y, m = y + 1, 1
    user = request.state.user
    docs = await _db().payroll_lines.find(
        {"user_id": user["user_id"], "status": "published", "month": {"$in": months}, "superseded": {"$ne": True}},
        {"_id": 0},
    ).to_list(24)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
        for doc in docs:
            run = await _run(doc["run_id"])
            line = _line_view(doc)
            archive.writestr(_pdf_name(line), await _render_line_pdf(run, line))
    filename = f"payslips_{fy}-{fy + 1}.zip"
    return Response(content=buf.getvalue(), media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.post("/api/me/payslips/{line_id}/query")
async def raise_query(line_id: str, payload: QueryIn, request: Request):
    message = payload.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="Write a message")
    doc = await _owned_published(line_id, request.state.user)
    line = _line_view(doc)
    body = {"message": message, "month": doc.get("month"), "employee_name": line.get("name"), "reply": None}
    stored = {"query_id": _id("pqry"), "user_id": request.state.user["user_id"], "line_id": line_id,
              "status": "open", "created_at": _now(), "enc": encrypt_json(body)}
    await _db().payslip_queries.insert_one(stored)
    await _log(request.state.user, "payslip_query", line.get("name") or "", f"Raised a query on the {month_label(doc['month'])} payslip")
    return {"ok": True, "query_id": stored["query_id"]}


async def _owned_published(line_id: str, actor: dict) -> dict:
    doc = await _db().payroll_lines.find_one({"line_id": line_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Payslip not found")
    authorize_payslip(actor, doc)
    return doc


# Imported by configure() callers that want the default template next to settings.
def default_template_settings():
    return default_template()
