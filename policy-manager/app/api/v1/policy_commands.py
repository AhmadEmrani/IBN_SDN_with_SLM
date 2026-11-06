"""HTTP adapters only. Commands stage durable operations; no Ryu calls here."""
from fastapi import APIRouter, Header, HTTPException
from app.schemas.policy import PolicyInput
from app.schemas.operation import OperationAccepted
from app.services.submission_service import submit, SubmissionError

router = APIRouter(prefix='/policies', tags=['Policy Commands'])


def _submit(kind: str, *, client: str, key: str, policy_id: str | None = None,
            policy: PolicyInput | None = None, expected_revision: int | None = None):
    try:
        return submit(kind, requester=client, key=key, policy_id=policy_id,
                      policy=policy, expected_revision=expected_revision).as_dict()
    except SubmissionError as e:
        raise HTTPException(status_code=e.http_status, detail=str(e)) from e


@router.post('', status_code=202, response_model=OperationAccepted)
def create(policy: PolicyInput,
           idempotency_key: str = Header(..., alias='Idempotency-Key', min_length=1, max_length=160),
           client_id: str = Header('local-lab', alias='X-Client-Id', min_length=1, max_length=128)):
    return _submit('create', client=client_id, key=idempotency_key, policy=policy)


@router.patch('/{policy_id}', status_code=202, response_model=OperationAccepted)
def update(policy_id: str, policy: PolicyInput,
           if_match: int = Header(..., alias='If-Match'),
           idempotency_key: str = Header(..., alias='Idempotency-Key', min_length=1, max_length=160),
           client_id: str = Header('local-lab', alias='X-Client-Id', min_length=1, max_length=128)):
    return _submit('update', policy_id=policy_id, policy=policy, expected_revision=if_match,
                   client=client_id, key=idempotency_key)


@router.post('/{policy_id}/enable', status_code=202, response_model=OperationAccepted)
def enable(policy_id: str,
           idempotency_key: str = Header(..., alias='Idempotency-Key', min_length=1, max_length=160),
           client_id: str = Header('local-lab', alias='X-Client-Id', min_length=1, max_length=128)):
    return _submit('enable', policy_id=policy_id, client=client_id, key=idempotency_key)


@router.post('/{policy_id}/disable', status_code=202, response_model=OperationAccepted)
def disable(policy_id: str,
            idempotency_key: str = Header(..., alias='Idempotency-Key', min_length=1, max_length=160),
            client_id: str = Header('local-lab', alias='X-Client-Id', min_length=1, max_length=128)):
    return _submit('disable', policy_id=policy_id, client=client_id, key=idempotency_key)


@router.delete('/{policy_id}', status_code=202, response_model=OperationAccepted)
def delete(policy_id: str,
           idempotency_key: str = Header(..., alias='Idempotency-Key', min_length=1, max_length=160),
           client_id: str = Header('local-lab', alias='X-Client-Id', min_length=1, max_length=128)):
    return _submit('delete', policy_id=policy_id, client=client_id, key=idempotency_key)
