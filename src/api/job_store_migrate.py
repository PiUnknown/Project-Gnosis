"""Operator-run reconciliation of the active-job index.

This module is intentionally NOT imported by the API, the worker, or the health
endpoint. It must be run manually, after every writer (API instances, including
the local thread-pool fallback, and workers) has been verified to run the
matching revision.

Safety properties:
  - Reconciliation is per-job atomic (WATCH/MULTI over the record + index), not
    a snapshot/RENAME, so concurrent transitions are not overwritten.
  - The initialization sentinel is added only with ``--arm`` after both scans
    complete without error. A failed or interrupted first run never arms.
  - Re-running against an already-armed index never removes the sentinel;
    individually completed repairs from a failed run are retained.
  - Running the reconciliation does not change result storage or TTLs.

Usage:
    # Reconcile without arming (safe to repeat; the legacy health path stays)
    python -m src.api.job_store_migrate

    # After verifying every writer runs this revision:
    python -m src.api.job_store_migrate --arm --confirm-all-writers-updated
"""

import argparse
import sys


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Reconcile gnosis:jobs:active with live job records."
    )
    parser.add_argument(
        "--arm",
        action="store_true",
        help="Add the initialization sentinel after a clean reconciliation.",
    )
    parser.add_argument(
        "--confirm-all-writers-updated",
        action="store_true",
        help=(
            "Required with --arm: assert that every API instance (including "
            "the local thread-pool fallback) and every worker runs this revision."
        ),
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=500,
        help="SSCAN batch size (default: 500).",
    )
    return parser


def main(argv=None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    arm = bool(args.arm)
    if arm and not args.confirm_all_writers_updated:
        print(
            "Refusing to arm: --arm requires --confirm-all-writers-updated "
            "after verifying every writer runs this revision."
        )
        return 2

    # Imported lazily so --help works even in environments without the
    # application's runtime dependencies configured.
    from src.api.job_store import ActiveIndexReconcileError, store

    if not store.is_redis:
        print("Refusing to reconcile: JobStore is not connected to Redis.")
        return 1

    try:
        stats = store.rebuild_active_index(
            batch_size=args.batch_size,
            arm=arm,
        )
    except (ActiveIndexReconcileError, ValueError) as exc:
        print(f"Active-index reconciliation failed: {type(exc).__name__}.")
        print(
            "This failed run did not arm the index; an already-armed index "
            "remains armed and may retain completed repairs."
        )
        return 1
    except Exception as exc:  # noqa: BLE001 - CLI boundary, no secret output
        print(f"Active-index reconciliation failed: {type(exc).__name__}.")
        print(
            "This failed run did not arm the index; an already-armed index "
            "remains armed and may retain completed repairs."
        )
        return 1

    print(
        "Active-index reconciliation complete: "
        f"index_scanned={stats['index_scanned']} "
        f"active_scanned={stats['active_scanned']} "
        f"reconciled={stats['reconciled']} "
        f"armed={bool(stats['armed'])}"
    )
    if not arm:
        print(
            "Not armed: sentinel state unchanged; the legacy health path "
            "remains in use unless the index was already armed."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
