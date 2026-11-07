"""Explicitly gated Stage 4B repair. Default is read-only check."""
import argparse
import json

from app.reconciliation.repair import RepairRefused, apply, check


def main():
    parser = argparse.ArgumentParser(description='Repair one confirmed missing LLNet DROP flow')
    parser.add_argument('--finding-id', required=True, help='ID of an open confirmed missing finding')
    parser.add_argument('--apply', action='store_true', help='Explicitly allow ONE verified OpenFlow ADD')
    args = parser.parse_args()
    try:
        result = apply(args.finding_id) if args.apply else check(args.finding_id)
    except RepairRefused as exc:
        print(json.dumps({'status': 'refused', 'reason': str(exc)}), flush=True)
        raise SystemExit(2) from exc
    print(json.dumps({'status': result.status, 'reason': result.reason,
                      'operation_id': result.operation_id}), flush=True)
    if result.status in ('failed', 'unresolved'):
        raise SystemExit(3)


if __name__ == '__main__':
    main()
