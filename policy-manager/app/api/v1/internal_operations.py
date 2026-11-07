"""Airflow-to-LLNet private API. All business logic remains on the API side."""
from __future__ import annotations
import hmac
import os
from fastapi import APIRouter, Header, HTTPException
from app.db.session import SessionLocal
from app.models import PolicyOperation
from app.services.execution_service import run_operation, OperationBusy, OperationNotFound

router = APIRouter(prefix='/api/v1/internal/operations', tags=['Internal Workflow'],
                   include_in_schema=False)


def _require_token(x_internal_token: str | None = Header(default=None, alias='X-Internal-Token')):
    actual = os.environ.get('LLNET_INTERNAL_TOKEN', '')
    if not actual or not x_internal_token or not hmac.compare_digest(x_internal_token, actual):
        raise HTTPException(403, detail='Forbidden')


def _read(operation_id: str):
    with SessionLocal() as db:
        op = db.get(PolicyOperation, operation_id)
        if op is None:
            raise HTTPException(404, detail='Operation not found')
        return {'operation_id': op.id, 'status': op.status,
                'airflow_run_id': op.airflow_run_id, 'error_code': op.error_code}


@router.get('/{operation_id}/preflight', dependencies=[])
def preflight(operation_id: str, x_internal_token: str | None = Header(None, alias='X-Internal-Token')):
    _require_token(x_internal_token)
    data = _read(operation_id)
    if data['status'] not in {'pending', 'queued', 'succeeded'}:
        raise HTTPException(409, detail='Operation is not safe to start')
    return data


@router.post('/{operation_id}/execute')
def execute(operation_id: str, x_internal_token: str | None = Header(None, alias='X-Internal-Token')):
    _require_token(x_internal_token)
    try:
        status = run_operation(operation_id)
    except OperationNotFound:
        raise HTTPException(404, detail='Operation not found') from None
    except OperationBusy:
        raise HTTPException(409, detail='Operation busy or unresolved') from None
    if status != 'succeeded':
        # No automatic replay of ambiguous side effects.
        raise HTTPException(409, detail=f'Operation finished with status {status}')
    return {'operation_id': operation_id, 'status': status}


@router.get('/{operation_id}/result')
def result(operation_id: str, x_internal_token: str | None = Header(None, alias='X-Internal-Token')):
    _require_token(x_internal_token)
    data = _read(operation_id)
    if data['status'] != 'succeeded':
        raise HTTPException(409, detail=f'Operation status: {data["status"]}')
    return data
