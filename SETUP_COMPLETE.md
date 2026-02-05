# Reroute v3 - Project Setup Complete ✅

## Environment Setup (using uv)

Both workspaces are now configured with `uv` for fast dependency management:

### Main branch (~/Desktop/projects/active/reroute-v3)
- ✅ Virtual environment created with `uv`
- ✅ All dependencies installed (173 packages in 486ms!)
- ✅ All 64 tests passing
- ✅ README.md created

### Feature branch (.worktrees/ai-route-generation)
- ✅ Virtual environment created with `uv`
- ✅ All dependencies installed
- ✅ Has uncommitted route model changes

## Quick Commands

```bash
# Main branch
cd ~/Desktop/projects/active/reroute-v3
source .venv/bin/activate
uvicorn app.main:app --reload  # Start dev server

# AI route generation branch
cd ~/Desktop/projects/active/reroute-v3/.worktrees/ai-route-generation
source .venv/bin/activate
```

## Current Project Status

### ✅ Working Features
- FastAPI backend with Auth0 authentication
- Strava OAuth integration
- Training plan CRUD (plans, blocks, workouts)
- AI plan generation using pydantic-ai
- User management with admin capabilities
- Database migrations (Alembic)
- Comprehensive test suite (64 tests, all passing)

### 🚧 Next Steps (AI Route Generation Feature)

The comprehensive design document is ready at:
`docs/plans/2025-10-31-ai-route-generation-design.md`

**Implementation roadmap:**

#### Phase 1: Foundation (Start Here)
1. **Database migrations** - Create new tables:
   - `routes` table (stores generated routes)
   - `user_routing_preferences` table (home location, preferences)
   - Add columns to `workouts` table (route_generation_status, error)

2. **Repository layer**:
   - `app/repositories/route_repository.py`
   - `app/repositories/user_preferences_repository.py`

3. **API endpoints**:
   - GET/PATCH `/v1/users/me/routing-preferences`
   - GET `/v1/workouts/{workout_id}/route`

#### Phase 2: Core Route Generation
4. **Graphhopper integration**:
   - Set up Graphhopper server (design mentions "already in place")
   - Create `app/services/graphhopper_client.py`
   - Basic route generation endpoint

#### Phase 3: AI Intelligence  
5. **Route ranking agent**:
   - `app/ai/route_agent.py` (similar to existing `plan_agent.py`)
   - Connector generation logic
   - Composite route assembly

#### Phase 4: Automation
6. **Weekly scheduler**:
   - Add APScheduler dependency
   - `app/tasks/route_generation.py`
   - Background job for Sunday 8pm generation

#### Phase 5: Polish
7. Testing, validation, monitoring

## Configuration Files Updated

- `pyproject.toml` - Fixed package discovery, removed README requirement
- `.env` - Contains Auth0, Strava, OpenAI credentials (already configured)
- `README.md` - Created with setup instructions

## Warnings to Address (Low Priority)

173 deprecation warnings in tests about `datetime.utcnow()`. Should be updated to:
```python
# Old
datetime.utcnow()

# New  
datetime.now(datetime.UTC)
```

Affected files:
- `app/models/base.py` (timestamps)
- `app/repositories/user.py` (line 54)

## Recommendations

1. **Start with Phase 1** - Create database migrations for route tables
2. **Verify Graphhopper setup** - Design mentions it's "already in place" but needs verification
3. **Consider adding APScheduler** - Not in dependencies yet, needed for Phase 4
4. **Fix datetime warnings** - Use `datetime.now(datetime.UTC)` instead of `utcnow()`

## Next Development Session

Suggested starting point:
```bash
cd ~/Desktop/projects/active/reroute-v3/.worktrees/ai-route-generation
source .venv/bin/activate

# Create migration for routes table
alembic revision --autogenerate -m "add routes and user routing preferences tables"

# Review and edit the migration
# Then apply it
alembic upgrade head
```
