"""Lab 6, variant 2 - client (the side that is verified).

Reads the protected file from the security token, decrypts it with the PIN and
sends identifier + password hash image to the server over an encrypted TCP channel.
"""

import argparse
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [_HERE, os.path.dirname(_HERE)]  # run directly: find `common` and siblings

from common import netproto, token
from common.protolog import ProtocolLog


def main():
    ap = argparse.ArgumentParser(description="Lab 6 authentication client")
    ap.add_argument("--pin", required=True)
    ap.add_argument("--server", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=5607)
    ap.add_argument("--token-dir", default=None)
    ap.add_argument("--slot", default="")
    ap.add_argument("--log", default=None)
    args = ap.parse_args()

    log = ProtocolLog(args.log, tag="CLIENT")

    try:
        token_dir = token.resolve_token_dir(args.token_dir, slot=args.slot)
        data = token.read_token(token_dir, args.pin)
    except token.TokenError as exc:
        log("TOKEN FAIL", str(exc))
        log("RESULT", "AUTHENTICATION DENIED (token unavailable)")
        return 2

    log("TOKEN READ", f"{token.token_file(token_dir)} -> user='{data['user_id']}' "
                      f"hash={data['pwd_hash'][:16]}...")

    try:
        with netproto.connect(args.server, args.port) as sock:
            netproto.send(sock, {"user_id": data["user_id"], "pwd_hash": data["pwd_hash"]})
            log("SENT", f"encrypted AES-256 frame to {args.server}:{args.port}")
            response = netproto.recv(sock)
    except OSError as exc:
        log("NET FAIL", str(exc))
        return 3

    ok = response.get("status") == "ok"
    log("RESPONSE", f"status={response.get('status')} reason={response.get('reason')}")
    log("RESULT", "AUTHENTICATION GRANTED" if ok else "AUTHENTICATION DENIED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
