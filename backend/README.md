# Voice Agent Platform - Backend API

FastAPI backend for the AI-powered voice agent platform.

## Tech Stack

- **Framework**: FastAPI
- **Database**: PostgreSQL 17 with pgvector
- **Cache**: Redis 7
- **Package Manager**: uv
- **Voice & AI**: OpenAI GPT-4o Realtime, Deepgram, ElevenLabs
- **Telephony**: Telnyx (primary), Twilio (alternative)
- **Python**: 3.12+

## Features

- **GPT-4o Realtime**: WebRTC-based voice conversations with streaming audio
- **RAG Knowledge Base**: Vector search with pgvector for document retrieval
- **Multi-Provider Voice**: Budget (Deepgram STT), Balanced, Premium (ElevenLabs TTS)
- **Tool Calling**: CRM operations, calendar management, SMS/email
- **Embeddable Widget**: Public voice widget with configurable branding
- **Multi-Workspace**: Organizations with role-based access control
- **Telephony**: Inbound/outbound calls via Telnyx or Twilio

## Project Structure

```
backend/
├── app/
│   ├── api/              # API routes
│   │   ├── agents.py     # Agent CRUD
│   │   ├── auth.py       # Authentication
│   │   ├── crm.py        # CRM operations
│   │   ├── documents.py  # RAG document management
│   │   ├── realtime.py   # GPT-4o Realtime WebSocket
│   │   └── telephony_ws.py  # Telephony WebSocket
│   ├── core/             # Core utilities
│   │   ├── config.py     # Settings & environment
│   │   ├── security.py   # JWT & password hashing
│   │   └── rate_limit.py # Redis-based rate limiting
│   ├── db/               # Database
│   │   ├── session.py    # SQLAlchemy session
│   │   └── redis_client.py  # Redis client
│   ├── models/           # SQLAlchemy models
│   │   ├── agent.py      # Agent & pricing tiers
│   │   ├── user.py       # User & authentication
│   │   ├── workspace.py  # Workspaces & roles
│   │   ├── document.py   # RAG documents
│   │   └── contact.py    # CRM contacts
│   └── services/         # Business logic
│       ├── gpt_realtime.py      # OpenAI Realtime API
│       ├── document_processor.py # File parsing
│       ├── embedding_service.py  # Vector embeddings
│       ├── rag_service.py        # RAG retrieval
│       └── tools/               # Voice agent tools
│           ├── registry.py      # Tool registration
│           ├── crm_tools.py     # CRM operations
│           └── rag_tools.py     # Knowledge base search
├── migrations/           # Alembic migrations
│   └── versions/        # Migration history
├── tests/               # Test suite
│   ├── api/            # API endpoint tests
│   ├── services/       # Service layer tests
│   └── integration/    # Integration tests
├── Dockerfile          # Production container
├── pyproject.toml      # Dependencies & config
└── README.md           # This file
```

## Development Setup

### Prerequisites

- Python 3.12+
- PostgreSQL 17 with pgvector extension
- Redis 7
- uv package manager

### Installation

```bash
# Install uv (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install dependencies
uv sync

# Set up environment
cp .env.example .env
# Edit .env with your API keys and database URLs
```

### Database Setup

```bash
# Start PostgreSQL and Redis (via Docker Compose)
docker-compose up -d postgres redis

# Run migrations
uv run alembic upgrade head

# Enable pgvector extension (if not already enabled)
psql $DATABASE_URL -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

### Run Development Server

```bash
# Start FastAPI with hot reload
uv run uvicorn app.main:app --reload --port 8000

# API will be available at:
# - http://localhost:8000
# - Docs: http://localhost:8000/docs
# - Health: http://localhost:8000/health
```

### Run Tests

```bash
# Run all tests
uv run pytest

# Run with coverage
uv run pytest --cov=app --cov-report=html

# Run specific test file
uv run pytest tests/api/test_agents.py
```

### Code Quality

```bash
# Lint
uv run ruff check app tests --fix

# Format
uv run ruff format app tests

# Type check
uv run mypy app
```

## Production Deployment

### Railway.com (Recommended)

See [RAILWAY_DEPLOYMENT.md](../RAILWAY_DEPLOYMENT.md) for detailed instructions.

Quick setup:
1. Add PostgreSQL service with pgvector extension
2. Add Redis service
3. Deploy backend service from GitHub
4. Configure environment variables
5. Verify deployment

### Environment Variables

Required:
- `DATABASE_URL` - PostgreSQL connection string
- `REDIS_URL` - Redis connection string
- `SECRET_KEY` - Application secret (generate with `openssl rand -hex 32`)
- `JWT_SECRET_KEY` - JWT signing key (generate with `openssl rand -hex 32`)
- `OPENAI_API_KEY` - OpenAI API key for GPT-4o Realtime

Optional (based on pricing tier):
- `DEEPGRAM_API_KEY` - For budget/balanced STT
- `ELEVENLABS_API_KEY` - For premium TTS
- `TELNYX_API_KEY` - For telephony (primary)
- `TWILIO_ACCOUNT_SID` / `TWILIO_AUTH_TOKEN` - For telephony (alternative)

See `.env.railway.example` for complete list.

### Docker Build

```bash
# Build image
docker build -t voicenoob-backend .

