"""Policy API assembly: tools, reads and commands are separate modules."""
from fastapi import APIRouter
from app.api.v1 import policy_tools, policy_queries, policy_commands

router = APIRouter(prefix="/api/v1", tags=["Policies"])
router.include_router(policy_tools.router)
router.include_router(policy_queries.router)
router.include_router(policy_commands.router)
