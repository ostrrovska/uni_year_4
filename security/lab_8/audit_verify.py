"""Lab 8 - check that the audit journal was not altered or truncated.

Each record carries SHA-256 over the previous record's hash and its own body, so
the journal is a chain. Editing a record, replacing it, or deleting one breaks the
chain, and the break is reported with the number of the record where it happens.
"""

import argparse
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [_HERE, os.path.dirname(_HERE)]  # run directly: find `common` and siblings

from common.audit import AuditLog

sys.stdout.reconfigure(encoding="utf-8")  # Cyrillic output survives a pipe

DEFAULT_JOURNAL = os.path.join(_HERE, "logs", "audit.jsonl")


def main():
    ap = argparse.ArgumentParser(description="Verify the integrity of the audit journal")
    ap.add_argument("--journal", default=DEFAULT_JOURNAL)
    ap.add_argument("--key", default=None)
    args = ap.parse_args()

    if not os.path.isfile(args.journal):
        print(f"Журналу немає: {args.journal}")
        return 1

    log = AuditLog(args.journal, args.key) if args.key else AuditLog(args.journal)
    ok, position, reason = log.verify()

    print(f"Журнал: {args.journal}")
    print()
    if ok:
        print("ЦІЛІСНІСТЬ ПІДТВЕРДЖЕНО")
        print(f"  {reason}")
        print("  Ланцюжок хешів неперервний: жоден запис не змінено й не видалено.")
        return 0

    print("ЦІЛІСНІСТЬ ПОРУШЕНО")
    print(f"  позиція: запис №{position}")
    print(f"  {reason}")
    print()
    print("  Усі записи до цього місця достовірні, після нього довіряти журналу не можна.")
    return 3


if __name__ == "__main__":
    sys.exit(main())
