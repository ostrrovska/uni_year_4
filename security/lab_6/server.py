"""Lab 6, variant 2 - authentication server (the side that verifies)."""

import argparse
import os
import socket
import sys
import threading

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [_HERE, os.path.dirname(_HERE)]  # run directly: find `common` and siblings

from common import authcore, netproto
from common.protolog import ProtocolLog
from common.userdb import UserDB

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB = os.path.join(HERE, "server_db.json")


def serve_client(conn, addr, db, log):
    peer = f"{addr[0]}:{addr[1]}"
    try:
        request = netproto.recv(conn)
        log("REQUEST", f"peer={peer} user='{request.get('user_id')}' "
                       f"hash={str(request.get('pwd_hash'))[:16]}...")
        _ok, response = authcore.handle_auth(db, request, log, peer)
        netproto.send(conn, response)
    except Exception as exc:
        log("ERROR", f"peer={peer} :: {exc}")
    finally:
        conn.close()


def main():
    ap = argparse.ArgumentParser(description="Lab 6 authentication server")
    ap.add_argument("--host", default="127.0.0.1", help="0.0.0.0 for the two-machine run")
    ap.add_argument("--port", type=int, default=5607)
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--log", default=None)
    ap.add_argument("--max-clients", type=int, default=0, help="exit after N clients (0 = forever)")
    args = ap.parse_args()

    log = ProtocolLog(args.log, tag="SERVER")
    db = UserDB(args.db)
    log("START", f"listening on {args.host}:{args.port}, users in database: {db.ids()}")

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

    served = 0
    try:
        while True:
            conn, addr = srv.accept()
            db.load()  # pick up users enrolled while the server was already running
            t = threading.Thread(target=serve_client, args=(conn, addr, db, log))
            t.start()
            t.join()
            served += 1
            if args.max_clients and served >= args.max_clients:
                break
    except KeyboardInterrupt:
        pass
    finally:
        srv.close()
        log("STOP", f"served {served} client(s)")


if __name__ == "__main__":
    main()
