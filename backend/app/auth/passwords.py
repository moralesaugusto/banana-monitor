"""Password hashing with scrypt from the standard library (memory-hard, no extra dependency).
Stored as `scrypt$n$r$p$salt$hash`, so the cost can be raised later without breaking old hashes."""

import base64
import hashlib
import hmac
import secrets

N, R, P = 2**15, 8, 1
KEY_LENGTH = 32


def _derive(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    maxmem = 128 * n * r * 2
    return hashlib.scrypt(password.encode(), salt=salt, n=n, r=r, p=p, maxmem=maxmem, dklen=KEY_LENGTH)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = _derive(password, salt, N, R, P)
    b64 = base64.b64encode
    return "$".join(["scrypt", str(N), str(R), str(P), b64(salt).decode(), b64(digest).decode()])


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        expected = base64.b64decode(digest)
        actual = _derive(password, base64.b64decode(salt), int(n), int(r), int(p))
    except ValueError:
        return False
    return scheme == "scrypt" and hmac.compare_digest(actual, expected)
