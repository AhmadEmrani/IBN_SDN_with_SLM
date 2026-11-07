"""One-off or polling Stage 4A observer. Never executes a repair."""
import argparse
import json
import logging
import time

from app.reconciliation.service import observe_once


def main():
    parser = argparse.ArgumentParser(description='LLNet read-only SDN flow observer')
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--once', action='store_true', help='Observe exactly once')
    mode.add_argument('--interval', type=int, metavar='SECONDS', help='Poll every N seconds')
    args = parser.parse_args()
    if args.interval is not None and args.interval < 5:
        parser.error('--interval must be >= 5 seconds')
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    while True:
        try:
            print(json.dumps(observe_once()), flush=True)
        except Exception:
            logging.exception('Reconciliation observation failed; no network writes attempted')
            if args.once:
                raise
        if args.once:
            break
        time.sleep(args.interval)


if __name__ == '__main__':
    main()
