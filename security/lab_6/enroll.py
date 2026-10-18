"""Lab 6, variant 2 - user enrollment.

Writes the identifier and the SHA-256 hash image of the password into the server
database, and the same pair into the encrypted file on the security token.
The password itself is never stored anywhere.
"""

import argparse
import datetime
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [_HERE, os.path.dirname(_HERE)]  # run directly: find `common` and siblings

from common import mscrypto, token
from common.protolog import ProtocolLog
from common.userdb import UserDB

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB = os.path.join(HERE, "server_db.json")


def hash_image(salt: bytes, password: str) -> str:
    return mscrypto.sha256(salt + password.encode("utf-8")).hex()


def main():
    ap = argparse.ArgumentParser(description="Enroll a user and write the security token")
    ap.add_argument("--user", required=True)
    ap.add_argument("--password", required=True)
    ap.add_argument("--pin", required=True, help="PIN that protects the file on the token")
    ap.add_argument("--token-dir", default=None, help="override token location (default: flash drive)")
    ap.add_argument("--slot", default="", help="subfolder on the token, one per user")
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--no-db", action="store_true",
                    help="write only the token, skip the server database (forged-token demo)")
    ap.add_argument("--log", default=None)
    args = ap.parse_args()

    log = ProtocolLog(args.log, tag="ENROLL")
    salt = mscrypto.random_bytes(16)
    image = hash_image(salt, args.password)

    if not args.no_db:
        db = UserDB(args.db)
        db.add(args.user, salt.hex(), image)
        log("DB WRITE", f"user='{args.user}' salt={salt.hex()[:16]}... hash={image[:16]}...")
    else:
        log("DB SKIPPED", f"user='{args.user}' is not registered on the server")

    token_dir = token.resolve_token_dir(args.token_dir, create=True, slot=args.slot)
    path = token.write_token(token_dir, args.pin, {
        "user_id": args.user,
        "salt": salt.hex(),
        "pwd_hash": image,
        "created_at": datetime.datetime.now().isoformat(timespec="seconds"),
    })
    log("TOKEN WRITE", f"{path} ({os.path.getsize(path)} bytes, AES-256 + SHA-256 tag)")


if __name__ == "__main__":
    main()
