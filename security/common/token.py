"""Security token (USB flash drive): locating it and reading/writing the protected file.

The file on the token is AES-256 encrypted with a key derived from the user's PIN
and carries a SHA-256 integrity tag, so neither reading nor silent tampering is possible
for someone who only holds the flash drive.
"""

import ctypes
import json
import os
import string

from . import mscrypto

TOKEN_DIR_NAME = "SECTOKEN"
TOKEN_FILE_NAME = "token.dat"
MAGIC = b"SECTOK01"
DRIVE_REMOVABLE = 2


class TokenError(Exception):
    pass


def find_removable_drives():
    """Drive letters whose GetDriveTypeW says DRIVE_REMOVABLE."""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    mask = kernel32.GetLogicalDrives()
    found = []
    for i, letter in enumerate(string.ascii_uppercase):
        if mask & (1 << i):
            root = f"{letter}:\\"
            if kernel32.GetDriveTypeW(ctypes.c_wchar_p(root)) == DRIVE_REMOVABLE:
                found.append(root)
    return found


def resolve_token_dir(explicit=None, create=False, slot=""):
    """Explicit path wins; otherwise auto-detect the flash drive.

    A slot is a subfolder of SECTOKEN, so that one physical flash drive can carry
    the tokens of several users during the lab demo.
    """
    if explicit:
        path = os.path.join(explicit, TOKEN_DIR_NAME)
    else:
        drives = find_removable_drives()
        if not drives:
            raise TokenError("security token not found: no removable drive is present "
                             "(insert the flash drive or pass --token-dir)")
        path = os.path.join(drives[0], TOKEN_DIR_NAME)
    if slot:
        path = os.path.join(path, slot)
    if create:
        os.makedirs(path, exist_ok=True)
    elif not os.path.isdir(path):
        raise TokenError(f"token directory {path} does not exist (run enroll.py first)")
    return path


def token_file(token_dir):
    return os.path.join(token_dir, TOKEN_FILE_NAME)


def _key(pin):
    return b"SECTOKEN-PIN|" + pin.encode("utf-8")


def write_token(token_dir, pin, payload):
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    plain = MAGIC + mscrypto.sha256(body) + body
    blob = mscrypto.encrypt(_key(pin), plain)
    path = token_file(token_dir)
    with open(path, "wb") as fh:
        fh.write(blob)
    return path


def read_token(token_dir, pin):
    path = token_file(token_dir)
    if not os.path.isfile(path):
        raise TokenError(f"token file {path} not found")
    with open(path, "rb") as fh:
        blob = fh.read()
    try:
        plain = mscrypto.decrypt(_key(pin), blob)
    except mscrypto.CryptoError:
        raise TokenError("cannot decrypt the token file: wrong PIN or the file is damaged")
    if not plain.startswith(MAGIC):
        raise TokenError("wrong PIN or the token file is not ours")
    tag, body = plain[8:40], plain[40:]
    if mscrypto.sha256(body) != tag:
        raise TokenError("integrity tag mismatch: the token file was tampered with")
    return json.loads(body.decode("utf-8"))
