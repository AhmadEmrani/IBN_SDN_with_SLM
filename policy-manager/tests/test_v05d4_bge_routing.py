"""Offline routing tests: deterministic synthetic vectors, never fetch BGE."""
import tempfile
import unittest
from pathlib import Path
from app.intents.capability_routing import route_intent, guard_labels, load_prototypes

class FakeEncoder:
    def __call__(self, texts):
        vectors=[]
        for text in texts:
            t=text.lower()
            # deterministic test double; production uses actual BGE.
            from app.intents.capability_routing import guard_labels
            labels=guard_labels(t)
            if 'firewall' in labels: vectors.append([1.0,0.0,0.0])
            elif 'rate_limit' in labels: vectors.append([0.0,1.0,0.0])
            elif 'load_profile' in labels: vectors.append([0.0,0.0,1.0])
            else: vectors.append([0.4,0.4,0.4])
        return vectors

class RouterTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.cache=Path(self.tmp.name)/'cache.json'
    def route(self,text):return route_intent(text,encoder=FakeEncoder(),cache_path=self.cache,min_score=.7,min_margin=.02)
    def test_all_capabilities_in_prototypes(self):
        rows=load_prototypes();self.assertEqual({r['result']['capability'] for r in rows},{'firewall','rate_limit','load_profile'})
    def test_explicit_multi_guard(self):
        r=self.route('Block TCP and throttle bandwidth to 5 Mbps')
        self.assertEqual(r['routing_status'],'multiple');self.assertFalse(self.cache.exists())
    def test_firewall_selected(self):
        r=self.route('Block TCP traffic from h1 to h2')
        self.assertEqual(r['capability'],'firewall');self.assertTrue(r['supported'])
    def test_rate_detected_but_disabled(self):
        r=self.route('Throttle network bandwidth to 10Mbps')
        self.assertEqual(r['capability'],'rate_limit');self.assertEqual(r['routing_status'],'unsupported')
    def test_load_detected_but_disabled(self):
        r=self.route('Simulate a synthetic network workload')
        self.assertEqual(r['capability'],'load_profile');self.assertEqual(r['routing_status'],'unsupported')
    def test_vague_no_forced_firewall(self):
        r=self.route('Make the network faster');self.assertEqual(r['routing_status'],'ambiguous')
    def test_unknown_no_forced_firewall(self):
        r=self.route('What is the weather tomorrow?')
        self.assertNotEqual(r['routing_status'],'selected')
    def test_cache_used_on_second_call(self):
        self.assertFalse(self.route('Block TCP from h1')['index_cache_hit'])
        self.assertTrue(self.route('Deny packets from h2')['index_cache_hit'])
    def test_input_invalid(self):
        for text in ('', ' '):
            with self.assertRaises(ValueError):self.route(text)
    def test_guard_labels(self):
        self.assertEqual(guard_labels('Deny UDP and set QoS at 5 Mbps'),{'firewall','rate_limit'})

if __name__=='__main__':unittest.main()
