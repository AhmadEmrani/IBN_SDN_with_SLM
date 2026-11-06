"""App assembly only. Route handlers live in dedicated API modules.

The database schema is managed by Alembic, never by create_all at startup.
"""
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.openapi.docs import get_swagger_ui_html
from app.api.v1.policies import router as policies_router
from app.api.v1.operations import router as operations_router
from app.api.audit import audit_failed_requests

app = FastAPI(title="LLNet Policy Manager", version="0.2.0-dev.2", docs_url=None)
app.middleware("http")(audit_failed_requests)
app.include_router(policies_router)
app.include_router(operations_router)

app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.get("/docs", include_in_schema=False)
def custom_swagger_ui():
    return get_swagger_ui_html(
        openapi_url=app.openapi_url,
        title="LLNet Policy Manager - Swagger UI",
        swagger_js_url="/static/swagger-ui-bundle.js",
        swagger_css_url="/static/swagger-ui.css",
    )


@app.get("/health", tags=["Health"])
def health():
    # Liveness only; readiness check will be introduced with the dispatcher.
    return {"status": "ok"}
