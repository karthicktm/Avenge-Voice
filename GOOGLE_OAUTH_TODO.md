# Google OAuth + Gluer AI Email Config — Testing Checklist

> Implemented on 2026-03-04. Ready to test after 2026-03-06.

---

## 1. Google Cloud Console Setup

1. Go to https://console.cloud.google.com/
2. Create a project (or select existing) → **APIs & Services** → **Credentials**
3. Click **Create Credentials** → **OAuth 2.0 Client ID**
4. Application type: **Web application**
5. Add **Authorized redirect URIs**:
   - `https://<your-backend>.railway.app/api/v1/auth/google/callback`
   - `http://localhost:8000/api/v1/auth/google/callback` (for local dev)
6. Copy **Client ID** and **Client Secret**

---

## 2. Environment Variables to Set

### Backend (Railway or `.env`)

```bash
# one.com SMTP (for support@gluer.ai)
SMTP_HOST=send.one.com
SMTP_PORT=587
SMTP_USER=support@gluer.ai
SMTP_PASSWORD=<one.com email password>
FROM_EMAIL=support@gluer.ai
FROM_NAME=Gluer AI

# Google OAuth
GOOGLE_CLIENT_ID=<from Google Cloud Console>
GOOGLE_CLIENT_SECRET=<from Google Cloud Console>

# URLs
PUBLIC_URL=https://<your-backend>.railway.app
FRONTEND_URL=https://gluer.ai
```

---

## 3. Test Cases

### Email (SMTP via one.com)
- [ ] Register a new account → verify 6-digit code email arrives **from support@gluer.ai**
- [ ] Email subject and body shows **Gluer AI** branding (not Avenge AI)
- [ ] Password reset email also shows Gluer AI branding

### Google OAuth — Login
- [ ] Click "Sign in with Google" on `/login` → Google consent screen appears
- [ ] After consent → redirected to `/auth/callback?token=...` → lands on `/dashboard`
- [ ] Token is stored in `localStorage` as `access_token`

### Google OAuth — New User
- [ ] Sign in with a Google account that has **never registered** → org + workspace auto-created
- [ ] User role is `USER` (not admin)
- [ ] Email is marked as verified (no OTP needed)

### Google OAuth — Existing Email User
- [ ] Register normally with email (e.g. `foo@gmail.com`) + password
- [ ] Then click "Sign in with Google" using the same Google account (`foo@gmail.com`)
- [ ] Accounts link correctly → same user in DB, `provider` updated to `google`

### Google OAuth — Register Page
- [ ] "Sign up with Google" button on account details step works the same as login

### Role / Access
- [ ] Super admin route guards still work for existing super_admin users
- [ ] Google OAuth users get `USER` role by default

### SMTP Fallback
- [ ] If `RESEND_API_KEY` is **not** set in system settings, emails still send via SMTP (one.com)
- [ ] If neither Resend nor SMTP is configured → `503 Email service not configured`

---

## 4. Files Changed (for reference)

| File | What changed |
|------|-------------|
| `backend/app/core/config.py` | Email defaults → gluer.ai; added `GOOGLE_CLIENT_ID/SECRET`; added gluer.ai CORS |
| `backend/app/api/auth.py` | Added `GET /api/v1/auth/google` and `GET /api/v1/auth/google/callback` |
| `backend/app/services/email_service.py` | Branding → Gluer AI; added SMTP fallback |
| `backend/app/services/signup_service.py` | `hashed_password: str | None` (supports OAuth users) |
| `backend/pyproject.toml` | Added `google-auth>=2.0.0` |
| `frontend/src/app/auth/callback/page.tsx` | **New** — handles OAuth redirect with token |
| `frontend/src/app/login/page.tsx` | Added Google sign-in button |
| `frontend/src/app/register/page.tsx` | Added Google sign-up button |
