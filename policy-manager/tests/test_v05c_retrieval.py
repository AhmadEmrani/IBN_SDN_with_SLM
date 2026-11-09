"""Stage 5C deterministic offline contract tests; no model download or Docker."""
import json
import tempfile
import unittest
from pathlib import Path

from app.intents.retrieval import (BGE_MODEL, QUERY_INSTRUCTION, RetrievalError,
    ROOT, assemble_messages, capability_info, load_corpus, retrieve)


class FakeEncoder:
    def __init__(self):
        self.calls = []

    def __call__(self, texts):
        self.calls.append(list(texts))
        output = []
        for text in texts:
            low = text.lower()
            if 'h9' in low or 'unknown' in low:
                output.append([0, 0, 1, 0])
            elif 'port' in low:
                output.append([0, 1, 0, 0])
            elif 'between' in low:
                output.append([0, 0, 0, 1])
            else:
                output.append([1, 0, 0, 0])
        return output


class RetrievalTests(unittest.TestCase):
    def setUp(self):
        self.encoder = FakeEncoder()
        self.tmp = tempfile.TemporaryDirectory()
        self.cache = Path(self.tmp.name) / 'bge.json'

    def tearDown(self):
        self.tmp.cleanup()

    def run_retrieval(self, text='Block traffic from h1 to h2.', **kw):
        return retrieve(text, capability='firewall', encoder=self.encoder,
                        model_id='fake-test-encoder-v1', cache_path=self.cache, **kw)

    def test_firewall_corpus_contains_18_enabled_examples(self):
        rows = load_corpus()
        self.assertEqual(18, len(rows))  # two disabled examples excluded
        self.assertEqual(10, sum(r['result']['status'] == 'ready' for r in rows))
        self.assertEqual(4, sum(r['result']['status'] == 'needs_clarification' for r in rows))
        self.assertEqual(4, sum(r['result']['status'] == 'unsupported' for r in rows))

    def test_disabled_capabilities_are_refused(self):
        for value in ('rate_limit', 'load_profile'):
            with self.subTest(value=value), self.assertRaisesRegex(RetrievalError, 'capability_disabled'):
                retrieve('hello', capability=value, encoder=self.encoder, model_id='fake')
        self.assertEqual([], self.encoder.calls)

    def test_unknown_capability_refused(self):
        with self.assertRaisesRegex(RetrievalError, 'unknown_capability'):
            capability_info('traffic_engineering')

    def test_top_k_and_determinism(self):
        r1 = self.run_retrieval(top_k=3)
        r2 = self.run_retrieval(top_k=3)
        self.assertEqual(3, len(r1['examples']))
        self.assertEqual([r['id'] for r in r1['examples']], [r['id'] for r in r2['examples']])
        self.assertEqual(sorted([r['score'] for r in r1['examples']], reverse=True),
                         [r['score'] for r in r1['examples']])

    def test_cache_hit_skips_corpus_encode(self):
        first = self.run_retrieval()
        self.assertFalse(first['index_cache_hit'])
        self.assertEqual(2, len(self.encoder.calls))
        second = self.run_retrieval()
        self.assertTrue(second['index_cache_hit'])
        self.assertEqual(3, len(self.encoder.calls))
        self.assertEqual(1, len(self.encoder.calls[-1]))

    def test_corrupt_cache_forces_safe_rebuild(self):
        self.run_retrieval()
        self.cache.write_text('{this is invalid', encoding='utf-8')
        self.assertFalse(self.run_retrieval()['index_cache_hit'])

    def test_invalid_cache_dimensions_rebuild(self):
        self.run_retrieval()
        cache = json.loads(self.cache.read_text(encoding='utf-8'))
        cache['vectors'][0] = [1.0]
        self.cache.write_text(json.dumps(cache), encoding='utf-8')
        self.assertFalse(self.run_retrieval()['index_cache_hit'])

    def test_model_id_changes_cache_key(self):
        self.run_retrieval()
        r = retrieve('Block from h1 to h2', capability='firewall', encoder=self.encoder,
                     model_id='fake-test-encoder-v2', cache_path=self.cache)
        self.assertFalse(r['index_cache_hit'])

    def test_query_uses_bge_instruction_only_for_query(self):
        self.run_retrieval()
        self.assertTrue(self.encoder.calls[-1][0].startswith(QUERY_INSTRUCTION))
        self.assertTrue(all(not t.startswith(QUERY_INSTRUCTION) for t in self.encoder.calls[0]))

    def test_negative_example_can_be_retrieved(self):
        r = self.run_retrieval('Block from h9 to h2', top_k=10)
        self.assertIn('needs_clarification', [x['expected_model_result']['status'] for x in r['examples']])

    def test_no_gold_policy_or_metadata_in_prompt(self):
        result = self.run_retrieval(top_k=3)
        messages = assemble_messages('Block traffic from h1 to h2', result)
        self.assertEqual(8, len(messages))
        self.assertEqual(['system', 'user', 'assistant', 'user', 'assistant', 'user', 'assistant', 'user'],
                         [m['role'] for m in messages])
        body = json.dumps(messages)
        self.assertNotIn('expected_policy', body)
        self.assertNotIn('expected_flow_count', body)
        self.assertNotIn('example_id', body)
        self.assertNotIn('scenario_id', body)
        self.assertNotIn('embedding', body.lower())
        self.assertEqual('Block traffic from h1 to h2', messages[-1]['content'])
        self.assertIn('oneOf', messages[0]['content'])

    def test_more_than_4000_chars_refused(self):
        with self.assertRaisesRegex(RetrievalError, '4000'):
            self.run_retrieval('x' * 4001)

    def test_invalid_topk_refused(self):
        for val in (0, 11, True):
            with self.subTest(val=val), self.assertRaises(RetrievalError):
                self.run_retrieval(top_k=val)

    def test_corpus_filters_noneligible_and_wrong_version(self):
        orig = (ROOT / 'data/intents/stage5a/firewall-contract-seed.jsonl').read_text(encoding='utf-8')
        rows = [json.loads(x) for x in orig.splitlines() if x.strip()]
        rows[0]['retrieval_eligible'] = False
        rows[1]['expected_model_result']['contract_version'] = '9.9'
        file = Path(self.tmp.name) / 'rows.jsonl'
        file.write_text('\n'.join(json.dumps(x) for x in rows), encoding='utf-8')
        eligible = load_corpus(file)
        self.assertEqual(16, len(eligible))

    def test_zero_or_nonfinite_embeddings_refused(self):
        with self.assertRaises(RetrievalError):
            retrieve('Block', capability='firewall', model_id='x', encoder=lambda xs: [[0.0, 0.0] for _ in xs])
        with self.assertRaises(RetrievalError):
            retrieve('Block', capability='firewall', model_id='x', encoder=lambda xs: [[float('nan')] for _ in xs])

    def test_example_assistant_is_only_model_result(self):
        result = self.run_retrieval(top_k=1)
        messages = assemble_messages('Block traffic from h1 to h2', result)
        self.assertEqual(result['examples'][0]['expected_model_result'], json.loads(messages[2]['content']))

    def test_no_network_or_policy_change_on_retrieval(self):
        result = self.run_retrieval()
        self.assertNotIn('policy', result)
        self.assertNotIn('deployment', result)
        self.assertNotIn('flow', result)


if __name__ == '__main__':
    unittest.main()
