"""TCP framing: 4-byte big-endian length + AES-256 encrypted JSON.

Bulk encryption of the traffic is the optional hardening asked for in lab 6;
the pre-shared channel key stands in for a key agreed at deployment time.
"""

import json
import socket
import struct

from . import mscrypto

CHANNEL_KEY = b"BPD-LAB6-CHANNEL-KEY-2026"
MAX_FRAME = 1 << 20


class ProtocolError(Exception):
    pass


def _recv_exactly(sock, n):
    chunks = []
    left = n
    while left:
        chunk = sock.recv(left)
        if not chunk:
            raise ProtocolError("connection closed by peer")
        chunks.append(chunk)
        left -= len(chunk)
    return b"".join(chunks)


def send(sock, obj):
    body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    blob = mscrypto.encrypt(CHANNEL_KEY, body)
    sock.sendall(struct.pack(">I", len(blob)) + blob)


def recv(sock):
    size = struct.unpack(">I", _recv_exactly(sock, 4))[0]
    if size > MAX_FRAME:
        raise ProtocolError(f"frame too large: {size}")
    blob = _recv_exactly(sock, size)
    try:
        body = mscrypto.decrypt(CHANNEL_KEY, blob)
    except mscrypto.CryptoError as exc:
        raise ProtocolError(f"cannot decrypt frame: {exc}")
    return json.loads(body.decode("utf-8"))


def connect(host, port, timeout=10):
    sock = socket.create_connection((host, port), timeout=timeout)
    sock.settimeout(timeout)
    return sock
