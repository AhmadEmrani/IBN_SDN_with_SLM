"""SQLite unit tests for transaction semantics; real PostgreSQL is separately verified.

JSONB compilation is adapted only for this test database. Runtime remains
PostgreSQL JSONB. These tests do NOT claim PostgreSQL integration coverage.
"""
import unittest
from sqlalchemy import create_engine, select, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.session import Base
from app.models import PolicyRecord, PolicyOperation, OutboxEvent, OperationEvent
from app.repositories.operation_repository import stage_operation, IdempotencyPayloadMismatch


@compiles(JSONB, "sqlite")
def _jsonb_for_sqlite(_type, _compiler, **_kwargs):
    return "JSON"


class OperationUnitOfWorkTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        with Session(self.engine) as db, db.begin():
            db.add(PolicyRecord(
                id="FW-test", revision=1, cookie=123,
                definition={"schema_version": "1.0"}, compiled_flows=[], status="active"
            ))

    def tearDown(self):
        self.engine.dispose()

    def _stage(self, db, payload=None):
        return stage_operation(
            db, policy_id="FW-test", operation_type="disable", requester_id="test-client",
            idempotency_key="key-1", request_payload=payload or {"reason": "test"},
        )

    def _count(self, table):
        with Session(self.engine) as db:
            return db.scalar(select(func.count()).select_from(table))

    def test_operation_event_outbox_commit_together(self):
        with Session(self.engine) as db, db.begin():
            outcome = self._stage(db)
            self.assertTrue(outcome.created)
        self.assertEqual(self._count(PolicyOperation), 1)
        self.assertEqual(self._count(OutboxEvent), 1)
        self.assertEqual(self._count(OperationEvent), 1)

    def test_same_key_returns_same_operation(self):
        with Session(self.engine) as db, db.begin():
            initial = self._stage(db).operation.id
        with Session(self.engine) as db, db.begin():
            repeat = self._stage(db)
            self.assertFalse(repeat.created)
            self.assertEqual(repeat.operation.id, initial)
        self.assertEqual(self._count(PolicyOperation), 1)
        self.assertEqual(self._count(OutboxEvent), 1)

    def test_same_key_different_payload_rejected(self):
        with Session(self.engine) as db, db.begin():
            self._stage(db)
        with self.assertRaises(IdempotencyPayloadMismatch):
            with Session(self.engine) as db, db.begin():
                self._stage(db, {"reason": "different"})
        self.assertEqual(self._count(PolicyOperation), 1)

    def test_rollback_removes_operation_and_outbox(self):
        with self.assertRaises(RuntimeError):
            with Session(self.engine) as db, db.begin():
                self._stage(db)
                raise RuntimeError("simulate application crash")
        self.assertEqual(self._count(PolicyOperation), 0)
        self.assertEqual(self._count(OutboxEvent), 0)
        self.assertEqual(self._count(OperationEvent), 0)


if __name__ == "__main__":
    unittest.main()
