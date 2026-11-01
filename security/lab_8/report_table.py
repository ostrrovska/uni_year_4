"""Lab 8 - the two-column protocol the task asks for.

Left column: what the user did. Right column: how that action is reflected in the
audit journal. The pairing needs no guessing, because every record already stores
the action that produced it.
"""

import argparse
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [_HERE, os.path.dirname(_HERE)]  # run directly: find `common` and siblings

from common.audit import SUCCESS, AuditError, AuditLog

sys.stdout.reconfigure(encoding="utf-8")  # Cyrillic output survives a pipe

DEFAULT_JOURNAL = os.path.join(_HERE, "logs", "audit.jsonl")
DEFAULT_OUT = os.path.join(_HERE, "logs", "audit_table.md")

# how an action reads in Ukrainian for the left column
PHRASE = {
    "authenticate": "пред'явив токен і пройшов аутентифікацію",
    "open": "відкрив сесію",
    "close": "завершив сесію",
    "read": "спробував прочитати об'єкт",
    "write": "спробував дописати в об'єкт",
    "delete": "спробував видалити об'єкт",
    "create": "створив об'єкт",
    "grant": "спробував надати право",
    "revoke": "спробував відкликати право",
    "audit": "звернувся до журналу аудиту",
    "list": "переглянув перелік об'єктів",
    "caps": "переглянув власні повноваження",
    "matrix": "переглянув матрицю доступу",
    "rights": "переглянув список доступу об'єкта",
}


def user_action(entry):
    """The left column: who did what, in words."""
    if entry["event"] == "SYSTEM":
        return f"*(система)* {entry['action']}"

    verb = entry["action"].split()[0] if entry["action"] else ""
    phrase = PHRASE.get(verb, entry["action"])
    subject = entry["subject"]
    tail = ""
    if entry.get("object"):
        tail = f" `{entry['object']}`"
    elif verb in ("grant", "revoke"):
        parts = entry["action"].split()
        if len(parts) >= 4:
            tail = f" `{parts[3]}` на `{parts[1]}` для `{parts[2]}`"
    return f"**{subject}** {phrase}{tail}<br>`{entry['action']}`"


def journal_entry(entry):
    """The right column: the record as the auditor reads it."""
    mark = "SUCCESS" if entry["result"] == SUCCESS else "FAILURE"
    rows = [
        f"`#{entry['seq']}` &nbsp; {entry['ts'].replace('T', ' ')}",
        f"**{entry['event']} / {mark}**",
    ]
    if entry.get("peer"):
        rows.append(f"джерело: `{entry['peer']}`")
    if entry.get("detail"):
        rows.append(f"вердикт: {entry['detail']}")
    return "<br>".join(rows)


def main():
    ap = argparse.ArgumentParser(description="Build the two-column protocol table")
    ap.add_argument("--journal", default=DEFAULT_JOURNAL)
    ap.add_argument("--key", default=None)
    ap.add_argument("--out", default=DEFAULT_OUT)
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

    ok, _, reason = log.verify()
    lines = [
        "# Протокол роботи підсистеми реєстрації",
        "",
        "Лівий стовпчик — дія користувача, правий — її відображення в журналі аудиту.",
        "",
        f"Записів: **{len(records)}**. Цілісність журналу: **{'підтверджена' if ok else 'ПОРУШЕНА'}** "
        f"({reason}).",
        "",
        "| Дія користувача | Запис у журналі аудиту |",
        "|---|---|",
    ]
    for entry in records:
        lines.append(f"| {user_action(entry)} | {journal_entry(entry)} |")
    lines.append("")

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines))

    print(f"Таблицю записано: {args.out}")
    print(f"Рядків у таблиці: {len(records)}")
    print()
    # a short preview so the demonstration shows something on screen
    for entry in records[:6]:
        left = user_action(entry).replace("<br>", "  ").replace("**", "").replace("`", "")
        print(f"  {left}")
        print(f"      -> #{entry['seq']} {entry['event']}/{entry['result']}: {entry['detail']}")
    if len(records) > 6:
        print(f"  ... ще {len(records) - 6} рядків у файлі")
    return 0


if __name__ == "__main__":
    sys.exit(main())
