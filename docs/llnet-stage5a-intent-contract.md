# LLNet Stage 5A — Intent contract v1

## Baseline
GitHub `AhmadEmrani/IBN_SDN_with_SLM`, main at `5736be03b16b0ad84fd2acf56005f4303837f5c3` (Stage 4C merged).
This is an ADDITIVE documentation and fixture overlay: no Docker changes, no migrations,
no API route, BGE, Phi, embedding service, new executable policy code or deployment.

## Purpose and boundaries
Natural-language request -> model result (`ready` / `needs_clarification` /
`unsupported`). The LLM generates only a semantic proposal. Backend MUST independently
validate, resolve hosts against authoritative inventory, assign policy identity, scope,
priority and intent ID, validate `PolicyInput`, and compile it before any deployment.
The semantic proposal is not a deployment authorization. The existing lifecycle engine
and eventual Digital Twin validation remain downstream gates.

## Three capabilities
`firewall`: enabled, create IPv4 deny only. `rate_limit` and `load_profile`: disabled;
unsupported/capability_disabled. Future capabilities must supply their own schemas,
resolver mappings, prompt rules and tests; avoid hard-coded fallback to firewall.

## Data contract
`contracts/intent-v1/translate-request.schema.json`: text + network_id.
`contracts/intent-v1/model-result.schema.json`: discriminated status branches.
`contracts/intent-v1/capabilities.json`: registry of enabled and disabled capabilities.
`data/intents/stage5a/firewall-contract-seed.jsonl`: 20 independent oracles.
`data/intents/stage5a/network-context.json`: fake h1, h2, h3, switch 1.

## Prompt order
System constraints/schema, trusted resolved context, relevant retrieved examples,
then user text. Never expose the expected backend policy as an assistant example.
BGE, pgvector, prompt selector and Phi are intentionally deferred.

## Next steps
5B: deterministic schema/semantic validator, authoritative resolver, adapter and
unit tests. 5C: BGE & example retrieval. 5D: Phi inference, measured evaluation and
Digital Twin preflight integration. Introduce independent held-out scenario families.
