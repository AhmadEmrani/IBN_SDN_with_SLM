"""Sanitized API error logging (no request payloads, tokens, or query strings)."""
import logging
from uuid import uuid4

from fastapi.concurrency import run_in_threadpool
from starlette.routing import Match

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
    """Return a matched *template*, never the raw URL path or an identifier.

    FastAPI >=0.137 retains included routers as wrappers without ``.path``.
    ``iter_route_contexts`` expands them to effective prefixed routes.
    For 405 responses retain the templated PARTIAL match.
    """
    try:
        from fastapi.routing import iter_route_contexts
    except ImportError:
        # FastAPI <0.137 has flat routes; 0.137.0/1 have private wrappers.
        def compatible_routes():
            for item in request.app.router.routes:
                expand = getattr(item, 'effective_route_contexts', None)
                if callable(expand):
                    yield from expand()
                else:
                    yield item
        routes = compatible_routes()
    else:
        routes = iter_route_contexts(request.app.router.routes)

    partial_template = None
    for route in routes:
        template = getattr(route, 'path_format', None) or getattr(route, 'path', None)
        if not isinstance(template, str):
            continue
        try:
            match, _scope = route.matches(request.scope)
        except (AttributeError, TypeError, ValueError):
            continue
        if match == Match.FULL:
            return template
        if match == Match.PARTIAL and partial_template is None:
            partial_template = template
    return partial_template or '/unmatched'


async def audit_failed_requests(request, call_next):
    request_id = str(uuid4())
    response = await call_next(request)
    response.headers['X-Request-Id'] = request_id
    if response.status_code >= 400:
        # Auditing must never cause an otherwise valid API error to become 500.
        try:
            route = _route_template(request)
            await run_in_threadpool(
                _write_event, request_id, request.method, route, response.status_code
            )
        except Exception:
            logger.exception('API audit persistence failed for status %d', response.status_code)
    return response
