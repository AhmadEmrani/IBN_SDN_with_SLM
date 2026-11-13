FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/workspace/policy-manager
WORKDIR /workspace
RUN pip install --no-cache-dir 'fastapi==0.115.12' 'uvicorn==0.34.2' 'httpx==0.28.1' 'jsonschema==4.23.0' \
 && pip check
COPY policy-manager/app/__init__.py /workspace/policy-manager/app/__init__.py
COPY policy-manager/app/intents /workspace/policy-manager/app/intents
COPY policy-manager/app/schemas/__init__.py /workspace/policy-manager/app/schemas/__init__.py
COPY policy-manager/app/schemas/policy.py /workspace/policy-manager/app/schemas/policy.py
COPY policy-manager/app/services/__init__.py /workspace/policy-manager/app/services/__init__.py
COPY policy-manager/app/services/compiler.py /workspace/policy-manager/app/services/compiler.py
COPY contracts/intent-v1/model-result.schema.json /workspace/contracts/intent-v1/model-result.schema.json
COPY contracts/intent-v1/capabilities.json /workspace/contracts/intent-v1/capabilities.json
COPY data/intents/stage5a/network-context.json /workspace/data/intents/stage5a/network-context.json
COPY policy-manager/tests/test_v05d2_orchestrator.py /workspace/policy-manager/tests/test_v05d2_orchestrator.py
COPY policy-manager/tests/test_v05d3_dry_run.py /workspace/policy-manager/tests/test_v05d3_dry_run.py
COPY policy-manager/tests/test_v05d4_routing.py /workspace/policy-manager/tests/test_v05d4_routing.py
COPY policy-manager/tests/test_intent_architecture.py /workspace/policy-manager/tests/test_intent_architecture.py
COPY policy-manager/tests/test_capability_boundaries.py /workspace/policy-manager/tests/test_capability_boundaries.py
EXPOSE 8094
CMD ["uvicorn", "app.intents.intent_app:app", "--host", "0.0.0.0", "--port", "8094"]
