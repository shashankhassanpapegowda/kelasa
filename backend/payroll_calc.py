"""Payroll arithmetic for Kelasa.

Money is decimal, never float. Unrounded amounts and rupee-rounded amounts are
kept separately, matching the salary register. ROUNDUP ceilings to the next
rupee after rounding to 6 decimal places, so binary dust such as 720.0000001
does not become 721.
"""
from __future__ import annotations

import calendar
from copy import deepcopy
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP, ROUND_UP
from typing import Iterable, Optional

TWOPLACES = Decimal("0.01")
SIXPLACES = Decimal("0.000001")
ZERO = Decimal("0")
ONE = Decimal("1")

MONTHS = ["January", "February", "March", "April", "May", "June",
          "July", "August", "September", "October", "November", "December"]

_ONES = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine",
         "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen",
         "Seventeen", "Eighteen", "Nineteen"]
_TENS = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]


def freeze(value):
    """JSON-safe money: decimals become strings so paise survive a round trip."""
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, dict):
        return {str(key): freeze(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [freeze(item) for item in value]
    return value


def D(value) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if value is None or value == "":
        return ZERO
    return Decimal(str(value))


def q2(value) -> Decimal:
    return D(value).quantize(TWOPLACES, rounding=ROUND_HALF_UP)


def round_rupee(amount, mode: str = "roundup") -> Decimal:
    """Rupee rounding. `roundup` matches the sheet's ROUNDUP after a 6-decimal guard."""
    amount = D(amount)
    mode = (mode or "roundup").lower()
    if mode == "none":
        return q2(amount)
    dust = amount.quantize(SIXPLACES, rounding=ROUND_HALF_UP)
    if mode == "roundup":
        return dust.to_integral_value(rounding=ROUND_UP)
    if mode in ("down", "rounddown"):
        return dust.to_integral_value(rounding=ROUND_DOWN)
    if mode in ("nearest", "round"):
        return dust.to_integral_value(rounding=ROUND_HALF_UP)
    raise ValueError(f"Unknown rounding mode {mode}")


def days_in_month(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]


def month_label(year_month: str) -> str:
    year, month = year_month.split("-")
    return f"{MONTHS[int(month) - 1]} {year}"


def financial_year(year_month: str) -> str:
    year, month = (int(p) for p in year_month.split("-"))
    start = year if month >= 4 else year - 1
    return f"{start}-{str(start + 1)[-2:]}"


def fy_months(year_month: str) -> tuple:
    """Inclusive financial-year window (April–March) up to and including year_month."""
    year, month = (int(p) for p in year_month.split("-"))
    start_year = year if month >= 4 else year - 1
    months = []
    y, m = start_year, 4
    while (y, m) <= (year, month):
        months.append(f"{y:04d}-{m:02d}")
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return tuple(months)


def default_components() -> list:
    return [
        {"code": "BASIC", "name": "Basic", "payslip_label": "Basic", "show_on_payslip": True,
         "prorate": True, "esi_base": True, "pf_base": True},
        {"code": "HRA", "name": "HRA", "payslip_label": "HRA", "show_on_payslip": True,
         "prorate": True, "esi_base": False, "pf_base": False},
        {"code": "TA", "name": "Travel Allowance", "payslip_label": "Travel Allowance (TA)",
         "show_on_payslip": True, "prorate": True, "esi_base": False, "pf_base": False},
    ]


def default_register_columns(components: Optional[list] = None) -> list:
    components = components or default_components()
    cols = [
        {"key": "sl", "label": "SL NO"},
        {"key": "name", "label": "NAME"},
        {"key": "account", "label": "A/C NO"},
        {"key": "uan", "label": "UAN"},
        {"key": "nwd", "label": "NWD"},
        {"key": "ndp", "label": "NDP"},
    ]
    for comp in components:
        cols.append({"key": f"earn:{comp['code']}", "label": comp["code"]})
    cols.extend([
        {"key": "gross", "label": "GROSS"},
        {"key": "e_esi", "label": "(E)ESI"},
        {"key": "e_esi_r", "label": "(E)ESI R"},
        {"key": "esi", "label": "ESI"},
        {"key": "esi_r", "label": "ESI R"},
        {"key": "e_pf", "label": "E(PF)"},
        {"key": "e_pf_r", "label": "E(PF) R"},
        {"key": "pf", "label": "PF"},
        {"key": "pf_r", "label": "PF (R)"},
        {"key": "pt", "label": "PT"},
        {"key": "ded_add", "label": "DED/ADD"},
        {"key": "final", "label": "FINAL PAY"},
        {"key": "atc", "label": "ATC"},
        {"key": "ctc", "label": "CTC"},
    ])
    return cols


def default_settings() -> dict:
    components = default_components()
    return {
        "profile": {
            "legal_name": "",
            "display_name": "",
            "address": "",
            "pf_establishment_code": "",
            "esi_code": "",
            "pt_registration": "",
        },
        "earning_components": components,
        "esi": {
            "enabled": True,
            "employer_rate": "0.0325",
            "employee_rate": "0.0075",
            "base": "basic",
            "gross_limit_enabled": False,
            "gross_limit": "21000",
            "rounding": "roundup",
        },
        "pf": {
            "enabled": True,
            "employer_rate": "0.12",
            "employee_rate": "0.12",
            "base": "basic",
            "ceiling_enabled": False,
            "ceiling": "15000",
            "rounding": "roundup",
        },
        "pt": {
            "mode": "threshold",
            "threshold": "25000",
            "amount": "200",
            "prorate": False,
            "base": "gross",
            "slabs": [],
        },
        "bearer": {
            "employee_pf_esi_deducted": False,
            "pt_deducted": False,
        },
        "proration": "calendar",
        "final_rounding": "roundup",
        "ctc_builder": {"basic_pct": "0.50", "hra_pct_of_basic": "0.50"},
        "register_columns": None,
        "bank_columns": [
            {"key": "name", "label": "Name"},
            {"key": "account_number", "label": "Account Number"},
            {"key": "ifsc", "label": "IFSC"},
            {"key": "bank_name", "label": "Bank"},
            {"key": "atc", "label": "Amount"},
        ],
    }


def normalize_settings(settings: Optional[dict]) -> dict:
    base = default_settings()
    if not settings:
        return base
    incoming = deepcopy(settings)
    for key in ("profile", "esi", "pf", "pt", "bearer", "ctc_builder"):
        merged = dict(base[key])
        merged.update(incoming.get(key) or {})
        incoming[key] = merged
    incoming.setdefault("earning_components", base["earning_components"])
    incoming.setdefault("proration", base["proration"])
    incoming.setdefault("final_rounding", base["final_rounding"])
    incoming.setdefault("register_columns", None)
    incoming.setdefault("bank_columns", base["bank_columns"])
    if not incoming["earning_components"]:
        incoming["earning_components"] = base["earning_components"]
    return incoming


def nwd_for(year: int, month: int, settings: Optional[dict] = None, weekly_off: Optional[Iterable[int]] = None) -> Decimal:
    settings = normalize_settings(settings)
    mode = settings.get("proration") or "calendar"
    if mode == "fixed_30":
        return D(30)
    if mode == "working_days":
        offs = set(weekly_off or [])
        return D(sum(1 for day in range(1, days_in_month(year, month) + 1)
                     if calendar.date(year, month, day).weekday() not in offs))
    return D(days_in_month(year, month))


def net_adjustments(entries: Optional[list]) -> Decimal:
    total = ZERO
    for entry in entries or []:
        label = (entry.get("label") or entry.get("reason") or "").strip()
        if not label:
            raise ValueError("Each deduction or addition needs a reason")
        kind = entry.get("type")
        amount = abs(D(entry.get("amount")))
        if kind == "addition":
            total += amount
        elif kind == "deduction":
            total -= amount
        else:
            raise ValueError("Adjustment type must be deduction or addition")
    return total


def _component_base(components: list, exact: dict, flag: str, declared_base: str) -> Decimal:
    """ESI/PF base. 'basic' uses components flagged for that base (default BASIC only).
    'gross' uses every earning."""
    if (declared_base or "basic").lower() == "gross":
        return sum(exact.values(), ZERO)
    return sum((exact[c["code"]] for c in components if c.get(flag) and c["code"] in exact), ZERO)


def professional_tax(gross_month, fixed_gross, settings: dict, *, pt_override: str = "branch",
                     pt_amount=None, ndp=None, nwd=None, month: Optional[int] = None) -> Decimal:
    settings = normalize_settings(settings)
    override = (pt_override or "branch").lower()
    if override == "none":
        raw = ZERO
    elif override == "fixed":
        raw = D(pt_amount or 0)
    else:
        pt = settings["pt"]
        base_gross = D(fixed_gross) if (pt.get("base") == "fixed_gross") else D(gross_month)
        if pt.get("mode") == "slabs":
            raw = ZERO
            for slab in pt.get("slabs") or []:
                low = D(slab.get("from") or 0)
                high = slab.get("to")
                if base_gross >= low and (high is None or high == "" or base_gross <= D(high)):
                    if month == 2 and slab.get("february_amount") not in (None, ""):
                        raw = D(slab["february_amount"])
                    else:
                        raw = D(slab.get("amount") or 0)
                    break
        else:
            raw = D(pt.get("amount") or 0) if base_gross >= D(pt.get("threshold") or 0) else ZERO
    if settings["pt"].get("prorate") and nwd and D(nwd) != 0 and override != "none":
        raw = raw * D(ndp) / D(nwd)
    return q2(raw) if settings["pt"].get("prorate") else (raw if raw == raw.to_integral_value() else q2(raw))


def _contribution(base: Decimal, rate, rounding: str, enabled: bool) -> tuple:
    if not enabled or base == 0 or D(rate) == 0:
        return ZERO, ZERO
    raw = base * D(rate)
    return raw, round_rupee(raw, rounding)


def compute_line(*, fixed: dict, ndp, nwd, adjustments: Optional[list] = None,
                  esi_applicable: bool = True, pf_applicable: bool = True,
                  pt_override: str = "branch", pt_amount=None,
                  employee_share_deducted: Optional[bool] = None,
                  settings: Optional[dict] = None, month: Optional[int] = None,
                  ndp_overridden: bool = False) -> dict:
    """One employee's month. Earnings are prorated as fixed × NDP / NWD and not rupee-rounded."""
    settings = normalize_settings(settings)
    components = settings["earning_components"]
    nwd_d = D(nwd)
    ndp_d = D(ndp)
    if nwd_d <= 0:
        raise ValueError("NWD must be positive")
    exact = {}
    display = {}
    fixed_display = {}
    for comp in components:
        code = comp["code"]
        monthly = D(fixed.get(code, 0))
        fixed_display[code] = q2(monthly)
        amount = monthly if not comp.get("prorate", True) else (monthly * ndp_d / nwd_d)
        exact[code] = amount
        display[code] = q2(amount)
    gross_exact = sum(exact.values(), ZERO)
    gross = q2(gross_exact)
    fixed_gross = q2(sum((D(fixed.get(c["code"], 0)) for c in components), ZERO))

    esi_cfg = settings["esi"]
    pf_cfg = settings["pf"]
    esi_on = bool(esi_cfg.get("enabled", True) and esi_applicable)
    if esi_on and esi_cfg.get("gross_limit_enabled") and gross_exact > D(esi_cfg.get("gross_limit") or 0):
        esi_on = False
    pf_on = bool(pf_cfg.get("enabled", True) and pf_applicable)

    esi_base_name = esi_cfg.get("base") or "basic"
    pf_base_name = pf_cfg.get("base") or "basic"
    # The default "basic" base is the sum of components flagged esi_base / pf_base
    # (only BASIC, unless an admin changes the flags). "gross" uses GROSS.
    if esi_base_name == "gross":
        esi_base = gross_exact
    else:
        esi_base = _component_base(components, exact, "esi_base", "basic")
    if pf_base_name == "gross":
        pf_base = gross_exact
    else:
        pf_base = _component_base(components, exact, "pf_base", "basic")
    if pf_on and pf_cfg.get("ceiling_enabled"):
        pf_base = min(pf_base, D(pf_cfg.get("ceiling") or 0))

    e_esi, e_esi_r = _contribution(esi_base, esi_cfg.get("employer_rate"), esi_cfg.get("rounding") or "roundup", esi_on)
    esi, esi_r = _contribution(esi_base, esi_cfg.get("employee_rate"), esi_cfg.get("rounding") or "roundup", esi_on)
    e_pf, e_pf_r = _contribution(pf_base, pf_cfg.get("employer_rate"), pf_cfg.get("rounding") or "roundup", pf_on)
    pf, pf_r = _contribution(pf_base, pf_cfg.get("employee_rate"), pf_cfg.get("rounding") or "roundup", pf_on)

    pt = professional_tax(gross_exact, fixed_gross, settings, pt_override=pt_override, pt_amount=pt_amount,
                          ndp=ndp_d, nwd=nwd_d, month=month)
    ded_add = net_adjustments(adjustments)
    bearer = settings["bearer"]
    deduct_pf_esi = bearer["employee_pf_esi_deducted"] if employee_share_deducted is None else bool(employee_share_deducted)
    # `_deduct_pt` is set by apply_employee_flags when an employee overrides the branch rule.
    deduct_pt = bool(settings["_deduct_pt"]) if "_deduct_pt" in settings else bool(bearer.get("pt_deducted"))
    final_exact = gross_exact + ded_add
    if deduct_pf_esi:
        final_exact -= (pf_r + esi_r)
    if deduct_pt:
        final_exact -= pt
    final = q2(final_exact)
    atc = round_rupee(final_exact, settings.get("final_rounding") or "roundup")
    ctc = q2(gross + e_esi_r + esi_r + e_pf_r + pf_r + pt)

    overridden = []
    if ndp_overridden:
        overridden.append("ndp")
    if (pt_override or "branch").lower() != "branch":
        overridden.append("pt")
    if not esi_applicable:
        overridden.append("esi")
    if not pf_applicable:
        overridden.append("pf")
    if employee_share_deducted is not None:
        overridden.append("bearer")

    return {
        "nwd": nwd_d,
        "ndp": ndp_d,
        "fixed": fixed_display,
        "earnings_exact": {k: str(v) for k, v in exact.items()},
        "earnings": display,
        "gross_exact": gross_exact,
        "gross": gross,
        "esi_base": q2(esi_base) if esi_on else ZERO,
        "pf_base": q2(pf_base) if pf_on else ZERO,
        "e_esi": e_esi,
        "e_esi_r": e_esi_r,
        "esi": esi,
        "esi_r": esi_r,
        "e_pf": e_pf,
        "e_pf_r": e_pf_r,
        "pf": pf,
        "pf_r": pf_r,
        "pt": pt,
        "ded_add": ded_add,
        "final_exact": final_exact,
        "final": final,
        "atc": atc,
        "ctc": ctc,
        "deduct_pf_esi": deduct_pf_esi,
        "deduct_pt": deduct_pt,
        "esi_applicable": bool(esi_applicable) and bool(esi_cfg.get("enabled", True)),
        "pf_applicable": bool(pf_applicable) and bool(pf_cfg.get("enabled", True)),
        "esi_charged": esi_on,
        "pf_charged": pf_on,
        "pt_override": (pt_override or "branch").lower(),
        "pt_amount": None if pt_amount is None else q2(pt_amount),
        "overridden": overridden,
        "adjustments": list(adjustments or []),
    }


def apply_employee_flags(settings: dict, *, pt_deducted: Optional[bool] = None) -> dict:
    """Return settings with the per-employee PT bearer applied, without mutating the branch copy."""
    out = deepcopy(normalize_settings(settings))
    if pt_deducted is not None:
        out["_deduct_pt"] = bool(pt_deducted)
    else:
        out["_deduct_pt"] = bool(out["bearer"].get("pt_deducted"))
    return out


def structure_from_ctc(ctc, *, esi_applicable: bool = True, settings: Optional[dict] = None,
                       month: Optional[int] = None) -> dict:
    """Basic 50% of CTC, HRA 50% of Basic, TA balances after rounded PF, ESI and PT.

    Provisional GROSS assumes PT is still inside the balancing pool (PT = 0). If that
    gross meets the branch rule, PT is applied and TA is reduced by the same amount.
    """
    settings = normalize_settings(settings)
    ctc_d = D(ctc)
    basic = q2(ctc_d * D(settings["ctc_builder"]["basic_pct"]))
    hra = q2(basic * D(settings["ctc_builder"]["hra_pct_of_basic"]))
    pf_cfg = settings["pf"]
    esi_cfg = settings["esi"]
    pf_on = bool(pf_cfg.get("enabled", True))
    esi_on = bool(esi_cfg.get("enabled", True) and esi_applicable)
    pf_er = round_rupee(basic * D(pf_cfg["employer_rate"]), pf_cfg.get("rounding") or "roundup") if pf_on else ZERO
    pf_ee = round_rupee(basic * D(pf_cfg["employee_rate"]), pf_cfg.get("rounding") or "roundup") if pf_on else ZERO
    if pf_on and pf_cfg.get("ceiling_enabled"):
        capped = min(basic, D(pf_cfg.get("ceiling") or 0))
        pf_er = round_rupee(capped * D(pf_cfg["employer_rate"]), pf_cfg.get("rounding") or "roundup")
        pf_ee = round_rupee(capped * D(pf_cfg["employee_rate"]), pf_cfg.get("rounding") or "roundup")
    esi_er = round_rupee(basic * D(esi_cfg["employer_rate"]), esi_cfg.get("rounding") or "roundup") if esi_on else ZERO
    esi_ee = round_rupee(basic * D(esi_cfg["employee_rate"]), esi_cfg.get("rounding") or "roundup") if esi_on else ZERO
    pool = ctc_d - basic - hra - pf_er - pf_ee - esi_er - esi_ee
    provisional_gross = basic + hra + pool
    pt = professional_tax(provisional_gross, provisional_gross, settings, month=month)
    # Gross-limit check uses the provisional gross. If ESI would not apply, rebuild without it.
    if esi_on and esi_cfg.get("gross_limit_enabled") and provisional_gross > D(esi_cfg.get("gross_limit") or 0):
        return structure_from_ctc(ctc, esi_applicable=False, settings=settings, month=month)
    ta = q2(pool - pt)
    return {
        "monthly_ctc": q2(ctc_d),
        "fixed": {"BASIC": basic, "HRA": hra, "TA": ta},
        "provisional_gross": q2(provisional_gross),
        "pt": pt,
        "pf_employer": pf_er,
        "pf_employee": pf_ee,
        "esi_employer": esi_er,
        "esi_employee": esi_ee,
        "esi_applicable": esi_applicable and not (esi_cfg.get("gross_limit_enabled") and provisional_gross > D(esi_cfg.get("gross_limit") or 0)),
    }


_TOTAL_KEYS = ("nwd", "ndp", "gross", "e_esi", "e_esi_r", "esi", "esi_r", "e_pf", "e_pf_r",
               "pf", "pf_r", "pt", "ded_add", "final", "atc", "ctc")


def sum_lines(lines: list, component_codes: Optional[Iterable[str]] = None) -> dict:
    """Totals row: the sum of every numeric column, using the values shown on the register."""
    codes = list(component_codes or [])
    if not codes and lines:
        codes = list((lines[0].get("earnings") or {}).keys())
    totals = {key: ZERO for key in _TOTAL_KEYS}
    totals["earnings"] = {code: ZERO for code in codes}
    totals["count"] = len(lines)
    for line in lines:
        for key in _TOTAL_KEYS:
            totals[key] += D(line.get(key) or 0)
        for code in codes:
            totals["earnings"][code] += D((line.get("earnings") or {}).get(code) or 0)
    return totals


def line_warnings(line: dict, *, previous_atc=None, has_bank: bool = True, has_uan: bool = True,
                  has_esi_number: bool = True, pf_on: bool = False, esi_on: bool = False) -> list:
    warnings = []
    if D(line.get("atc")) < 0:
        warnings.append("Amount to credit is negative")
    if D(line.get("ndp")) > D(line.get("nwd")):
        warnings.append("Days paid are higher than the days in the month")
    if not has_bank:
        warnings.append("Bank account is missing")
    if pf_on and not has_uan:
        warnings.append("UAN is missing while PF is on")
    if esi_on and not has_esi_number:
        warnings.append("ESI number is missing while ESI is on")
    for entry in line.get("adjustments") or []:
        if not (entry.get("label") or entry.get("reason") or "").strip():
            warnings.append("A deduction or addition has no reason")
            break
    if previous_atc not in (None, ""):
        prev = D(previous_atc)
        if prev > 0 and abs(D(line.get("atc")) - prev) / prev > D("0.20"):
            warnings.append("Amount to credit changed by more than 20% from last month")
    return warnings


def mask_account(number: Optional[str]) -> str:
    if not number:
        return ""
    digits = "".join(ch for ch in str(number) if ch.isdigit())
    if len(digits) <= 4:
        return digits
    return "X" * (len(digits) - 4) + digits[-4:]


def strip_hidden(value) -> str:
    if value is None:
        return ""
    text = str(value)
    for ch in ("\u202a", "\u202b", "\u202c", "\u202d", "\u202e", "\u200b", "\u200c", "\u200d", "\ufeff"):
        text = text.replace(ch, "")
    return text.strip()


def _under_hundred(n: int) -> str:
    if n < 20:
        return _ONES[n]
    ten, one = divmod(n, 10)
    return _TENS[ten] + (f"-{_ONES[one]}" if one else "")


def _under_thousand(n: int) -> str:
    hundred, rest = divmod(n, 100)
    parts = []
    if hundred:
        parts.append(f"{_ONES[hundred]} Hundred")
    if rest:
        parts.append(_under_hundred(rest))
    return " ".join(parts)


def _indian_int_words(n: int) -> str:
    if n == 0:
        return "Zero"
    parts = []
    crore, n = divmod(n, 10_000_000)
    lakh, n = divmod(n, 100_000)
    thousand, n = divmod(n, 1000)
    if crore:
        parts.append(f"{_under_thousand(crore)} Crore")
    if lakh:
        parts.append(f"{_under_thousand(lakh)} Lakh")
    if thousand:
        parts.append(f"{_under_thousand(thousand)} Thousand")
    if n:
        parts.append(_under_thousand(n))
    return " ".join(parts)


def rupees_in_words(amount) -> str:
    amount = q2(amount)
    sign = "Minus " if amount < 0 else ""
    amount = abs(amount)
    rupees = int(amount)
    paise = int((amount - rupees) * 100)
    text = f"{sign}Rupees {_indian_int_words(rupees)}"
    if paise:
        text += f" and {_indian_int_words(paise)} Paise"
    return text + " Only"


def recurring_active(entry: dict, year_month: str) -> bool:
    start = entry.get("start_month")
    count = int(entry.get("months") or 0)
    if not start or count <= 0:
        return False
    sy, sm = (int(p) for p in start.split("-"))
    y, m = (int(p) for p in year_month.split("-"))
    elapsed = (y - sy) * 12 + (m - sm)
    return 0 <= elapsed < count


def ytd_from_lines(lines: list, through_month: str) -> dict:
    window = set(fy_months(through_month))
    acc = {"gross": ZERO, "pf_ee": ZERO, "pf_er": ZERO, "esi_ee": ZERO, "esi_er": ZERO, "pt": ZERO, "net": ZERO}
    for line in lines:
        if line.get("month") not in window:
            continue
        if line.get("status") not in (None, "published"):
            continue
        if line.get("superseded"):
            continue
        acc["gross"] += D(line.get("gross"))
        acc["pf_ee"] += D(line.get("pf_r"))
        acc["pf_er"] += D(line.get("e_pf_r"))
        acc["esi_ee"] += D(line.get("esi_r"))
        acc["esi_er"] += D(line.get("e_esi_r"))
        acc["pt"] += D(line.get("pt"))
        acc["net"] += D(line.get("atc"))
    return acc


def fixed_from_formula(formula: str):
    """'=19000/E4*F4' → 19000. Returns None when the cell is not that shape."""
    if not isinstance(formula, str):
        return None
    text = formula.strip()
    if not text.startswith("="):
        return None
    body = text[1:].split("/")[0].strip()
    if not body or not body.replace(".", "", 1).isdigit():
        return None
    return D(body)


def fixed_from_values(value, nwd, ndp):
    paid = D(ndp)
    if paid == 0:
        return None
    return q2(D(value) * D(nwd) / paid)
