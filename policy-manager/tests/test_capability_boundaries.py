"""Capability boundaries independent of Phi, database, Airflow or Ryu."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.intents.capability_registry import (
    read_catalog, require_enabled, enabled_map,
    CapabilityConfigurationError, CapabilityUnavailable,
)
from app.intents.capability_preview import build_preview, PreviewNotSupported

READY = {
    "contract_version": "1.0", "status": "ready", "capability": "firewall",
    "proposal": {"source": "h1", "destination": "h2", "direction": "unidirectional",
                 "protocol": "tcp", "source_ports": None,
                 "destination_ports": [443], "action": "deny"},
    "clarification": None, "reason_code": None,
}
CONTEXT = {
    "network_id": "lab", "fixture_only": True, "hosts": {"h1": "10.0.0.1/32", "h2": "10.0.0.2/32"},
    "switches": ["1"], "default_switches": ["1"], "default_priority": 100,
}


class CapabilityBoundariesTests(unittest.TestCase):
    def fixture_catalog(self, update=None):
        from app.intents.capability_registry import REGISTRY_PATH
        catalog = json.loads(REGISTRY_PATH.read_text())
        if update:
            update(catalog)
        f = tempfile.TemporaryDirectory()
        self.addCleanup(f.cleanup)
        path = Path(f.name) / "registry.json"
        path.write_text(json.dumps(catalog), encoding="utf-8")
        return path

    def test_catalog_has_all_capabilities(self):
        self.assertEqual(set(read_catalog()), {"firewall", "rate_limit", "load_profile"})

    def test_only_firewall_enabled(self):
        self.assertEqual(enabled_map(), {"firewall": True, "rate_limit": False, "load_profile": False})

    def test_disabled_does_not_auto_activate(self):
        with self.assertRaises(CapabilityUnavailable):
            require_enabled("rate_limit")
        with self.assertRaises(CapabilityUnavailable):
            require_enabled("load_profile")

    def test_unknown_fail_closed(self):
        with self.assertRaises(CapabilityUnavailable):
            require_enabled("not_a_capability")

    def test_duplicate_registration_rejected(self):
        path = self.fixture_catalog(lambda c: c["capabilities"].append(dict(c["capabilities"][0])))
        with self.assertRaises(CapabilityConfigurationError):
            read_catalog(path)

    def test_enabled_but_missing_handler_rejected(self):
        path = self.fixture_catalog(lambda c: c["capabilities"][1].update(enabled=True))
        with self.assertRaises(CapabilityConfigurationError):
            read_catalog(path)

    def test_invalid_registry_rejected(self):
        path = self.fixture_catalog()
        path.write_text("{invalid", encoding="utf-8")
        with self.assertRaises(CapabilityConfigurationError):
            read_catalog(path)

    def test_firewall_preview_compiles_without_actuation(self):
        output = build_preview(READY, context=CONTEXT, network_id="lab",
                               intent_id="test-fw", allow_fixture=True)
        self.assertEqual(output["policy"]["policy"]["type"], "firewall")
        self.assertEqual(output["compiled_flows"][0]["match"]["tcp_dst"], 443)
        self.assertEqual(output["compiled_flows"][0]["actions"], [])

    def test_disabled_preview_cannot_generate_flows(self):
        with self.assertRaises(PreviewNotSupported):
            build_preview({**READY, "capability": "rate_limit"}, context=CONTEXT,
                          network_id="lab", intent_id="test-rate", allow_fixture=True)

    def test_preview_rejects_nonready(self):
        with self.assertRaises(PreviewNotSupported):
            build_preview({**READY, "status": "unsupported"}, context=CONTEXT,
                          network_id="lab", intent_id="test", allow_fixture=True)

    def test_preview_has_no_network_or_persistence_dependency(self):
        import inspect
        import app.intents.capability_preview as mod
        code = inspect.getsource(mod)
        for forbidden in ("app.db", "submission_service", "ryu_adapter", "outbox_dispatcher", "airflow_adapter"):
            self.assertNotIn(forbidden, code)


if __name__ == "__main__":
    unittest.main()
