"""Stage 5D.3: real 5B Adapter+Compiler, mocked AI calls, no SDN access."""
from __future__ import annotations

import os
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from app.intents.dry_run_api import DryRunRequest, dry_run
from app.intents.context_provider import ContextUnavailable, get_trusted_context

READY = {
    "contract_version": "1.0", "status": "ready", "capability": "firewall",
    "proposal": {"source": "h1", "destination": "h2", "direction": "unidirectional",
                 "protocol": "tcp", "source_ports": None,
                 "destination_ports": [443], "action": "deny"},
    "clarification": None, "reason_code": None,
}


def translation(model_result):
    return {"status": model_result["status"], "capability": "firewall",
            "model_result": model_result, "retrieved_example_ids": ["fw-004"],
            "validated": True, "deployment": "not_requested"}


class DryRunTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        patcher = patch.dict(os.environ, {"LLNET_DRY_RUN_CONTEXT_MODE": "fixture"})
        patcher.start()
        self.addCleanup(patcher.stop)

    async def _convert(self, result):
        with patch("app.intents.dry_run_api.translate", new=AsyncMock(return_value=translation(result))) as mock:
            response = await dry_run(
                DryRunRequest(text="Block TCP traffic from h1 to h2 on port 443", network_id="lab"),
                client=None,
            )
            mock.assert_awaited_once()
        return response

    async def test_ready_returns_real_policy_and_compiled_flow(self):
        result = await self._convert(READY)
        self.assertEqual(result["status"], "ready")
        self.assertTrue(result["policy_validated"])
        self.assertEqual(result["context_source"], "lab_fixture")
        self.assertEqual(result["deployment"], "not_requested")
        self.assertEqual(result["policy"]["match"]["source"]["value"], "10.0.0.1/32")
        flow = result["compiled_flows"][0]
        self.assertEqual(flow["match"]["ip_proto"], 6)
        self.assertEqual(flow["match"]["tcp_dst"], 443)
        self.assertEqual(flow["priority"], 1100)
        self.assertEqual(flow["actions"], [])

    async def test_udp_flow(self):
        proposal = dict(READY["proposal"], source="h2", destination="h3", protocol="udp", destination_ports=None)
        result = await self._convert({**READY, "proposal": proposal})
        self.assertEqual(result["compiled_flows"][0]["match"]["ip_proto"], 17)
        self.assertNotIn("tcp_dst", result["compiled_flows"][0]["match"])

    async def test_unknown_host_rejected(self):
        proposal = dict(READY["proposal"], source="h99")
        with self.assertRaises(HTTPException) as caught:
            await self._convert({**READY, "proposal": proposal})
        self.assertEqual(caught.exception.status_code, 422)
        self.assertEqual(caught.exception.detail["code"], "policy_dry_run_rejected")

    async def test_unsupported_skips_context_and_compiler(self):
        invalid = {"contract_version": "1.0", "status": "unsupported", "capability": None,
                   "proposal": None, "clarification": None, "reason_code": "multiple_intents"}
        with patch("app.intents.dry_run_api.get_trusted_context", side_effect=AssertionError("inventory should not be accessed")):
            result = await self._convert(invalid)
        self.assertIsNone(result["policy"])
        self.assertEqual(result["compiled_flows"], [])
        self.assertFalse(result["policy_validated"])

    async def test_clarification_has_no_policy(self):
        clarification = {"contract_version": "1.0", "status": "needs_clarification",
                         "capability": "firewall", "proposal": None,
                         "clarification": "Which destination?", "reason_code": "missing_destination"}
        result = await self._convert(clarification)
        self.assertEqual(result["status"], "needs_clarification")
        self.assertIsNone(result["policy"])

    async def test_unknown_network_rejected(self):
        with patch("app.intents.dry_run_api.translate", new=AsyncMock(return_value=translation(READY))):
            with self.assertRaises(HTTPException) as caught:
                await dry_run(DryRunRequest(text="Block traffic", network_id="other"), None)
        self.assertEqual(caught.exception.status_code, 503)

    async def test_fixture_disabled_by_default(self):
        with patch.dict(os.environ, {"LLNET_DRY_RUN_CONTEXT_MODE": "disabled"}):
            with patch("app.intents.dry_run_api.translate", new=AsyncMock(return_value=translation(READY))):
                with self.assertRaises(HTTPException) as caught:
                    await dry_run(DryRunRequest(text="Block traffic", network_id="lab"), None)
        self.assertEqual(caught.exception.status_code, 503)
        self.assertEqual(caught.exception.detail["code"], "trusted_runtime_context_unavailable")

    async def test_no_deployment_module_imports(self):
        import inspect
        import app.intents.dry_run_api as mod
        source = inspect.getsource(mod)
        for forbidden in ("from app.services.submission_service", "from app.adapters.ryu_adapter", "from app.db.session"):
            self.assertNotIn(forbidden, source)

    def test_trusted_context_from_baked_fixture_only(self):
        ctx, provenance, is_fixture = get_trusted_context("lab")
        self.assertEqual(provenance, "lab_fixture")
        self.assertTrue(is_fixture)
        self.assertEqual(ctx["hosts"]["h1"], "10.0.0.1/32")
        with self.assertRaises(ContextUnavailable):
            get_trusted_context("arbitrary")

    def test_client_cannot_override_fixture_mode(self):
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            DryRunRequest.model_validate({"text":"block", "network_id":"lab", "allow_fixture":True})


if __name__ == "__main__":
    unittest.main()
