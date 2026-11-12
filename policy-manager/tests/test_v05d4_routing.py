"""Orchestrator integration tests with fully mocked HTTP, no deployment imports."""
import json
import unittest
from unittest.mock import AsyncMock, patch
import httpx
from app.intents.orchestrator_api import TranslateRequest, route_capability, translate, RouteRequest

READY={"contract_version":"1.0","status":"ready","capability":"firewall",
       "proposal":{"source":"h1","destination":"h2","direction":"unidirectional","protocol":"tcp",
                   "source_ports":None,"destination_ports":[443],"action":"deny"},
       "clarification":None,"reason_code":None}

def routed(status, capability, reason=None):
    return {'routing_status':status,'capability':capability,
            'supported':status=='selected','reason_code':reason,'scores':{},'method':'test'}

class RoutingOrchestratorTests(unittest.IsolatedAsyncioTestCase):
    async def _run(self,routing, explicit=False):
        calls=[]
        def handler(request):
            calls.append(request.url.path)
            if request.url.path=='/v1/route-candidates':return httpx.Response(200,json=routing)
            if request.url.path=='/v1/prepare':return httpx.Response(200,json={
                'capability':'firewall', 'retrieved_example_ids':['fw-004'],
                'messages':[{'role':'system','content':'Network rules.\n\nOutput schema (JSON):\n'+json.dumps({'oneOf':[{'type':'object'}]})},
                            {'role':'user','content':'Block TCP from h1 to h2'}]})
            if request.url.path=='/v1/chat/completions':return httpx.Response(200,json={
                'choices':[{'message':{'content':json.dumps(READY)},'finish_reason':'stop'}]})
            raise AssertionError(request.url.path)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            response=await translate(TranslateRequest(text='Block TCP from h1 to h2',
                                                      capability='firewall' if explicit else None),client)
        return response,calls
    async def test_auto_firewall_enters_phi(self):
        r,calls=await self._run(routed('selected','firewall'))
        self.assertEqual(r['status'],'ready');self.assertEqual(calls,['/v1/route-candidates','/v1/prepare','/v1/chat/completions'])
        self.assertIn('routing',r)
    async def test_disabled_rate_never_calls_phi(self):
        r,calls=await self._run(routed('unsupported','rate_limit','capability_disabled'))
        self.assertEqual(r['status'],'unsupported');self.assertFalse(r['validated']);self.assertIsNone(r['model_result'])
        self.assertEqual(calls,['/v1/route-candidates'])
    async def test_disabled_load_never_calls_phi(self):
        r,calls=await self._run(routed('unsupported','load_profile','capability_disabled'))
        self.assertEqual(r['capability'],'load_profile');self.assertEqual(calls,['/v1/route-candidates'])
    async def test_ambiguous_clarifies_without_phi(self):
        r,calls=await self._run(routed('ambiguous',None,'low_margin'))
        self.assertEqual(r['status'],'needs_clarification');self.assertEqual(calls,['/v1/route-candidates'])
    async def test_multiple_rejected_without_phi(self):
        r,calls=await self._run(routed('multiple',None,'multiple_intents'))
        self.assertEqual(r['status'],'unsupported');self.assertEqual(calls,['/v1/route-candidates'])
    async def test_unknown_rejected_without_phi(self):
        r,calls=await self._run(routed('unknown',None,'out_of_scope'))
        self.assertEqual(r['status'],'unsupported');self.assertEqual(calls,['/v1/route-candidates'])
    async def test_explicit_firewall_no_route_call(self):
        r,calls=await self._run(routed('selected','firewall'),explicit=True)
        self.assertTrue(r['validated'])
        self.assertEqual(calls,['/v1/prepare','/v1/chat/completions'])
    async def test_bad_router_payload_fail_closed(self):
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req:httpx.Response(200,json={'routing_status':'selected','capability':'rate_limit'}))) as c:
            from fastapi import HTTPException
            with self.assertRaises(HTTPException) as e:await route_capability('limit something',c)
            self.assertEqual(e.exception.detail['code'],'router_unavailable_or_invalid')
    def test_request_default_auto(self):
        self.assertIsNone(TranslateRequest(text='Block something').capability)
        self.assertEqual(RouteRequest(text='x').text,'x')

if __name__=='__main__':unittest.main()
