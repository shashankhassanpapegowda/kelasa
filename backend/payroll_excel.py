"""Salary register and statutory workbooks. Formulas recalculate under the branch rules."""
from __future__ import annotations

import io
from decimal import Decimal
from typing import Optional

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from payroll_calc import D, default_register_columns, mask_account, month_label, normalize_settings

THIN = Border(
    left=Side(style="thin", color="BFBFBF"), right=Side(style="thin", color="BFBFBF"),
    top=Side(style="thin", color="BFBFBF"), bottom=Side(style="thin", color="BFBFBF"),
)
HEADER_FILL = PatternFill("solid", fgColor="0D0D12")
TOTAL_FILL = PatternFill("solid", fgColor="F5F5F6")


def _num(value):
    if isinstance(value, Decimal):
        return float(value) if value != value.to_integral_value() else int(value)
    return value


def register_workbook(lines: list, settings: dict, *, branch_name: str, year_month: str,
                      formulas: bool = True) -> bytes:
    settings = normalize_settings(settings)
    columns = settings.get("register_columns") or default_register_columns(settings["earning_components"])
    wb = Workbook()
    ws = wb.active
    ws.title = month_label(year_month)[:31]
    title = f"{(branch_name or settings['profile'].get('display_name') or 'BRANCH').upper()} SALARY LIST {month_label(year_month).upper()}"
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(columns))
    cell = ws.cell(1, 1, title)
    cell.font = Font(bold=True, size=14, color="0D0D12")
    cell.alignment = Alignment(horizontal="left", vertical="center")
    ws.row_dimensions[1].height = 24
    for index, col in enumerate(columns, 1):
        header = ws.cell(2, index, col["label"])
        header.font = Font(bold=True, color="FFFFFF", size=9)
        header.fill = HEADER_FILL
        header.alignment = Alignment(horizontal="center")
        header.border = THIN
        ws.column_dimensions[get_column_letter(index)].width = max(12, len(col["label"]) + 2)

    key_col = {col["key"]: index for index, col in enumerate(columns, 1)}
    first_data = 3
    for offset, line in enumerate(lines):
        row = first_data + offset
        _write_line(ws, row, line, columns, key_col, settings, formulas, serial=offset + 1)
    if lines:
        total_row = first_data + len(lines)
        _write_totals(ws, total_row, columns, key_col, first_data, total_row - 1)
    ws.freeze_panes = "C3"
    ws.auto_filter.ref = f"A2:{get_column_letter(len(columns))}{max(2, first_data + len(lines))}"
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToPage = True
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.oddHeader.left.text = title
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def _earning_codes(columns: list) -> list:
    return [col["key"].split(":", 1)[1] for col in columns if col["key"].startswith("earn:")]


def _formula_for(key: str, row: int, line: dict, key_col: dict, settings: dict, codes: list) -> Optional[str]:
    def ref(name):
        idx = key_col.get(name)
        return f"{get_column_letter(idx)}{row}" if idx else None

    nwd, ndp = ref("nwd"), ref("ndp")
    if key.startswith("earn:"):
        code = key.split(":", 1)[1]
        fixed = (line.get("fixed") or {}).get(code, 0)
        comp = next((c for c in settings["earning_components"] if c["code"] == code), None)
        if comp and not comp.get("prorate", True):
            return str(D(fixed))
        return f"={D(fixed)}/{nwd}*{ndp}"
    if key == "gross":
        refs = [ref(f"earn:{code}") for code in codes]
        refs = [r for r in refs if r]
        return "=" + "+".join(refs) if refs else "=0"
    gross = ref("gross")
    esi = settings["esi"]
    pf = settings["pf"]
    basic_ref = ref("earn:BASIC") or gross
    if key == "e_esi":
        return _rate_formula(line, "esi", basic_ref, gross, esi, esi.get("employer_rate"), rounded=False)
    if key == "e_esi_r":
        return _rate_formula(line, "esi", basic_ref, gross, esi, esi.get("employer_rate"), rounded=True)
    if key == "esi":
        return _rate_formula(line, "esi", basic_ref, gross, esi, esi.get("employee_rate"), rounded=False)
    if key == "esi_r":
        return _rate_formula(line, "esi", basic_ref, gross, esi, esi.get("employee_rate"), rounded=True)
    if key == "e_pf":
        return _rate_formula(line, "pf", basic_ref, gross, pf, pf.get("employer_rate"), rounded=False)
    if key == "e_pf_r":
        return _rate_formula(line, "pf", basic_ref, gross, pf, pf.get("employer_rate"), rounded=True)
    if key == "pf":
        return _rate_formula(line, "pf", basic_ref, gross, pf, pf.get("employee_rate"), rounded=False)
    if key == "pf_r":
        return _rate_formula(line, "pf", basic_ref, gross, pf, pf.get("employee_rate"), rounded=True)
    if key == "pt":
        override = (line.get("pt_override") or "branch").lower()
        if override == "none":
            return "=0"
        if override == "fixed":
            return f"={D(line.get('pt_amount') or line.get('pt') or 0)}"
        pt = settings["pt"]
        if pt.get("mode") == "slabs":
            return f"={D(line.get('pt') or 0)}"
        base = gross
        return f'=IF({base}>={D(pt.get("threshold") or 0)},{D(pt.get("amount") or 0)},0)'
    if key == "final":
        parts = [gross, ref("ded_add")]
        expr = "+".join(p for p in parts if p)
        if line.get("deduct_pf_esi"):
            expr += f"-{ref('pf_r')}-{ref('esi_r')}"
        if line.get("deduct_pt"):
            expr += f"-{ref('pt')}"
        return f"={expr}"
    if key == "atc":
        final = ref("final")
        mode = (settings.get("final_rounding") or "roundup").lower()
        if mode == "none":
            return f"={final}"
        if mode in ("down", "rounddown"):
            return f"=ROUNDDOWN({final},0)"
        if mode in ("nearest", "round"):
            return f"=ROUND({final},0)"
        return f"=ROUNDUP({final},0)"
    if key == "ctc":
        bits = [gross, ref("e_esi_r"), ref("esi_r"), ref("e_pf_r"), ref("pf_r"), ref("pt")]
        return "=" + "+".join(b for b in bits if b)
    return None


