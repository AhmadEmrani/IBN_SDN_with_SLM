#!/usr/bin/env python3
"""Safely register the Stage 5D.2 service in the existing Stage 5D Compose file."""
from pathlib import Path

root = Path(__file__).resolve().parents[1]
compose = root / 'compose.stage5d.yml'
env = root / '.env'
if not compose.is_file() or not env.is_file():
    raise SystemExit('Missing compose.stage5d.yml or .env; apply the Stage 5D.1 overlay first')

service = '''\n  # Stage 5D.2: read-only BGE -> Phi -> JSON validation. No SDN execution.\n  intent-orchestrator:\n    build:\n      context: .\n      dockerfile: Dockerfile.intent-orchestrator\n    environment:\n      LLNET_RETRIEVER_URL: http://intent-retriever:8092\n      LLNET_PHI_URL: http://phi-inference:8093\n      LLNET_PHI_TIMEOUT_SECONDS: '180'\n    ports:\n      - '127.0.0.1:8094:8094'\n    restart: unless-stopped\n    networks: [sdn-net]\n'''
contents = compose.read_text(encoding='utf-8')
if '\n  intent-orchestrator:' not in contents:
    if '\nservices:\n' not in '\n' + contents or '\nvolumes:' in contents or '\nnetworks:' in contents:
        raise SystemExit('Unexpected Stage 5D Compose structure; refusing to edit')
    compose.write_text(contents.rstrip() + '\n' + service, encoding='utf-8')
    print('Added intent-orchestrator to existing compose.stage5d.yml')
else:
    print('intent-orchestrator already registered')

lines = env.read_text(encoding='utf-8').splitlines()
wanted = 'COMPOSE_FILE=docker-compose.yml:compose.stage5c.yml:compose.stage5d.yml'
new_lines = [line for line in lines if not line.startswith('COMPOSE_FILE=')]
new_lines.append(wanted)
env.write_text('\n'.join(new_lines) + '\n', encoding='utf-8')
env.chmod(0o600)
print('COMPOSE_FILE set to 3 existing Compose files')
print('Run: docker compose config --quiet')
