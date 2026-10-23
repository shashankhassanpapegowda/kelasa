# ಕೆಲಸ (Kelasa) — Product Requirements

## Original Problem Statement
Employee attendance and route-tracking app, now expanding into a full **employee management platform**. Admin web panel (PWA) + native mobile app (built separately via Mobile Agent). Tracks user location, builds a path map with time, and lets a master panel map each employee's work timings.

**Branding:** ಕೆಲಸ (Kelasa) — Powered by Gyarahalli Thammayya Groups (footer only; header shows ಕೆಲಸ / KELASA). Kannada font: **Hubballi**.

## Stack
- Frontend: React + Tailwind + Shadcn UI, React-Leaflet (OpenStreetMap tiles), Recharts, face-api.js, Geolocation `watchPosition`. PWA.
- Backend: FastAPI + MongoDB (Motor). Emergent-managed Google Auth. Emergent Object Storage for selfies.
- Auth: dual — httpOnly cookie + `Authorization: Bearer` fallback (localStorage `gtg_session_token`) for Samsung Internet. **Do not remove the Bearer fallback.**

## Roles
- `admin` — everything, all employees.
- `sub_admin` — scoped console: their reportees (`manager_id`) + their `managed_departments` + `managed_sites`. No Organisation/Activity tabs, no role changes, no leave-type editing, cannot edit own shift/assignment/face.
- `employee` — My Day + My Leave.

## Core Requirements (implemented)
- Google auth (first user auto-admin), mandatory face recognition check-in/out (threshold < 0.55)
- Continuous GPS tracking (`watchPosition`), auto-pauses on breaks; Live Admin Map with fading last-hour trails
- Break management, per-employee shifts, late/over-break calculation, CSV reports
- `tracking_mode` per employee (`duty_only` vs `always_on`)
- **Leave management**: configurable leave types (yearly quota / monthly accrual / no tracking), balances, apply, half-day, overlap + quota guards, holiday-aware day counting, approve/reject with note, cancel
- **Tabbed admin console**: Overview (7 stats + attendance trend + leave-by-type + dept headcount), Live Map, Team, Leave, Holidays, Notices, Organisation, Activity
- **Manual employee add/delete**, departments, sites, Reports-To, designation, phone, employee code
- **Holiday calendar** (excluded from absent days + leave day counts), **announcements**, **admin activity log**

## Changelog
- 2026-09-08: Rebrand to ಕೆಲಸ (Kelasa); Live Admin Map + last-hour fading trails; OSM tiles; Hubballi font; generalised homepage copy.
- 2026-09-08: Removed group name from header; live map labels → hover-only tooltips (verified iteration_4).
- 2026-10-22: **Leave management + powerful admin/sub-admin console.**
  - Backend: `require_manager`, `scoped_user_ids`, `ensure_in_scope`, `ensure_manages_other`, `log_activity`; all admin endpoints scoped for sub-admins.
  - Leave: types CRUD, balances (yearly/monthly/unlimited), request/cancel, decide (self-approval blocked), manager balance matrix.
  - Org: departments, sites, sub-admin coverage chips; manual employee create/delete/assignment; reports now show Leave/Holiday/Absent days.
  - Holidays, announcements (dashboard banner), activity log, `/admin/analytics` charts.
  - Frontend: `AdminPanel.jsx` is now a tab shell; tabs live in `components/admin/*`; new `/leave` page for employees.
  - Verified: iteration_5 + iteration_6 test reports (42/43 backend pytest, all frontend fixes confirmed; mobile 390px Team rows fixed).

