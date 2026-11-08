# Prompt assembly contract (implementation pending)

1. System message: system.md + selected capability rules + output JSON schema.
2. Trusted context: resolved network inventory and capability registry version.
3. Retrieved examples: user text and assistant expected_model_result ONLY.
   Never include expected_policy, notes or fixture IDs in assistant messages.
4. User message: original request text.

Use BGE on example request.text and incoming request.text; never send vectors to Phi.
Filter examples by compatible capability/schema version and retrieval-eligible split.
Include negative cases as examples where relevant. Disabled capabilities must be
recognized before generation or returned unsupported, never forced to firewall.
Start with top-k 3 within measured token budget; this is a tuning choice, not a guarantee.
Start temperature 0; record model hash, template, schema, embedding/index versions,
retrieved example IDs and timing. This bundle does not implement any of these steps.
