"""Lab 7, variant 1 - server: authentication from lab 6 plus the access control subsystem.

A client first authenticates with its security token (common/authcore.py, i.e. the
very program written for lab 6) and only then may issue operations on the data
objects stored on this server side.
"""

import argparse
import os
import socket
import sys
import threading

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [_HERE, os.path.dirname(_HERE)]  # run directly: find `common` and siblings

from acl import ALL_RIGHTS, DELETE, GRANT, OWN, READ, WRITE, AccessError, AccessMatrix
from common import authcore, netproto
from common.protolog import ProtocolLog
from common.userdb import UserDB

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB = os.path.join(HERE, "..", "lab_6", "server_db.json")
DEFAULT_ACL = os.path.join(HERE, "acl.json")
DEFAULT_STORAGE = os.path.join(HERE, "storage")


def reply(sock, ok, message, **extra):
    netproto.send(sock, dict(status="ok" if ok else "deny", message=message, **extra))


def handle_command(matrix, user, request, log, lock):
    """Returns (ok, message, extra). Every decision goes into the protocol."""
    op = request.get("op", "")
    obj = request.get("object")
    with lock:
        matrix.load()

        if op == "list":
            rows = []
            for name in sorted(matrix.objects):
                rights = sorted(matrix.rights_of(user, name))
                rows.append(f"{name:<16} owner={matrix.owner_of(name):<12} "
                            f"your rights={','.join(rights) if rights else '-'}")
            return True, f"{len(matrix.objects)} object(s)", {"text": "\n".join(rows)}

        if op == "matrix":
            subjects = sorted({matrix.owner_of(o) for o in matrix.objects} |
                              {s for o in matrix.objects for s in matrix.objects[o]["acl"]})
            return True, "access matrix", {"text": matrix.render_matrix(subjects)}

        if op == "caps":
            caps = matrix.capability_list(user)
            text = "\n".join(f"{o:<16} {','.join(r)}" for o, r in caps.items()) or "(empty)"
            return True, f"capability list of '{user}'", {"text": text}

        if op == "rights":
            if not matrix.exists(obj):
                return False, f"object '{obj}' does not exist", {}
            column = matrix.access_list(obj)
            text = "\n".join(f"{s:<16} {','.join(r)}" for s, r in sorted(column.items()))
            return True, f"access list of '{obj}'", {"text": text}

        if op == "create":
            if matrix.exists(obj):
                return False, f"object '{obj}' already exists", {}
            matrix.create(user, obj, request.get("text", ""))
            return True, f"object '{obj}' created, owner '{user}'", {}

        if op in ("read", "write", "delete"):
            right = {"read": READ, "write": WRITE, "delete": DELETE}[op]
            allowed, reason = matrix.check(user, obj, right)
            if not allowed:
                return False, reason, {}
            if op == "read":
                return True, reason, {"text": matrix.read(obj)}
            if op == "write":
                matrix.write(obj, request.get("text", ""))
                return True, reason, {}
            matrix.delete(obj)
            return True, reason + " -> object removed", {}

        if op in ("grant", "revoke"):
            target, right = request.get("subject"), request.get("right")
            if not matrix.exists(obj):
                return False, f"object '{obj}' does not exist", {}
            if right not in ALL_RIGHTS:
                return False, f"unknown right '{right}'", {}
            allowed, reason = matrix.check(user, obj, GRANT)
            if not allowed:
                return False, reason + " (only the owner or a delegate may change rights)", {}
            if right == OWN and matrix.owner_of(obj) != user:
                return False, "only the owner may hand over ownership", {}
            if target == matrix.owner_of(obj) and op == "revoke":
                return False, "the owner's rights cannot be revoked", {}
            matrix.set_right(obj, target, right, op == "grant")
            verb = "granted to" if op == "grant" else "revoked from"
            return True, f"right '{right}' on '{obj}' {verb} '{target}'", {}

        return False, f"unknown operation '{op}'", {}


def serve_client(conn, addr, db, matrix, log, lock):
    peer = f"{addr[0]}:{addr[1]}"
    user = None
    try:
        request = netproto.recv(conn)
        if request.get("op") != "auth":
            reply(conn, False, "the first message must be 'auth'")
            return
        db.load()
        ok, response = authcore.handle_auth(db, request, log, peer)
        netproto.send(conn, response)
        if not ok:
            return
        user = request["user_id"]
        log("SESSION OPEN", f"subject '{user}' from {peer}")

        while True:
            try:
                request = netproto.recv(conn)
            except netproto.ProtocolError:
                break
            op = request.get("op")
            if op == "quit":
                break
            try:
                ok, message, extra = handle_command(matrix, user, request, log, lock)
            except AccessError as exc:
                ok, message, extra = False, str(exc), {}
            detail = f"subject='{user}' op={op}"
            if request.get("object"):
                detail += f" object='{request['object']}'"
            if request.get("subject"):
                detail += f" to='{request['subject']}' right='{request.get('right')}'"
            log("ALLOW" if ok else "DENY", f"{detail} :: {message}")
            reply(conn, ok, message, **extra)
    except Exception as exc:
        log("ERROR", f"peer={peer} :: {exc}")
    finally:
        if user:
            log("SESSION CLOSE", f"subject '{user}'")
        conn.close()


def main():
    ap = argparse.ArgumentParser(description="Lab 7 access control server")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=5707)
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--acl", default=DEFAULT_ACL)
    ap.add_argument("--storage", default=DEFAULT_STORAGE)
    ap.add_argument("--log", default=None)
    args = ap.parse_args()

    log = ProtocolLog(args.log, tag="SERVER")
    db = UserDB(args.db)
    matrix = AccessMatrix(args.acl, args.storage)
    lock = threading.Lock()
    log("START", f"{args.host}:{args.port}, subjects={db.ids()}, "
                 f"objects={len(matrix.objects)}")

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        srv.bind((args.host, args.port))
    except OSError as exc:
        # WinError 10013: the port sits inside a range Windows reserved for
        # Hyper-V/WSL. Those ranges are reshuffled on every reboot.
        log("BIND FAILED", f"port {args.port}: {exc}")
        log("HINT", "see 'netsh interface ipv4 show excludedportrange protocol=tcp' "
                    "and restart with --port <free port below 49152>")
        raise SystemExit(1)
    srv.listen(5)
    try:
        while True:
            conn, addr = srv.accept()
            t = threading.Thread(target=serve_client,
                                 args=(conn, addr, db, matrix, log, lock), daemon=True)
            t.start()
            t.join()
    except KeyboardInterrupt:
        pass
    finally:
        srv.close()
        log("STOP", "server stopped")


if __name__ == "__main__":
    main()