# Run container
docker run -p 8000:8000 \
  -e DATABASE_URL=$DATABASE_URL \
  -e REDIS_URL=$REDIS_URL \
  -e OPENAI_API_KEY=$OPENAI_API_KEY \
  voicenoob-backend
```

## API Endpoints

### Authentication
- `POST /api/auth/signup` - Create account
- `POST /api/auth/login` - Login
- `GET /api/auth/me` - Get current user

### Agents
- `GET /api/agents` - List agents
- `POST /api/agents` - Create agent
- `GET /api/agents/{id}` - Get agent
- `PUT /api/agents/{id}` - Update agent
- `DELETE /api/agents/{id}` - Delete agent

### Voice Realtime
- `WS /api/realtime/{agent_id}` - GPT-4o Realtime WebSocket
- `WS /api/telephony-ws/{agent_id}` - Telephony WebSocket

### Knowledge Base (RAG)
- `POST /api/agents/{id}/documents` - Upload document
- `GET /api/agents/{id}/documents` - List documents
- `DELETE /api/documents/{id}` - Delete document

### CRM
- `GET /api/contacts` - List contacts
- `POST /api/contacts` - Create contact
- `GET /api/appointments` - List appointments
- `POST /api/appointments` - Book appointment

### Public
- `GET /api/public/embed/{public_id}/config` - Get widget config
- `POST /api/public/embed/{public_id}/session` - Start session

## Architecture

### Voice Pipeline (Pipecat)
```
Microphone → STT (Deepgram) → GPT-4o Realtime → TTS (ElevenLabs) → Speaker
                                    ↓
                              Tool Calling
                                    ↓
                          [CRM, Calendar, RAG, SMS]
```

### RAG Pipeline
```
Upload → Parse (Unstructured) → Chunk → Embed (OpenAI) → Store (pgvector)
Query → Embed → Vector Search → Retrieve → GPT-4o Context
```

### Database Schema
- **users** - User accounts
- **workspaces** - Organizations
- **agents** - Voice agent configurations
- **agent_workspaces** - Agent-workspace mapping
- **documents** - RAG knowledge base
- **document_chunks** - Vector embeddings
- **contacts** - CRM contacts
- **appointments** - Calendar bookings
- **calls** - Call history

## Performance

- **Realtime latency**: <200ms average
- **Vector search**: <50ms for 10k documents
- **Concurrent calls**: 100+ per instance
- **Database pooling**: 20 connections
- **Redis caching**: 1 hour TTL for configs

## Security

- JWT authentication with refresh tokens
- Password hashing with bcrypt
- Rate limiting (100 req/min per IP)
- CORS protection
- SQL injection prevention (SQLAlchemy ORM)
- XSS protection (FastAPI validation)
- Environment variable encryption

## Monitoring

### Health Checks
```bash
curl http://localhost:8000/health
# Returns: {"status": "healthy"}
```

### Logs
- Structured JSON logging
- Request tracing with correlation IDs
- Error tracking with stack traces
- Performance metrics

### Metrics (via Railway)
- CPU/Memory usage
- Request latency
- Error rates
- Database connections

## Troubleshooting

### Database Connection Failed
```bash
# Check PostgreSQL is running
psql $DATABASE_URL -c "SELECT 1;"

# Verify pgvector extension
psql $DATABASE_URL -c "SELECT * FROM pg_extension WHERE extname = 'vector';"
```

### Redis Connection Failed
```bash
# Test Redis connection
redis-cli -u $REDIS_URL ping
# Should return: PONG
```

### Migration Errors
```bash
# Check current migration version
uv run alembic current

# Rollback one version
uv run alembic downgrade -1

# Re-apply migrations
uv run alembic upgrade head
```

### OpenAI API Errors
- Check API key is valid
- Verify you have GPT-4o Realtime access
- Check usage limits in OpenAI dashboard

## Contributing

1. Create feature branch from `main`
2. Run tests and linting
3. Update documentation if needed
4. Submit pull request

## License

Proprietary - All rights reserved

## Support

For issues and questions:
- GitHub Issues: [link to your repo]
- Documentation: See `/docs` directory
- Railway Deployment: See `RAILWAY_DEPLOYMENT.md`
