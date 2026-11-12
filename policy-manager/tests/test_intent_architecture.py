"""Architecture regression: public paths and read-only imports."""
import unittest
from fastapi.testclient import TestClient
from app.intents.intent_app import app as intent_app
from app.intents.retriever_app import app as retriever_app

class IntentArchitectureTests(unittest.TestCase):
    def test_intent_routes_preserved(self):
        methods={(m,path) for r in intent_app.routes for path in [getattr(r,'path',None)] for m in getattr(r,'methods',())}
        for path in ('/v1/intents/route','/v1/intents/translate','/v1/intents/dry-run'):
            self.assertIn(('POST',path),methods)
        self.assertEqual(200,TestClient(intent_app).get('/health').status_code)

    def test_retriever_routes_preserved(self):
        paths={getattr(r,'path',None) for r in retriever_app.routes}
        for path in ('/health','/v1/retrieve','/v1/prepare','/v1/route-candidates'):
            self.assertIn(path, paths)

    def test_application_imports_no_actuation(self):
        import inspect
        from app.intents import orchestrator_service, dry_run_service
        for mod in (orchestrator_service,dry_run_service):
            s=inspect.getsource(mod)
            for forbidden in ('from app.db.', 'from app.adapters.ryu_adapter',
                              'from app.services.submission_service', 'from app.services.execution_service'):
                self.assertNotIn(forbidden,s)

if __name__=='__main__':unittest.main()
