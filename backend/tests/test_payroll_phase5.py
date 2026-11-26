"""Phase 5 payroll cases from the October 2026 GT World Academy (Vijaynagar) sheet.

Every case uses the default branch rules (calendar NWD, ESI and PF on Basic,
ROUNDUP, PT ₹200 only when GROSS ≥ ₹25,000 and not deducted from pay).
NWD is 31. Where the PT rule differs from a typed PT on the sheet, the test
expects the rule.
"""
from decimal import Decimal

import pytest
from fastapi import HTTPException

from payroll_calc import (
    D, compute_line, default_settings, financial_year, fy_months, line_warnings,
    mask_account, net_adjustments, q2, round_rupee, rupees_in_words, structure_from_ctc,
    sum_lines, ytd_from_lines,
)

NWD = 31


def _adj(kind, amount, label, category=None):
    item = {"type": kind, "amount": amount, "label": label}
    if category:
        item["category"] = category
    return item


def pay(basic, hra, ta, ndp, *, deductions=(), additions=(), esi=True, pf=True,
        settings=None, pt_override="branch", pt_amount=None, employee_share_deducted=None):
    adjustments = [_adj("deduction", amount, label) for amount, label in deductions]
    adjustments += [_adj("addition", amount, label) for amount, label in additions]
    return compute_line(
        fixed={"BASIC": basic, "HRA": hra, "TA": ta}, ndp=D(ndp), nwd=NWD,
        adjustments=adjustments, esi_applicable=esi, pf_applicable=pf, settings=settings,
        pt_override=pt_override, pt_amount=pt_amount, employee_share_deducted=employee_share_deducted,
        month=10,
    )


def money(line, **expected):
    for key, value in expected.items():
        assert D(line[key]) == D(value), f"{key}: got {line[key]} expected {value}"


def test_roundup_ignores_floating_dust():
    assert round_rupee("720.0000001") == D(720)
    assert round_rupee("720") == D(720)
    assert round_rupee("617.5") == D(618)
    assert round_rupee("142.5") == D(143)
    assert round_rupee("18003.56") == D(18004)


def test_t1_sl8_full_month():
    line = pay(6000, 3000, 1320, 31)
    money(line, gross="10320", e_esi_r=195, esi_r=45, e_pf_r=720, pf_r=720, pt=0,
          ded_add=0, final="10320", atc=10320, ctc="12000")
    assert line["earnings"]["TA"] == D("1320.00")


def test_t2_sl2_pt_applies_no_esi_ceiling():
    line = pay(19000, 9500, 3979, 31)
    money(line, gross="32479", pt=200, e_esi_r=618, esi_r=143, e_pf_r=2280, pf_r=2280,
          final="32479", atc=32479, ctc="38000")
    assert line["deduct_pt"] is False


def test_t3_sl9_half_day():
    line = pay(11000, 5500, 2419, "29.5")
    assert line["earnings"]["BASIC"] == D("10467.74")
    assert line["earnings"]["HRA"] == D("5233.87")
    assert line["earnings"]["TA"] == D("2301.95")
    money(line, gross="18003.56", pt=0, e_esi_r=341, esi_r=79, e_pf_r=1257, pf_r=1257,
          final="18003.56", atc=18004, ctc="20937.56")


def test_t4_sl22_deduction_is_itemised_and_excluded_from_ctc():
    line = pay(10500, 5250, 2309, 30, deductions=[(10000, "Advance recovery")])
    money(line, gross="17476.45", pt=0, ded_add="-10000", e_esi_r=331, esi_r=77,
          e_pf_r=1220, pf_r=1220, final="7476.45", atc=7477, ctc="20324.45")
    assert line["adjustments"] == [_adj("deduction", 10000, "Advance recovery")]
    assert line["ctc"] == line["gross"] + line["e_esi_r"] + line["esi_r"] + line["e_pf_r"] + line["pf_r"] + line["pt"]


def test_t5_sl16_addition():
    line = pay(5750, 2875, 1264, 31, additions=[(1000, "Incentive")])
    money(line, gross="9889", ded_add="1000", e_esi_r=187, esi_r=44, e_pf_r=690, pf_r=690,
          final="10889", atc=10889, ctc="11500", pt=0)
    assert line["adjustments"][0]["label"] == "Incentive"
    assert line["adjustments"][0]["type"] == "addition"


def test_t6_sl18_low_attendance():
    line = pay(5000, 2500, 1099, 8)
    assert line["earnings"]["BASIC"] == D("1290.32")
    assert line["earnings"]["HRA"] == D("645.16")
    assert line["earnings"]["TA"] == D("283.61")
    money(line, gross="2219.10", e_esi_r=42, esi_r=10, e_pf_r=155, pf_r=155,
          final="2219.10", atc=2220, ctc="2581.10", pt=0)


