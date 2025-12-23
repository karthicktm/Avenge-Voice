# Railway Quick Setup Guide

Copy-paste guide for deploying to Railway.com

## 1. Add Database Services

### PostgreSQL
```
Railway → "+ New" → "Database" → "Add PostgreSQL"
```
After provisioning, run this SQL:
```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

### Redis
```
Railway → "+ New" → "Database" → "Add Redis"
```

---

## 2. Backend Service Environment Variables

**Service Settings:**
- Root Directory: `backend`
- Watch Paths: `backend/**`
- Builder: `DOCKERFILE`

**Environment Variables** (copy these to Backend → Variables tab):

```bash
# Database & Redis (using private endpoints for security and performance)
# These use Railway's internal network (*.railway.internal)
DATABASE_URL=${{Postgres.DATABASE_PRIVATE_URL}}
REDIS_URL=${{Redis.REDIS_PRIVATE_URL}}

# Alternative: Use default URLs (also private)
# DATABASE_URL=${{Postgres.DATABASE_URL}}
# REDIS_URL=${{Redis.REDIS_URL}}

# Server
PORT=8000
ENVIRONMENT=production
DEBUG=false

# Security (generate with: openssl rand -hex 32)
SECRET_KEY=PASTE_YOUR_32_CHAR_SECRET_HERE
JWT_SECRET_KEY=PASTE_ANOTHER_32_CHAR_SECRET_HERE
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30

# CORS (update after frontend deploys)
CORS_ORIGINS=["http://localhost:3000"]

# OpenAI (REQUIRED for voice and RAG)
OPENAI_API_KEY=sk-proj-...

# Deepgram (for STT in budget/balanced tiers)
DEEPGRAM_API_KEY=...

# ElevenLabs (for TTS in premium tier)
ELEVENLABS_API_KEY=...

# Telephony - Telnyx (recommended)
TELNYX_API_KEY=...
TELNYX_PUBLIC_KEY=...

# OR Telephony - Twilio (alternative)
TWILIO_ACCOUNT_SID=...
TWILIO_AUTH_TOKEN=...
```

---

## 3. Frontend Service Environment Variables

**Service Settings:**
- Root Directory: `frontend`
- Watch Paths: `frontend/**`
- Builder: `DOCKERFILE`

**Environment Variables** (copy these to Frontend → Variables tab):

```bash
# Backend API URL (update after backend deploys)
NEXT_PUBLIC_API_URL=https://backend-production-XXXX.up.railway.app

# Environment
NODE_ENV=production
```

---

## 4. Post-Deployment Updates

### After Backend Deploys:
1. Copy backend URL: `https://backend-production-XXXX.up.railway.app`
2. Update Frontend → Variables:
   ```
   NEXT_PUBLIC_API_URL=<paste-backend-url>
   ```
3. Redeploy frontend

### After Frontend Deploys:
1. Copy frontend URL: `https://frontend-production-YYYY.up.railway.app`
2. Update Backend → Variables:
   ```
   CORS_ORIGINS=["https://frontend-production-YYYY.up.railway.app"]
   ```
3. Redeploy backend

---

## 5. Generate Secrets

Run locally to generate secure secrets:

```bash
# SECRET_KEY
openssl rand -hex 32

# JWT_SECRET_KEY
openssl rand -hex 32
```

Copy the outputs and paste into Railway variables.

---

## 6. Verify Deployment

### Backend Health Check:
```bash
curl https://backend-production-XXXX.up.railway.app/health
```
Should return: `{"status":"healthy"}`

### Frontend:
Visit: `https://frontend-production-YYYY.up.railway.app`
Should show login page.

---

## Troubleshooting

### Backend won't start:
- Check logs for missing env vars
- Verify DATABASE_URL and REDIS_URL are set
- Ensure PostgreSQL has pgvector extension

### Frontend can't connect to backend:
- Check NEXT_PUBLIC_API_URL is correct
- Verify backend CORS_ORIGINS includes frontend URL
- Check browser console for errors

### Database connection fails:
- Verify Postgres service is running
- Check DATABASE_URL format
- Look for connection timeout errors in logs

---

## Service Dependencies

Deploy in this order:
1. PostgreSQL ✅
2. Redis ✅
3. Backend ✅ (depends on PostgreSQL + Redis)
4. Frontend ✅ (depends on Backend)

---

## Cost Estimate

- **Free Tier**: $5/month credit (good for testing)
- **Production**: ~$25-45/month
  - PostgreSQL: $5-15
  - Redis: $3-8
  - Backend: $5-10
  - Frontend: $5-10

---

## Important Notes

✅ Use `${{Service.VARIABLE}}` syntax for service references
✅ Railway auto-provides DATABASE_URL and REDIS_URL
✅ Use internal DNS (*.railway.internal) for service-to-service communication
✅ Enable pgvector extension after PostgreSQL provisioning
✅ Update CORS after each deployment

🚫 Don't deploy docker-compose.yml (local development only)
🚫 Don't commit secrets to Git
🚫 Don't use wildcards in CORS_ORIGINS in production
