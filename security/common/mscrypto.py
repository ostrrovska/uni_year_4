"""Microsoft CryptoAPI (advapi32.dll) wrappers used by labs 6 and 7.

Only ctypes + stdlib: no third-party crypto, no pip install.
Every primitive below is a real CryptoAPI call, not a hashlib substitute.
"""

import ctypes
from ctypes import POINTER, byref, create_string_buffer, wintypes

advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)

PROV_RSA_AES = 24
CRYPT_VERIFYCONTEXT = 0xF0000000
CALG_SHA_256 = 0x0000800C
CALG_AES_256 = 0x00006610
HP_HASHVAL = 0x0002
KP_IV = 1
AES_BLOCK = 16

HCRYPTPROV = ctypes.c_void_p
HCRYPTHASH = ctypes.c_void_p
HCRYPTKEY = ctypes.c_void_p

advapi32.CryptAcquireContextW.argtypes = [POINTER(HCRYPTPROV), wintypes.LPCWSTR,
                                          wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
advapi32.CryptAcquireContextW.restype = wintypes.BOOL
advapi32.CryptReleaseContext.argtypes = [HCRYPTPROV, wintypes.DWORD]
advapi32.CryptReleaseContext.restype = wintypes.BOOL
advapi32.CryptCreateHash.argtypes = [HCRYPTPROV, wintypes.DWORD, HCRYPTKEY,
                                     wintypes.DWORD, POINTER(HCRYPTHASH)]
advapi32.CryptCreateHash.restype = wintypes.BOOL
advapi32.CryptHashData.argtypes = [HCRYPTHASH, ctypes.c_char_p, wintypes.DWORD, wintypes.DWORD]
advapi32.CryptHashData.restype = wintypes.BOOL
advapi32.CryptGetHashParam.argtypes = [HCRYPTHASH, wintypes.DWORD, ctypes.c_char_p,
                                       POINTER(wintypes.DWORD), wintypes.DWORD]
advapi32.CryptGetHashParam.restype = wintypes.BOOL
advapi32.CryptDestroyHash.argtypes = [HCRYPTHASH]
advapi32.CryptDestroyHash.restype = wintypes.BOOL
advapi32.CryptDeriveKey.argtypes = [HCRYPTPROV, wintypes.DWORD, HCRYPTHASH,
                                    wintypes.DWORD, POINTER(HCRYPTKEY)]
advapi32.CryptDeriveKey.restype = wintypes.BOOL
advapi32.CryptSetKeyParam.argtypes = [HCRYPTKEY, wintypes.DWORD, ctypes.c_char_p, wintypes.DWORD]
advapi32.CryptSetKeyParam.restype = wintypes.BOOL
advapi32.CryptDestroyKey.argtypes = [HCRYPTKEY]
advapi32.CryptDestroyKey.restype = wintypes.BOOL
advapi32.CryptEncrypt.argtypes = [HCRYPTKEY, HCRYPTHASH, wintypes.BOOL, wintypes.DWORD,
                                  ctypes.c_char_p, POINTER(wintypes.DWORD), wintypes.DWORD]
advapi32.CryptEncrypt.restype = wintypes.BOOL
advapi32.CryptDecrypt.argtypes = [HCRYPTKEY, HCRYPTHASH, wintypes.BOOL, wintypes.DWORD,
                                  ctypes.c_char_p, POINTER(wintypes.DWORD)]
advapi32.CryptDecrypt.restype = wintypes.BOOL
advapi32.CryptGenRandom.argtypes = [HCRYPTPROV, wintypes.DWORD, ctypes.c_char_p]
advapi32.CryptGenRandom.restype = wintypes.BOOL


class CryptoError(Exception):
    pass


def _check(ok, what):
    if not ok:
        raise CryptoError(f"{what} failed, GetLastError=0x{ctypes.get_last_error():08X}")


class Provider:
    """Handle of a CSP key container (CryptAcquireContext / CryptReleaseContext)."""

    def __init__(self):
        self.h = HCRYPTPROV()
        _check(advapi32.CryptAcquireContextW(byref(self.h), None, None,
                                             PROV_RSA_AES, CRYPT_VERIFYCONTEXT),
               "CryptAcquireContext")

    def close(self):
        if self.h:
            advapi32.CryptReleaseContext(self.h, 0)
            self.h = HCRYPTPROV()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def _hash_of(prov, data):
    h = HCRYPTHASH()
    _check(advapi32.CryptCreateHash(prov.h, CALG_SHA_256, None, 0, byref(h)), "CryptCreateHash")
    _check(advapi32.CryptHashData(h, data, len(data), 0), "CryptHashData")
    return h


def sha256(data: bytes) -> bytes:
    """SHA-256 digest computed by the CSP."""
    with Provider() as prov:
        h = _hash_of(prov, data)
        try:
            size = wintypes.DWORD(32)
            buf = create_string_buffer(32)
            _check(advapi32.CryptGetHashParam(h, HP_HASHVAL, buf, byref(size), 0),
                   "CryptGetHashParam")
            return buf.raw[:size.value]
        finally:
            advapi32.CryptDestroyHash(h)


def random_bytes(n: int) -> bytes:
    """Cryptographic RNG of the CSP."""
    with Provider() as prov:
        buf = create_string_buffer(n)
        _check(advapi32.CryptGenRandom(prov.h, n, buf), "CryptGenRandom")
        return buf.raw[:n]


def _derive_key(prov, secret: bytes):
    h = _hash_of(prov, secret)
    try:
        key = HCRYPTKEY()
        _check(advapi32.CryptDeriveKey(prov.h, CALG_AES_256, h, 0, byref(key)), "CryptDeriveKey")
        return key
    finally:
        advapi32.CryptDestroyHash(h)


def encrypt(secret: bytes, plaintext: bytes) -> bytes:
    """AES-256-CBC. Returns random IV || ciphertext."""
    iv = random_bytes(AES_BLOCK)
    with Provider() as prov:
        key = _derive_key(prov, secret)
        try:
            _check(advapi32.CryptSetKeyParam(key, KP_IV, iv, 0), "CryptSetKeyParam(KP_IV)")
            buf = create_string_buffer(plaintext, len(plaintext) + AES_BLOCK)
            size = wintypes.DWORD(len(plaintext))
            _check(advapi32.CryptEncrypt(key, None, True, 0, buf, byref(size),
                                         len(plaintext) + AES_BLOCK), "CryptEncrypt")
            return iv + buf.raw[:size.value]
        finally:
            advapi32.CryptDestroyKey(key)


def decrypt(secret: bytes, blob: bytes) -> bytes:
    """Inverse of encrypt(). Raises CryptoError on a wrong key or damaged data."""
    if len(blob) < AES_BLOCK * 2:
        raise CryptoError("ciphertext too short")
    iv, body = blob[:AES_BLOCK], blob[AES_BLOCK:]
    with Provider() as prov:
        key = _derive_key(prov, secret)
        try:
            _check(advapi32.CryptSetKeyParam(key, KP_IV, iv, 0), "CryptSetKeyParam(KP_IV)")
            buf = create_string_buffer(body, len(body))
            size = wintypes.DWORD(len(body))
            _check(advapi32.CryptDecrypt(key, None, True, 0, buf, byref(size)), "CryptDecrypt")
            return buf.raw[:size.value]
        finally:
            advapi32.CryptDestroyKey(key)


def hash_chain(data: bytes, rounds: int) -> bytes:
    out = data
    for _ in range(rounds):
        out = sha256(out)
    return out
