# ಕೆಲಸ (Kelasa) — Product Requirements

## Original Problem Statement
Employee attendance and route-tracking app. Admin web panel (PWA) + native mobile app (built separately via Mobile Agent). Tracks user location, builds a path map with time, and lets a master panel map each employee's work timings.

**Branding:** ಕೆಲಸ (Kelasa) — Powered by Gyarahalli Thammayya Groups. GTG logo retained. Kannada font: **Hubballi**.

## Stack
- Frontend: React + Tailwind + Shadcn UI, React-Leaflet (maps, OpenStreetMap tiles), face-api.js, Geolocation `watchPosition`. PWA.
- Backend: FastAPI + MongoDB (Motor). Emergent-managed Google Auth. Emergent Object Storage for selfies.
- Auth: dual — httpOnly cookie + `Authorization: Bearer` fallback (localStorage `gtg_session_token`) for Samsung Internet.

## Core Requirements (implemented)
- Google auth (first user auto-admin), mandatory face recognition check-in/out (threshold < 0.55, client-side matching)
- Continuous GPS tracking (`watchPosition`), auto-pauses on breaks
- Break management, per-employee shifts, late/over-break calculation
- Admin master panel: stats, employee shift mapping, route inspector, CSV reports
- `tracking_mode` per employee (`duty_only` vs `always_on`) for native app support
- **Live Admin Map** with fading last-hour trails per worker

## Changelog
- 2026-09-08: Rebranded app to **ಕೆಲಸ (Kelasa)** across Login, AppHeader, index.html, manifest.json, backend root.
- 2026-09-08: Live Admin Map — `GET /api/admin/live` returns on-duty employees + latest ping; `LiveMap.jsx` component; AdminPanel polls every 15s; green/yellow(break) markers + on-duty side list + LIVE/PAUSE toggle. Switched all map tiles CartoDB→OpenStreetMap (CartoDB now key-gated).
- 2026-09-08: `/admin/live` now also returns each worker's last-hour `trail` (pings within 60 min). LiveMap draws a fading polyline behind each marker (older=fainter, newest=solid), per-worker hashed color used for trail + marker border; fill = status (green duty / yellow break).
- 2026-09-08: Kannada font finalized to **Hubballi** (user picked from 6-option preview). index.html loads Hubballi; Login.jsx + AppHeader.jsx apply it to ಕೆಲಸ.

## Key API Endpoints
- POST /api/auth/session, GET /api/auth/me, POST /api/auth/logout
- POST /api/face/enroll, GET /api/face/status
- POST /api/attendance/checkin | checkout | break/start | break/end
- GET /api/attendance/today | me
- POST /api/location/ping, GET /api/location/today
- GET /api/admin/stats | employees | attendance | live (live returns trail)
- GET /api/admin/employees/{id}/route
- PATCH /api/admin/employees/{id}/role | shift | tracking_mode
- DELETE /api/admin/employees/{id}/face
- GET /api/admin/reports | reports.csv

## Key Files
- backend/server.py — all routes/models (admin_live at ~line 677)
- frontend/src/pages/AdminPanel.jsx — master panel + live map integration (polls /admin/live 15s)
- frontend/src/components/LiveMap.jsx — live on-duty map + fading trails
- frontend/src/components/MapView.jsx — route inspector map
- frontend/src/lib/{api,auth,face,geo}.js

## Backlog (P1/P2)
- P1: Kannada language toggle (full app i18n)
- P1: Geofencing alerts (flag check-in outside assigned site)
- P2: Stale-ping indicator (grey marker when last ping > few min)
- P2: Payroll CSV export (monthly hours + over-breaks)
- P2: Code quality refactor sprint (AdminPanel.jsx, Dashboard.jsx, FaceCapture.jsx complexity)
- P2: Additional backend endpoints if native Mobile Agent app requests them
