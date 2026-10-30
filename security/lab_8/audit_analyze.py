"""Lab 8 - look for signs of security violations in the audit journal.

A journal only records facts; a violation is a pattern across several facts. This
script looks for the patterns the subsystems of labs 6 and 7 can actually produce,
and prints the record numbers, so every finding can be shown in the journal itself.
"""

import argparse
import datetime
import os
import sys
from collections import defaultdict

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [_HERE, os.path.dirname(_HERE)]  # run directly: find `common` and siblings

from common.audit import ACCESS, AUDIT, AUTH, FAILURE, RIGHTS, SUCCESS, AuditError, AuditLog

sys.stdout.reconfigure(encoding="utf-8")  # Cyrillic output survives a pipe

DEFAULT_JOURNAL = os.path.join(_HERE, "logs", "audit.jsonl")
BURST_SECONDS = 120
BRUTE_FORCE_TRIES = 2
PROBE_DENIALS = 3


def when(entry):
    return datetime.datetime.fromisoformat(entry["ts"])


def finding(out, level, title, records, explanation):
    out.append({"level": level, "title": title,
                "records": [r["seq"] for r in records], "why": explanation})


def analyse(records):
    out = []

    # 1. repeated failed authentications from one place - password or token guessing
    by_peer = defaultdict(list)
    for r in records:
        if r["event"] == AUTH and r["result"] == FAILURE:
            by_peer[r["peer"] or "-"].append(r)
    for peer, group in by_peer.items():
        if len(group) >= BRUTE_FORCE_TRIES:
            span = (when(group[-1]) - when(group[0])).total_seconds()
            if span <= BURST_SECONDS:
                finding(out, "ВИСОКИЙ",
                        f"{len(group)} невдалих аутентифікацій з адреси {peer} за {span:.0f} с",
                        group,
                        "Схоже на підбір пароля або перебір токенів. Окрема невдала "
                        "спроба — норма, але серія у вузькому вікні часу — ні.")

    # 2. a failure followed soon by a success for the same identifier
    for i, r in enumerate(records):
        if r["event"] != AUTH or r["result"] != FAILURE:
            continue
        for later in records[i + 1:]:
            if later["event"] != AUTH or later["subject"] != r["subject"]:
                continue
            if later["result"] == SUCCESS and (when(later) - when(r)).total_seconds() <= BURST_SECONDS:
                finding(out, "ВИСОКИЙ",
                        f"невдала аутентифікація '{r['subject']}', а невдовзі вдала",
                        [r, later],
                        "Можливо, підбір завершився успіхом. Потребує перевірки, "
                        "чи це був сам користувач, що помилився при введенні.")
            break

    # 3. unknown identifiers - someone probes which accounts exist
    unknown = [r for r in records
               if r["event"] == AUTH and r["result"] == FAILURE
               and "unknown identifier" in r.get("detail", "")]
    if unknown:
        names = sorted({r["subject"] for r in unknown})
        finding(out, "СЕРЕДНІЙ",
                f"спроби входу під незареєстрованими іменами: {', '.join(names)}",
                unknown,
                "Ознака розвідки: зловмисник шукає, які облікові записи існують.")

    # 4. a burst of access denials - the subject is mapping out its own rights
    by_subject = defaultdict(list)
    for r in records:
        if r["event"] == ACCESS and r["result"] == FAILURE:
            by_subject[r["subject"]].append(r)
    for subject, group in by_subject.items():
        if len(group) >= PROBE_DENIALS:
            finding(out, "СЕРЕДНІЙ",
                    f"суб'єкт '{subject}' отримав {len(group)} відмов у доступі",
                    group,
                    "Схоже на промацування меж своїх повноважень. Сама по собі "
                    "відмова означає, що розмежування доступу спрацювало.")

    # 5. a subject granting a right to itself - abuse of a delegated 'grant'
    for r in records:
        if r["event"] != RIGHTS or r["result"] != SUCCESS:
            continue
        parts = r["action"].split()
        if len(parts) >= 4 and parts[0] == "grant" and parts[2] == r["subject"]:
            finding(out, "ВИСОКИЙ",
                    f"'{r['subject']}' видав право '{parts[3]}' самому собі на '{parts[1]}'",
                    [r],
                    "Класичне зловживання делегованим правом grant у дискреційній "
                    "моделі: той, кому доручили керувати правами, розширив власні. "
                    "Формально дозволено, по суті — порушення намірів власника.")

    # 6. the journal itself addressed by someone who is not the auditor
    for r in records:
        if r["event"] == AUDIT and r["result"] == FAILURE:
            finding(out, "ВИСОКИЙ",
                    f"'{r['subject']}' намагався прочитати журнал аудиту",
                    [r],
                    "Спроба дістатися журналу реєстрації — типовий крок перед "
                    "приховуванням слідів. Доступ відхилено підсистемою керування доступом.")

    # 7. an object deleted soon after rights on it were obtained
    granted = {}
    for r in records:
        if r["event"] == RIGHTS and r["result"] == SUCCESS:
            parts = r["action"].split()
            if len(parts) >= 3 and parts[0] == "grant":
                granted[(parts[2], parts[1])] = r
    for r in records:
        if r["event"] == ACCESS and r["result"] == SUCCESS and r["action"].startswith("delete"):
            key = (r["subject"], r.get("object"))
            if key in granted:
                finding(out, "СЕРЕДНІЙ",
                        f"'{r['subject']}' видалив '{r['object']}' після отримання прав на нього",
                        [granted[key], r],
                        "Поєднання «отримав права — одразу знищив дані» вартує уваги "
                        "навіть тоді, коли кожна дія окремо була дозволена.")

    return out


def main():
    ap = argparse.ArgumentParser(description="Look for signs of violations in the journal")
    ap.add_argument("--journal", default=DEFAULT_JOURNAL)
    ap.add_argument("--key", default=None)
    args = ap.parse_args()

    if not os.path.isfile(args.journal):
        print(f"Журналу немає: {args.journal}")
        return 1

    log = AuditLog(args.journal, args.key) if args.key else AuditLog(args.journal)
    try:
        records = log.read_all()
    except AuditError as exc:
        print(f"Прочитати журнал не вдалося: {exc}")
        return 2

    totals = defaultdict(int)
    for r in records:
        totals[(r["event"], r["result"])] += 1

    print(f"Проаналізовано записів: {len(records)}")
    print()
    print("Розподіл подій:")
    for (event, result), count in sorted(totals.items()):
        print(f"  {event:<8} {result:<8} {count}")
    print()

    results = analyse(records)
    if not results:
        print("Ознак порушень не виявлено.")
        return 0

    print(f"Виявлено ознак порушень: {len(results)}")
    print("=" * 78)
    for i, f in enumerate(results, start=1):
        seqs = ", ".join(f"#{s}" for s in f["records"])
        print()
        print(f"{i}. [{f['level']}] {f['title']}")
        print(f"   записи: {seqs}")
        print(f"   {f['why']}")

    print()
    print("=" * 78)
    print("Межі методу: журнал фіксує факти, а не наміри. Кожна знахідка вище —")
    print("лише привід для перевірки: та сама послідовність подій буває й у")
    print("законної роботи, а зловмисник із чинними повноваженнями не залишає")
    print("жодної відмови й у цей перелік не потрапляє взагалі.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
