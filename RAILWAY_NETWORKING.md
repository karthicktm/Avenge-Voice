# Railway Private Networking Guide

## Network Architecture

### Private Network (Recommended) ✅

```
┌─────────────────────────────────────────────────────────┐
│                Railway Internal Network                  │
│                    (Private, Secure)                     │
│                                                          │
│  ┌──────────┐  private   ┌────────────┐  private       │
│  │ Frontend │──────────→ │  Backend   │──────────→     │
│  │ Service  │            │  Service   │               │
│  └──────────┘            └────────────┘               │
│                                │                        │
│                                │ private                │
│                                ↓                        │
│                      ┌──────────────────┐              │
│                      │   PostgreSQL     │              │
│                      │ postgres.railway │              │
│                      │    .internal     │              │
│                      └──────────────────┘              │
│                                │                        │
│                                │ private                │
│                                ↓                        │
│                      ┌──────────────────┐              │
│                      │      Redis       │              │
│                      │ redis.railway    │              │
│                      │    .internal     │              │
│                      └──────────────────┘              │
└─────────────────────────────────────────────────────────┘
         ↑
         │ HTTPS (Public)
         │
   ┌──────────┐
   │  Users   │
   │ Internet │
   └──────────┘
```

**Benefits:**
- ✅ Fast (internal network, <1ms latency)
- ✅ Secure (not exposed to internet)
- ✅ Free (no egress bandwidth charges)
- ✅ Simple (automatic service discovery)

### Public Network (Not Recommended for Production) ❌

```
                    Internet
                       │
      ┌────────────────┼────────────────┐
      │                │                │
      ↓                ↓                ↓
 ┌──────────┐   ┌────────────┐   ┌──────────┐
 │ Frontend │   │  Backend   │   │PostgreSQL│
 │ (public) │   │  (public)  │   │ (public) │
 └──────────┘   └────────────┘   └──────────┘
                      │
                      └──→ Public URL: slow, insecure, costs money
```

**Drawbacks:**
- ❌ Slower (routes through public internet)
- ❌ Less secure (database exposed to internet)
- ❌ Costs money (egress bandwidth charges)
- ❌ Complex (need to manage firewall rules)

---

## Railway Variables Explained

### PostgreSQL Variables

| Variable | Example Value | Network | Use Case |
|----------|--------------|---------|----------|
| `DATABASE_URL` | `postgresql://user:pass@postgres.railway.internal:5432/db` | **Private** | ✅ Default (recommended) |
| `DATABASE_PRIVATE_URL` | `postgresql://user:pass@postgres.railway.internal:5432/db` | **Private** | ✅ Explicit private |
| `DATABASE_PUBLIC_URL` | `postgresql://user:pass@abc.railway.app:1234/db` | Public | ❌ External only |

### Redis Variables

| Variable | Example Value | Network | Use Case |
|----------|--------------|---------|----------|
| `REDIS_URL` | `redis://default:pass@redis.railway.internal:6379` | **Private** | ✅ Default (recommended) |
| `REDIS_PRIVATE_URL` | `redis://default:pass@redis.railway.internal:6379` | **Private** | ✅ Explicit private |
| `REDIS_PUBLIC_URL` | `redis://default:pass@xyz.railway.app:5678` | Public | ❌ External only |

---

## Configuration Examples

### ✅ RECOMMENDED: Use Private Endpoints

**Backend Environment Variables:**
```bash
DATABASE_URL=${{Postgres.DATABASE_PRIVATE_URL}}
REDIS_URL=${{Redis.REDIS_PRIVATE_URL}}
```

**Result:**
```bash
DATABASE_URL=postgresql://postgres:abc123@postgres.railway.internal:5432/railway
REDIS_URL=redis://default:xyz789@redis.railway.internal:6379
```

**Backend connects via:**
- `postgres.railway.internal:5432` (private, fast, free)
- `redis.railway.internal:6379` (private, fast, free)

### ❌ NOT RECOMMENDED: Public Endpoints

