"""Deprecated compatibility shim (Stage 2).

Synchronous network mutations were intentionally removed from this module.
Use submission_service.submit() for durable requests and
execution_service.run_operation() for the temporary stage-2 CLI worker.
"""
from app.domain.cookies import new_cookie  # noqa: F401 - legacy import compatibility


def create_policy(*_args, **_kwargs):
    raise RuntimeError('Synchronous create_policy was retired; use submission_service.submit')


def delete_policy(*_args, **_kwargs):
    raise RuntimeError('Synchronous delete_policy was retired; use submission_service.submit')
