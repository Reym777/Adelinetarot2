"""FastAPI application entry point for Adelinemagica.

Wires configuration, database, security middleware and routers, and (in
development) hosts the static frontend (``index.html`` + ``admin.html``).

Run locally:
    uvicorn app.main:app --reload --port 8000
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.gzip import GZipMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

try:
    from brotli_asgi import BrotliMiddleware
except ImportError:  # pragma: no cover - optional dependency in local dev
    BrotliMiddleware = None

from . import __version__
from .article_backup import push_articles_snapshot, restore_articles_from_backup
from .config import settings
from .database import init_db
from .routers import admin as admin_router
from .routers import analytics as analytics_router
from .routers import articles as articles_router
from .routers import bookings as bookings_router
from .routers import contact as contact_router
from .routers import payments as payments_router
from .database import SessionLocal
from .models import PageVisit
from .security import BodySizeLimitMiddleware, SecurityHeadersMiddleware

logger = logging.getLogger("adelinemagica")
logging.basicConfig(level=logging.INFO)


_REMOVED_URLS = {
    "/mapa_bienestar_astral",
    "/mapa_bienestar_astral test.html",
    "/test.html",
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    if settings.articles_backup_enabled:
        db = SessionLocal()
        try:
            report = restore_articles_from_backup(db)
            logger.info(
                "Articles backup restore: remote=%s restored=%s updated=%s",
                report.get("remote", 0),
                report.get("restored", 0),
                report.get("updated", 0),
            )
            if int(report.get("remote", 0)) == 0:
                push_articles_snapshot(db, reason="bootstrap")
        finally:
            db.close()
    # Surface the admin token once so Adelinemagica can sign in (generated if
    # ADELINE_ADMIN_TOKEN was not provided).
    logger.info("Adelinemagica API %s started (debug=%s)", __version__, settings.debug)
    logger.info("Admin token: %s", settings.resolved_admin_token)
    if settings.stripe_enabled and not settings.stripe_webhook_secret:
        logger.error(
            "Stripe is enabled but ADELINE_STRIPE_WEBHOOK_SECRET is missing. "
            "Direct payment-link notifications will not be verified."
        )
    if settings.stripe_enabled and not (settings.resend_enabled or settings.mail_enabled):
        logger.error(
            "Stripe is enabled but no email transport is configured (Resend/SMTP). "
            "Payment notifications cannot be delivered."
        )
    yield


app = FastAPI(
    title=settings.app_name,
    version=__version__,
    description="Backend seguro del sitio Adelinemagica.",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url=None,
    openapi_url="/api/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.effective_cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Accept", "X-Admin-Token"],
    max_age=600,
)
app.add_middleware(BodySizeLimitMiddleware)
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=settings.trusted_hosts,
)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(GZipMiddleware, minimum_size=1024)
if BrotliMiddleware is not None:
    app.add_middleware(BrotliMiddleware, quality=5, minimum_size=1024)


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    errors = [
        {"loc": ".".join(str(p) for p in e.get("loc", [])), "msg": e.get("msg", "")}
        for e in exc.errors()
    ]
    return JSONResponse(status_code=422, content={"detail": "validation_error", "errors": errors})


@app.exception_handler(Exception)
async def unhandled_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Error interno del servidor"})


@app.get("/api/health", tags=["meta"])
def health() -> dict:
    return {"status": "ok", "version": __version__}


@app.get("/api/config", tags=["meta"])
def public_config() -> dict:
    """Non-secret config the frontend needs to render prices and PayPal."""
    return {
        "prices": {
            "mxn": settings.price_mxn,
            "pen": settings.price_pen,
            "pen_as_usd": settings.price_pen_as_usd,
        },
        "paypal_me_handle": settings.paypal_me_handle,
        "paypal_enabled": bool(settings.paypal_client_id),
        "paypal_advanced": settings.paypal_server_enabled,
        "paypal_env": settings.paypal_env,
        "paypal_components": settings.paypal_components,
        "stripe_enabled": settings.stripe_enabled,
        "stripe_publishable_key": settings.stripe_publishable_key,
        "mail_enabled": settings.mail_enabled,
        "ga_measurement_protocol_enabled": settings.ga_measurement_protocol_enabled,
    }


@app.get(
    "/.well-known/apple-developer-merchantid-domain-association",
    include_in_schema=False,
)
def apple_pay_domain() -> Response:
    """Serve the Apple Pay domain-verification file (set via env) so Apple Pay
    can be enabled for this domain. Returns 404 when not configured."""
    if not settings.apple_pay_domain_association:
        return Response(status_code=404)
    return Response(
        content=settings.apple_pay_domain_association,
        media_type="text/plain",
    )


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> FileResponse:
    return FileResponse(settings.frontend_path / "assets" / "images" / "apple-touch-icon.png")


@app.get("/mapa_bienestar_astral", include_in_schema=False)
@app.get("/mapa_bienestar_astral test.html", include_in_schema=False)
@app.get("/test.html", include_in_schema=False)
def removed_urls() -> Response:
    return Response(
        status_code=410,
        headers={
            "Cache-Control": "public, max-age=3600",
            "X-Robots-Tag": "noindex, nofollow",
        },
    )


app.include_router(bookings_router.router)
app.include_router(admin_router.router)
app.include_router(analytics_router.router)
app.include_router(articles_router.router)
app.include_router(payments_router.router)
app.include_router(contact_router.router)


@app.middleware("http")
async def track_visits(request: Request, call_next):
    if request.url.path in _REMOVED_URLS:
        return Response(
            status_code=410,
            headers={
                "Cache-Control": "public, max-age=3600",
                "X-Robots-Tag": "noindex, nofollow",
            },
        )

    response = await call_next(request)
    path = request.url.path or "/"
    if request.method == "GET":
        if path in ("/admin", "/admin.html"):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        elif path.startswith("/assets/"):
            response.headers.setdefault("Cache-Control", "public, max-age=31536000, immutable")
        elif path == "/" or path.endswith(".html"):
            response.headers.setdefault("Cache-Control", "public, max-age=300")
    try:
        if request.method == "GET" and not path.startswith("/api") and not path.startswith("/assets"):
            today = datetime.now(timezone.utc).date()
            db = SessionLocal()
            try:
                row = (
                    db.query(PageVisit)
                    .filter(PageVisit.day == today)
                    .filter(PageVisit.path == path)
                    .first()
                )
                if row is None:
                    row = PageVisit(day=today, path=path, hits=1)
                    db.add(row)
                else:
                    row.hits = int(row.hits or 0) + 1
                db.commit()
            finally:
                db.close()
    except Exception:
        # Never break page delivery for analytics bookkeeping.
        pass
    return response


# --- Static frontend (convenience for local dev) -----------------------------
if settings.serve_frontend and (settings.frontend_path / "index.html").exists():
    frontend = settings.frontend_path
    assets_dir = frontend / "assets"

    def frontend_page_response(page_name: str) -> FileResponse:
        safe_name = Path(page_name).name
        if safe_name != page_name:
            raise HTTPException(status_code=404, detail="Not found")
        allowed_raw = (".html", ".txt", ".xml", ".webmanifest")
        if safe_name.endswith(allowed_raw):
            file_path = frontend / safe_name
        else:
            file_path = frontend / f"{safe_name}.html"
        if not file_path.is_file():
            raise HTTPException(status_code=404, detail="Not found")
        return FileResponse(file_path)

    # Mount ONLY the assets folder â€” never the site root. A catch-all mount at
    # "/" would swallow every unmatched /api/* request and let StaticFiles answer
    # "405 Method Not Allowed" on POST (e.g. a stray trailing slash). With assets
    # scoped here, unknown /api paths fall through to FastAPI's JSON 404 and
    # Starlette's automatic trailing-slash redirect (307, method preserved).
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(frontend / "index.html")

    @app.get("/index", include_in_schema=False)
    @app.get("/index.html", include_in_schema=False)
    def index_redirect() -> RedirectResponse:
        return RedirectResponse(url="/", status_code=308)

    @app.get("/fr", include_in_schema=False)
    @app.get("/fr/", include_in_schema=False)
    def fr_index() -> FileResponse:
        return FileResponse(frontend / "fr" / "index.html")

    @app.get("/en", include_in_schema=False)
    @app.get("/en/", include_in_schema=False)
    def en_index() -> FileResponse:
        return FileResponse(frontend / "en" / "index.html")

    @app.get("/es", include_in_schema=False)
    @app.get("/es/", include_in_schema=False)
    def es_index() -> RedirectResponse:
        return RedirectResponse(url="/", status_code=308)

    _localized_services = {
        "oraciones",
        "meditaciones",
        "tarot-terapeutico",
        "lectura-de-carta-natal",
        "sinastria",
        "paquete-magica",
        "prediccion-astral",
    }

    def _localized_service_response(lang: str, service_slug: str) -> FileResponse:
        safe_lang = Path(lang).name
        safe_slug = Path(service_slug).name
        if safe_lang != lang or safe_slug != service_slug:
            raise HTTPException(status_code=404, detail="Not found")
        if safe_slug not in _localized_services:
            raise HTTPException(status_code=404, detail="Not found")
        file_path = frontend / safe_lang / f"{safe_slug}.html"
        if not file_path.is_file():
            raise HTTPException(status_code=404, detail="Not found")
        return FileResponse(file_path)

    @app.get("/fr/{service_slug}", include_in_schema=False)
    def fr_service_page(service_slug: str) -> FileResponse:
        return _localized_service_response("fr", service_slug)

    @app.get("/en/{service_slug}", include_in_schema=False)
    def en_service_page(service_slug: str) -> FileResponse:
        return _localized_service_response("en", service_slug)

    @app.get("/es/{service_slug}", include_in_schema=False)
    def es_service_page(service_slug: str) -> RedirectResponse:
        safe_slug = Path(service_slug).name
        if safe_slug != service_slug or safe_slug not in _localized_services:
            raise HTTPException(status_code=404, detail="Not found")
        return RedirectResponse(url=f"/{safe_slug}", status_code=308)

    @app.get("/admin", include_in_schema=False)
    @app.get("/admin.html", include_in_schema=False)
    def admin_page() -> FileResponse:
        return FileResponse(frontend / "admin.html")

    @app.get("/{page_name}", include_in_schema=False)
    def frontend_page(page_name: str) -> FileResponse:
        return frontend_page_response(page_name)

else:
    @app.get("/", include_in_schema=False)
    def root_info() -> dict:
        return {"service": settings.app_name, "docs": "/api/docs"}

