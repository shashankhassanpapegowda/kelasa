"""Import historical salary sheets. Values are kept as typed; they are not recalculated.

Older sheets head the third earning 'SA'. That column is Travel Allowance (TA).
"""
from __future__ import annotations

import io
import re
from decimal import Decimal, InvalidOperation
from typing import Optional

from openpyxl import load_workbook

from payroll_calc import D, ZERO, fixed_from_formula, fixed_from_values, q2, strip_hidden

MONTHS = {
    "JANUARY": 1, "FEBRUARY": 2, "MARCH": 3, "APRIL": 4, "MAY": 5, "JUNE": 6,
    "JULY": 7, "AUGUST": 8, "SEPTEMBER": 9, "SEPTEMEBER": 9, "OCTOBER": 10,
    "NOVEMBER": 11, "DECEMBER": 12,
}
HEADER_MAP = {
    "SL NO": "sl", "SL": "sl", "SL.NO": "sl", "SL. NO": "sl",
    "NAME": "name", "EMPLOYEE NAME": "name",
    "A/C NO": "account", "A/C NO.": "account", "AC NO": "account", "ACCOUNT NO": "account", "ACCOUNT NUMBER": "account",
    "UAN": "uan",
    "NWD": "nwd", "NDP": "ndp",
    "BASIC": "BASIC", "HRA": "HRA", "TA": "TA", "SA": "TA",
    "GROSS": "gross",
    "(E)ESI": "e_esi", "(E)ESI R": "e_esi_r", "ESI": "esi", "ESI R": "esi_r",
    "E(PF)": "e_pf", "E(PF) R": "e_pf_r", "PF": "pf", "PF (R)": "pf_r", "PF(R)": "pf_r",
    "PT": "pt", "DED/ADD": "ded_add", "FINAL PAY": "final", "ATC": "atc", "CTC": "ctc",
    "NET SALARY": "net_salary",
}


def _header_key(value) -> Optional[str]:
    if value is None:
        return None
    text = strip_hidden(value).upper()
    text = re.sub(r"\s+", " ", text)
    return HEADER_MAP.get(text)


def detect_month(sheet_name: str, title: str = "") -> Optional[str]:
    for source in (sheet_name or "", title or ""):
        text = strip_hidden(source).upper()
        for name, month in MONTHS.items():
            if name in text:
                year = _year_in(text)
                if year:
                    return f"{year:04d}-{month:02d}"
    return None


def _year_in(text: str) -> Optional[int]:
    match = re.search(r"(20\d{2})", text)
    if match:
        return int(match.group(1))
    match = re.search(r"\b(\d{2})\b", text)
    if match:
        yy = int(match.group(1))
        if yy <= 40:
            return 2000 + yy
    return None


def _number(value):
    if value is None or value == "":
        return None
    if isinstance(value, str):
        text = strip_hidden(value).replace(",", "")
        if text.startswith("="):
            return None
        if text == "":
            return None
        try:
            return q2(D(text))
        except (InvalidOperation, ValueError):
            return None
    try:
        return q2(D(value))
    except (InvalidOperation, ValueError):
        return None


def parse_workbook(data: bytes, sheet_names: Optional[list] = None) -> dict:
    wb = load_workbook(io.BytesIO(data), data_only=False)
    chosen = sheet_names or wb.sheetnames
    sheets = []
    for name in chosen:
        if name not in wb.sheetnames:
            continue
        sheets.append(_parse_sheet(wb[name]))
    return {"sheets": sheets}


def _parse_sheet(ws) -> dict:
    title = strip_hidden(ws.cell(1, 1).value)
    header_row = None
    columns = {}
    for row in range(1, min(ws.max_row or 1, 15) + 1):
        keys = {}
        for col in range(1, (ws.max_column or 1) + 1):
            key = _header_key(ws.cell(row, col).value)
            if key and key not in keys:
                keys[key] = col
        if "sl" in keys and "name" in keys:
            header_row = row
            columns = keys
            break
    month = detect_month(ws.title, title)
    rows = []
    sheet_totals = None
    if header_row:
        for row in range(header_row + 1, (ws.max_row or header_row) + 1):
            sl = ws.cell(row, columns["sl"]).value
            name = ws.cell(row, columns["name"]).value if "name" in columns else ""
            if strip_hidden(sl) == "" or "TOTAL" in strip_hidden(name).upper():
                if "TOTAL" in strip_hidden(name).upper():
                    sheet_totals = _read_row(ws, row, columns)
                break
            parsed = _read_row(ws, row, columns)
            parsed["sl"] = strip_hidden(sl)
            parsed["name"] = strip_hidden(name)
            parsed["account"] = strip_hidden(parsed.get("account"))
            parsed["uan"] = strip_hidden(parsed.get("uan"))
            parsed["formulas"] = _formulas(ws, row, columns)
            rows.append(parsed)
    return {
        "sheet": ws.title,
        "title": title,
        "month": month,
        "header_row": header_row,
        "rows": rows,
        "sheet_totals": sheet_totals,
        "sa_mapped_to_ta": "TA" in columns,
    }


def _read_row(ws, row, columns) -> dict:
    out = {}
    for key, col in columns.items():
        if key in ("sl", "name"):
            continue
        value = ws.cell(row, col).value
        if key in ("account", "uan"):
            out[key] = strip_hidden(value)
        else:
            out[key] = _number(value)
    return out


def _formulas(ws, row, columns) -> dict:
    found = {}
    for code in ("BASIC", "HRA", "TA"):
        col = columns.get(code)
        if not col:
            continue
        value = ws.cell(row, col).value
        if isinstance(value, str) and value.startswith("="):
            found[code] = value
    return found


def structures_from_sheet(sheet: dict) -> list:
    """Fixed BASIC / HRA / TA from October-style formulas. PT is not copied."""
    structures = []
    for row in sheet.get("rows") or []:
        nwd = row.get("nwd") or D(0)
        ndp = row.get("ndp") or D(0)
        fixed = {}
        for code in ("BASIC", "HRA", "TA"):
            formula = (row.get("formulas") or {}).get(code)
            amount = fixed_from_formula(formula) if formula else None
            if amount is None and row.get(code) is not None and ndp:
                amount = fixed_from_values(row[code], nwd, ndp)
            if amount is not None:
                fixed[code] = amount
        esi_raw = row.get("e_esi")
        structures.append({
            "sl": row.get("sl"),
            "name": row.get("name"),
            "uan": row.get("uan"),
            "account": row.get("account"),
            "fixed": {k: str(q2(v)) for k, v in fixed.items()},
            "esi_applicable": not (esi_raw is None or esi_raw == 0 or esi_raw == ZERO),
            "pf_applicable": True,
            "pt_override": "branch",
        })
    return structures


def compare_totals(parsed_rows: list, sheet_totals: Optional[dict]) -> dict:
    keys = ["gross", "e_esi_r", "esi_r", "e_pf_r", "pf_r", "pt", "ded_add", "final", "atc", "ctc", "BASIC", "HRA", "TA"]
    summed = {key: ZERO for key in keys}
    for row in parsed_rows:
        for key in keys:
            if row.get(key) is not None:
                summed[key] += D(row[key])
    diffs = {}
    if sheet_totals:
        for key in keys:
            if sheet_totals.get(key) is not None:
                diffs[key] = {"sheet": str(D(sheet_totals[key])), "imported": str(summed[key]),
                              "matches": D(sheet_totals[key]) == summed[key]}
    return {"imported": {k: str(v) for k, v in summed.items()}, "comparison": diffs}
