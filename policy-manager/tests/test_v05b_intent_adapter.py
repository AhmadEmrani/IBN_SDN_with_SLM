"""Stage 5B contract tests, no DB, external services, or writes."""
import json
from pathlib import Path
import unittest
from copy import deepcopy

from app.intents.adapter import adapt_model_result, IntentContractError, PROJECT_ROOT
from app.schemas.policy import PolicyInput
from app.services.compiler import compile_policy

DATA = PROJECT_ROOT / 'data/intents/stage5a'


class IntentAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.context = json.loads((DATA / 'network-context.json').read_text())
        cls.fixtures = [json.loads(line) for line in (DATA / 'firewall-contract-seed.jsonl').read_text().splitlines() if line.strip()]

    def adapt(self, model, *, context=None, allow_fixture=True, intent_id='example'):
        return adapt_model_result(model, context=self.context if context is None else context,
                                  network_id='lab', intent_id=intent_id, allow_fixture=allow_fixture)

    def test_all_20_gold_contracts_match_backend(self):
        self.assertEqual(20, len(self.fixtures))
        counts = {'ready': 0, 'needs_clarification': 0, 'unsupported': 0}
        for record in self.fixtures:
            with self.subTest(example=record['example_id']):
                expected = record['expected_model_result']
                counts[expected['status']] += 1
                got = self.adapt(expected, intent_id=record['example_id'])
                self.assertEqual(record['expected_converter_status'], got['status'])
                self.assertEqual(expected['reason_code'], got['reason_code'])
                self.assertEqual(record['expected_policy'], got['policy'])
                if got['status'] == 'ready':
                    validated = PolicyInput.model_validate(got['policy'])
                    self.assertEqual(record['expected_flow_count'], len(compile_policy(validated, cookie=1)))
                else:
                    self.assertIsNone(got['policy'])
        self.assertEqual({'ready': 10, 'needs_clarification': 4, 'unsupported': 6}, counts)

    def test_fixture_context_refused_by_default(self):
        with self.assertRaisesRegex(IntentContractError, 'fixture_only'):
            self.adapt(self.fixtures[0]['expected_model_result'], allow_fixture=False)

    def test_network_id_mismatch_fails_closed(self):
        ctx = deepcopy(self.context)
        ctx['network_id'] = 'other'
        with self.assertRaisesRegex(IntentContractError, 'network_id'):
            self.adapt(self.fixtures[0]['expected_model_result'], context=ctx)

    def test_unknown_host_cannot_be_guessed(self):
        r = deepcopy(self.fixtures[0]['expected_model_result'])
        r['proposal']['source'] = 'h9'
        with self.assertRaisesRegex(IntentContractError, 'unknown_host'):
            self.adapt(r)

    def test_invalid_default_switch_fails_closed(self):
        ctx = deepcopy(self.context)
        ctx['default_switches'] = ['999']
        with self.assertRaisesRegex(IntentContractError, 'default switch'):
            self.adapt(self.fixtures[0]['expected_model_result'], context=ctx)

    def test_extra_output_fields_are_rejected(self):
        r = deepcopy(self.fixtures[0]['expected_model_result'])
        r['execute'] = True
        with self.assertRaisesRegex(IntentContractError, 'schema invalid'):
            self.adapt(r)

    def test_invalid_ports_rejected_before_compilation(self):
        r = deepcopy(self.fixtures[3]['expected_model_result'])
        r['proposal']['destination_ports'] = [70000]
        with self.assertRaisesRegex(IntentContractError, 'schema invalid'):
            self.adapt(r)

    def test_nonready_never_returns_policy(self):
        for r in self.fixtures[10:]:
            with self.subTest(example=r['example_id']):
                self.assertIsNone(self.adapt(r['expected_model_result'])['policy'])

    def test_unknown_untrusted_inventory_hosts_are_not_assumed(self):
        ctx = deepcopy(self.context)
        ctx['hosts'].pop('h1')
        with self.assertRaises(IntentContractError):
            self.adapt(self.fixtures[0]['expected_model_result'], context=ctx)

    def test_raw_model_result_is_not_accepted_as_policy(self):
        self.assertNotIn('scope', self.fixtures[0]['expected_model_result']['proposal'])
        self.assertNotIn('priority', self.fixtures[0]['expected_model_result']['proposal'])

    def test_missing_trusted_intent_id_is_rejected(self):
        with self.assertRaisesRegex(IntentContractError, 'intent_id'):
            self.adapt(self.fixtures[0]['expected_model_result'], intent_id='')


if __name__ == '__main__':
    unittest.main()
