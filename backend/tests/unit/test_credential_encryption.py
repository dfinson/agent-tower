"""Unit tests for PAT encryption-at-rest (Story 3.1, NFR1)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from backend.services.credentials import encryption

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture(autouse=True)
def _isolated_codeplane_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point the key file at a throwaway directory instead of the real home dir."""
    monkeypatch.setattr(encryption, "get_codeplane_dir", lambda: tmp_path)


class TestEncryptDecryptRoundTrip:
    def test_round_trip_recovers_plaintext(self) -> None:
        token = encryption.encrypt_secret("super-secret-pat-value")
        assert encryption.decrypt_secret(token) == "super-secret-pat-value"

    def test_encrypted_token_never_contains_plaintext(self) -> None:
        secret = "ghp_representative_sentinel_token_123456"
        token = encryption.encrypt_secret(secret)
        assert secret not in token

    def test_key_file_created_on_first_use(self, tmp_path: Path) -> None:
        assert not (tmp_path / "credential.key").exists()
        encryption.encrypt_secret("x")
        assert (tmp_path / "credential.key").exists()

    def test_key_reused_across_calls(self, tmp_path: Path) -> None:
        token1 = encryption.encrypt_secret("value-one")
        key_bytes_after_first = (tmp_path / "credential.key").read_bytes()
        token2 = encryption.encrypt_secret("value-two")
        key_bytes_after_second = (tmp_path / "credential.key").read_bytes()

        assert key_bytes_after_first == key_bytes_after_second
        assert encryption.decrypt_secret(token1) == "value-one"
        assert encryption.decrypt_secret(token2) == "value-two"


class TestDecryptionFailure:
    def test_invalid_token_raises_decryption_error(self) -> None:
        encryption.encrypt_secret("prime-the-key")  # ensure key exists
        with pytest.raises(encryption.CredentialDecryptionError):
            encryption.decrypt_secret("not-a-valid-fernet-token")

    def test_tampered_token_raises_decryption_error(self) -> None:
        token = encryption.encrypt_secret("original-value")
        tampered = token[:-4] + ("A" * 4)
        with pytest.raises(encryption.CredentialDecryptionError):
            encryption.decrypt_secret(tampered)