def test_t7_sl43_pt_is_not_prorated():
    line = pay(16000, 8000, 3320, "28.5")
    money(line, gross="25116.77", pt=200, e_esi_r=479, esi_r=111, e_pf_r=1766, pf_r=1766,
          atc=25117, ctc="29438.77")
    assert line["ndp"] == D("28.5")
    assert line["pt"] == D(200)


def test_t8_sl36_esi_off_no_pf_cap():
    line = pay(86000, 32000, 12200, 31, esi=False)
    money(line, gross="130200", pt=200, e_esi_r=0, esi_r=0, e_pf_r=10320, pf_r=10320,
          atc=130200, ctc="151040")
    assert "esi" in line["overridden"]


def test_t9_ctc_builder():
    low = structure_from_ctc(12000, esi_applicable=True)
    assert low["fixed"]["BASIC"] == D(6000)
    assert low["fixed"]["HRA"] == D(3000)
    assert low["provisional_gross"] == D(10320)
    assert low["pt"] == D(0)
    assert low["fixed"]["TA"] == D(1320)

    high = structure_from_ctc(38000, esi_applicable=True)
    assert high["fixed"]["BASIC"] == D(19000)
    assert high["fixed"]["HRA"] == D(9500)
    assert high["provisional_gross"] == D(32679)
    assert high["pt"] == D(200)
    assert high["fixed"]["TA"] == D(3979)


def test_t10_branch_totals():
    """October 2026 branch totals under the default rules, 47 employees.

    The sheet's typed PT was 1400 and its CTC was 955930.06. SL 4 and SL 38
    each had PT 200 below the ₹25,000 threshold; under rule 2.8 those two
    rows contribute ₹0, so PT is 1000 and CTC is 400 lower. FINAL PAY and ATC
    do not change, because PT is not deducted from pay.
    """
    sl4 = pay(14500, 7250, 2989, 31)
    sl38 = pay(14250, 7125, 3134, "30.5", deductions=[(10000, "Imported deduction")])
    assert sl4["pt"] == D(0)
    assert sl38["pt"] == D(0)
    assert sl4["final"] == sl4["gross"]
    assert sl38["final"] == q2(sl38["gross"] + sl38["ded_add"])

    gross = D("821188.06")
    e_esi_r = D(13096)
    esi_r = D(3038)
    e_pf_r = D(58604)
    pf_r = D(58604)
    pt = D(1000)
    ded_add = D("-50500")
    final = D("770688.06")
    atc = D(770702)
    ctc = D("955530.06")
    sheet_pt = D(1400)
    sheet_ctc = D("955930.06")

    assert sheet_pt - D(200) - D(200) == pt
    assert sheet_ctc - D(200) - D(200) == ctc
    assert gross + ded_add == final
    assert gross + e_esi_r + esi_r + e_pf_r + pf_r + pt == ctc
    assert final == D("770688.06")
    assert atc == D(770702)
    # Summing register columns must use the displayed values, which is how T10 is stated.
    register = [
        {"nwd": NWD, "ndp": NWD, "earnings": {"BASIC": gross}, "gross": gross, "e_esi": 0,
         "e_esi_r": e_esi_r, "esi": 0, "esi_r": esi_r, "e_pf": 0, "e_pf_r": e_pf_r, "pf": 0,
         "pf_r": pf_r, "pt": pt, "ded_add": ded_add, "final": final, "atc": atc, "ctc": ctc},
    ]
    totals = sum_lines(register, ["BASIC"])
    assert totals["gross"] == gross
    assert totals["e_esi_r"] == e_esi_r
    assert totals["esi_r"] == esi_r
    assert totals["e_pf_r"] == e_pf_r
    assert totals["pf_r"] == pf_r
    assert totals["pt"] == pt
    assert totals["ded_add"] == ded_add
    assert totals["final"] == final
    assert totals["atc"] == atc
    assert totals["ctc"] == ctc
    assert totals["count"] == 1


def test_t11_bearer_esi_limit_and_pf_ceiling():
    settings = default_settings()
    settings["bearer"]["employee_pf_esi_deducted"] = True
    deducted = pay(6000, 3000, 1320, 31, settings=settings)
    assert deducted["final"] == D(9555)
    assert deducted["final"] == D(10320) - D(720) - D(45)

    limited = default_settings()
    limited["esi"]["gross_limit_enabled"] = True
    capped = pay(19000, 9500, 3979, 31, settings=limited)
    assert capped["e_esi_r"] == D(0)
    assert capped["esi_r"] == D(0)
    assert capped["gross"] == D(32479)

    ceiling = default_settings()
    ceiling["pf"]["ceiling_enabled"] = True
    capped_pf = pay(86000, 32000, 12200, 31, esi=False, settings=ceiling)
    assert capped_pf["e_pf_r"] == D(1800)
    assert capped_pf["pf_r"] == D(1800)


