# Railway Deployment Guide

Complete guide to deploying your Voice Agent platform to Railway.app

## Prerequisites

- [Railway account](https://railway.app/) (free tier available)
- Git repository with your code
- API keys for:
  - OpenAI (required for GPT-4o Realtime & embeddings)
  - Deepgram (STT for budget/balanced tiers)
  - ElevenLabs (TTS for premium tier)
  - Telnyx or Twilio (telephony)

## Architecture Overview

Your Railway project will have 4 services:

1. **PostgreSQL** (with pgvector extension) - Database
2. **Redis** - Caching & rate limiting
3. **Backend** (FastAPI) - API server
4. **Frontend** (Next.js) - Web application

## Step-by-Step Deployment

### 1. Create New Railway Project

```bash
# Install Railway CLI (optional but recommended)
npm install -g @railway/cli

# Login to Railway
railway login

# Create new project
railway init
```

Or use the Railway dashboard: https://railway.app/new

### 2. Add PostgreSQL Service

1. Click **"+ New"** → **"Database"** → **"Add PostgreSQL"**
2. Railway auto-provisions PostgreSQL 17
3. **Important**: Enable pgvector extension:
   - Go to PostgreSQL service → **"Data"** tab
   - Click **"Query"**
   - Run: `CREATE EXTENSION IF NOT EXISTS vector;`
   - Or this will happen automatically when backend runs migrations

### 3. Add Redis Service

1. Click **"+ New"** → **"Database"** → **"Add Redis"**
2. Railway auto-provisions Redis 7

### 4. Deploy Backend Service

#### A. Add Backend Service

1. Click **"+ New"** → **"GitHub Repo"** or **"Empty Service"**
2. If using GitHub:
   - Connect your repository
   - Set **Root Directory**: `backend`
   - Railway will auto-detect Dockerfile
3. Service will be named `backend` (you can rename)

#### B. Configure Backend Environment Variables

Go to backend service → **Variables** tab and add:

```bash
# Database (auto-provided by Railway)
DATABASE_URL=${{Postgres.DATABASE_URL}}

# Redis (auto-provided by Railway)
REDIS_URL=${{Redis.REDIS_URL}}

# Server
PORT=8000
ENVIRONMENT=production
DEBUG=false

# Security (generate with: openssl rand -hex 32)
SECRET_KEY=<your-secret-key-here>
JWT_SECRET_KEY=<your-jwt-secret-here>
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30

# CORS - Will be updated after frontend deployment
ALLOWED_ORIGINS=http://localhost:3000

# OpenAI (required)
OPENAI_API_KEY=sk-...

# Deepgram (for budget/balanced tiers)
DEEPGRAM_API_KEY=...

# ElevenLabs (for premium tier)
ELEVENLABS_API_KEY=...

# Telephony (choose one)
TELNYX_API_KEY=...
TELNYX_PUBLIC_KEY=...
# OR
TWILIO_ACCOUNT_SID=...
TWILIO_AUTH_TOKEN=...
```

#### C. Configure Backend Settings

1. Go to **Settings** tab
2. **Build & Deploy**:
   - Build Command: (leave empty - uses Dockerfile)
   - Start Command: (defined in Dockerfile)
3. **Networking**:
   - Railway will auto-generate public domain
   - Copy the URL (e.g., `https://backend-production-xxxx.up.railway.app`)

#### D. Deploy Backend

Click **"Deploy"** - Railway will:
1. Build Docker image from `backend/Dockerfile`
2. Run database migrations (`alembic upgrade head`)
3. Start FastAPI server on port 8000

### 5. Deploy Frontend Service

#### A. Add Frontend Service

1. Click **"+ New"** → **"GitHub Repo"** or **"Empty Service"**
2. If using GitHub:
   - Connect same repository
   - Set **Root Directory**: `frontend`
   - Railway will auto-detect Dockerfile
3. Service will be named `frontend`

#### B. Configure Frontend Environment Variables

Go to frontend service → **Variables** tab and add:

```bash
# Backend API URL (use your backend Railway URL from step 4C)
NEXT_PUBLIC_API_URL=https://backend-production-xxxx.up.railway.app

# Environment
NODE_ENV=production
```

#### C. Configure Frontend Settings

1. Go to **Settings** tab
2. **Build & Deploy**:
   - Build Command: (leave empty - uses Dockerfile)
   - Start Command: `node server.js` (defined in Dockerfile)
3. **Networking**:
   - Railway will auto-generate public domain
   - Copy the URL (e.g., `https://frontend-production-xxxx.up.railway.app`)

#### D. Deploy Frontend

Click **"Deploy"**

### 6. Update CORS Settings

After frontend deploys, update backend CORS:

1. Go to **Backend Service** → **Variables**
2. Update `ALLOWED_ORIGINS`:
   ```bash
   ALLOWED_ORIGINS=https://frontend-production-xxxx.up.railway.app,https://yourdomain.com
   ```
3. Click **"Deploy"** to restart backend with new settings

### 7. Custom Domains (Optional)

#### Backend Domain
1. Go to Backend service → **Settings** → **Domains**
2. Click **"Add Domain"**
3. Add custom domain: `api.yourdomain.com`
4. Update DNS: Add CNAME record pointing to Railway domain

#### Frontend Domain
1. Go to Frontend service → **Settings** → **Domains**
2. Click **"Add Domain"**
3. Add custom domain: `yourdomain.com` or `app.yourdomain.com`
4. Update DNS: Add CNAME record pointing to Railway domain

#### Update Environment Variables
After adding custom domains:
- Backend: Update `ALLOWED_ORIGINS` with new frontend domain
- Frontend: Update `NEXT_PUBLIC_API_URL` with new backend domain

## Post-Deployment Verification

### 1. Check Backend Health

```bash
curl https://backend-production-xxxx.up.railway.app/health
```

Should return: `{"status": "healthy"}`

### 2. Check Database Migrations

1. Go to Backend service → **Logs**
2. Look for: `INFO  [alembic.runtime.migration] Running upgrade ...`
3. Verify pgvector extension:
   ```bash
   # In PostgreSQL Query tab
   SELECT * FROM pg_extension WHERE extname = 'vector';
   ```

### 3. Test Frontend

Visit: `https://frontend-production-xxxx.up.railway.app`
- Should load login/signup page
- Try creating an account
- Create a test agent

### 4. Test API Integration

1. Create agent in frontend
2. Check backend logs for requests
3. Verify database records in PostgreSQL

## Monitoring & Logs

### View Logs
- **Real-time**: Service → **Logs** tab
- **Search logs**: Use Railway's log search
- **Download logs**: Click download icon

### Metrics
- **CPU/Memory**: Service → **Metrics** tab
- **Deployments**: Service → **Deployments** tab
- **Usage**: Project → **Usage** tab

### Set Up Alerts
1. Project Settings → **Integrations**
2. Add Slack/Discord webhook
3. Configure alerts for:
   - Deployment failures
   - High CPU/memory usage
   - Service crashes

## Troubleshooting

### Backend Won't Start

**Check logs for:**
- Database connection errors → Verify `DATABASE_URL`
- Redis connection errors → Verify `REDIS_URL`
- Missing environment variables → Check Variables tab
- Port conflicts → Railway uses `PORT` env var

**Solutions:**
```bash
# Test database connection
railway run psql $DATABASE_URL

# Test Redis connection
railway run redis-cli -u $REDIS_URL ping

# View environment variables
railway variables
```

### Frontend Build Fails

**Common issues:**
- Missing `NEXT_PUBLIC_API_URL` → Add to Variables
- TypeScript errors → Run `npm run check` locally first
- Memory limit exceeded → Increase service resources

**Solutions:**
```bash
# Build locally to check errors
cd frontend
npm run build

# Check Railway build logs
railway logs --service frontend
```

### Database Migration Fails

**If migrations fail on startup:**
```bash
# Connect to Railway backend shell
railway run --service backend bash

# Run migrations manually
uv run alembic upgrade head

# Check current migration version
uv run alembic current
```

### pgvector Extension Missing

```sql
-- Connect to PostgreSQL via Railway console
CREATE EXTENSION IF NOT EXISTS vector;

-- Verify installation
SELECT * FROM pg_extension WHERE extname = 'vector';
```

### CORS Errors

**Symptoms:** Frontend can't connect to backend

**Solutions:**
1. Check backend `ALLOWED_ORIGINS` includes frontend domain
2. Verify frontend `NEXT_PUBLIC_API_URL` is correct
3. Check browser console for exact CORS error
4. Ensure no trailing slashes in URLs

## Scaling & Performance

### Vertical Scaling
1. Service → **Settings** → **Resources**
2. Upgrade to Pro plan for:
   - More CPU/RAM
   - Faster builds
   - Custom resources

### Horizontal Scaling
1. Backend can scale to multiple replicas
2. Frontend can scale to multiple replicas
3. PostgreSQL and Redis are single-instance

**Enable replicas:**
```json
// railway.json
{
  "deploy": {
    "numReplicas": 2
  }
}
```

### Performance Tips
- Enable Redis caching for frequent queries
- Use PostgreSQL connection pooling
- Monitor query performance with pg_stat_statements
- Add database indexes for slow queries
- Use CDN for frontend static assets

## Cost Optimization

### Railway Pricing (as of 2024)
- **Free Tier**: $5/month credit (good for testing)
- **Pro Plan**: $20/month + usage
- **Resources**:
  - PostgreSQL: ~$5-10/month (based on storage)
  - Redis: ~$3-5/month
  - Backend: ~$5-10/month
  - Frontend: ~$5-10/month

### Reduce Costs
1. Use free tier for development
2. Scale down resources during off-hours
3. Enable auto-sleep for non-production services
4. Monitor usage in Project → **Usage** tab
5. Set spending limits in Project Settings

## Backup & Disaster Recovery

### Database Backups

**Automated backups** (Pro plan):
- Daily automatic backups
- Point-in-time recovery
- Access via PostgreSQL service → **Backups** tab

**Manual backups:**
```bash
# Export database
railway run pg_dump $DATABASE_URL > backup.sql

# Import database
railway run psql $DATABASE_URL < backup.sql
```

### Restore from Backup
1. PostgreSQL service → **Backups** tab
2. Select backup to restore
3. Click **"Restore"**
4. Confirm restoration

## Security Best Practices

1. **Environment Variables**
   - Never commit secrets to Git
   - Use Railway's encrypted variables
   - Rotate keys regularly

2. **Database**
   - Use strong passwords
   - Enable SSL connections (Railway default)
   - Limit access to internal network

3. **API Keys**
   - Store in Railway variables
   - Use separate keys for prod/dev
   - Monitor usage in provider dashboards

4. **CORS**
   - Only allow trusted domains
   - Don't use wildcards (`*`) in production

5. **Rate Limiting**
   - Configured in backend (Redis-based)
   - Monitor for abuse
   - Adjust limits as needed

## Next Steps

After successful deployment:

1. **Set up monitoring**: Integrate with Sentry, LogRocket, or DataDog
2. **Configure CI/CD**: Auto-deploy on Git push
3. **Add health checks**: Monitor service uptime
4. **Set up staging environment**: Create separate Railway project
5. **Configure backups**: Schedule regular database backups
6. **Add custom domains**: Point your domain to Railway
7. **Enable HTTPS**: Railway provides SSL certificates automatically

## Support & Resources

- [Railway Documentation](https://docs.railway.app/)
- [Railway Discord](https://discord.gg/railway)
- [Railway Status Page](https://status.railway.app/)
- [Railway CLI Reference](https://docs.railway.app/develop/cli)

## Useful Commands

```bash
# Link local project to Railway
railway link

# View environment variables
railway variables

# Run command in Railway environment
railway run <command>

# Stream logs
railway logs

# Connect to database
railway run psql

# Connect to Redis
railway run redis-cli

# SSH into service
railway shell

# Deploy from local
railway up

# Check service status
railway status
```

---

**Need help?** Check Railway docs or ask in their Discord community!
