"""Payslip PDFs. Rendered with reportlab from the frozen payroll line, so the
PDF matches the register for that run version."""
from __future__ import annotations

import os
from datetime import datetime
from decimal import Decimal
from io import BytesIO
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

from reportlab.lib.colors import Color, HexColor, white
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4, A5, letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, HRFlowable

from payroll_calc import D, month_label, rupees_in_words

PAGES = {"A4": A4, "A5": A5, "LETTER": letter}
KN = {
    "Basic": "ಮೂಲ ವೇತನ",
    "HRA": "ಮನೆ ಬಾಡಿಗೆ ಭತ್ಯೆ",
    "Travel Allowance (TA)": "ಪ್ರಯಾಣ ಭತ್ಯೆ",
    "Gross": "ಒಟ್ಟು",
    "Net pay": "ನಿವ್ವಳ ವೇತನ",
    "Days in month": "ತಿಂಗಳ ದಿನಗಳು",
    "Days paid": "ವೇತನ ದಿನಗಳು",
    "LOP days": "ವೇತನರಹಿತ ದಿನಗಳು",
}


def default_template() -> dict:
    return {
        "legal_name": "",
        "address_lines": [],
        "logo_path": None,
        "header_text": "Payslip",
        "footer_text": "This is a computer-generated payslip.",
        "signatory_name": "",
        "signatory_designation": "",
        "signature_path": None,
        "no_signature_required": True,
        "primary": "#0D0D12",
        "accent": "#0047FF",
        "font_size": 9,
        "paper": "A4",
        "language": "en",
        "sections": [
            {"id": "header", "show": True},
            {"id": "employee", "show": True},
            {"id": "bank", "show": True},
            {"id": "attendance", "show": True},
            {"id": "earnings", "show": True},
            {"id": "contributions", "show": True},
            {"id": "adjustments", "show": True},
            {"id": "net", "show": True},
            {"id": "employer", "show": True},
            {"id": "ytd", "show": True},
            {"id": "footer", "show": True},
        ],
    }


def _register_fonts() -> str:
    """DejaVu covers Latin and the rupee sign. Kannada is a second face, used only for labels."""
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    latin = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    kannada = "/usr/share/fonts/truetype/noto/NotoSansKannada-Regular.ttf"
    names = pdfmetrics.getRegisteredFontNames()
    if os.path.exists(latin) and "Kelasa" not in names:
        pdfmetrics.registerFont(TTFont("Kelasa", latin))
    if os.path.exists(kannada) and "KelasaKannada" not in names:
        pdfmetrics.registerFont(TTFont("KelasaKannada", kannada))
    if "Kelasa" in pdfmetrics.getRegisteredFontNames():
        return "Kelasa"
    return "Helvetica"


def _font_name() -> str:
    return _register_fonts()


def _label(text: str, language: str) -> str:
    if language == "en-kn" and text in KN:
        from reportlab.pdfbase import pdfmetrics
        if "KelasaKannada" in pdfmetrics.getRegisteredFontNames():
            return f'{text} / <font name="KelasaKannada">{KN[text]}</font>'
        return f"{text} / {KN[text]}"
    return text


def _money(value) -> str:
    number = D(value or 0)
    sign = "-" if number < 0 else ""
    number = abs(number)
    whole, frac = f"{number:.2f}".split(".")
    groups = []
    if len(whole) > 3:
        groups.append(whole[-3:])
        whole = whole[:-3]
        while whole:
            groups.append(whole[-2:])
            whole = whole[:-2]
        whole = ",".join(reversed(groups))
    else:
        whole = whole or "0"
    return f"{sign}₹{whole}.{frac}"


def _shown(template: dict, section_id: str) -> bool:
    for section in template.get("sections") or []:
        if section.get("id") == section_id:
            return bool(section.get("show", True))
    return True


