# PRD: Attendance & Field Work — Powered by Gyarahalli Thammayya Groups

## Original Problem Statement
Employee attendance & route tracking app. Admin web panel and admin-cum-user Android (PWA). Track user location and create a path map with time, individually map each employee's work timing.

## Architecture
- Backend: FastAPI + MongoDB (motor). Routes under `/api`. Auth via Emergent Google OAuth (cookie + bearer fallback).
- Frontend: React 19 + Tailwind + Shadcn UI baseline, react-router-dom, axios, sonner, Leaflet/react-leaflet (CartoDB Positron tiles), @phosphor-icons/react.
- Face Recognition: face-api.js (client-side, 128-dim descriptor, threshold 0.55). Photos in Emergent Object Storage.
- Design: Swiss & High-Contrast (Archetype 4) — Space Grotesk headings, Inter body, JetBrains Mono for tabular numerics, status colors (#00E676 on-duty / #FF3B30 off-duty / #0047FF primary).

## Personas
- **Employee (Field Worker)**: Logs in via Google → enrolls face once → face check-in starts duty → app pings location every 60s → face check-out ends day.
- **Admin/Master**: Logs in via Google → views fleet stats, employee list, daily attendance log with photos, per-employee route inspector with timeline.

## Implemented (Feb 2026)
- Backend endpoints: `/api/auth/*`, `/api/attendance/*`, `/api/location/*`, `/api/admin/*`, `/api/face/enroll`, `/api/face/status`, `/api/files/{path}`, `/api/admin/employees/{id}/face` (reset)
- Face recognition (mandatory) with photo proof at check-in + check-out
- High-accuracy GPS (watchPosition, accuracy threshold, low-accuracy ping rejection)
- Admin photo modal: photo + timestamp + GPS + accuracy + match score + OSM map link
- Custom GTG branding, PWA icon, manifest
- Tests: 18/18 backend pytest + 7/7 frontend playwright pass
- **Deployed to production**: `https://employee-locator-4.emergent.host`

## ✅ Critical Fixes Applied (Feb 2026)
- `server.py` file-download handler: explicit error chaining (`raise … from None`)
- `auth.jsx` logout catch: now logs via `console.warn`
- `FaceCapture.jsx` detection tick catch: now logs via `console.warn`

## 🗓️ Scheduled Follow-up Sprint — Code Quality Refactor

### Sprint goal
Reduce cyclomatic complexity, eliminate code smells, improve testability — **zero behavior change**.

### Backend (Python)
- **P1** Refactor `tests/test_attendance_api.py::test_full_checkin_ping_checkout_flow` (CCN 22, 60 lines) → split into `test_checkin`, `test_ping_updates`, `test_checkout` with shared helpers.
- **P1** Replace 21 `is`-vs-`==` constant-literal comparisons across `tests/test_attendance_api.py` and `server.py` (lines 144, 346, 406).
- **P2** `tests/conftest.py::_make_session` (8 args) → wrap in a `@dataclass SessionSpec` config.
- **P2** Move `FACE_MATCH_THRESHOLD` (currently hardcoded 0.55) to env var `FACE_MATCH_THRESHOLD`.
- **P2** Switch storage `requests.put`/`get` to `httpx.AsyncClient` (avoid blocking the event loop on uploads).
- **P2** Add `asyncio.Lock` around `init_storage()` global mutation.

### Frontend (React)
- **P1** `AdminPanel.jsx` (CCN 44, 292 lines) → extract `EmployeeTable`, `EmployeeRow`, `AttendanceTable`, `RouteInspector`, `PhotoModal` components.
- **P1** `Dashboard.jsx` (CCN 36, 251 lines) → extract `StatusCard`, `RouteCard`, `HistoryList`; move ping/elapsed logic into custom hooks `usePingInterval`, `useElapsedClock`.
- **P1** `FaceCapture.jsx` (CCN 32, 131 lines) → extract `useFaceDetection` hook + `CameraView` component.
- **P2** Replace 11 nested ternaries with helper fns (e.g. `accClass()`, `getDutyLabel()`).
- **P2** Memoize Leaflet `pathOptions`/`tileLayer` props in `MapView.jsx` with `useMemo`.
- **P2** Memoize `AuthProvider` context value in `auth.jsx` with `useMemo`.

### Tooling
- **P1** Add `eslint-plugin-react-hooks` exhaustive-deps rule + Husky pre-commit hook.
- **P2** Add Ruff/Black pre-commit for Python.

### Definition of Done
- All current tests (18 backend + 7 frontend) still pass.
- Cyclomatic complexity ≤ 12 on every function.
- No `console.warn`s removed; all kept or replaced with `toast` where user-visible.
- New components have data-testid props matching existing test IDs (no test breakage).

## Pre-existing Backlog (Product features, not refactors)
- **P1**: Auto-close stale on-duty sessions (cron) + axios 401 interceptor for session expiry
- **P1**: CSV/Excel export of attendance + routes (payroll-grade)
- **P1**: Geofencing — block check-in outside assigned site polygons
- **P1**: Tighten `/api/files/{path}` so non-admins only fetch their own photos
- **P2**: IST/local timezone "today" boundary for reports
- **P2**: Native Android `.apk` via Capacitor wrapper (background location tracking)
- **P2**: Push notifications, offline-first PWA, weekly/monthly aggregate reports
- **P2**: Map heatmap, manager hierarchies, teams

## Next Action Items
1. **Refactor Sprint** (above) — pick when you're ready to start it.
2. Or pick next product feature: geofencing / CSV export / native APK.
