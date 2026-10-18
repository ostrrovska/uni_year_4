"""Lab 7, variant 1 - client: authenticates with the token, then works with the objects.

Interactive by default; --cmd may be repeated to replay a scripted session.
"""

import argparse
import os
import shlex
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [_HERE, os.path.dirname(_HERE)]  # run directly: find `common` and siblings

from common import netproto, token
from common.protolog import ProtocolLog

USAGE = """commands:
  list                      objects on the server and your rights on them
  caps                      your capability list (row of the access matrix)
  matrix                    the whole access matrix
  rights <obj>              access list of an object (column of the matrix)
  create <obj> [text]       create an object, you become its owner
  read <obj>                read an object
  write <obj> <text>        append a line to an object
  delete <obj>              delete an object
  grant  <obj> <user> <r>   give right r (read|write|delete|grant|own) to a user
  revoke <obj> <user> <r>   take right r away from a user
  quit"""


def parse_command(line):
    parts = shlex.split(line)
    if not parts:
        return None
    op, rest = parts[0].lower(), parts[1:]
    if op in ("list", "caps", "matrix", "quit"):
        return {"op": op}
    if op == "rights" and len(rest) == 1:
        return {"op": op, "object": rest[0]}
    if op in ("read", "delete") and len(rest) == 1:
        return {"op": op, "object": rest[0]}
    if op == "create" and rest:
        return {"op": op, "object": rest[0], "text": " ".join(rest[1:])}
    if op == "write" and len(rest) >= 2:
        return {"op": op, "object": rest[0], "text": " ".join(rest[1:])}
    if op in ("grant", "revoke") and len(rest) == 3:
        return {"op": op, "object": rest[0], "subject": rest[1], "right": rest[2].lower()}
    raise ValueError(f"cannot parse command: {line}")


def main():
    ap = argparse.ArgumentParser(description="Lab 7 access control client")
    ap.add_argument("--pin", required=True)
    ap.add_argument("--server", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=5707)
    ap.add_argument("--token-dir", default=None)
    ap.add_argument("--slot", default="")
    ap.add_argument("--log", default=None)
    ap.add_argument("--cmd", action="append", default=[], help="command to run (repeatable)")
    args = ap.parse_args()

    log = ProtocolLog(args.log, tag="CLIENT")

    try:
        token_dir = token.resolve_token_dir(args.token_dir, slot=args.slot)
        data = token.read_token(token_dir, args.pin)
    except token.TokenError as exc:
        log("TOKEN FAIL", str(exc))
        return 2

    with netproto.connect(args.server, args.port, timeout=30) as sock:
        netproto.send(sock, {"op": "auth", "user_id": data["user_id"],
                             "pwd_hash": data["pwd_hash"]})
        response = netproto.recv(sock)
        if response.get("status") != "ok":
            log("AUTH DENIED", response.get("reason", ""))
            return 1
        log("AUTH OK", f"subject '{data['user_id']}' authenticated, session open")

        lines = args.cmd if args.cmd else None
        if lines is None:
            print(USAGE)

        while True:
            if lines is not None:
                if not lines:
                    break
                line = lines.pop(0)
            else:
                try:
                    line = input(f"{data['user_id']}> ")
                except EOFError:
                    break
            try:
                request = parse_command(line)
            except ValueError as exc:
                log("BAD COMMAND", str(exc))
                continue
            if request is None:
                continue
            if request["op"] == "quit":
                break
            log("COMMAND", line)
            netproto.send(sock, request)
            response = netproto.recv(sock)
            verdict = "ALLOWED" if response.get("status") == "ok" else "DENIED"
            log(verdict, response.get("message", ""))
            if response.get("text"):
                for out in response["text"].splitlines():
                    log("  |", out)

        netproto.send(sock, {"op": "quit"})
    return 0


if __name__ == "__main__":
    sys.exit(main())
