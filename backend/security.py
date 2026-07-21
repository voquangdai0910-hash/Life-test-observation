"""Password hashing helpers.

Uses bcrypt (salted, adaptive) for new passwords. Legacy accounts created with
the old unsalted SHA-256 scheme are still accepted at login and transparently
re-hashed to bcrypt on the next successful sign-in.
"""
import hashlib
import hmac
import bcrypt

# bcrypt only considers the first 72 bytes of the password. We truncate the
# encoded bytes explicitly so long passwords never raise ValueError.
_MAX_BCRYPT_BYTES = 72


def _legacy_sha256(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def _is_legacy_hash(stored_hash: str) -> bool:
    """A bare unsalted SHA-256 hex digest is 64 lowercase hex chars."""
    return len(stored_hash) == 64 and all(c in "0123456789abcdef" for c in stored_hash.lower())


def hash_password(password: str) -> str:
    """Hash a plaintext password with bcrypt."""
    pw = password.encode("utf-8")[:_MAX_BCRYPT_BYTES]
    return bcrypt.hashpw(pw, bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, stored_hash: str):
    """Verify a password against a stored hash.

    Returns a (is_valid, needs_rehash) tuple. ``needs_rehash`` is True when the
    password matched a legacy SHA-256 hash and should be upgraded to bcrypt.
    """
    if not stored_hash:
        return (False, False)

    if _is_legacy_hash(stored_hash):
        if hmac.compare_digest(stored_hash, _legacy_sha256(password)):
            return (True, True)
        return (False, False)

    try:
        pw = password.encode("utf-8")[:_MAX_BCRYPT_BYTES]
        return (bcrypt.checkpw(pw, stored_hash.encode("utf-8")), False)
    except (ValueError, TypeError):
        return (False, False)
