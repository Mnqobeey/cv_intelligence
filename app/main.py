from __future__ import annotations

"""Application entrypoint for the refactored CestaCV Intelligence Studio."""

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .constants import BASE_DIR, UPLOAD_DIR
from .routes import register_routes
from .storage import SQLiteDocumentStore


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(title="CestaCV Intelligence Studio", version="7.0.0")
    app.mount("/static", StaticFiles(directory=str(BASE_DIR / "app" / "static")), name="static")
    app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")

    templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))
    store = SQLiteDocumentStore()
    app.include_router(register_routes(templates, store))
    return app


app = create_app()
