"""Manual Stage-2 worker. Stage 3 replaces manual triggering with Airflow."""
import argparse
from app.services.execution_service import run_operation


def main():
    parser = argparse.ArgumentParser(description='Run one pending LLNet policy operation')
    parser.add_argument('operation_id')
    args = parser.parse_args()
    outcome = run_operation(args.operation_id)
    print(f'Operation {args.operation_id}: {outcome}')
    if outcome != 'succeeded':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