def render_payslip(line: dict, template: dict, *, ytd: dict | None = None, generated_at: datetime | None = None) -> bytes:
    template = {**default_template(), **(template or {})}
    if "sections" not in (template or {}):
        template["sections"] = default_template()["sections"]
    font = _font_name()
    size = int(template.get("font_size") or 9)
    primary = HexColor(template.get("primary") or "#0D0D12")
    accent = HexColor(template.get("accent") or "#0047FF")
    language = template.get("language") or "en"
    page = PAGES.get((template.get("paper") or "A4").upper(), A4)
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=page, leftMargin=14 * mm, rightMargin=14 * mm, topMargin=12 * mm, bottomMargin=14 * mm,
                             title=f"Payslip {line.get('month') or ''}")
    styles = _styles(font, size, primary)
    story = []
    generated_at = generated_at or datetime.now(ZoneInfo("Asia/Kolkata"))
    month = month_label(line["month"]) if line.get("month") else ""

    if _shown(template, "header"):
        story.extend(_header(line, template, styles, accent, month))
    if _shown(template, "employee"):
        story.append(_kv_table(_employee_rows(line), styles, primary))
        story.append(Spacer(1, 3 * mm))
    if _shown(template, "bank"):
        story.append(Paragraph("Bank and statutory", styles["h"]))
        story.append(_kv_table(_bank_rows(line), styles, primary))
        story.append(Spacer(1, 3 * mm))
    if _shown(template, "attendance"):
        story.append(Paragraph("Attendance", styles["h"]))
        story.append(_attendance(line, styles, primary, language))
        story.append(Spacer(1, 3 * mm))
    if _shown(template, "earnings"):
        story.append(Paragraph("Earnings", styles["h"]))
        story.append(_earnings(line, styles, primary, accent, language))
        story.append(Spacer(1, 3 * mm))
    if _shown(template, "contributions"):
        story.append(Paragraph("Contributions", styles["h"]))
        story.append(_contributions(line, styles, primary))
        story.append(Spacer(1, 3 * mm))
    if _shown(template, "adjustments"):
        story.append(Paragraph("Deductions and additions", styles["h"]))
        story.append(_adjustments(line, styles, primary))
        story.append(Spacer(1, 3 * mm))
    if _shown(template, "net"):
        story.extend(_net(line, styles, accent, language))
    if _shown(template, "employer"):
        story.append(Spacer(1, 2 * mm))
        story.append(Paragraph(
            f"Employer PF {_money(line.get('e_pf_r'))} · Employer ESI {_money(line.get('e_esi_r'))} (informational, paid by the employer)",
            styles["small"]))
    if _shown(template, "ytd") and ytd:
        story.append(Spacer(1, 2 * mm))
        story.append(Paragraph("Year to date (April–March)", styles["h"]))
        story.append(_kv_table([
            ["Gross", _money(ytd.get("gross"))],
            ["PF employee / employer", f"{_money(ytd.get('pf_ee'))} / {_money(ytd.get('pf_er'))}"],
            ["ESI employee / employer", f"{_money(ytd.get('esi_ee'))} / {_money(ytd.get('esi_er'))}"],
            ["Professional tax", _money(ytd.get("pt"))],
            ["Net paid", _money(ytd.get("net"))],
        ], styles, primary))
    if _shown(template, "footer"):
        story.append(Spacer(1, 4 * mm))
        story.append(HRFlowable(width="100%", thickness=0.4, color=Color(0.8, 0.8, 0.82)))
        story.append(Spacer(1, 2 * mm))
        if not template.get("no_signature_required") and template.get("signatory_name"):
            story.append(Paragraph(escape(template.get("signatory_name") or ""), styles["body"]))
            story.append(Paragraph(escape(template.get("signatory_designation") or ""), styles["small"]))
        elif template.get("no_signature_required"):
            story.append(Paragraph("Computer-generated, no signature required.", styles["small"]))
        if template.get("footer_text"):
            story.append(Paragraph(escape(template["footer_text"]), styles["small"]))
        stamp = generated_at.astimezone(ZoneInfo("Asia/Kolkata")).strftime("%d %b %Y, %H:%M IST")
        story.append(Paragraph(f"Generated {stamp}", styles["small"]))
        if line.get("superseded"):
            story.append(Paragraph("Superseded", styles["small"]))
        if line.get("imported"):
            story.append(Paragraph("Imported from a previous salary sheet. Amounts were not recalculated.", styles["small"]))
    doc.build(story)
    return buf.getvalue()


