"""Observe flows; optionally invoke safe automatic repair after each valid scan."""
import argparse
import json
import logging
import os
import time

from app.reconciliation.service import observe_once
from app.reconciliation.auto_heal import auto_heal_once


def main():
    parser = argparse.ArgumentParser(description='LLNet SDN observer (automatic repair opt-in)')
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--once', action='store_true', help='Observe exactly once')
    mode.add_argument('--interval', type=int, metavar='SECONDS', help='Poll every N seconds')
    args = parser.parse_args()
    if args.interval is not None and args.interval < 5:
        parser.error('--interval must be >= 5 seconds')
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    auto_enabled = (args.interval is not None and
                    os.getenv('LLNET_AUTO_HEAL', 'false').lower() in ('true', '1', 'yes', 'on'))
    logging.info('Automatic repair %s', 'ENABLED' if auto_enabled else 'DISABLED')
    while True:
        observed = False
        try:
            print(json.dumps(observe_once()), flush=True)
            observed = True
        except Exception:
            logging.exception('Observation failed; automatic repair skipped this cycle')
            if args.once:
                raise
        if observed and auto_enabled:
            try:
                result = auto_heal_once()
                if result is not None:
                    logging.info('Automatic repair %s', result)
            except Exception:
                # A crash may have occurred *after* an OpenFlow write. Stage 4B's
                # durable operation/reservation decides whether a retry is safe.
                logging.exception('Automatic repair error; inspect operations before manual action')
        if args.once:
            break
        time.sleep(args.interval)


if __name__ == '__main__':
    main()
