"""FastAPI application factory: wiring, pages, errors, middleware."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException

from .api import ROUTERS
from .config import VERSION, RuntimeConfig
from .db import Database
from .errors import AppError
from .security import TokenMiddleware

logger = logging.getLogger("wenshu")

BASE_DIR = Path(__file__).parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"
ALLOWED_HOSTS = {"127.0.0.1", "localhost", "[::1]", "testserver"}


def create_app(cfg: RuntimeConfig) -> FastAPI:
    cfg.ensure_dirs()
    db = Database(cfg.db_path)
    db.init()

    app = FastAPI(
        title="文枢 Wenshu",
        version=VERSION,
        docs_url="/docs",
        openapi_url="/openapi.json",
        redoc_url=None,
    )
    app.state.cfg = cfg
    app.state.db = db
    app.state.templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

    app.add_middleware(
        TokenMiddleware,
        token=cfg.token,
        allowed_hosts=set(ALLOWED_HOSTS) | {cfg.host},
    )
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    for module in ROUTERS:
        app.include_router(module.router)

    _register_errors(app)

    templates: Jinja2Templates = app.state.templates

    def ctx(request: Request, **extra) -> dict:
        return {
            "request": request,
            "token": cfg.token,
            "demo": cfg.demo,
            "version": VERSION,
            "data_dir": str(cfg.data_dir),
            **extra,
        }

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request):
        con = db.connect()
        try:
            projects = [
                dict(row)
                for row in con.execute(
                    "SELECT p.*, "
                    "(SELECT COUNT(*) FROM documents d WHERE d.project_id=p.id) AS document_count, "
                    "(SELECT COUNT(*) FROM project_refs r WHERE r.project_id=p.id) AS ref_count "
                    "FROM projects p ORDER BY p.updated_at DESC"
                )
            ]
            totals = {
                "refs": con.execute("SELECT COUNT(*) FROM refs").fetchone()[0],
                "documents": con.execute("SELECT COUNT(*) FROM documents").fetchone()[0],
            }
        finally:
            con.close()
        return templates.TemplateResponse(
            request, "index.html", ctx(request, projects=projects, totals=totals)
        )

    @app.get("/p/{project_id}", response_class=HTMLResponse)
    def project_page(request: Request, project_id: int):
        con = db.connect()
        try:
            project = con.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
            if not project:
                return templates.TemplateResponse(
                    request, "404.html", ctx(request, message="项目不存在。"), status_code=404
                )
            documents = [
                dict(row)
                for row in con.execute(
                    "SELECT id, project_id, title, kind, word_count, version, created_at, updated_at "
                    "FROM documents WHERE project_id=? ORDER BY updated_at DESC",
                    (project_id,),
                )
            ]
            ref_count = con.execute(
                "SELECT COUNT(*) FROM project_refs WHERE project_id=?", (project_id,)
            ).fetchone()[0]
        finally:
            con.close()
        return templates.TemplateResponse(
            request,
            "project.html",
            ctx(
                request=request,
                project=dict(project),
                documents=documents,
                ref_count=ref_count,
            ),
        )

    @app.get("/settings", response_class=HTMLResponse)
    def settings_page(request: Request):
        return templates.TemplateResponse(request, "settings.html", ctx(request))

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon():
        return Response(status_code=204)

    return app


def _register_errors(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError):
        return JSONResponse(exc.to_dict(), status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        return JSONResponse(
            {
                "error": {
                    "code": "validation_failed",
                    "message": "请求参数不合法。",
                    "detail": exc.errors(),
                }
            },
            status_code=422,
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_handler(request: Request, exc: StarletteHTTPException):
        if request.url.path.startswith("/api"):
            return JSONResponse(
                {
                    "error": {
                        "code": "http_error",
                        "message": str(exc.detail),
                    }
                },
                status_code=exc.status_code,
            )
        templates: Jinja2Templates = app.state.templates
        cfg: RuntimeConfig = app.state.cfg
        return templates.TemplateResponse(
            request,
            "404.html",
            {
                "request": request,
                "token": cfg.token,
                "demo": cfg.demo,
                "version": VERSION,
                "message": str(exc.detail),
            },
            status_code=exc.status_code,
        )

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        logger.exception("unhandled error on %s", request.url.path)
        if request.url.path.startswith("/api"):
            return JSONResponse(
                {
                    "error": {
                        "code": "internal_error",
                        "message": "服务器内部错误，请查看终端日志。",
                    }
                },
                status_code=500,
            )
        return PlainTextResponse("内部错误，请查看终端日志。", status_code=500)
