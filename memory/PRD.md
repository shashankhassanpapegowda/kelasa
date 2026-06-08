# PRD: Attendance & Field Work — Powered by Gyarahalli Thammayya Groups

## Original Problem Statement
Employee attendance & route tracking app. Admin web panel and admin-cum-user Android (PWA). Track user location and create a path map with time, individually map each employee's work timing.

## Architecture
- Backend: FastAPI + MongoDB (motor). Routes under `/api`. Auth via Emergent Google OAuth (cookie + bearer fallback).
- Frontend: React 19 + Tailwind + Shadcn UI baseline, react-router-dom, axios, sonner, Leaflet/react-leaflet (CartoDB Positron tiles), @phosphor-icons/react.
- Design: Swiss & High-Contrast (Archetype 4) — Space Grotesk headings, Inter body, JetBrains Mono for tabular numerics, status colors (#00E676 on-duty / #FF3B30 off-duty / #0047FF primary).
- Auth: First user auto-promoted to admin; admins can flip roles for any other user.

## Personas
- **Employee (Field Worker)**: Logs in via Google → checks in to start a duty session → app pings location every 60s → checks out at end of day.
- **Admin/Master**: Logs in via Google → views fleet stats, employee list with on-duty badge, daily attendance log, and per-employee route inspector with timeline.

## Core Requirements (Static)
- Google OAuth login (Emergent)
- Check-in / Check-out with geolocation
- Periodic location pings (1 min) while on duty
- Today's route map with timestamped pins per employee
- Admin dashboard: stats, employees, attendance log, route inspector per date
- Mobile-responsive PWA-ready UI

## Implemented (Feb 2026)
- Backend endpoints: `/api/auth/session`, `/api/auth/me`, `/api/auth/logout`, `/api/attendance/checkin|checkout|today|me`, `/api/location/ping|today`, `/api/admin/stats|employees|attendance|employees/{id}/route|employees/{id}/role`
- Frontend pages: Login (with topographic OAuth visual), AuthCallback, Employee Dashboard (live elapsed clock, route map, history), Admin Master Panel (4-stat grid, employees list, attendance table, Route Inspector with timeline)
- Tests: 18/18 backend pytest + 7/7 frontend playwright pass

## P0/P1/P2 Backlog
- **P1**: Auto-close stale on-duty sessions older than X hours (cron); CSV export of attendance/route; geofencing for site-specific check-ins.
- **P1**: Axios 401 interceptor → redirect to login on session expiry.
- **P2**: Push notifications for low-activity alerts; offline-first PWA with background sync; weekly/monthly aggregate reports.
- **P2**: Map heatmap of high-traffic zones, manager hierarchies / teams.

## Next Action Items
- Optional: Add CSV export per employee/date.
- Optional: Geofence-based auto check-in when user enters a configured site polygon.
- Wait for user feedback / new feature requests.
