"""Registration subsystem (lab 8): a tamper-evident, encrypted audit journal.

This is not the console protocol of common/protolog.py. A journal of registration
has stricter duties: every record is structured, the file is unreadable without the
auditor key, and any alteration or deletion of a record is detectable.

Protection rests on three mechanisms, all built on the same Microsoft CryptoAPI
that protects the security token:

  integrity        every record carries SHA-256 over the previous record's hash
                   and its own body, so the records form a chain; editing or
                   removing one breaks the chain at a known position
  confidentiality  every record is encrypted with AES-256 under the auditor key
                   and stored as one base64 line, so the journal stays appendable
  access           reading needs the key; over the network it needs the subject
                   the server was told is the auditor
"""

import base64
import datetime
import json
import os
import threading

from . import mscrypto

# Events the lab requires, plus the ones that give an auditor context.
AUTH = "AUTH"          # authentication attempt
ACCESS = "ACCESS"      # read / write / delete of a protected object
RIGHTS = "RIGHTS"      # granting or revoking a right
OBJECT = "OBJECT"      # creating an object
SESSION = "SESSION"    # a session opened or closed
SYSTEM = "SYSTEM"      # the service itself started or stopped
AUDIT = "AUDIT"        # the journal itself was addressed

SUCCESS = "SUCCESS"
FAILURE = "FAILURE"

GENESIS = "0" * 64
DEFAULT_KEY = b"BPD-LAB8-AUDIT-KEY-2026"
BODY_FIELDS = ("seq", "ts", "event", "subject", "object", "action", "result",
               "detail", "peer")


class AuditError(Exception):
    pass


def _canonical(body):
    """Stable text of a record body: the hash must not depend on key order."""
    return json.dumps(body, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def chain_hash(prev_hash, body):
    return mscrypto.sha256(prev_hash.encode("ascii") + _canonical(body)).hex()


class AuditLog:
    """Append-only journal. One encrypted record per line."""

    def __init__(self, path, key=DEFAULT_KEY):
        self.path = path
        self.key = key if isinstance(key, bytes) else str(key).encode("utf-8")
        self._lock = threading.Lock()
        folder = os.path.dirname(os.path.abspath(path))
        if folder:
            os.makedirs(folder, exist_ok=True)

    # --- writing ---

    def _tail(self):
        """Sequence number and hash to continue from."""
        records = self.read_all(stop_on_error=True)
        if not records:
            return 0, GENESIS
        last = records[-1]
        return last["seq"], last["hash"]

    def record(self, event, result, subject="-", action="", detail="",
               obj=None, peer=""):
        """Append one event. Returns the stored record."""
        with self._lock:
            seq, prev = self._tail()
            body = {
                "seq": seq + 1,
                "ts": datetime.datetime.now().isoformat(timespec="milliseconds"),
                "event": event,
                "subject": subject or "-",
                "object": obj or "",
                "action": action,
                "result": result,
                "detail": detail,
                "peer": peer,
            }
            entry = dict(body, prev=prev, hash=chain_hash(prev, body))
            line = base64.b64encode(
                mscrypto.encrypt(self.key, json.dumps(entry, ensure_ascii=False).encode("utf-8"))
            ).decode("ascii")
            with open(self.path, "a", encoding="ascii") as fh:
                fh.write(line + "\n")
            return entry

    # --- reading ---

    def read_all(self, stop_on_error=False):
        """Decrypt the whole journal. Raises AuditError on a wrong key."""
        if not os.path.isfile(self.path):
            return []
        out = []
        with open(self.path, "r", encoding="ascii") as fh:
            for number, line in enumerate(fh, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    plain = mscrypto.decrypt(self.key, base64.b64decode(line))
                    out.append(json.loads(plain.decode("utf-8")))
                except Exception:
                    if stop_on_error:
                        break
                    raise AuditError(
                        f"line {number} cannot be read: wrong auditor key, "
                        f"or the record was altered")
        return out

    def verify(self):
        """Walk the chain. Returns (ok, position, reason)."""
        if not os.path.isfile(self.path):
            return True, 0, "journal is empty"

        prev = GENESIS
        expected_seq = 1
        with open(self.path, "r", encoding="ascii") as fh:
            lines = [ln.strip() for ln in fh if ln.strip()]

        for number, line in enumerate(lines, start=1):
            try:
                plain = mscrypto.decrypt(self.key, base64.b64decode(line))
                entry = json.loads(plain.decode("utf-8"))
            except Exception:
                return False, number, (
                    f"record {number} does not decrypt: it was altered, "
                    f"or the key is wrong")

            body = {k: entry.get(k) for k in BODY_FIELDS}

            if entry.get("prev") != prev:
                return False, entry.get("seq", number), (
                    f"record {entry.get('seq')} does not continue the chain: "
                    f"a record before it was removed or replaced")
            if chain_hash(prev, body) != entry.get("hash"):
                return False, entry.get("seq", number), (
                    f"record {entry.get('seq')} was altered: its content no "
                    f"longer matches its hash")
            if entry.get("seq") != expected_seq:
                return False, entry.get("seq", number), (
                    f"sequence jumps from {expected_seq} to {entry.get('seq')}: "
                    f"a record is missing")

            prev = entry["hash"]
            expected_seq += 1

        return True, len(lines), f"chain intact, {len(lines)} record(s)"


def format_record(entry, width=None):
    """One human-readable line, the way an auditor sees it."""
    mark = "+" if entry["result"] == SUCCESS else "-"
    parts = [
        f"#{entry['seq']:<4}",
        entry["ts"].replace("T", " "),
        f"{mark} {entry['event']:<7}",
        f"{entry['result']:<7}",
        f"subject={entry['subject']}",
    ]
    if entry.get("object"):
        parts.append(f"object={entry['object']}")
    if entry.get("peer"):
        parts.append(f"peer={entry['peer']}")
    if entry.get("detail"):
        parts.append(f":: {entry['detail']}")
    line = "  ".join(parts)
    return line[:width] if width else line
