"""Authentication core of lab 6, reused unchanged by the lab 7 server.

Variant 2: the token carries the identifier and the hash image of the password;
the server compares that image with the one stored in its own database.

Lab 8: every attempt, successful or not, also goes into the audit journal. Both
servers reach authentication through this one function, so registration of
authentication cannot be bypassed or forgotten in one of them.
"""

import hmac

from . import audit as audit_mod
from .userdb import UserDB


def verify(db: UserDB, user_id, pwd_hash_hex):
    """Returns (ok, reason). The reason is what goes into the protocol log."""
    if not user_id or not pwd_hash_hex:
        return False, "malformed request"
    record = db.get(user_id)
    if record is None:
        return False, f"unknown identifier '{user_id}'"
    if hmac.compare_digest(record["pwd_hash"], pwd_hash_hex):
        return True, "hash image matches the database"
    return False, "hash image does not match the database"


def handle_auth(db: UserDB, request, log=None, peer="", audit=None):
    user_id = request.get("user_id")
    ok, reason = verify(db, user_id, request.get("pwd_hash"))
    if log:
        log("AUTH " + ("OK" if ok else "FAIL"), f"user='{user_id}' peer={peer} :: {reason}")
    if audit:
        audit.record(audit_mod.AUTH,
                     audit_mod.SUCCESS if ok else audit_mod.FAILURE,
                     subject=user_id or "-",
                     action=f"authenticate as '{user_id}'",
                     detail=reason, peer=peer)
    return ok, {"status": "ok" if ok else "fail", "reason": reason, "user_id": user_id}
