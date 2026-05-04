"""At-rest API key encryption — FR Entry 16.0 §4.1.

The deployment-level encryption key lives in the ``SAMRIDDHI_ENCRYPTION_KEY``
environment variable (urlsafe-base64-encoded 32 bytes; the format
:func:`cryptography.fernet.Fernet.generate_key` produces). On each LLM call
the router decrypts the per-provider API key in memory, makes the call, and
the plaintext key never enters logs.

In DEVELOPMENT, an empty ``SAMRIDDHI_ENCRYPTION_KEY`` causes a per-process
random key to be generated on first use — ciphertext written under that key
is unreadable across restarts, which is acceptable for local demos. Any
non-development environment MUST set the key explicitly; an empty value
raises :class:`MissingEncryptionKeyError`.

The choice of Fernet (over a custom AES-256-GCM implementation) follows
chunk plan §1.3 implementation notes: "Fernet is simpler and adequate for
cluster 1." Future clusters can rotate to authenticated-encryption-with-
associated-data (AEAD) if richer envelopes are needed; the encrypt/decrypt
helpers below are the only call sites.
"""

from __future__ import annotations

import logging
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from artha.config import Environment, settings

logger = logging.getLogger(__name__)


class MissingEncryptionKeyError(RuntimeError):
    """Raised when ``SAMRIDDHI_ENCRYPTION_KEY`` is required but unset.

    Translates to a 5xx in the LLM-config write path; the CIO does not see
    this surface in the demo (key is provisioned at deploy time).
    """


class EncryptionKeyInvalidError(RuntimeError):
    """The configured encryption key is not a valid Fernet key.

    Fernet keys must be urlsafe-base64 of 32 raw bytes. A user-typed string
    (or a truncated copy-paste) trips this on first use.
    """


class CiphertextCorruptedError(RuntimeError):
    """Fernet authentication failed — the ciphertext was tampered with or
    was encrypted under a different key than the one currently configured.
    """


# Cluster 1 keeps a single in-process Fernet instance. The key resolution is
# memoised so re-reading it on every LLM call is cheap; the ``lru_cache`` is
# cleared by ``reset_encryption_cache`` for tests + key-rotation flows.
_dev_key_cache: bytes | None = None


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    """Return the deployment's Fernet instance (memoised).

    Resolution order:

    1. ``settings.samriddhi_encryption_key`` is non-empty → use it directly.
    2. Empty + ``ENVIRONMENT=development`` → generate a per-process key with
       a one-time warning (ciphertext won't survive restart).
    3. Empty + non-development → :class:`MissingEncryptionKeyError`.
    """
    raw = settings.samriddhi_encryption_key
    if raw:
        try:
            return Fernet(raw.encode("ascii"))
        except (ValueError, TypeError) as exc:
            raise EncryptionKeyInvalidError(
                "SAMRIDDHI_ENCRYPTION_KEY is not a valid Fernet key. "
                "Generate one with `python -c 'from cryptography.fernet "
                "import Fernet; print(Fernet.generate_key().decode())'`."
            ) from exc

    if settings.environment != Environment.DEVELOPMENT:
        raise MissingEncryptionKeyError(
            "SAMRIDDHI_ENCRYPTION_KEY must be set in non-development "
            "environments (current ENVIRONMENT=%s)." % settings.environment.value
        )

    global _dev_key_cache
    if _dev_key_cache is None:
        _dev_key_cache = Fernet.generate_key()
        logger.warning(
            "SAMRIDDHI_ENCRYPTION_KEY unset; generated a per-process "
            "development encryption key. LLM API keys persisted under it "
            "are unreadable after backend restart. Set "
            "SAMRIDDHI_ENCRYPTION_KEY in .env to make ciphertext persist."
        )
    return Fernet(_dev_key_cache)


def encrypt_api_key(plaintext: str) -> bytes:
    """Wrap an API key in Fernet ciphertext.

    Returns the raw ciphertext bytes (Fernet's URL-safe base64 token, taken
    as bytes for storage in :class:`sqlalchemy.LargeBinary`).
    """
    if not plaintext:
        raise ValueError("plaintext API key is empty; nothing to encrypt")
    return _fernet().encrypt(plaintext.encode("utf-8"))


def decrypt_api_key(ciphertext: bytes) -> str:
    """Unwrap Fernet ciphertext to the plaintext API key.

    Raises :class:`CiphertextCorruptedError` on Fernet auth failure (key
    rotation, ciphertext tampering, or decoding under the wrong dev key).
    """
    if not ciphertext:
        raise ValueError("ciphertext is empty; nothing to decrypt")
    try:
        return _fernet().decrypt(ciphertext).decode("utf-8")
    except InvalidToken as exc:
        raise CiphertextCorruptedError(
            "Failed to decrypt API key: ciphertext is corrupt or was "
            "encrypted under a different SAMRIDDHI_ENCRYPTION_KEY."
        ) from exc


def mask_api_key(plaintext: str | None) -> str | None:
    """Return a UI-safe masked version of an API key.

    Shows the first 4 characters and a fixed ``****`` suffix so the CIO can
    see "is the key still the one I last entered?" without exposing the
    secret. Returns ``None`` if no key is configured.
    """
    if plaintext is None:
        return None
    if len(plaintext) <= 4:
        return "****"
    return f"{plaintext[:4]}****"


def reset_encryption_cache() -> None:
    """Test-only helper: clear the memoised Fernet + the dev key cache."""
    global _dev_key_cache
    _dev_key_cache = None
    _fernet.cache_clear()
