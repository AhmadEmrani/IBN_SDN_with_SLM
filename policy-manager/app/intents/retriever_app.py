"""Single explicit FastAPI assembly for BGE endpoints."""
from app.intents.retriever_api import app
from app.intents.routing_api import router as route_candidates_router
app.include_router(route_candidates_router)
