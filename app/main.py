from fastapi import FastAPI

from app.api.routes import api_router


def create_app() -> FastAPI:
    application = FastAPI(title="Reroute Backend")
    application.include_router(api_router)
    return application


app = create_app()