def _styles(font, size, primary):
    base = ParagraphStyle("body", fontName=font, fontSize=size, leading=size + 3, textColor=primary)
    return {
        "body": base,
        "h": ParagraphStyle("h", parent=base, fontSize=size + 1, leading=size + 4, spaceBefore=2, spaceAfter=2),
        "title": ParagraphStyle("title", parent=base, fontSize=size + 6, leading=size + 8),
        "small": ParagraphStyle("small", parent=base, fontSize=max(7, size - 1), leading=size + 1, textColor=HexColor("#52525B")),
        "right": ParagraphStyle("right", parent=base, alignment=TA_RIGHT),
    }


def _header(line, template, styles, accent, month):
    legal = template.get("legal_name") or line.get("legal_name") or "Payslip"
    bits = [Paragraph(escape(legal), styles["title"])]
    for row in template.get("address_lines") or []:
        if row:
            bits.append(Paragraph(escape(str(row)), styles["small"]))
    if template.get("header_text"):
        bits.append(Paragraph(escape(template["header_text"]), styles["small"]))
    bits.append(Paragraph(f"Payslip for {escape(month)}", styles["h"]))
    logo = template.get("logo_bytes")
    if logo:
        img = Image(BytesIO(logo), width=18 * mm, height=18 * mm)
        table = Table([[img, bits]], colWidths=[22 * mm, None])
        table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
        return [table, Spacer(1, 3 * mm)]
    return bits + [Spacer(1, 2 * mm)]


def _employee_rows(line):
    person = line.get("employee") or {}
    return [
        ["Name", line.get("name") or person.get("name") or ""],
        ["Employee code", line.get("employee_code") or ""],
        ["Designation", line.get("designation") or ""],
        ["Department", line.get("department") or ""],
        ["Branch", line.get("branch_name") or ""],
        ["Date of joining", line.get("date_of_joining") or ""],
        ["PAN", line.get("pan") or ""],
    ]


def _bank_rows(line):
    return [
        ["UAN", line.get("uan") or ""],
        ["ESI number", line.get("esi_number") or ""],
        ["Bank", line.get("bank_name") or ""],
        ["Account", line.get("account_masked") or ""],
        ["IFSC", line.get("ifsc") or ""],
    ]


def _rich(text: str) -> str:
    value = "" if text is None else str(text)
    if "<font" in value:
        return value
    return escape(value)


def _kv_table(rows, styles, primary):
    data = [[Paragraph(_rich(a), styles["small"]), Paragraph(_rich(b), styles["body"])] for a, b in rows]
    table = Table(data, colWidths=[42 * mm, None])
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), styles["body"].fontName),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 1),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
        ("LINEBELOW", (0, 0), (-1, -2), 0.2, HexColor("#E4E4E7")),
    ]))
    return table


def _attendance(line, styles, primary, language):
    att = line.get("attendance") or {}
    leave = att.get("paid_leave") or {}
    leave_text = ", ".join(f"{name} {D(days)}" for name, days in leave.items()) or "—"
    rows = [
        [_label("Days in month", language), str(line.get("nwd") or att.get("nwd") or "")],
        [_label("Days paid", language), str(line.get("ndp") or "")],
        [_label("LOP days", language), str(att.get("lop") if att.get("lop") is not None else (D(line.get("nwd") or 0) - D(line.get("ndp") or 0)))],
        ["Present", str(att.get("present") or 0)],
        ["Half days", str(att.get("half_days") or 0)],
        ["Paid leave", leave_text],
        ["Holidays", str(att.get("holidays") or 0)],
        ["Weekly offs", str(att.get("weekly_offs") or 0)],
    ]
    return _kv_table(rows, styles, primary)