def _rate_formula(line, kind, basic_ref, gross_ref, cfg, rate, rounded: bool) -> str:
    applicable = line.get("esi_applicable") if kind == "esi" else line.get("pf_applicable")
    if kind == "esi" and line.get("esi_charged") is False and not cfg.get("gross_limit_enabled"):
        applicable = False
    if kind == "pf" and line.get("pf_charged") is False and not cfg.get("ceiling_enabled"):
        applicable = False
    if applicable is False:
        return "=0"
    base = gross_ref if (cfg.get("base") or "basic") == "gross" else basic_ref
    body = f"{base}*{D(rate or 0)}"
    if kind == "pf" and cfg.get("ceiling_enabled"):
        body = f"MIN({base},{D(cfg.get('ceiling') or 0)})*{D(rate or 0)}"
    if kind == "esi" and cfg.get("gross_limit_enabled"):
        inner = f"IF({gross_ref}>{D(cfg.get('gross_limit') or 0)},0,{body})"
    else:
        inner = body
    mode = (cfg.get("rounding") or "roundup").lower()
    if not rounded or mode == "none":
        return f"={inner}"
    fn = {"roundup": "ROUNDUP", "down": "ROUNDDOWN", "rounddown": "ROUNDDOWN", "nearest": "ROUND", "round": "ROUND"}.get(mode, "ROUNDUP")
    return f"={fn}({inner},0)"


def _cell_value(key: str, line: dict, serial: int):
    if key == "sl":
        return serial
    if key == "name":
        return line.get("name") or ""
    if key == "account":
        raw = line.get("account_number") or ""
        if raw and "X" not in str(raw):
            return mask_account(raw)
        return line.get("account_masked") or mask_account(raw)
    if key == "uan":
        return line.get("uan") or ""
    if key.startswith("earn:"):
        return _num((line.get("earnings") or {}).get(key.split(":", 1)[1], 0))
    mapping = {
        "nwd": "nwd", "ndp": "ndp", "gross": "gross", "e_esi": "e_esi", "e_esi_r": "e_esi_r",
        "esi": "esi", "esi_r": "esi_r", "e_pf": "e_pf", "e_pf_r": "e_pf_r", "pf": "pf",
        "pf_r": "pf_r", "pt": "pt", "ded_add": "ded_add", "final": "final", "atc": "atc", "ctc": "ctc",
    }
    if key in mapping:
        return _num(line.get(mapping[key], 0))
    return ""


def _write_line(ws, row, line, columns, key_col, settings, formulas, serial):
    codes = _earning_codes(columns)
    for index, col in enumerate(columns, 1):
        key = col["key"]
        formula = _formula_for(key, row, line, key_col, settings, codes) if formulas else None
        value = formula if formula else _cell_value(key, line, serial)
        cell = ws.cell(row, index, value)
        cell.border = THIN
        cell.font = Font(name="Calibri", size=10)
        if key in ("nwd", "ndp") or key.startswith("earn:") or key in ("gross", "e_esi", "esi", "e_pf", "pf", "ded_add", "final", "ctc"):
            cell.number_format = "0.00"
        elif key in ("e_esi_r", "esi_r", "e_pf_r", "pf_r", "pt", "atc", "sl"):
            cell.number_format = "0"


def _write_totals(ws, row, columns, key_col, start, end):
    numeric = {"nwd", "ndp", "gross", "e_esi", "e_esi_r", "esi", "esi_r", "e_pf", "e_pf_r",
               "pf", "pf_r", "pt", "ded_add", "final", "atc", "ctc"}
    for index, col in enumerate(columns, 1):
        key = col["key"]
        if key == "name":
            value = "TOTAL"
        elif key in numeric or key.startswith("earn:"):
            letter = get_column_letter(index)
            value = f"=SUM({letter}{start}:{letter}{end})"
        else:
            value = ""
        cell = ws.cell(row, index, value)
        cell.font = Font(bold=True, size=10)
        cell.fill = TOTAL_FILL
        cell.border = THIN
        cell.number_format = "0.00"


def bank_rows(lines: list, settings: dict) -> tuple:
    settings = normalize_settings(settings)
    columns = settings.get("bank_columns") or default_settings_bank()
    header = [c["label"] for c in columns]
    rows = []
    for line in lines:
        full = {
            "name": line.get("name") or "",
            "account_number": line.get("account_number") or "",
            "ifsc": line.get("ifsc") or "",
            "bank_name": line.get("bank_name") or "",
            "atc": _num(line.get("atc") or 0),
        }
        rows.append([full.get(c["key"], "") for c in columns])
    return header, rows


def default_settings_bank():
    return normalize_settings(None)["bank_columns"]


def adjustment_rows(lines: list) -> tuple:
    header = ["Employee code", "Name", "Month", "Type", "Category", "Amount", "Reason"]
    rows = []
    for line in lines:
        for entry in line.get("adjustments") or []:
            rows.append([
                line.get("employee_code") or "", line.get("name") or "", line.get("month") or "",
                entry.get("type") or "", entry.get("category") or "", _num(D(entry.get("amount") or 0)),
                entry.get("label") or entry.get("reason") or "",
            ])
    return header, rows
