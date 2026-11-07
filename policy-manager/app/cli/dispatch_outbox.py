"""Dedicated dispatcher process; never run it inside the API worker."""
import argparse
import logging
import time
from app.services.outbox_dispatcher import dispatch_once


def main():
    parser = argparse.ArgumentParser(description='Deliver LLNet outbox events to Airflow')
    parser.add_argument('--once', action='store_true', help='Process at most one due event')
    parser.add_argument('--interval', type=float, default=5.0)
    args = parser.parse_args()
    if args.interval <= 0:
        parser.error('--interval must be positive')
    logging.basicConfig(level=logging.INFO)
    if args.once:
        dispatch_once()
        return
    while True:
        try:
            if not dispatch_once():
                time.sleep(args.interval)
        except Exception:
            logging.exception('Dispatcher cycle failed, retrying')
            time.sleep(args.interval)


if __name__ == '__main__':
    main()
