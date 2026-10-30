"""Lab 8 - read the audit journal.

Without the auditor key the journal cannot be read at all: it is stored as one
encrypted record per line. With the key, records can be filtered the way an
auditor needs them.
"""

import argparse
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [_HERE, os.path.dirname(_HERE)]  # run directly: find `common` and siblings

from common.audit import AuditError, AuditLog, format_record

sys.stdout.reconfigure(encoding="utf-8")  # Cyrillic output survives a pipe

DEFAULT_JOURNAL = os.path.join(_HERE, "logs", "audit.jsonl")


def main():
    ap = argparse.ArgumentParser(description="Show the audit journal")
    ap.add_argument("--journal", default=DEFAULT_JOURNAL)
    ap.add_argument("--key", default=None, help="auditor key; the default one is used if omitted")
    ap.add_argument("--tail", type=int, default=0, help="only the last N records")
    ap.add_argument("--user", default=None, help="only this subject")
    ap.add_argument("--event", default=None, help="AUTH, ACCESS, RIGHTS, OBJECT, SESSION, SYSTEM, AUDIT")
    ap.add_argument("--result", default=None, choices=["SUCCESS", "FAILURE"])
    ap.add_argument("--raw", action="store_true", help="print the stored records as JSON")
    args = ap.parse_args()

    if not os.path.isfile(args.journal):
        print(f"Журналу немає: {args.journal}")
        print("Спершу запустіть демонстрацію лабораторної 8.")
        return 1

    log = AuditLog(args.journal, args.key) if args.key else AuditLog(args.journal)
    try:
        records = log.read_all()
    except AuditError as exc:
        print(f"Прочитати журнал не вдалося: {exc}")
        return 2

    picked = records
    if args.user:
        picked = [r for r in picked if r["subject"] == args.user]
    if args.event:
        picked = [r for r in picked if r["event"] == args.event.upper()]
    if args.result:
        picked = [r for r in picked if r["result"] == args.result]
    if args.tail:
        picked = picked[-args.tail:]

    header = f"Записів у журналі: {len(records)}"
    if len(picked) != len(records):
        header += f"    показано за фільтром: {len(picked)}"
    print(header)
    print()
    for entry in picked:
        print(repr(entry) if args.raw else format_record(entry))

    if not picked:
        print("(за цим фільтром нічого немає)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
