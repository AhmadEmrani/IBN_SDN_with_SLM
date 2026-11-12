"""BGE candidate routing endpoint, deliberately distinct from few-shot search."""
from __future__ import annotations
from fastapi import HTTPException, APIRouter
from pydantic import BaseModel, ConfigDict, Field
from app.intents.retriever_api import _encoder
router = APIRouter()
from app.intents.capability_routing import route_intent

class RouteCandidatesRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    text:str=Field(min_length=1,max_length=4000)

@router.post('/v1/route-candidates')
def route_candidates(request:RouteCandidatesRequest):
    try:
        return route_intent(request.text,encoder=_encoder())
    except (ValueError,KeyError,TypeError,OSError) as exc:
        raise HTTPException(status_code=503,detail={'code':'routing_index_unavailable'}) from exc
