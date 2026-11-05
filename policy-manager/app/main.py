from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.api.v1.policies import router
from app.db.session import Base, engine
from app.models.policy import PolicyRecord  # noqa: F401 - registers table
from fastapi.staticfiles import StaticFiles
from fastapi.openapi.docs import get_swagger_ui_html

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Development bootstrap only. Replace with Alembic migrations before production.
    Base.metadata.create_all(bind=engine)
    yield

app = FastAPI(title="LLNet Policy Manager", version="0.1.0", lifespan=lifespan , docs_url=None)
app.include_router(router)

app.mount(
    "/static",
    StaticFiles(directory="app/static"),
    name="static"
)


@app.get("/docs", include_in_schema=False)
def custom_swagger_ui():
    return get_swagger_ui_html(
        openapi_url=app.openapi_url,
        title="LLNet Policy Manager - Swagger UI",
        swagger_js_url="/static/swagger-ui-bundle.js",
        swagger_css_url="/static/swagger-ui.css",
    )

@app.get("/health")
def health():
    return {"status": "ok"}
