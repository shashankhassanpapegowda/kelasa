# ಕೆಲಸ (Kelasa)

Employee attendance, leave and payroll app for Gyarahalli Thammayya Groups (GT Groups).
It is an installable PWA (React) on a FastAPI + MongoDB backend, self-hosted at https://kelasa.gtgroups.in.

## What it does

- Check-in / check-out and breaks, each with a selfie and GPS; live map and route trails for managers.
- Roles: `admin` (all branches), `sub_admin` (their own branch/team), `employee`.
- Leave: one paid leave day per employee per month, no carry-forward, anything beyond it is loss of pay (LOP). Optional per-branch Saturday/Monday/holiday "sandwich" LOP rule.
- Attendance corrections (admin only), holidays, announcements (company-wide or by branch), "Absent today" list on the dashboard.
- Payroll and payslips (admin and the employee's own payslip only), monthly summary aligned with payroll NDP.
- Push notifications (VAPID web push) and email (SMTP).

## Layout

| Path | What |
|---|---|
| `backend/` | FastAPI app (`server.py`), payroll and staff-rule modules, tests |
| `frontend/` | React 19 app built with CRA/Craco (`yarn build`) |
| `docs/` | Specs, cron schedules, auth testing notes |

## Configuration (environment variables)

Names only; never commit values.

`MONGO_URL`, `DB_NAME`, `CORS_ORIGINS`, `APP_PUBLIC_URL`, `ADMIN_EMAIL`, `ADMIN_PASSWORD`,
`VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_SUBJECT`, `WEBHOOK_CRON_SECRET`,
`SMTP_HOST`, `SMTP_PORT`, `SMTP_STARTTLS`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`,
`EMAIL_FROM_NAME`, `EMAIL_REPLY_TO`, `LOCAL_STORAGE_DIR` (default `/data/uploads`),
`PAYROLL_DATA_KEY` (encrypts payroll data; losing it makes payroll unreadable), `SELFIE_RETENTION_MONTHS`.

Photos and payslip files are stored on local disk under `LOCAL_STORAGE_DIR/gtg-attendance/...`.
The `gtg-attendance` prefix is stored in the database; do not rename it.

## Scheduled jobs

All times are Asia/Kolkata. Each job is a `POST` to the backend with `Authorization: Bearer $WEBHOOK_CRON_SECRET`.

| Job | Schedule | Endpoint |
|---|---|---|
| morning-celebrations | daily 08:00 | `/api/cron/celebrations` |
| checkout-reminders | every 15 minutes | `/api/cron/checkout-reminders` |
| missed-checkout-digest | daily 08:00 | `/api/cron/missed-checkout-digest` |
| selfie-purge | daily 03:00 | `/api/cron/selfie-purge` |

Endpoints acknowledge with 2xx immediately and do the work in the background.
See `docs/crons.md` for what each does.

## Run locally

```
# backend
cd backend && pip install -r requirements.txt
uvicorn server:app --reload --port 8000     # needs MongoDB and the env vars above

# frontend
cd frontend && yarn install --frozen-lockfile
yarn start                                  # http://localhost:3000
yarn build
```

Backend tests are API tests: set `REACT_APP_BACKEND_URL` (default `http://localhost:8000`) and run `pytest backend/tests`.
