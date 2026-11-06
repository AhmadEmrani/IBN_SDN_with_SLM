"""Pure validation and dry-run compilation endpoints."""
from fastapi import APIRouter
from app.schemas.policy import PolicyInput
from app.services.compiler import compile_policy

router = APIRouter(prefix="/policies")


@router.post("/validate")
def validate(policy: PolicyInput):
    return {"valid": True, "normalized_policy": policy.model_dump(mode="json")}


@router.post("/compile")
def compile_preview(policy: PolicyInput):
    # Placeholder cookie is never installed.
    return {"flows": compile_policy(policy, 1), "dry_run": True}