**Backend Environment Variables:**
```bash
DATABASE_URL=${{Postgres.DATABASE_PUBLIC_URL}}
REDIS_URL=${{Redis.REDIS_PUBLIC_URL}}
```

**Result:**
```bash
DATABASE_URL=postgresql://postgres:abc123@abc.railway.app:12345/railway
REDIS_URL=redis://default:xyz789@xyz.railway.app:54321
```

**Backend connects via:**
- `abc.railway.app:12345` (public internet, slow, costs money)
- `xyz.railway.app:54321` (public internet, slow, costs money)

---

## When to Use Public Endpoints

Use public endpoints **only** for:
- 🔧 Database GUI tools (e.g., pgAdmin, DBeaver)
- 🔧 Local development connecting to Railway database
- 🔧 External monitoring tools
- 🔧 Data migration from external sources

**Never use public endpoints for:**
- ❌ Service-to-service communication (Backend → Database)
- ❌ Production application connections
- ❌ High-traffic endpoints

---

## Security Best Practices

### ✅ Do This:

1. **Use private endpoints for all service-to-service communication:**
   ```bash
   DATABASE_URL=${{Postgres.DATABASE_PRIVATE_URL}}
   REDIS_URL=${{Redis.REDIS_PRIVATE_URL}}
   ```

2. **Use Railway's service references** (auto-updates if credentials change):
   ```bash
   # ✅ Good - uses service reference
   DATABASE_URL=${{Postgres.DATABASE_PRIVATE_URL}}

   # ❌ Bad - hardcoded, breaks if credentials rotate
   DATABASE_URL=postgresql://user:pass@postgres.railway.internal:5432/db
   ```

3. **Keep public endpoints disabled** unless you need external access

### ❌ Don't Do This:

1. **Don't hardcode connection strings:**
   ```bash
   # ❌ Bad - what if password changes?
   DATABASE_URL=postgresql://postgres:mypassword@postgres.railway.internal:5432/db
   ```

2. **Don't use public URLs for service communication:**
   ```bash
   # ❌ Bad - slow, expensive, insecure
   DATABASE_URL=${{Postgres.DATABASE_PUBLIC_URL}}
   ```

3. **Don't expose database to internet** unless absolutely necessary

---

## Verification

After deploying, check your backend logs:

### ✅ Good - Using Private Network:
```
INFO: Connecting to database at postgres.railway.internal:5432
INFO: Connected to Redis at redis.railway.internal:6379
```

### ❌ Bad - Using Public Network:
```
INFO: Connecting to database at abc-xyz.railway.app:12345
INFO: Connected to Redis at def-uvw.railway.app:54321
```

---

## Troubleshooting

### Connection Refused on Private Network

**Error:**
```
sqlalchemy.exc.OperationalError: could not connect to server: Connection refused
```

**Solution:**
1. Verify PostgreSQL service is running
2. Check DATABASE_URL is set correctly
3. Ensure services are in the same Railway project
4. Check service logs for errors

### Slow Database Connections

**Symptoms:**
- Queries taking >100ms
- High latency
- Timeout errors

**Likely Cause:** Using public endpoint instead of private

**Solution:**
```bash
# Change from:
DATABASE_URL=${{Postgres.DATABASE_PUBLIC_URL}}

# To:
DATABASE_URL=${{Postgres.DATABASE_PRIVATE_URL}}
```

### Bandwidth Costs Too High

**Cause:** Using public endpoints for service communication

**Solution:** Switch all service-to-service communication to private endpoints

**Expected bandwidth costs:**
- Private network: **$0** (free)
- Public egress: **$0.10/GB** (expensive)

---

## Summary

| Aspect | Private Network | Public Network |
|--------|----------------|----------------|
| **Speed** | <1ms latency | 50-200ms latency |
| **Security** | Internal only | Exposed to internet |
| **Cost** | Free | $0.10/GB egress |
| **Setup** | Automatic | Manual firewall |
| **Use Case** | ✅ Service-to-service | ❌ External access only |

**Recommendation:** Always use private endpoints for production workloads.
