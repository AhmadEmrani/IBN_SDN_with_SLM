# Stage 5A: authored reference fixtures

20 independent English scenarios: 10 ready, 4 needs_clarification, 6 unsupported.
These are contract seeds, NOT model predictions, NOT a held-out benchmark and NOT
Chatito/GPT-generated training data. `expected_model_result` is an authored oracle.
`expected_policy` is the expected backend mapping only for ready scenarios.
No test should deploy all the rules together; some intentionally overlap.
`network-context.json` is a TEST FIXTURE, not live inventory. A production resolver
must obtain authoritative network context. Never count success on this seed as SLM accuracy.
Future paraphrase families must be split by scenario family BEFORE paraphrasing.
