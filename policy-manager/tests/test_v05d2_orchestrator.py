"""Unit tests use mocked HTTP responses; no model, policy API or SDN access."""
from __future__ import annotations

import json
import unittest

import httpx
from fastapi import HTTPException

from app.intents.orchestrator_api import TranslateRequest, translate, _compact_phi_messages


READY = {
    'contract_version': '1.0', 'status': 'ready', 'capability': 'firewall',
    'proposal': {
        'source': 'h1', 'destination': 'h2', 'direction': 'unidirectional',
        'protocol': 'tcp', 'source_ports': None, 'destination_ports': [443],
        'action': 'deny',
    }, 'clarification': None, 'reason_code': None,
}


class OrchestratorTests(unittest.IsolatedAsyncioTestCase):
    async def _run(self, content=None, finish_reason='stop', prepare_status=200):
        called = []

        def handler(request: httpx.Request) -> httpx.Response:
            called.append((request.url.path, json.loads(request.content)))
            if request.url.path == '/v1/prepare':
                return httpx.Response(prepare_status, json={
                    'capability': 'firewall', 'messages': [{'role': 'system', 'content':
                        'Do not invent hosts.\n\nOutput schema (JSON):\n' +
                        json.dumps({'oneOf': [{'type': 'object'}]})},
                                 {'role': 'user', 'content': 'Block TCP traffic'}],
                    'retrieved_example_ids': ['fw-004'],
                })
            if request.url.path == '/v1/chat/completions':
                return httpx.Response(200, json={
                    'choices': [{'message': {'content': content if content is not None else json.dumps(READY)},
                                 'finish_reason': finish_reason}],
                })
            raise AssertionError('Unexpected downstream call: ' + str(request.url))

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await translate(TranslateRequest(text='Block TCP traffic', capability='firewall'), client)
        return result, called

    async def test_valid_ready(self):
        result, called = await self._run()
        self.assertEqual(result['status'], 'ready')
        self.assertTrue(result['validated'])
        self.assertEqual(result['deployment'], 'not_requested')
        self.assertEqual([path for path, _ in called], ['/v1/prepare', '/v1/chat/completions'])
        self.assertEqual(called[0][1]['top_k'], 3)
        self.assertEqual(called[1][1]['temperature'], 0)
        self.assertNotIn('response_format', called[1][1])
        self.assertEqual(called[1][1]['max_tokens'], 1024)
        self.assertIn('\n {', called[1][1]['stop'])
        self.assertNotIn('Output schema (JSON)', called[1][1]['messages'][0]['content'])
        self.assertIn('Do not invent hosts.', called[1][1]['messages'][0]['content'])

    async def test_valid_clarification(self):
        result = {
            'contract_version': '1.0', 'status': 'needs_clarification',
            'capability': 'firewall', 'proposal': None,
            'clarification': 'Which destination?', 'reason_code': 'missing_destination',
        }
        response, _ = await self._run(json.dumps(result))
        self.assertEqual(response['status'], 'needs_clarification')

    async def test_valid_unsupported(self):
        result = {
            'contract_version': '1.0', 'status': 'unsupported',
            'capability': None, 'proposal': None, 'clarification': None,
            'reason_code': 'multiple_intents',
        }
        response, _ = await self._run(json.dumps(result))
        self.assertEqual(response['status'], 'unsupported')

    def test_compact_prompt_keeps_few_shots(self):
        original = [
            {'role': 'system', 'content': 'IMPORTANT FIREWALL RULES\n\nOutput schema (JSON):\n' +
             json.dumps({'oneOf': [{'type': 'object'}]})},
            {'role': 'user', 'content': 'Example'},
            {'role': 'assistant', 'content': json.dumps(READY)},
            {'role': 'user', 'content': 'New request'},
        ]
        result = _compact_phi_messages(original)
        self.assertEqual(result[1:], original[1:])
        self.assertIn('IMPORTANT FIREWALL RULES', result[0]['content'])
        self.assertNotIn('oneOf', result[0]['content'])

    async def test_reject_multiple_json_objects(self):
        with self.assertRaises(HTTPException) as caught:
            await self._run(json.dumps(READY) + '\n' + json.dumps(READY))
        self.assertEqual(caught.exception.detail['code'], 'invalid_model_json')

    async def test_reject_trailing_schema_echo(self):
        with self.assertRaises(HTTPException) as caught:
            await self._run(json.dumps(READY) + '\n' + json.dumps({'$schema': 'example'}))
        self.assertEqual(caught.exception.detail['code'], 'invalid_model_json')

    async def test_reject_non_json(self):
        with self.assertRaises(HTTPException) as caught:
            await self._run('Some prose and not JSON')
        self.assertEqual(caught.exception.status_code, 502)
        self.assertEqual(caught.exception.detail['code'], 'invalid_model_json')

    async def test_reject_wrong_schema(self):
        with self.assertRaises(HTTPException) as caught:
            await self._run('{"status":"ready"}')
        self.assertEqual(caught.exception.detail['code'], 'model_contract_violation')

    async def test_reject_truncated_generation(self):
        with self.assertRaises(HTTPException) as caught:
            await self._run(json.dumps(READY), finish_reason='length')
        self.assertEqual(caught.exception.detail['code'], 'phi_output_truncated')

    async def test_disabled_capability_does_not_call_downstream(self):
        called = []
        def handler(request):
            called.append(request.url.path)
            raise AssertionError('downstream must not be called')
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with self.assertRaises(HTTPException) as caught:
                await translate(TranslateRequest(text='Limit bandwidth', capability='rate_limit'), client)
        self.assertEqual(caught.exception.status_code, 422)
        self.assertEqual(called, [])

    async def test_retriever_error_does_not_call_phi(self):
        with self.assertRaises(HTTPException) as caught:
            await self._run(prepare_status=503)
        self.assertEqual(caught.exception.detail['code'], 'retriever_unavailable_or_invalid')

    async def test_reject_wrong_capability(self):
        result = dict(READY, status='unsupported', proposal=None, clarification=None,
                      capability='rate_limit', reason_code='capability_disabled')
        with self.assertRaises(HTTPException) as caught:
            await self._run(json.dumps(result))
        self.assertEqual(caught.exception.detail['code'], 'capability_mismatch')

    async def test_model_result_unsupported_action_not_ready(self):
        result = dict(READY)
        result['proposal'] = dict(READY['proposal'], action='allow')
        with self.assertRaises(HTTPException) as caught:
            await self._run(json.dumps(result))
        self.assertEqual(caught.exception.detail['code'], 'model_contract_violation')


if __name__ == '__main__':
    unittest.main()
