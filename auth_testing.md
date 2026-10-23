# Auth Testing — Kelasa email & password login

Sessions are server-side rows in `user_sessions` (not JWT). Password login issues the same
`session_token` cookie (httpOnly, secure, SameSite=None) plus a Bearer fallback that the
frontend stores in localStorage under `gtg_session_token`.

## Endpoints
- POST /api/auth/login `{email, password}` → `{user, session_token}` + cookie
- POST /api/auth/change-password `{current_password, new_password}` (authenticated)
- POST /api/auth/forgot-password `{email}` → always `{ok:true}` (no account enumeration), emails a reset link
- POST /api/auth/reset-password `{token, new_password}` → clears all sessions for that user
- PATCH /api/admin/employees/{user_id}/password `{password}` (admin/sub-admin, scoped) → sets temp password, forces change, kills their sessions
- POST /api/auth/logout

## Rules
- bcrypt hashes (`$2b$...`), never returned by any endpoint
- Minimum 8 characters
- 5 failed attempts per `{ip}:{email}` → 15 minute lockout (429), cleared on success
- Reset tokens: single-use, 1 hour TTL (`password_reset_tokens`, TTL index on `expires_at`)
- `must_change_password` forces the /change-password screen before anything else

## Legacy Google session (for automation)
Creating a session row directly still authenticates, which is how the seeded
`test_session_*` tokens in /app/memory/test_credentials.md work.

## MongoDB checks
```
mongosh test_database --quiet --eval 'db.users.findOne({email:"emp1.test@gtgroups.local"},{password_hash:1,must_change_password:1})'
mongosh test_database --quiet --eval 'db.login_attempts.find().toArray()'
mongosh test_database --quiet --eval 'db.password_reset_tokens.find().toArray()'
```

## API checks
```
API=https://employee-locator-4.preview.emergentagent.com/api
curl -s -X POST $API/auth/login -H 'Content-Type: application/json' -d '{"email":"...","password":"..."}'
curl -s $API/auth/me -H "Authorization: Bearer <session_token>"
```

## Email
Reset emails go out through the Emergent-managed Resend proxy (`EMERGENT_EMAIL_KEY`,
`EMAIL_FROM_NAME=Kelasa`). Link base comes from `APP_PUBLIC_URL`. Use `delivered@resend.dev`
as the recipient for delivery tests only.
