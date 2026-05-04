"""Cluster 1 chunk 1.3 — encryption helper test suite.

Covers Fernet wrap/unwrap, key masking, dev-key fallback, missing-key
errors in non-development environments, and invalid-key rejection.
Per FR Entry 16.0 §4.1.
"""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from artha.api_v2.llm.encryption import (
    CiphertextCorruptedError,
    EncryptionKeyInvalidError,
    MissingEncryptionKeyError,
    decrypt_api_key,
    encrypt_api_key,
    mask_api_key,
    reset_encryption_cache,
)
from artha.config import Environment, settings


@pytest.fixture(autouse=True)
def reset_state(monkeypatch):
    """Reset Fernet + dev key cache between tests so they stay isolated."""
    reset_encryption_cache()
    yield
    reset_encryption_cache()


# ---------------------------------------------------------------------------
# 1. Round-trip with explicit key
# ---------------------------------------------------------------------------


class TestEncryptionRoundTrip:
    def test_round_trip_recovers_plaintext(self, monkeypatch):
        key = Fernet.generate_key().decode("ascii")
        monkeypatch.setattr(settings, "samriddhi_encryption_key", key)
        reset_encryption_cache()

        ciphertext = encrypt_api_key("sk-test-secret-key-12345")
        assert isinstance(ciphertext, bytes)
        assert b"sk-test" not in ciphertext  # plaintext doesn't leak

        recovered = decrypt_api_key(ciphertext)
        assert recovered == "sk-test-secret-key-12345"

    def test_two_encrypts_produce_different_ciphertexts(self, monkeypatch):
        """Fernet uses random IVs, so the same plaintext encrypts differently
        each time. Important for not leaking plaintext via ciphertext equality."""
        key = Fernet.generate_key().decode("ascii")
        monkeypatch.setattr(settings, "samriddhi_encryption_key", key)
        reset_encryption_cache()

        a = encrypt_api_key("same-plaintext")
        b = encrypt_api_key("same-plaintext")
        assert a != b
        assert decrypt_api_key(a) == decrypt_api_key(b) == "same-plaintext"

    def test_decrypt_with_wrong_key_raises(self, monkeypatch):
        key1 = Fernet.generate_key().decode("ascii")
        monkeypatch.setattr(settings, "samriddhi_encryption_key", key1)
        reset_encryption_cache()
        ciphertext = encrypt_api_key("sk-secret")

        # Rotate the key — old ciphertext should no longer decrypt.
        key2 = Fernet.generate_key().decode("ascii")
        monkeypatch.setattr(settings, "samriddhi_encryption_key", key2)
        reset_encryption_cache()
        with pytest.raises(CiphertextCorruptedError):
            decrypt_api_key(ciphertext)

    def test_empty_plaintext_rejected(self, monkeypatch):
        key = Fernet.generate_key().decode("ascii")
        monkeypatch.setattr(settings, "samriddhi_encryption_key", key)
        reset_encryption_cache()
        with pytest.raises(ValueError):
            encrypt_api_key("")

    def test_empty_ciphertext_rejected(self, monkeypatch):
        key = Fernet.generate_key().decode("ascii")
        monkeypatch.setattr(settings, "samriddhi_encryption_key", key)
        reset_encryption_cache()
        with pytest.raises(ValueError):
            decrypt_api_key(b"")


# ---------------------------------------------------------------------------
# 2. Key resolution + fallback
# ---------------------------------------------------------------------------


class TestKeyResolution:
    def test_dev_environment_with_no_key_generates_per_process_key(
        self, monkeypatch
    ):
        monkeypatch.setattr(settings, "samriddhi_encryption_key", "")
        monkeypatch.setattr(settings, "environment", Environment.DEVELOPMENT)
        reset_encryption_cache()

        # Round trip works under the auto-generated key.
        ciphertext = encrypt_api_key("hello")
        assert decrypt_api_key(ciphertext) == "hello"

    def test_non_dev_environment_with_no_key_raises(self, monkeypatch):
        monkeypatch.setattr(settings, "samriddhi_encryption_key", "")
        monkeypatch.setattr(settings, "environment", Environment.PRODUCTION)
        reset_encryption_cache()

        with pytest.raises(MissingEncryptionKeyError):
            encrypt_api_key("hello")

    def test_invalid_fernet_key_raises(self, monkeypatch):
        # Looks like a string, isn't valid Fernet key material.
        monkeypatch.setattr(settings, "samriddhi_encryption_key", "not-a-fernet-key")
        reset_encryption_cache()

        with pytest.raises(EncryptionKeyInvalidError):
            encrypt_api_key("hello")

    def test_dev_key_persists_across_calls_within_process(self, monkeypatch):
        monkeypatch.setattr(settings, "samriddhi_encryption_key", "")
        monkeypatch.setattr(settings, "environment", Environment.DEVELOPMENT)
        reset_encryption_cache()

        c1 = encrypt_api_key("plaintext-1")
        # Same dev key — second call's ciphertext decrypts cleanly.
        assert decrypt_api_key(c1) == "plaintext-1"
        c2 = encrypt_api_key("plaintext-2")
        assert decrypt_api_key(c2) == "plaintext-2"


# ---------------------------------------------------------------------------
# 3. Masking
# ---------------------------------------------------------------------------


class TestMasking:
    def test_mask_returns_first_four_plus_stars(self):
        assert mask_api_key("sk-abc123def456") == "sk-a****"

    def test_mask_short_key_returns_just_stars(self):
        assert mask_api_key("abc") == "****"

    def test_mask_none_returns_none(self):
        assert mask_api_key(None) is None

    def test_mask_does_not_reveal_full_key(self):
        secret = "sk-this-is-a-very-secret-anthropic-key"
        masked = mask_api_key(secret)
        assert "secret" not in masked
        assert "anthropic" not in masked
        assert masked.endswith("****")