def _earnings(line, styles, primary, accent, language):
    header = ["Component", "Fixed monthly", "This month"]
    data = [[Paragraph(escape(h), styles["small"]) for h in header]]
    labels = line.get("component_labels") or {}
    fixed = line.get("fixed") or {}
    earnings = line.get("earnings") or {}
    for code, amount in earnings.items():
        label = _label(labels.get(code) or code, language)
        data.append([
            Paragraph(_rich(label), styles["body"]),
            Paragraph(_money(fixed.get(code, 0)), styles["right"]),
            Paragraph(_money(amount), styles["right"]),
        ])
    data.append([
        Paragraph(_rich(_label("Gross", language)), styles["h"]),
        "",
        Paragraph(_money(line.get("gross")), styles["h"]),
    ])
    table = Table(data, colWidths=[80 * mm, 40 * mm, 40 * mm])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), primary),
        ("TEXTCOLOR", (0, 0), (-1, 0), white),
        ("BACKGROUND", (0, -1), (-1, -1), HexColor("#F5F5F6")),
        ("LINEBELOW", (0, 1), (-1, -2), 0.2, HexColor("#E4E4E7")),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
    ]))
    return table


def _bearer(line, key) -> str:
    if key == "pt":
        return "Deducted" if line.get("deduct_pt") else "Paid by employer"
    return "Deducted" if line.get("deduct_pf_esi") else "Paid by employer"


def _contributions(line, styles, primary):
    rows = [
        [Paragraph("Employee PF", styles["body"]), Paragraph(_money(line.get("pf_r")), styles["right"]), Paragraph(_bearer(line, "pf"), styles["small"])],
        [Paragraph("Employee ESI", styles["body"]), Paragraph(_money(line.get("esi_r")), styles["right"]), Paragraph(_bearer(line, "esi"), styles["small"])],
        [Paragraph("Professional tax", styles["body"]), Paragraph(_money(line.get("pt")), styles["right"]), Paragraph(_bearer(line, "pt"), styles["small"])],
    ]
    table = Table(rows, colWidths=[70 * mm, 40 * mm, 50 * mm])
    table.setStyle(TableStyle([
        ("LINEBELOW", (0, 0), (-1, -2), 0.2, HexColor("#E4E4E7")),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("BACKGROUND", (0, 0), (-1, 0), HexColor("#F5F5F6")),
    ]))
    return table


def _adjustments(line, styles, primary):
    entries = line.get("adjustments") or []
    if not entries:
        return Paragraph("None", styles["small"])
    data = [[Paragraph(h, styles["small"]) for h in ("Type", "Amount", "Reason")]]
    for entry in entries:
        data.append([
            Paragraph(escape((entry.get("type") or "").title()), styles["body"]),
            Paragraph(_money(entry.get("amount")), styles["right"]),
            Paragraph(escape(entry.get("label") or entry.get("reason") or ""), styles["body"]),
        ])
    data.append([
        Paragraph("Net DED/ADD", styles["h"]),
        Paragraph(_money(line.get("ded_add")), styles["h"]),
        Paragraph("Included in final pay", styles["small"]),
    ])
    table = Table(data, colWidths=[35 * mm, 35 * mm, 90 * mm])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), primary),
        ("TEXTCOLOR", (0, 0), (-1, 0), white),
        ("LINEBELOW", (0, 1), (-1, -2), 0.2, HexColor("#E4E4E7")),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("BACKGROUND", (0, -1), (-1, -1), HexColor("#F5F5F6")),
    ]))
    return table


def _net(line, styles, accent, language):
    additions = sum((D(e.get("amount")) for e in line.get("adjustments") or [] if e.get("type") == "addition"), D(0))
    deductions = sum((D(e.get("amount")) for e in line.get("adjustments") or [] if e.get("type") == "deduction"), D(0))
    rows = [
        ["Gross", _money(line.get("gross"))],
        ["Total additions", _money(additions)],
        ["Total deductions", _money(deductions)],
        ["Monthly CTC", _money(line.get("ctc"))],
        [_label("Net pay", language), _money(line.get("atc"))],
    ]
    block = [_kv_table(rows, styles, accent)]
    block.append(Paragraph(escape(rupees_in_words(line.get("atc") or 0)), styles["body"]))
    return block
