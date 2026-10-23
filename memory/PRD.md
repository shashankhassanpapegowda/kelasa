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

## 2026-06 — Branch geofencing, field staff, editable employee email
- Admin Console → **Branches** tab (admin only): add/rename/delete branches, pin location on map (click, place search via backend `/api/admin/geocode` → Photon → Nominatim → Open-Meteo fallback, or "My location"), radius 10–10000 m.
- Punch in/out blocked (403) unless inside ANY branch circle (radius + min(GPS accuracy, 50 m) slack). No pinned branches ⇒ geofencing off. Branch name saved on attendance (`check_in_branch`/`check_out_branch`).
- `field_staff` flag per employee (Team → Edit checkbox) bypasses geofence. `PATCH /api/admin/employees/{id}/field_staff`.
- Employee dashboard pre-checks zone and shows "Inside X / N m outside X"; camera won't open outside.
- Live Map draws branch circles. Team tab: Branch filter, "Site" renamed "Branch". Sub-admin coverage chips = Branches (managed_sites).
- Edit existing employee name + email (validated, unique, lowercased; email change signs them out).
- Tested: iteration_8 (backend 21/21, frontend flows pass).

### Backlog
- P1: Per-branch geofence report (punches outside / by branch) in Reports + CSV branch column
- P1: Payroll export (deferred by user)
- P2: Auto check-out when leaving geofence, marker clustering, multilingual

## 2026-06 — Branch report + leaving-area alerts
- Reports → "By Branch" view: branch cards (punch count, employees, left-area alerts), per-branch punch tables; "Punch Log CSV" (`/api/admin/reports/punches.csv`) with Punch In/Out Branch columns. Employee CSV gained Home Branch + Punched At.
- Leaving-area alerts: location pings outside every branch circle (non field staff) open an alert (`geofence_alerts`), updated while outside, resolved when back inside or on checkout. Admin console red banner + beep (mute toggle), ACK, MAP; Live Map shows OUTSIDE tag/red marker. `GET /api/admin/geofence-alerts`, `POST /api/admin/geofence-alerts/{id}/ack`.
- Field staff punches still record the branch they were inside (not blocked).
- Pings during breaks are skipped, so alerts don't update during breaks.
- Not done: pinning Bengaluru HQ / Tumkur Yard — user did not provide locations.
- Tested: iteration_9 (29/29 backend, frontend 100%).

## 2026-06 — Alert history + long-absence escalation
- Admin setting "repeat alert every N min" (5–480, default 30) — `GET/PUT /api/admin/settings/geofence`, Alerts tab (admin only card).
- Open alerts carry minutes_outside / escalation_level / needs_attention; ACK stores acknowledged_level, so the banner re-alerts (beep + toast "still outside · N min") at every next interval until they return or check out.
- Resolved alerts freeze final_minutes/final_level so history doesn't change if the setting changes.
- Alert history: console "Alerts" tab (admin + sub-admin, scoped) and Reports "Left Area" view (uses applied range); day-by-day blocks with left/returned/away/near/repeats/acknowledged; CSV `/api/admin/geofence-alerts/history.csv`. Screen times use the profile timezone, same as the CSV.
- Known: days are grouped by attendance (check-in) date, so overnight-shift exits count under the shift's start day.
- Tested: iteration_10 (30/30 backend, frontend 100%) + post-fix regression 30/30.

