"""Lab 7 - initial set of protected objects (done once by the administrator)."""

import argparse
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [_HERE, os.path.dirname(_HERE)]  # run directly: find `common` and siblings

from acl import AccessMatrix
from common.protolog import ProtocolLog

HERE = os.path.dirname(os.path.abspath(__file__))

SEED = [
    ("ostrovska",  "finance_q1",   "Quarterly figures, draft.\n"),
    ("ostrovska",  "finance_q2",   "Quarterly figures, second quarter.\n"),
    ("ostrovska",  "passwords",    "Private notes of ostrovska.\n"),
    ("ostrovska",  "diary",        "Personal diary, nobody else may read it.\n"),
    ("shevchenko", "lab_report",   "Report on the access control subsystem.\n"),
    ("shevchenko", "poems",        "Catalogue of poems.\n"),
    ("shevchenko", "budget",       "Department budget.\n"),
    ("shevchenko", "contacts",     "Contact list.\n"),
    ("kovalenko",  "schedule",     "Timetable of the group.\n"),
    ("kovalenko",  "grades",       "Grades of the students.\n"),
    ("kovalenko",  "protocol",     "Protocol of the meeting.\n"),
    ("kovalenko",  "public_notes", "Notes meant to be shared.\n"),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--acl", default=os.path.join(HERE, "acl.json"))
    ap.add_argument("--storage", default=os.path.join(HERE, "storage"))
    ap.add_argument("--log", default=None)
    args = ap.parse_args()

    log = ProtocolLog(args.log, tag="SEED")
    for name in os.listdir(args.storage) if os.path.isdir(args.storage) else []:
        os.remove(os.path.join(args.storage, name))
    if os.path.isfile(args.acl):
        os.remove(args.acl)

    matrix = AccessMatrix(args.acl, args.storage)
    for owner, obj, text in SEED:
        matrix.create(owner, obj, text)
        log("OBJECT", f"'{obj}' created, owner '{owner}'")
    log("READY", f"{len(matrix.objects)} objects, access matrix in {args.acl}")


if __name__ == "__main__":
    main()
