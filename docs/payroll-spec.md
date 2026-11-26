# Phase 5 — Payroll & payslips

This replaces the earlier Phase 5. It is the specification for the Kelasa payroll module (Gyarahalli Thammayya Groups).

## Binding permission update

Recorded by the owner after this spec was written, and enforced in the implementation:

- Only role `admin` can read or write payroll: salary structures and components, TA, DED/ADD entries, payroll runs, payslip generation, settings, templates, import and exports.
- Role `sub_admin` has no payroll access at all, not even read. Every payroll menu, page and route is hidden, and every payroll endpoint returns HTTP 403.
- Employees can only view and download their own published payslips (and raise a query on them), plus their own read-only salary structure summary.
- This replaces section 5.5's optional "Payroll for my branches" grant. Sub-admins cannot approve, and they also cannot view.

The app is self-hosted. Payslip PDFs are rendered on the server with reportlab. Files go through the existing storage helper, with a local-disk fallback when that helper is not configured. No Emergent dependency is added.

---

## Reference

Earnings, ESI, PF, FINAL PAY, rounding, CTC and the register layout follow the "OCTOBER 2026" salary sheet for GT World Academy (Vijaynagar). That is the only month to take formulas from. Two confirmed updates are the default rules, not exceptions:

1. The earning formerly called SA is now TA (Travel Allowance).
2. Professional Tax is ₹200 only when the month's GROSS is ₹25,000 or more, otherwise ₹0 (see 2.8).