## 2026-06 — Phone alert push (Web Push)
- VAPID keys in backend/.env (VAPID_PUBLIC_KEY / VAPID_PRIVATE_KEY / VAPID_SUBJECT) — don't regenerate, it breaks existing subscriptions. pywebpush.
- `/api/push/public-key|status|subscribe|test` (managers only). `push_subscriptions` collection, one record per device; dead endpoints (404/410) are removed automatically.
- track_zone sends a push on the first leave and on each repeat interval (pushed_level), while the employee's phone keeps sending location. Recipients: all admins plus sub-admins whose scope includes the employee. One notification per alert (tag = alert_id).
- frontend/public/sw.js (push + click opens /admin#live or #alerts), lib/push.js, PhoneAlertsCard on Alerts tab (iPhone: Add to Home Screen first).
- Tested: iteration_11 (backend 6/6 + 51 regression, frontend 100% with mocked push). Real-phone delivery is not testable in headless.

## 2026-06 — Per-phone sound/silent + employee leave push
- `push_subscriptions.silent` per device; PATCH /api/push/subscribe {endpoint, silent}; service worker sends silent notifications without vibration.
- Push endpoints open to all signed-in users. Employees turn notifications on from the Leave page card, or from the offer shown ~2 s after they apply.
- Leave approve/reject sends the employee "Leave approved/rejected · <type> · dates" plus "Note: <reason>". Tapping it opens /leave.
- Tested: iteration_12 (18/18 backend, frontend 100%).
- Known stale test: test_iter6_leave_fixes::test_sub_admin_cannot_decide_out_of_scope (it contradicts the user's choice that any manager can approve any leave).

## 2026-06 — Announcement push
- Notices tab has an "Also send to everyone's phone" checkbox (ticked by default) → `notify_phones`. Sends "Notice: <title>" plus the body (up to 180 chars) to every subscribed device except the poster's; the number of devices reached is saved as `pushed_devices`.
- Per-device switches `leave_updates` / `announcements` (both on by default) via PATCH /api/push/subscribe. Employee card (Leave page) shows both; the admin card shows Announcements.
- Self-tested via curl with fake endpoints: devices that opted out and the author's device are skipped; unticked notices aren't pushed.

## 2026-06 — Employee profile + celebrations
- /profile page (header avatar + "Profile" nav): photo upload (resized to a 512px square, stored in object storage as `users.avatar_path`), date of birth / wedding anniversary / joining date, EPF UAN (12 digits) / ESI (10 or 17 digits), bank account (holder, number 9–18 digits, IFSC, bank name).
- `employee_profiles` collection (sensitive data kept apart from users). Bank changes go into `bank_change_requests` (pending → approved/rejected/superseded/cancelled). Only main admins approve, from the Team tab panel; the employee gets a push on the decision.
- Sensitive view: the employee, admins, and sub-admins for their own team (`GET /api/admin/employees/{id}/profile`, PROFILE button in the Team tab).
- `/api/celebrations`: today plus the next 7 days — birthdays, wedding and work anniversaries (years ≥ 1); birth year never shown. Celebrations card appears on My Day and the Console Overview.
- /api/files now limits face/check-in photos to their owner or a manager in scope; avatars are visible to all signed-in users. AuthPhoto caches blob URLs.
- Tested: iteration_13 (29/29 backend, frontend flows pass) and every reported issue fixed.

## 2026-06 — Morning celebrations push, profile nudge, payroll export, private wishes
- Cron `.emergent/crons.yml` morning-celebrations runs at 08:00 Asia/Kolkata → POST /api/cron/celebrations (Bearer WEBHOOK_CRON_SECRET in backend/.env, at most one send per IST day via `cron_runs.key`). Celebrants get "Happy <occasions>, <first>!"; everyone else gets "Celebrations today: …". Per-device `celebrations` switch.
- ProfileNudge (bank/UAN/ESI; ESI "not applicable" option; a pending bank change counts as half) on My Day (below the check-in card) and the Profile page.
- `GET /api/admin/reports/payroll-details.csv` (admin = everyone incl. admin accounts; sub-admin = their team). Button in Reports.
- Private wishes: `wishes` collection, one conversation per sender + celebrant + occasion; a wish can be sent from 3 days before to 7 days after the occasion (relative to today); replies; unread badge on the "Wishes" nav item; push to the other person. Wish buttons on the celebrations card; /wishes page.
- Tested: iteration_14 (backend 100%, frontend 100%) + fixes (multi-occasion greeting, kind Literal, placeholders, badge spacing).

## 2026-06 — Celebration banner
- CelebrationBanner (frontend only, uses /api/celebrations?days=0) on My Day, Profile and Console Overview. The person celebrating sees a big dark banner ("Happy Birthday & 4-year Work Anniversary, Ravi!" plus a wish-count link to /wishes); everyone else sees a yellow "Celebrating today" strip with Wish / WISHED. A canvas-confetti burst plays on every page open (bigger for the celebrant) and is skipped when the phone's reduce-motion setting is on.
- Self-tested via screenshots (390px + desktop, no overflow).
