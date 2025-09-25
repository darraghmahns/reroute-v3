from fastapi import APIRouter

from app.api.v1.endpoints import auth, health, plans, strava, users

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(health.router)
api_router.include_router(strava.router)
api_router.include_router(users.router)
api_router.include_router(plans.router)
