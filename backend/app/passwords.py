"""Local-account password hashing.

Stdlib scrypt — no extra dependency. Stored format packs the parameters
with the hash so they can evolve without a schema change:

    scrypt$<n>$<r>$<p>$<salt_b64>$<hash_b64>

Verification is constant-time and recomputes with the *stored* parameters,
so old hashes keep validating after the defaults below are raised.
"""

import base64
import hashlib
import hmac
import secrets

# Defaults for new hashes. n must be a power of two; these are comfortably
# above interactive-login cost without being painful on a login request.
_N = 2**15
_R = 8
_P = 1
_SALT_BYTES = 16
_KEY_LEN = 32


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.b64decode(text.encode("ascii"))


def _maxmem(n: int, r: int) -> int:
    # OpenSSL caps scrypt memory at 32 MiB by default; n=2**15 needs ~33.5 MiB.
    # Size the limit to the parameters with headroom so it scales if they rise.
    return 128 * n * r + (1 << 20)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(_SALT_BYTES)
    derived = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_N,
        r=_R,
        p=_P,
        dklen=_KEY_LEN,
        maxmem=_maxmem(_N, _R),
    )
    return f"scrypt${_N}${_R}${_P}${_b64(salt)}${_b64(derived)}"


def verify_password(password: str, stored: str | None) -> bool:
    if not stored:
        return False
    try:
        scheme, n_s, r_s, p_s, salt_s, hash_s = stored.split("$")
        if scheme != "scrypt":
            return False
        n, r, p = int(n_s), int(r_s), int(p_s)
        salt, expected = _unb64(salt_s), _unb64(hash_s)
    except (ValueError, TypeError):
        return False
    derived = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=n,
        r=r,
        p=p,
        dklen=len(expected),
        maxmem=_maxmem(n, r),
    )
    return hmac.compare_digest(derived, expected)
