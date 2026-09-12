from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from src.admin.routes import build_router

ADMIN_DIR = Path(__file__).resolve().parent


def create_app() -> FastAPI:
    app = FastAPI(title="Akisok review queue", docs_url=None, redoc_url=None)
    templates = Jinja2Templates(directory=str(ADMIN_DIR / "templates"))
    app.mount("/static", StaticFiles(directory=str(ADMIN_DIR / "static")), name="static")
    app.include_router(build_router(templates))
    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("ADMIN_UI_PORT", "8001"))
    uvicorn.run("src.admin.main:app", host="127.0.0.1", port=port, reload=True)
