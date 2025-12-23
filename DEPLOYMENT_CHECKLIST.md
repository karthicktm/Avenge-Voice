# Railway Deployment Checklist

Quick checklist for deploying to Railway.app

## Pre-Deployment

- [ ] Push all code changes to Git repository
- [ ] Verify Docker builds locally:
  ```bash
  # Test backend
  cd backend && docker build -t backend-test .

  # Test frontend
  cd frontend && docker build -t frontend-test .
  ```
- [ ] Collect all required API keys:
  - [ ] OpenAI API key
  - [ ] Deepgram API key
  - [ ] ElevenLabs API key (if using premium tier)
  - [ ] Telnyx/Twilio credentials
- [ ] Generate secure secrets:
  ```bash
  openssl rand -hex 32  # For SECRET_KEY
  openssl rand -hex 32  # For JWT_SECRET_KEY
  ```

## Railway Setup

- [ ] Create Railway account at https://railway.app
- [ ] Install Railway CLI: `npm install -g @railway/cli`
- [ ] Login to Railway: `railway login`
- [ ] Create new project: `railway init`

## Service Deployment Order

### 1. PostgreSQL
- [ ] Add PostgreSQL service
- [ ] Wait for provisioning to complete
- [ ] Enable pgvector extension:
  ```sql
  CREATE EXTENSION IF NOT EXISTS vector;
  ```
- [ ] Copy `DATABASE_URL` from service variables

### 2. Redis
- [ ] Add Redis service
- [ ] Wait for provisioning to complete
- [ ] Copy `REDIS_URL` from service variables

### 3. Backend
- [ ] Add backend service from GitHub repo
- [ ] Set root directory to `backend`
- [ ] Add all environment variables from `.env.railway.example`
- [ ] Reference database: `${{Postgres.DATABASE_URL}}`
- [ ] Reference Redis: `${{Redis.REDIS_URL}}`
- [ ] Deploy and wait for completion
- [ ] Copy backend public URL
- [ ] Verify health endpoint: `https://<backend-url>/health`

### 4. Frontend
- [ ] Add frontend service from GitHub repo
- [ ] Set root directory to `frontend`
- [ ] Add environment variables:
  - [ ] `NEXT_PUBLIC_API_URL` = backend URL from step 3
  - [ ] `NODE_ENV=production`
- [ ] Deploy and wait for completion
- [ ] Copy frontend public URL

### 5. Update CORS
- [ ] Go to backend service variables
- [ ] Update `ALLOWED_ORIGINS` with frontend URL
- [ ] Redeploy backend service

## Post-Deployment Verification

### Backend
- [ ] Check health endpoint: `curl https://<backend-url>/health`
- [ ] Verify logs show successful startup
- [ ] Confirm database migrations ran
- [ ] Test API: `curl https://<backend-url>/api/v1/agents` (should return 401)

### Frontend
- [ ] Visit frontend URL in browser
- [ ] Check browser console for errors
- [ ] Try creating an account
- [ ] Login and access dashboard
- [ ] Create a test agent
- [ ] Verify agent appears in list

### Database
- [ ] PostgreSQL service → Query tab
- [ ] Verify tables exist: `\dt`
- [ ] Check pgvector: `SELECT * FROM pg_extension WHERE extname = 'vector';`
- [ ] Verify agent created: `SELECT * FROM agents LIMIT 1;`

### Redis
- [ ] Check Redis service logs
- [ ] Verify no connection errors in backend logs

## Optional Enhancements

- [ ] Add custom domain to backend
- [ ] Add custom domain to frontend
- [ ] Update environment variables with custom domains
- [ ] Set up monitoring/alerting
- [ ] Configure CI/CD auto-deploy
- [ ] Create staging environment
- [ ] Set up automated backups
- [ ] Enable Railway Pro features

## Environment Variables Reference

### Backend Service
```bash
DATABASE_URL=${{Postgres.DATABASE_URL}}
REDIS_URL=${{Redis.REDIS_URL}}
PORT=8000
ENVIRONMENT=production
DEBUG=false
SECRET_KEY=<generated-secret>
JWT_SECRET_KEY=<generated-secret>
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
ALLOWED_ORIGINS=https://<frontend-url>
OPENAI_API_KEY=sk-...
DEEPGRAM_API_KEY=...
ELEVENLABS_API_KEY=...
TELNYX_API_KEY=...
TELNYX_PUBLIC_KEY=...
```

### Frontend Service
```bash
NEXT_PUBLIC_API_URL=https://<backend-url>
NODE_ENV=production
```

## Troubleshooting Quick Fixes

### Backend won't start
```bash
railway logs --service backend
# Check for missing env vars or database connection issues
```

### Frontend build fails
```bash
# Build locally first to catch errors
cd frontend && npm run build
```

### CORS errors
- Ensure `ALLOWED_ORIGINS` in backend includes frontend URL
- No trailing slashes in URLs
- Check browser console for exact error

### Database connection fails
- Verify `DATABASE_URL` is set
- Check PostgreSQL service is running
- Try: `railway run --service backend psql $DATABASE_URL`

### Migrations fail
```bash
railway run --service backend bash
uv run alembic upgrade head
```

## Rollback Plan

If deployment fails:
1. Check service logs for errors
2. Rollback to previous deployment:
   - Service → Deployments → Click previous deployment → Redeploy
3. Verify services are working
4. Fix issues locally and redeploy

## Support

- Documentation: [RAILWAY_DEPLOYMENT.md](./RAILWAY_DEPLOYMENT.md)
- Railway Docs: https://docs.railway.app
- Railway Discord: https://discord.gg/railway
- Railway Status: https://status.railway.app

---

**Estimated deployment time:** 30-45 minutes

**Recommended approach:** Deploy in order (PostgreSQL → Redis → Backend → Frontend)
