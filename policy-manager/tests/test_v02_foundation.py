"""Fast, no-network foundation checks. PostgreSQL integration runs on host."""
import unittest
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from app.db.session import Base
import app.models  # registers metadata
from app.domain.fingerprint import sha256_json
from app.domain.states import OperationStatus, DeploymentStatus


class FoundationTests(unittest.TestCase):
    def test_expected_tables_registered(self):
        self.assertTrue({
            "policies", "policy_revisions", "policy_operations", "operation_events",
            "flow_deployments", "outbox_events", "api_request_events", "scope_reservations",
        }.issubset(set(Base.metadata.tables.keys())))

    def test_postgresql_table_ddl_renders(self):
        for table in Base.metadata.tables.values():
            rendered = str(CreateTable(table).compile(dialect=postgresql.dialect()))
            self.assertIn("CREATE TABLE", rendered)

    def test_fingerprint_is_order_independent(self):
        self.assertEqual(sha256_json({"a": 1, "b": {"x": 2}}), sha256_json({"b": {"x": 2}, "a": 1}))
        self.assertNotEqual(sha256_json({"a": 1}), sha256_json({"a": 2}))

    def test_unknown_is_not_failure(self):
        self.assertNotEqual(OperationStatus.UNRESOLVED, OperationStatus.FAILED)
        self.assertNotEqual(DeploymentStatus.UNKNOWN, DeploymentStatus.ABSENT)


if __name__ == "__main__":
    unittest.main()
