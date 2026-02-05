# AI Route Generation Design

**Date:** 2025-10-31
**Status:** Approved
**Priority:** Route quality over speed

## Overview

Add intelligent route generation to Reroute that creates safe, realistic cycling routes for each workout in a user's training plan. Routes are generated weekly, start from the user's home location, and are matched to workout requirements using AI analysis.

## Design Principles

1. **Quality First:** Prefer community-validated Strava routes over generated routes
2. **Safety Critical:** Never route on highways or through impossible terrain
3. **Intelligent Matching:** Use AI to understand workout intent and match terrain to training needs
4. **Weekly Regeneration:** Routes generated fresh each week as plans adapt to performance
5. **Graceful Degradation:** System continues functioning even when components fail

## High-Level Architecture

### Three Main Components

**1. Weekly Route Generation Service**
- Scheduled background job runs Sunday 8pm (configurable)
- Processes all users with active training plans
- Generates routes for upcoming week's workouts (Monday-Sunday)
- Asynchronous processing, one user failure doesn't block others

**2. Route Discovery & Ranking Engine**
- **Search Phase:** Query multiple sources for candidate routes
  - Strava routes (user's saved routes + community routes near home)
  - Local route database (cached good routes)
- **Ranking Phase:** AI agent scores candidates 0-1 based on workout fit
  - Analyzes workout requirements (duration, intensity, description)
  - Matches terrain to training needs (flat for intervals, hilly for climbing work)
  - Returns top route with reasoning for transparency
- **Selection:** Pick best route if score >0.7, otherwise fall back to generation

**3. Fallback Route Generator**
- Uses self-hosted Graphhopper server for route generation
- Applies user preferences: avoid highways, prefer bike paths, max grade limits
- Cycling-optimized profile with elevation awareness
- Validates generated routes for safety before acceptance

### Route Connector Logic

Since Strava routes rarely start exactly at a user's home:

1. **Search Strategy:** Find Strava routes at 70-90% of target distance (leaving room for connectors)
2. **Connector Generation:** Use Graphhopper to create:
   - Outbound: Home → Strava route start
   - Return: Strava route end → Home (if not a loop)
3. **Route Assembly:** Merge into unified route: Home → Connector → Strava → Connector → Home
4. **Validation:** Reject if combined route exceeds target by >20%

**Example:** 50km workout → find 40km Strava route 3km away → generate 3km+3km connectors → 46km total

## Data Model

### New `routes` Table
```sql
id                      INTEGER PRIMARY KEY
workout_id              INTEGER UNIQUE NOT NULL (FK to workouts)
source                  TEXT NOT NULL  -- 'strava', 'graphhopper', 'composite'
strava_route_id         INTEGER NULL
name                    TEXT NOT NULL
distance_km             REAL NOT NULL
elevation_gain_m        REAL NOT NULL
gpx_data                TEXT NOT NULL  -- Full GPX/GeoJSON geometry
polyline                TEXT NOT NULL  -- Encoded polyline for map display
is_composite            BOOLEAN DEFAULT FALSE
connector_distance_km   REAL NULL      -- If composite, distance added by connectors
ai_match_score          REAL NULL      -- 0-1 score from AI ranking
ai_match_reasoning      TEXT NULL      -- Why AI chose this route
generated_at            TIMESTAMP NOT NULL
created_at              TIMESTAMP NOT NULL
updated_at              TIMESTAMP NOT NULL
```

### New `user_routing_preferences` Table
```sql
user_id                 INTEGER PRIMARY KEY (FK to users)
home_latitude           REAL NOT NULL
home_longitude          REAL NOT NULL
avoid_highways          BOOLEAN DEFAULT TRUE
prefer_bike_paths       BOOLEAN DEFAULT TRUE
max_grade_percent       INTEGER DEFAULT 15
avoid_high_traffic      BOOLEAN DEFAULT TRUE
search_radius_km        INTEGER DEFAULT 25
created_at              TIMESTAMP NOT NULL
updated_at              TIMESTAMP NOT NULL
```

### Modified `workouts` Table
Add columns:
- `route_generation_status` - ENUM('pending', 'generated', 'failed', 'skipped')
- `route_generation_error` - TEXT NULL (error message if failed)

## AI Agent Implementation

### Route Ranking Agent (`app/ai/route_agent.py`)

Following existing `plan_agent.py` pattern using pydantic-ai:

**System Prompt:**
```
You are an expert cycling coach analyzing routes for training workouts.
Score each route 0-1 on how well it matches the workout requirements.

Consider:
- Distance match (closer to target = higher score)
- Terrain suitability (flat for intervals/recovery, hilly for climbing/tempo, rolling for endurance)
- Elevation gain appropriate for intensity level
- Route quality indicators (popularity, recent activity)

Return scores with clear reasoning for transparency.
```

**Input Context:**
```python
@dataclass
class RouteRankingContext:
    workout: WorkoutSchema          # duration, distance, intensity, description
    candidates: list[CandidateRoute]  # 3-10 Strava routes with elevation profiles
    user_preferences: UserRoutingPreferences
```

**Output Schema:**
```python
@dataclass
class RouteRankingResult:
    ranked_routes: list[RankedRoute]  # sorted by score, highest first

@dataclass
class RankedRoute:
    route_id: str
    score: float              # 0-1
    reasoning: str            # why this score
    distance_km: float
    elevation_gain_m: float
```

**AI Behaviors:**
- **Smart Route Matching:** Understand workout intent from descriptions
  - "threshold intervals" → prefer sustained flat sections or steady climbs
  - "recovery ride" → flat, low-stress terrain
  - "climbing work" → routes with significant elevation
- **Terrain-to-Workout Mapping:** Match route characteristics to workout structure
  - High intensity + short duration → flat or consistent gradient
  - Endurance + long duration → rolling terrain, varied
  - VO2max intervals → steep climbs or flat with turnaround points

## Route Generation Flow

### Per-Workout Generation Process

```python
async def generate_route_for_workout(user: User, workout: Workout) -> Route:
    # 1. Search Strava routes
    candidates = await search_strava_routes(
        center=(user.preferences.home_latitude, user.preferences.home_longitude),
        radius_km=user.preferences.search_radius_km,
        target_distance_min=workout.distance_km * 0.7,  # Allow room for connectors
        target_distance_max=workout.distance_km * 0.9
    )

    # 2. AI ranking
    try:
        ranking_result = await route_ranking_agent.run(
            RouteRankingContext(
                workout=workout,
                candidates=candidates,
                user_preferences=user.preferences
            )
        )
        best_route = ranking_result.ranked_routes[0]
    except Exception:
        # Fallback to rule-based scoring
        best_route = simple_distance_based_ranking(candidates, workout)

    # 3. Use best route or generate new one
    if best_route and best_route.score > 0.7:
        # Generate connectors
        outbound = await graphhopper_route(
            user.preferences.home,
            best_route.start_point,
            user.preferences
        )
        if not best_route.is_loop:
            return_connector = await graphhopper_route(
                best_route.end_point,
                user.preferences.home,
                user.preferences
            )

        # Combine into composite route
        route = combine_routes(outbound, best_route, return_connector)
        route.source = 'composite'
        route.ai_match_score = best_route.score
        route.ai_match_reasoning = best_route.reasoning
    else:
        # Generate full route with Graphhopper
        route = await graphhopper_generate_route(
            start=user.preferences.home,
            target_distance_km=workout.distance_km,
            preferences=user.preferences
        )
        route.source = 'graphhopper'

    # 4. Validate and save
    validate_route_safety(route)  # No highways, realistic geometry
    await route_repository.create(route)
    workout.route_generation_status = 'generated'

    return route
```

## Weekly Scheduling

### Background Task (`app/tasks/route_generation.py`)

**Schedule:** Sunday 8pm (configurable via `ROUTE_GENERATION_SCHEDULE` env var)

**Task Logic:**
```python
async def generate_weekly_routes():
    active_users = await user_repository.get_users_with_active_plans()

    next_monday = get_next_monday()
    next_sunday = next_monday + timedelta(days=6)

    for user in active_users:
        try:
            workouts = await workout_repository.get_by_date_range(
                user_id=user.id,
                start_date=next_monday,
                end_date=next_sunday
            )

            for workout in workouts:
                if workout.route_generation_status == 'pending':
                    await generate_route_for_workout(user, workout)

        except Exception as e:
            log.error(f"Route generation failed for user {user.id}: {e}")
            # Continue with next user - don't let one failure block others
```

**Task Scheduling Options:**
- **MVP:** APScheduler (simple, in-process)
- **Production:** Celery + Redis (distributed, better monitoring)

## API Endpoints

### New Routes (`app/api/v1/routes.py`)

**1. Get Workout Route**
```
GET /v1/workouts/{workout_id}/route
Authorization: Required
Response: RouteResponse
```

**2. Manually Trigger Route Generation**
```
POST /v1/workouts/{workout_id}/generate-route
Authorization: Required
Response: 202 Accepted (async job started)
```

**3. Get User Routing Preferences**
```
GET /v1/users/me/routing-preferences
Authorization: Required
Response: UserRoutingPreferences
```

**4. Update User Routing Preferences**
```
PATCH /v1/users/me/routing-preferences
Authorization: Required
Body: {
  home_latitude?: float,
  home_longitude?: float,
  avoid_highways?: boolean,
  prefer_bike_paths?: boolean,
  max_grade_percent?: integer,
  search_radius_km?: integer
}
Response: UserRoutingPreferences
```

### Response Schema

```python
class RouteResponse(BaseModel):
    id: int
    workout_id: int
    source: str  # 'strava', 'graphhopper', 'composite'
    name: str
    distance_km: float
    elevation_gain_m: float
    polyline: str  # Encoded polyline for map rendering
    gpx_url: str  # Download link
    ai_match_score: float | None
    ai_match_reasoning: str | None
    is_composite: bool
    connector_distance_km: float | None
    generated_at: datetime
```

### Existing Endpoint Updates

**Modify `GET /v1/plans/{plan_id}` response:**
- Include `route_generation_status` in each WorkoutSchema
- Frontend can show badges: "Route ready", "Generating...", "Failed"

## Error Handling & Fallbacks

### Graceful Degradation Chain

**1. Strava API Failure** (rate limit, timeout, unavailable)
- Log warning
- Skip Strava search phase
- Jump directly to Graphhopper generation
- System continues working without community routes

**2. Graphhopper Server Unavailable**
- Retry with exponential backoff (3 attempts: 1s, 2s, 4s)
- If all attempts fail:
  - Set `workout.route_generation_status = 'failed'`
  - Store error in `workout.route_generation_error`
  - User can manually retry later via API

**3. AI Ranking Agent Failure** (OpenAI timeout, quota exceeded)
- Fall back to rule-based scoring:
  ```python
  def simple_distance_based_ranking(candidates, workout):
      for route in candidates:
          distance_diff = abs(route.distance_km - workout.distance_km)
          score = max(0, 1 - (distance_diff / workout.distance_km))
          route.score = score
      return sorted(candidates, key=lambda r: r.score, reverse=True)[0]
  ```
- Log degraded mode for monitoring
- System continues with reduced intelligence

**4. No Suitable Routes Found**
- After exhausting search + generation attempts
- Set `workout.route_generation_status = 'skipped'`
- Provide user-facing message: "Couldn't generate safe route, manual upload recommended"
- Offer manual GPX upload option

**5. Invalid Route Geometry**
- Validate GPX has minimum 10 coordinate points
- Check distances are realistic (connectors <50km)
- Verify no gaps in route geometry
- Reject and try next candidate or regenerate

### Observability

**Logging:**
- All route generation attempts with timing, source, AI scores
- Failures with full error context
- Success rate per user/week

**Monitoring:**
- Alert if Graphhopper failure rate >10%
- Alert if OpenAI failure rate >10%
- Track average route generation time
- Monitor weekly job completion rate

## Integration Points

### Existing Services

**Strava Service (`app/services/strava_api.py`)**
- Add methods:
  - `search_routes_near_location(lat, lng, radius_km, distance_range)`
  - `get_route_detail(route_id)` - get GPX/elevation data

**Task Dispatcher (`app/services/task_dispatcher.py`)**
- Register weekly route generation task
- Handle async job dispatch for manual generation

### New Services

**Route Service (`app/services/route_service.py`)**
- Main orchestration logic
- Route generation, validation, storage
- Connector generation and route assembly

**Graphhopper Client (`app/services/graphhopper_client.py`)**
- HTTP client for Graphhopper server
- Route generation with cycling profile
- Elevation data queries

### New Repositories

**Route Repository (`app/repositories/route_repository.py`)**
- CRUD operations for routes
- Query routes by workout, user, date range

**User Preferences Repository (`app/repositories/user_preferences_repository.py`)**
- Get/update routing preferences
- Initialize defaults for new users

## Testing Strategy

### Unit Tests

**1. AI Route Agent** (`tests/test_ai/test_route_agent.py`)
- Mock OpenAI responses for various workout scenarios
- Test scoring logic for different workout types (intervals, recovery, endurance, climbing)
- Verify fallback to rule-based scoring when AI fails
- Test reasoning extraction and transparency

**2. Route Service** (`tests/test_services/test_route_service.py`)
- Mock Strava API responses (search results, route details)
- Mock Graphhopper API responses (GPX generation, elevation data)
- Test connector generation logic (distance calculation, geometry merging)
- Test distance validation (reject routes too far from target)
- Test composite route assembly (GPX merging, metadata calculation)

**3. Repository Layer** (`tests/test_repositories/test_route_repository.py`)
- CRUD operations for routes and preferences
- Constraint validation (workout_id uniqueness)
- Query operations (by date range, by status)

**4. Graphhopper Client** (`tests/test_services/test_graphhopper_client.py`)
- Mock HTTP responses from Graphhopper
- Test preference mapping to API parameters
- Test error handling (timeouts, server errors)
- Test GPX parsing and validation

### Integration Tests

**1. End-to-End Route Generation** (`tests/test_integration/test_route_generation.py`)
- Create user with home location and preferences
- Create workout with specific requirements
- Trigger route generation
- Verify route created with valid GPX, correct distance, metadata
- Test full flow: Strava search → AI ranking → connector generation → save

**2. Weekly Scheduler** (`tests/test_tasks/test_route_generation_task.py`)
- Mock current date to trigger schedule
- Create multiple users with active plans and next week's workouts
- Run scheduler task
- Verify all workouts get routes generated with correct status
- Test failure isolation (one user fails, others continue)

**3. Fallback Scenarios** (`tests/test_integration/test_route_fallbacks.py`)
- Test Strava API failure → Graphhopper fallback
- Test AI failure → rule-based scoring fallback
- Test Graphhopper failure → status='failed'
- Verify graceful degradation at each level

### Manual/QA Testing

1. Real Graphhopper server integration testing
2. Verify routes display correctly on web maps (Mapbox/Leaflet)
3. Test GPX export and import to Strava/Garmin devices
4. Validate generated routes are safe (no highways, realistic paths)
5. Test with various home locations (urban, rural, suburban)
6. Verify route quality for different workout types

## Implementation Phases

### Phase 1: Foundation
- Database schema and migrations
- Repository layer
- User preferences API endpoints
- Graphhopper client with basic route generation

### Phase 2: Core Route Generation
- Route service orchestration
- Strava route search integration
- Basic Graphhopper route generation
- Manual route generation endpoint

### Phase 3: AI Intelligence
- Route ranking agent implementation
- Connector generation logic
- Composite route assembly
- AI fallback mechanisms

### Phase 4: Automation
- Weekly scheduler implementation
- Background task queue setup
- Error handling and retry logic
- Observability and monitoring

### Phase 5: Polish
- Route quality validation
- Enhanced error messages
- Performance optimization
- Comprehensive testing

## Future Enhancements (Out of Scope)

- Manual route upload/override
- Route history and favorites
- Community route sharing
- Real-time traffic/weather integration
- Turn-by-turn navigation
- Offline route caching
- Route difficulty ratings
- Multi-sport support (running, gravel, MTB)

## Technical Constraints

- Requires self-hosted Graphhopper server (already in place)
- OpenAI API access for route ranking
- Strava API rate limits (100 requests/15 min, 1000 requests/day)
- GPX file storage (estimate 50-100KB per route)
- Weekly job must complete before Monday morning

## Success Criteria

1. 90%+ of workouts get routes generated successfully
2. Generated routes are safe (0 highway routing incidents)
3. AI match scores correlate with user satisfaction
4. Route generation completes within 10 seconds per workout
5. System degrades gracefully when components fail
6. Routes start and end at user's home location
7. Distance accuracy within ±15% of target
