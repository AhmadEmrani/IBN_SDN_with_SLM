FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/workspace/policy-manager \
    HF_HOME=/var/cache/llnet/huggingface \
    TOKENIZERS_PARALLELISM=false
WORKDIR /workspace
RUN python -m pip install --no-cache-dir --timeout 120 --retries 5 \
      torch==2.5.1 --index-url https://download.pytorch.org/whl/cpu \
 && python -m pip install --no-cache-dir --timeout 120 --retries 5 \
      'sentence-transformers==3.4.1' 'transformers==4.49.0' 'fastapi>=0.115,<1' \
      'uvicorn>=0.30,<1' 'httpx>=0.27,<1' 'pydantic>=2.8,<3'
RUN python -m pip check \
 && python -c "import torch, transformers, sentence_transformers; print('BGE dependencies:', torch.__version__, transformers.__version__, sentence_transformers.__version__)"
COPY policy-manager/app/intents /workspace/policy-manager/app/intents
COPY contracts/intent-v1 /workspace/contracts/intent-v1
COPY data/intents/stage5a /workspace/data/intents/stage5a
COPY data/intents/stage5d4/routing-prototypes.jsonl /workspace/data/intents/stage5d4/routing-prototypes.jsonl
COPY prompts/intents/v1 /workspace/prompts/intents/v1
COPY scripts/retrieve_examples.py /workspace/scripts/retrieve_examples.py
COPY policy-manager/tests/test_v05c_retriever_api.py /workspace/policy-manager/tests/test_v05c_retriever_api.py
COPY policy-manager/tests/test_v05d4_bge_routing.py /workspace/policy-manager/tests/test_v05d4_bge_routing.py
RUN mkdir -p /var/cache/llnet/huggingface /var/cache/llnet/index
EXPOSE 8092
CMD ["uvicorn", "app.intents.retriever_app:app", "--host", "0.0.0.0", "--port", "8092"]
