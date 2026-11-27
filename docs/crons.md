# Scheduled jobs

All times Asia/Kolkata. Production runs them from a small cron container that calls `POST <backend>/api/cron/<job>` with `Authorization: Bearer $WEBHOOK_CRON_SECRET`.

- **morning-celebrations** — `0 8 * * *` → `/api/cron/celebrations`. 8am phone notification about today's birthdays and anniversaries. At most one send per IST day (`cron_runs.key`). Celebrants get "Happy <occasions>, <first>!"; everyone else gets "Celebrations today: …".
- **checkout-reminders** — `*/15 * * * *` → `/api/cron/checkout-reminders`. Every 15 minutes, reminds on-duty staff on their phone once their shift has ended.
- **missed-checkout-digest** — `0 8 * * *` → `/api/cron/missed-checkout-digest`. 8am phone summary to admins and sub-admins of who missed check-out yesterday.
- **selfie-purge** — `0 3 * * *` → `/api/cron/selfie-purge`. Clears check-in/out selfies older than the retention window (the current Asia/Kolkata month plus `SELFIE_RETENTION_MONTHS` previous months, default 1). Enrolment photos and avatars are kept.

Operational notes
- Do not regenerate the VAPID keys: existing push subscriptions stop working.
- Keep the Bearer-token fallback for sessions (`Authorization: Bearer`, token in localStorage `gtg_session_token`); some Android browsers drop the cookie.
