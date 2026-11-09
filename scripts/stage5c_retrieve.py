"""Run BGE retrieval for Stage 5C, without importing application/server state."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'policy-manager'))
from app.intents.retrieval import (BGE_MODEL, RetrievalError, assemble_messages,
                                  capability_info, load_bge_encoder, retrieve)


def main():
    parser = argparse.ArgumentParser(description='Stage 5C read-only BGE retrieval')
    parser.add_argument('--text', required=True, help='English network request')
    parser.add_argument('--capability', default='firewall', help='Trusted preselected capability')
    parser.add_argument('--model', default=BGE_MODEL)
    parser.add_argument('--top-k', type=int, default=3)
    parser.add_argument('--cache', type=Path, default=Path.home() / '.cache/llnet/stage5c/bge-index.json')
    parser.add_argument('--offline', action='store_true', help='Never download model files')
    parser.add_argument('--show-messages', action='store_true', help='Print assembled prompt messages')
    args = parser.parse_args()
    try:
        capability_info(args.capability)  # refuse disabled capabilities before model initialization
        encoder = load_bge_encoder(args.model, local_files_only=args.offline)
        result = retrieve(args.text, capability=args.capability, encoder=encoder,
                          model_id=args.model, top_k=args.top_k, cache_path=args.cache)
        # Normal CLI only shows IDs/status/similarity, not gold policies or embeddings.
        out = {'index_version': result['index_version'], 'model_id': result['model_id'],
               'corpus_fingerprint': result['corpus_fingerprint'],
               'index_cache_hit': result['index_cache_hit'], 'capability': result['capability'],
               'retrieved': [{'example_id': ex['id'], 'score': ex['score'],
                              'status': ex['expected_model_result']['status']}
                             for ex in result['examples']]}
        if args.show_messages:
            out['messages'] = assemble_messages(args.text, result)
        print(json.dumps(out, indent=2, ensure_ascii=False))
    except (RetrievalError, OSError, ValueError) as exc:
        parser.exit(2, 'retrieval refused: ' + str(exc) + '\n')


if __name__ == '__main__':
    main()
