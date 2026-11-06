"""No live DB/Ryu calls: validate route assembly and the pure APIs."""
import unittest
from fastapi.testclient import TestClient
from app.main import app

POLICY = {
    "schema_version": "1.0",
    "policy": {"name": "block-lab", "type": "firewall"},
    "scope": {"network_id": "mininet-lab", "switches": ["1"]},
    "match": {
        "source": {"type": "ipv4", "value": "10.0.0.1/32"},
        "destination": {"type": "ipv4", "value": "10.0.0.3/32"},
        "direction": "bidirectional", "protocol": "any"
    },
    "action": {"type": "deny"},
}


class APIRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_legacy_paths_still_exposed(self):
        schema = self.client.get("/openapi.json").json()
        routes = schema["paths"]
        self.assertIn("post", routes["/api/v1/policies"])
        self.assertIn("delete", routes["/api/v1/policies/{policy_id}"])
        self.assertIn("post", routes["/api/v1/policies/validate"])
        self.assertIn("post", routes["/api/v1/policies/compile"])
        self.assertIn("get", routes["/api/v1/operations/{operation_id}"])
        self.assertIn("get", routes["/api/v1/operations/{operation_id}/events"])

    def test_validate_has_no_network_effects(self):
        response = self.client.post("/api/v1/policies/validate", json=POLICY)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["valid"])

    def test_compile_is_dry_run(self):
        response = self.client.post("/api/v1/policies/compile", json=POLICY)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["dry_run"])
        self.assertEqual(2, len(response.json()["flows"]))


if __name__ == "__main__":
    unittest.main()
