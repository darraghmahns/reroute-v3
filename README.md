# Reroute Backend

FastAPI backend for AI-powered cycling training route generation.

## Quick Start

### Setup with uv (recommended)

```bash
# Create virtual environment
uv venv

# Activate
source .venv/bin/activate  # macOS/Linux
# or
.venv\Scripts\activate     # Windows

# Install dependencies
uv pip install -e ".[dev]"
```

### Run the app

```bash
# Development server with auto-reload
uvicorn app.main:app --reload

# Production
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### Database

```bash
# Run migrations
alembic upgrade head

# Create new migration
alembic revision --autogenerate -m "description"
```

### Testing

```bash
# Run all tests
pytest

# With coverage
pytest --cov=app --cov-report=html
```

## Project Structure

```
app/
├── ai/              # AI agents (plan generation, route ranking)
├── api/             # API endpoints
├── core/            # Core configuration
├── db/              # Database setup
├── models/          # SQLAlchemy models
├── repositories/    # Data access layer
├── schemas/         # Pydantic schemas
├── security/        # Auth/security
├── services/        # Business logic
└── tasks/           # Background tasks

migrations/          # Alembic migrations
tests/              # Test suite
docs/               # Documentation
```

## Current Status

✅ Implemented:
- FastAPI backend with Auth0 authentication
- Strava integration
- Training plan models (plans, blocks, workouts)
- AI plan generation agent

🚧 In Progress (see docs/plans/2025-10-31-ai-route-generation-design.md):
- AI route generation system
- Route discovery & ranking
- Graphhopper integration
- Weekly route scheduling