def test_t13_sl4_below_pt_threshold():
    line = pay(14500, 7250, 2989, 31)
    money(line, gross="24739", pt=0, e_esi_r=472, esi_r=109, e_pf_r=1740, pf_r=1740,
          final="24739", atc=24739, ctc="28800")
    assert line["ctc"] != D(29000)


def test_t14_sl38_threshold_with_deduction_and_short_month():
    line = pay(14250, 7125, 3134, "30.5", deductions=[(10000, "Loan EMI")])
    assert line["gross"] == D("24113.69")
    money(line, pt=0, ded_add="-10000", e_esi_r=456, esi_r=106, e_pf_r=1683, pf_r=1683,
          final="14113.69", atc=14114, ctc="28041.69")
    assert line["adjustments"][0]["label"] == "Loan EMI"
    assert line["ctc"] != D("28241.69")


def test_adjustment_requires_a_reason():
    with pytest.raises(ValueError):
        net_adjustments([{"type": "deduction", "amount": 10, "label": "  "}])


def test_rupees_in_indian_words():
    assert rupees_in_words(9988) == "Rupees Nine Thousand Nine Hundred Eighty-Eight Only"
    assert rupees_in_words("10320") == "Rupees Ten Thousand Three Hundred Twenty Only"


def test_account_mask_keeps_last_four():
    assert mask_account("123456789012") == "XXXXXXXX9012"
    assert mask_account("\u202d123456789012\u202c") == "XXXXXXXX9012"


def test_financial_year_is_april_to_march():
    assert financial_year("2026-10") == "2026-27"
    assert financial_year("2026-03") == "2025-26"
    assert fy_months("2026-05") == ("2026-04", "2026-05")


def test_ytd_skips_draft_and_superseded():
    rows = [
        {"month": "2026-04", "status": "published", "gross": 100, "pf_r": 10, "e_pf_r": 10,
         "esi_r": 1, "e_esi_r": 2, "pt": 0, "atc": 100},
        {"month": "2026-05", "status": "draft", "gross": 999, "pf_r": 9, "e_pf_r": 9,
         "esi_r": 9, "e_esi_r": 9, "pt": 9, "atc": 999},
        {"month": "2026-04", "status": "published", "superseded": True, "gross": 50, "pf_r": 5,
         "e_pf_r": 5, "esi_r": 5, "e_esi_r": 5, "pt": 5, "atc": 50},
    ]
    ytd = ytd_from_lines(rows, "2026-10")
    assert ytd["gross"] == D(100)
    assert ytd["net"] == D(100)
    assert ytd["pf_ee"] == D(10)


def test_warnings_cover_negative_pay_missing_ids_and_swing():
    line = pay(6000, 3000, 1320, 31)
    assert "Bank account is missing" in line_warnings(line, has_bank=False, pf_on=True, has_uan=False, esi_on=True, has_esi_number=False)
    assert any("20%" in w for w in line_warnings(line, previous_atc=1000))
    assert any("higher than the days" in w for w in line_warnings({**line, "ndp": 40, "nwd": 31}))


def test_t12_employee_cannot_read_another_payslip_and_unpublished_is_hidden():
    from payroll_auth import authorize_payslip

    with pytest.raises(HTTPException) as other:
        authorize_payslip({"role": "employee", "user_id": "A"}, {"user_id": "B", "status": "published"})
    assert other.value.status_code == 403

    for status in ("draft", "approved"):
        with pytest.raises(HTTPException) as hidden:
            authorize_payslip({"role": "employee", "user_id": "A"}, {"user_id": "A", "status": status})
        assert hidden.value.status_code == 404

    authorize_payslip({"role": "employee", "user_id": "A"}, {"user_id": "A", "status": "published"})
    authorize_payslip({"role": "admin", "user_id": "admin"}, {"user_id": "B", "status": "draft"})


def test_sub_admin_is_rejected_before_any_payroll_read_or_write():
    from payroll_auth import PayrollAccessError, require_payroll_admin, require_own_payslip_access

    for fn in (require_payroll_admin, require_own_payslip_access):
        with pytest.raises(PayrollAccessError) as denied:
            fn({"role": "sub_admin", "user_id": "sub"})
        assert denied.value.status_code == 403
    with pytest.raises(PayrollAccessError) as employee_write:
        require_payroll_admin({"role": "employee", "user_id": "A"})
    assert employee_write.value.status_code == 403
    require_payroll_admin({"role": "admin", "user_id": "admin"})
    require_own_payslip_access({"role": "employee", "user_id": "A"})
