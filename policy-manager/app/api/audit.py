"""Sanitized API error logging (no request payloads, tokens, or query strings)."""
import logging
from uuid import uuid4

from fastapi.concurrency import run_in_threadpool

from app.db.session import SessionLocal
from app.models.event import APIRequestEvent

logger = logging.getLogger('llnet.api.audit')


def _write_event(request_id: str, method: str, route: str, status_code: int):
    with SessionLocal.begin() as db:
        db.add(APIRequestEvent(
            id=str(uuid4()), request_id=request_id, method=method,
            route=route[:255], status_code=status_code,
            error_code=f'HTTP_{status_code}',
        ))


def _route_template(request) -> str:
    """Resolve the full route template for audit, never log raw URL identifiers.

    Router match data in middleware scope may be partial/rewritten by nested
    routers. Match the full request path against the application's compiled
    route regexes instead.
    """
    full_path = request.url.path
    for route in request.app.router.routes:
        regex = getattr(route, "path_regex", None)
        methods = getattr(route, "methods", None)
        if regex is None:
            continue
        if methods is not None and request.method not in methods:
            continue
        if regex.fullmatch(full_path):
            return route.path
    return "/unmatched"


async def audit_failed_requests(request, call_next):
    request_id = str(uuid4())
    response = await call_next(request)
    response.headers['X-Request-Id'] = request_id
    if response.status_code >= 400:
        route = _route_template(request)
        try:
            await run_in_threadpool(
                _write_event, request_id, request.method, route, response.status_code
            )
        except Exception:
            # An audit DB outage must not transform a validation error into 500.
            logger.exception('API audit persistence failed for status %d', response.status_code)
    return response
