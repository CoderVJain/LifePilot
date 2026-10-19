"""OAuth tokens at rest: encrypted with Fernet, a key read from the environment.

Nothing here returns a token to anywhere but the Gmail client. Tokens never reach the model, the
browser or a log, so this module has no __str__, no repr helper and no "show me the token" path.
"""

import json
import os

from cryptography.fernet import Fernet, InvalidToken

KEY_ENV = "TOKEN_ENCRYPTION_KEY"


class NoEncryptionKey(RuntimeError):
    """TOKEN_ENCRYPTION_KEY is unset, so a token cannot be stored or read."""


class CannotDecrypt(RuntimeError):
    """The stored token does not match this key. Re-link rather than guess."""


def _cipher() -> Fernet:
    key = (os.environ.get(KEY_ENV) or "").strip()
    if not key:
        raise NoEncryptionKey(
            f"{KEY_ENV} is not set. Generate one with "
            '`python -c "from cryptography.fernet import Fernet; '
            'print(Fernet.generate_key().decode())"` and put it in .env.'
        )
    return Fernet(key.encode())


def seal(token: dict) -> bytes:
    """Encrypt a token for the database."""
    return _cipher().encrypt(json.dumps(token).encode())


def unseal(blob: bytes) -> dict:
    """Decrypt a stored token. A key mismatch is named, not swallowed."""
    try:
        return json.loads(_cipher().decrypt(blob))
    except InvalidToken as wrong:
        raise CannotDecrypt(
            f"the stored Gmail token cannot be read with the current {KEY_ENV}; link Gmail again"
        ) from wrong