Every branch has its own payroll settings and its own payslip template, customisable from the admin panel. Existing employee, branch, attendance, leave, holiday, weekly-off, bank, UAN and ESI data is reused. Phase 1 fixed work-hours and absent logic (`attendance_calc.day_status`, including the calendar's half-day rule) runs before payroll counts a day.

## 1. Data model

1.1 Branch payroll profile (one per branch, versioned by effective month): legal entity name, display name (e.g. "Gyarahalli Thammayya World Academy (Vijaynagar)"), address, PF establishment code, ESI code, PT registration number, plus every setting in section 3.

1.2 Employee salary structure (versioned, with an effective-from date; never overwrite, a revision creates a new version): branch, monthly CTC (optional), fixed monthly amount for each earning component (default components: BASIC, HRA, TA), ESI applicable (yes/no), PF applicable (yes/no), PT override (use branch rule / fixed amount / none) and optional PT amount, "employee share deducted from pay" (yes/no, inherits the branch default), and optional notes.

1.3 Payroll run: branch + month, status (Draft → Approved → Published), and version number. A run holds one payroll line per employee.

1.4 Payroll line: a frozen snapshot of every input and every calculated value, so a later structure change never alters a published month. Salary amounts are encrypted at rest.

1.5 DED/ADD is any manual deduction or addition for an employee in that month. Model it as itemised entries. Each entry has a type (deduction or addition), an amount, and a required reason/label. An optional category (Advance recovery, Loan EMI, Fine, Bonus, Arrears, Incentive, Other) may also be stored. The line's DED/ADD = (sum of additions) − (sum of deductions). Recurring entries (e.g. a loan EMI for N months) are supported. Every item appears separately on the payslip and in the DED/ADD report.

## 2. Default calculation

For each employee in a branch for a month:

2.1 NWD = number of calendar days in the month (31 for October, 30 for September, 28/29 for February).

2.2 NDP = days paid (decimal, half days allowed, e.g. 29.5). See section 4.

2.3 Each earning = fixed monthly amount × NDP / NWD, not rounded. BASIC, HRA and TA are all prorated the same way.

2.4 GROSS = BASIC + HRA + TA (+ any custom earning components), not rounded.

2.5 ESI is calculated on BASIC, as per the current guidelines. (E)ESI = BASIC × 3.25%, then (E)ESI R = ROUNDUP to the next whole rupee. Zero if the employee's ESI applicable = no. There is no gross-salary ceiling by default.

2.6 ESI (employee) = BASIC × 0.75%, then ESI R = ROUNDUP to the next rupee. Zero if ESI applicable = no.

2.7 E(PF) = BASIC × 12%, then E(PF) R = ROUNDUP. PF (employee) = BASIC × 12%, then PF R = ROUNDUP. No wage ceiling by default. Zero if PF applicable = no.

2.8 PT (default rule) = ₹200 if the month's GROSS (section 2.4) is greater than or equal to ₹25,000, otherwise ₹0. The ₹200 is a flat amount and is NOT prorated by attendance (a person with GROSS ≥ ₹25,000 pays the full ₹200 even if NDP is less than NWD). The threshold (default ₹25,000) and the amount (default ₹200) are configurable per branch. An admin may override PT for a single employee (fixed amount or none). This rule replaces the typed PT values in the October sheet; two October rows (SL 4 and SL 38) had PT ₹200 at a GROSS below ₹25,000, and under this rule their PT is ₹0 (see T13, T14 and T10).

2.9 DED/ADD = (sum of addition entries) − (sum of deduction entries) for the month. Each entry needs a reason/label.

2.10 FINAL PAY = GROSS + DED/ADD. By default employee PF, employee ESI and PT are NOT subtracted (the employer bears them, as in the sheet).

2.11 ATC (amount to credit) = ROUNDUP(FINAL PAY) to the next rupee. This is the amount paid to the bank.

2.12 CTC (for the month) = GROSS + (E)ESI R + ESI R + E(PF) R + PF R + PT, not rounded. DED/ADD is not part of CTC. GROSS in this sum is the displayed 2-decimal gross.

2.13 ROUNDUP means ceiling to the next whole rupee. Guard against floating-point errors: round to 6 decimals first, then take the ceiling, so 720.0000001 must not become 721. Use decimal arithmetic for money.

2.14 Totals row: sum of every numeric column across the branch (NWD, NDP, BASIC ... CTC).

## 3. Branch payroll settings

Admin panel, per branch, editable. The defaults reproduce section 2.

3.1 Earning components: add, rename, reorder or remove (default BASIC, HRA, TA). For each one: name, short code, show on payslip (yes/no), prorate by attendance (default yes), and whether it counts toward the ESI base and the PF base (defaults: only BASIC counts for both).

3.2 ESI: on/off, employer rate (default 3.25%), employee rate (default 0.75%), base (default "Basic"; "Gross" is available), optional gross eligibility limit (default OFF; the admin may turn on a ₹21,000 limit), rounding (default ROUNDUP; options Round nearest / Round down / None).

3.3 PF: on/off, employer rate (default 12%), employee rate (default 12%), base (default Basic), optional wage ceiling (default OFF; option ₹15,000), rounding (default ROUNDUP).

3.4 PT: default mode is the auto rule in 2.8. The threshold and the amount are editable. A multi-row slab table (salary from/to, monthly amount, special month override such as February) is also supported. Evaluation base: the month's GROSS by default; optionally the fixed monthly gross. Prorate PT: default no. The admin can still set a per-employee override (fixed amount or none).

3.5 Contribution bearer: "Employee PF/ESI deducted from pay" (default NO) and "PT deducted from pay" (default NO). When switched on, FINAL PAY = GROSS − deducted items + DED/ADD.

3.6 Proration: NWD = calendar days (default); options "fixed 30 days" and "working days excluding weekly offs".

3.7 Final pay rounding: default ROUNDUP; options Nearest / Down / None.

3.8 Structure builder from CTC (optional helper): Basic = 50% of CTC, HRA = 50% of Basic, PF = employer and employee % of Basic, ESI = employer and employee % of Basic (if applicable), and TA = CTC − Basic − HRA − both PF (rounded up) − both ESI (rounded up) − PT, as the balancing figure. Compute a provisional GROSS assuming PT = 0 (Basic + HRA + the balancing pool), then apply the branch PT rule (if that GROSS ≥ threshold, subtract PT and reduce TA by the PT amount). Percentages are editable per branch. The admin can always override any fixed amount by hand.

3.9 Every setting can be overridden per employee (ESI applicable, PF applicable, PT override, bearer, custom components). Show an "Overridden" badge in the register.

3.10 Settings are versioned with an effective month, and a payroll run uses the settings that were valid for that month (copied onto the run).

3.11 "Copy settings from another branch" button.

## 4. Days paid (NDP) from Kelasa

4.1 When a Draft run is generated, NDP for each employee = present days (a half day = 0.5) + approved paid leave days (half day leave = 0.5) + declared holidays + weekly offs, within the employee's active dates (joining date to exit date), capped at NWD. A day is classified with Phase 1 `day_status` and the same half-day / punch-error rules as the employee calendar, so a day cannot be counted twice.

4.2 Unpaid leave (LOP) and unexplained absences reduce NDP. LOP days = NWD − NDP.

4.3 The line stores the breakdown (present, half days, paid leave by type, holidays, weekly offs, LOP). The register links an employee to their attendance calendar by user id.

4.4 The admin can override NDP per employee in Draft. The override requires a reason, is shown with a badge, and is logged in the activity log.

4.5 Mid-month joiners and leavers are prorated on their active days only.

## 5. Payroll run flow

Admin > Payroll tab (hidden from sub-admins).

5.1 Choose branch + month → "Generate draft". The system creates lines for all active employees of that branch who have a salary structure, and lists employees who are missing a structure or bank details.

5.2 Register screen (spreadsheet-style, editable in Draft): NDP override, itemised DED/ADD entries (type, amount, required reason/label), ESI/PF/PT overrides. Saving a line recalculates it.

5.3 Validation warnings: negative ATC, NDP > NWD, missing bank/UAN/ESI number when that contribution is on, a DED/ADD entry without a reason/label, a big change from last month's ATC (more than 20%).

5.4 Draft → Approved (admin only; locks edits) → Published (payslips become visible to employees and push notifications are sent). Revising a published run creates version 2, keeps version 1 read-only and marks the old payslips "Superseded". History is never deleted.

5.5 Permissions: see the binding update at the top of this document. Only `admin` can see salary amounts and run payroll. Employees can see only their own published payslips. Draft and Approved payslips are invisible to employees (HTTP 404). Another employee's payslip is HTTP 403. Enforce all of this on the server for every API, not only in the UI.

5.6 Log every action in plain English in the activity log (generated, NDP override, DED/ADD added, approved, published, revised, payslip downloaded by an admin).

## 6. Salary register export

Excel, per branch per month. It must look like the sheet, with TA in place of SA.

6.1 Row 1 is a merged title: "<BRANCH DISPLAY NAME IN CAPS> SALARY LIST <MONTH YEAR>", e.g. "GYARAHALLI THAMMAYYA WORLD ACADEMY (VIJAYNAGAR) SALARY LIST OCTOBER 2026".

6.2 Row 2 headers in this exact order: SL NO, NAME, A/C NO, UAN, NWD, NDP, BASIC, HRA, TA, GROSS, (E)ESI, (E)ESI R, ESI, ESI R, E(PF), E(PF) R, PF, PF (R), PT, DED/ADD, FINAL PAY, ATC, CTC. Custom earning components are inserted after TA in their configured order. Account numbers are masked (last 4 digits) everywhere except the bank transfer export.

6.3 One row per employee, then a totals row. Write real Excel formulas (BASIC = fixed/NWD*NDP, ROUNDUP(...,0), PT = IF(GROSS>=threshold, amount, 0), FINAL PAY = GROSS+DED/ADD, ATC = ROUNDUP(FINAL PAY,0), CTC = GROSS + rounded contributions + PT), so the file recalculates under these rules. Also offer a "values only" export. Imported history exports as values, because those months must not be recalculated.

6.4 The column order and header labels are editable per branch (Branch settings > Register layout), with a "Reset to default" option.

6.5 Other exports: a bank transfer file (name, account number, IFSC, bank, ATC; CSV, plus a configurable column layout), a PF summary (UAN, name, PF wages, EE share, ER share, NCP days = LOP), an ESI summary (ESI number, name, days paid, ESI wages, EE share, ER share), a PT summary, and a DED/ADD report listing every item with type, amount and reason/label.

## 7. Payslip PDF

One per employee per month, per branch template. Rendered with reportlab from the frozen line, so the payslip equals the register for that run version.

7.1 Company/legal entity name, logo, address; "Payslip for <Month Year>"; employee name, employee code, designation, department, branch, date of joining, PAN, UAN, ESI number, bank name, masked account number (last 4 digits only), IFSC.

7.2 Attendance: NWD, NDP, LOP days, present, half days, paid leave by type, holidays, weekly offs.

7.3 Earnings table: each component (BASIC, HRA, TA, and any custom components) with its fixed monthly amount and the actual amount for the month; Gross.

7.4 Contributions table: employee PF, employee ESI and PT, each marked "Deducted" or "Paid by employer" according to the bearer setting; employer PF and employer ESI (informational).

7.5 DED/ADD: list every item separately with its type, amount and reason/label. Net DED/ADD is included in FINAL PAY.

7.6 Totals: Gross, total additions, total deductions, net pay (ATC) in figures and in words in Indian format (e.g. "Rupees Nine Thousand Nine Hundred Eighty-Eight Only"), monthly CTC.

7.7 Year-to-date for the financial year April–March: gross, PF (EE/ER), ESI (EE/ER), PT, net paid. Superseded versions are excluded so a month is not counted twice.

7.8 Footer text and generated date/time (IST).

7.9 The payslip values must equal the register values for that run version.

## 8. Payslip template designer

Admin > Payroll > Payslip template (also reachable per branch).

8.1 One template per branch: legal entity name, address lines, header text, footer text, signatory name, signatory designation, "computer-generated, no signature required" toggle, primary/accent colours, font size, paper size (A4 default), language (English / English + ಕನ್ನಡ labels). Logo and signature paths are stored when uploaded through the storage helper.

8.2 Sections: show/hide and reorder (Header, Employee details, Bank & statutory, Attendance, Earnings, Contributions, DED/ADD items, Net pay, Employer contributions, YTD, Footer).

8.3 Fields inside each section use the default earnings labels Basic, HRA and Travel Allowance (TA).

8.4 A published payslip re-renders with the template version it was published with. Template saves create a new version; they do not overwrite history.

8.5 Live preview using sample data from the October rules (TA plus itemised DED/ADD with reasons), plus "Download sample PDF".

8.6 "Duplicate template from another branch" button.

## 9. Employee side

New "Salary" page in the employee nav. Hidden from sub-admins; the route redirects them away.

9.1 A list of published months: month, days paid, net pay (ATC), Download PDF. Superseded versions are labelled. Imported months are labelled.

9.2 Download all payslips for a financial year as a ZIP.

9.3 The current salary structure summary (fixed monthly BASIC, HRA, TA and other components, read-only).

9.4 Push notification on publish: "Your payslip for <Month Year> is ready."

9.5 "Raise a query" on each payslip; it goes to the admin with the month and the message, and the admin can reply.

## 10. Admin bulk actions

10.1 Download all payslips for a branch + month as a ZIP (file name: `<EmpCode>_<Name>_<YYYY-MM>.pdf`).

10.2 Re-send notifications. The register export is the printable register.

## 11. Import past months

11.1 Admin > Payroll > Import: choose the branch, upload an .xlsx and pick a sheet (one sheet per month, e.g. "APRIL 26" ... "OCTOBER 26"; "SEPTEMEBER 26" is recognised).

11.2 Detect the month and year from the sheet name or the title in row 1. Find the header row (it contains "SL NO") and map columns by header name, not by position. The old header "SA" maps to TA. Stop at the first blank SL NO or the totals row.

11.3 Match employees by UAN first, then by account number, then by name (case-insensitive, trimmed; strip hidden Unicode such as U+202D and U+202C). The preview lists unmatched rows so an admin can link, create or skip them on commit.

11.4 Store imported months as Published history with the values exactly as they appear in the sheet (do not recalculate). Mark them "Imported". On imported payslips, show the third earning as TA. If the sheet had a single DED/ADD number, store it as one item with reason "Imported".

11.5 From a sheet, "Create salary structures from this sheet": the fixed monthly BASIC, HRA and TA are the numbers inside each formula (e.g. "=19000/E4*F4" means fixed BASIC 19000), or fixed = value × NWD / NDP when only values are present. The old "SA" column is TA. ESI applicable = (E)ESI is not 0. Do not copy the sheet's typed PT as a per-employee override. The preview can show sheet PT next to rule PT.

11.6 The import response includes an import summary with totals compared against the sheet's totals row.

## 12. Tests

These use real rows from the OCTOBER 2026 sheet, referenced by SL NO. All have NWD = 31. Default branch settings (section 2). ESI applicable = yes unless stated. Where a result differs from the October sheet because of the PT rule in 2.8, that is called out.

T1 (SL 8, full month): fixed B 6000, HRA 3000, TA 1320; NDP 31; GROSS 10320; PT 0; DED/ADD 0; (E)ESI R 195; ESI R 45; E(PF) R 720; PF R 720; FINAL 10320; ATC 10320; CTC 12000.

T2 (SL 2, PT applies because GROSS ≥ ₹25,000; ESI on Basic with no gross ceiling): fixed 19000 / 9500 / 3979; NDP 31; DED/ADD 0; GROSS 32479; PT 200; (E)ESI R 618; ESI R 143; E(PF) R 2280; PF R 2280; FINAL 32479; ATC 32479; CTC 38000.

T3 (SL 9, half day): fixed 11000 / 5500 / 2419; NDP 29.5; PT 0; BASIC 10467.74; HRA 5233.87; TA 2301.95; GROSS 18003.56; (E)ESI R 341; ESI R 79; E(PF) R 1257; PF R 1257; FINAL 18003.56; ATC 18004; CTC 20937.56.

T4 (SL 22, one deduction, amount 10000, reason required): fixed 10500 / 5250 / 2309; NDP 30; PT 0; DED/ADD −10000; GROSS 17476.45; (E)ESI R 331; ESI R 77; E(PF) R 1220; PF R 1220; FINAL 7476.45; ATC 7477; CTC 20324.45. The payslip lists that deduction with its reason.

T5 (SL 16, one addition, amount 1000, reason required): fixed 5750 / 2875 / 1264; NDP 31; DED/ADD +1000; GROSS 9889; (E)ESI R 187; ESI R 44; E(PF) R 690; PF R 690; FINAL 10889; ATC 10889; CTC 11500. The payslip lists that addition with its reason.

T6 (SL 18, low attendance): fixed 5000 / 2500 / 1099; NDP 8; BASIC 1290.32; HRA 645.16; TA 283.61; GROSS 2219.10; (E)ESI R 42; ESI R 10; E(PF) R 155; PF R 155; FINAL 2219.10; ATC 2220; CTC 2581.10.

T7 (SL 43, PT not prorated): fixed 16000 / 8000 / 3320; NDP 28.5; GROSS 25116.77; PT 200 (full, not prorated); (E)ESI R 479; ESI R 111; E(PF) R 1766; PF R 1766; ATC 25117; CTC 29438.77.

T8 (SL 36, ESI not applicable, no PF cap): fixed 86000 / 32000 / 12200; NDP 31; ESI applicable = no; GROSS 130200; PT 200; ESI 0 / 0; E(PF) R 10320; PF R 10320; ATC 130200; CTC 151040.

T9 (CTC builder): CTC 12000, ESI on → Basic 6000, HRA 3000, provisional GROSS 10320, PT 0, TA 1320. CTC 38000, ESI on → Basic 19000, HRA 9500, provisional GROSS 32679, PT 200, TA 3979.

T10 (branch totals under these default rules, 47 employees, same attendance and DED/ADD as the October sheet): GROSS 821188.06; (E)ESI R 13096; ESI R 3038; E(PF) R 58604; PF R 58604; PT 1000; DED/ADD −50500; FINAL 770688.06; ATC 770702; CTC 955530.06. These PT and CTC totals intentionally differ from the October sheet (sheet PT 1400, sheet CTC 955930.06) because SL 4 and SL 38 no longer attract PT. FINAL PAY and ATC are unchanged because PT is not deducted from pay.

T11 (settings): switching "Employee PF/ESI deducted from pay" ON for T1 gives FINAL = 10320 − 720 − 45 = 9555; switching on the optional ESI ₹21,000 gross limit makes T2's ESI 0; turning on the PF ₹15,000 ceiling makes T8's PF 1800 each.

T12 (security): employee A cannot fetch employee B's payslip (HTTP 403); a sub-admin receives HTTP 403 on every payroll endpoint (not only another branch); Draft and Approved payslips are invisible to employees.

T13 (SL 4, PT threshold; intentionally differs from the October sheet, which had PT 200): fixed 14500 / 7250 / 2989; NDP 31; GROSS 24739; PT 0; (E)ESI R 472; ESI R 109; E(PF) R 1740; PF R 1740; FINAL 24739; ATC 24739; CTC 28800 (the sheet's CTC was 29000).

T14 (SL 38, PT threshold with a deduction and a short month; intentionally differs from the October sheet, which had PT 200): fixed 14250 / 7125 / 3134; NDP 30.5; DED/ADD −10000; GROSS 24113.69; PT 0; (E)ESI R 456; ESI R 106; E(PF) R 1683; PF R 1683; FINAL 14113.69; ATC 14114; CTC 28041.69 (the sheet's CTC was 28241.69).

## 13. Rules

- Money in decimal (not float); store unrounded and rounded values separately, as the sheet does.
- Encrypt salary data at rest; mask account numbers everywhere except the bank transfer export.
- Never delete payroll history; revisions are new versions. Stopping a recurring item ends the schedule; it does not delete past lines.
- Keep the existing look and feel and roles (admin, sub_admin, employee).
- Do not break attendance, check-in/out, calendar or regularization.

## Environment, collections, indexes

New environment variables:

- `PAYROLL_DATA_KEY` — Fernet key used to encrypt salary structures, payroll lines, recurring items and payslip queries. Preferred in production.
- `PAYROLL_DATA_SECRET` — if `PAYROLL_DATA_KEY` is unset, a key is derived from this secret. If both are unset, the server writes `backend/payroll_data.key` (gitignored) on first use. Back this file up; without it, stored salary snapshots cannot be read.
- `KELASA_STORAGE_DIR` — optional directory for payslip copies when the shared storage helper is unavailable. Defaults to `backend/var/storage` (gitignored).

New MongoDB collections:

- `payroll_settings` — versioned branch payroll settings. Index `(branch_id, effective_month, version)`.
- `salary_structures` — versioned employee structures; amounts in `enc`. Index `(user_id, effective_from, version)`.
- `payroll_runs` — one document per branch, month and version. Unique index `(branch_id, month, version)`.
- `payroll_lines` — frozen lines; amounts in `enc`. Unique `(run_id, user_id)`. Index `(user_id, month, status)`.
- `payslip_templates` — versioned templates. Index `(branch_id, version)`.
- `payslip_queries` — employee queries; message and reply in `enc`. Index `(user_id, created_at)`.
- `payroll_recurring` — encrypted schedules. Index `(user_id, branch_id)`.

Migration: none. Collections and indexes are created on startup. Existing attendance, employees, branches and the old payroll-summary / payroll-details exports are unchanged. There is no backfill. Import a past workbook from Admin > Payroll > Import when history is needed. New months are generated as drafts after each employee has a salary structure.
