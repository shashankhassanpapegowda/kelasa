# Auth testing: email and password login

Sessions are server-side rows in `user_sessions` (not JWT). Password login issues a `session_token` cookie (httpOnly, secure, SameSite=None) plus a Bearer fallback that the frontend stores in localStorage under `gtg_session_token`.

## Endpoints
- `POST /api/auth/login` `{email, password}` → `{user, session_token}` + cookie
- `POST /api/auth/change-password` `{current_password, new_password}` (authenticated)
- `POST /api/auth/forgot-password` `{email}` → always `{ok:true}` (no account enumeration); emails a reset link
- `POST /api/auth/reset-password` `{token, new_password}` → clears all sessions for that user
- `PATCH /api/admin/employees/{user_id}/password` `{password}` (admin/sub-admin, scoped) → temporary password, forces change, ends their sessions
- `POST /api/auth/logout`

## Rules
- bcrypt hashes, never returned by any endpoint; minimum 8 characters
- 5 failed attempts per `{ip}:{email}` → 15 minute lockout (429), cleared on success
- Reset tokens: single-use, 1 hour TTL (`password_reset_tokens`, TTL index on `expires_at`)
- `must_change_password` forces the /change-password screen before anything else

## Email
Reset emails go out over SMTP (`SMTP_*` variables). The link base comes from `APP_PUBLIC_URL`.

## API checks
```
API=http://localhost:8000/api
curl -s -X POST $API/auth/login -H 'Content-Type: application/json' -d '{"email":"...","password":"..."}'
curl -s $API/auth/me -H "Authorization: Bearer <session_token>"
```