- 2026-10-23: **Email & password login (Google sign-in removed from the UI).**
  - bcrypt password hashes, server-side sessions reused (no JWT), min 8 chars, per-IP+email lockout after 5 fails (15 min) plus a 10-attempt per-account cap.
  - Admin sets the first password when adding an employee → `must_change_password` forces /change-password (enforced in the router AND in `get_current_user`).
  - Admin/sub-admin "Reset password" action kills the member's sessions; sub-admins cannot touch admin or sub-admin accounts, nor themselves.
  - Forgot password → single-use 1-hour token emailed through the Emergent-managed Resend proxy; /reset-password page sets the new password and clears all sessions.
  - New pages: `ChangePassword.jsx`, `ResetPassword.jsx`; `Login.jsx` rewritten as an email/password form.
  - Verified: iteration_7 report (16/16 backend pytest + full browser flows) plus follow-up curl/browser checks of every fix.
  - **Email delivery is currently paused**: the proxy returns `insufficient_credits` for this app owner, so reset emails are not reaching inboxes until credits/auto top-up are added.

## Key API Endpoints
- Auth: POST /api/auth/login (email+password), /api/auth/change-password, /api/auth/forgot-password, /api/auth/reset-password, /api/auth/logout, GET /api/auth/me (legacy POST /api/auth/session kept but unused by the UI)
- Passwords: PATCH /api/admin/employees/{id}/password (manager, scoped, cannot target another manager)
- Face: POST /api/face/enroll, GET /api/face/status
- Attendance: POST /api/attendance/checkin | checkout | break/start | break/end, GET /api/attendance/today | me
- Location: POST /api/location/ping, GET /api/location/today
- Admin (manager-scoped): GET /api/admin/stats | employees | attendance | live | analytics | reports | reports.csv, GET /api/admin/employees/{id}/route
- Employees: POST /api/admin/employees, DELETE /api/admin/employees/{id}, PATCH /api/admin/employees/{id}/shift | assignment | tracking_mode(admin) | role(admin) | scope(admin), DELETE .../face
- Org: GET /api/admin/org, POST/DELETE /api/admin/org/departments|sites (admin)
- Leave: GET /api/leave/types | balance | me, POST /api/leave/request, POST /api/leave/{id}/cancel, GET /api/admin/leave | /api/admin/leave/balances, POST /api/admin/leave/{id}/decide, POST/PATCH/DELETE /api/admin/leave-types (admin)
- Calendar/Notices/Audit: GET /api/holidays, POST/DELETE /api/admin/holidays (admin), GET /api/announcements, POST/DELETE /api/admin/announcements, GET /api/admin/activity (admin)

## Deliberate product decisions
- **Any admin or sub-admin can decide anyone's leave** (user's explicit choice). Only self-approval is blocked. A tester flagged this as an IDOR — it is intentional, revisit only if the user asks for team-restricted approvals.
- Leave days count calendar days minus declared holidays. Weekends are counted (no weekly-off config exists yet).
- A leave range crossing 31 Dec is charged entirely to the start year.

## Key Files
- backend/server.py (1562 lines — split into routers when convenient)
- frontend/src/pages/AdminPanel.jsx (tab shell), LeavePage.jsx, Dashboard.jsx, Reports.jsx
- frontend/src/components/admin/{OverviewTab,LiveTab,TeamTab,LeaveTab,OrgTab,CalendarTab,NoticesTab,ActivityTab,PhotoModal}.jsx
- frontend/src/components/{LiveMap,MapView,AppHeader,FaceCapture,AuthPhoto}.jsx
- frontend/src/lib/{api,auth,face,geo,format}.js

## Backlog (P1/P2)
- P1: Payroll-ready monthly export (hours + leaves + over-breaks) — user said "plan payroll later"
- P1: Weekly-off configuration so weekends are excluded from leave day counts
- P1: Kannada language toggle (full app i18n)
- P2: Geofencing alerts (flag check-in outside assigned site)
- P2: Stale-ping indicator (grey marker when last ping > few min); marker clustering
- P2: Leave calendar view (who is away this month) + email/WhatsApp notification on leave decision
- P2: Split server.py into routers; shadcn date-picker instead of native inputs
- P2: Redeploy — production still runs code from before the 2026-10-22 release
