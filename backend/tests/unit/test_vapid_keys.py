"""Tests for vapid_keys — VAPID key generation and persistence."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

from backend.services.vapid_keys import get_or_create_vapid_keys

if TYPE_CHECKING:
    from pathlib import Path


class TestGetOrCreateVapidKeys:
    def test_reads_existing_valid_keys(self, tmp_path: Path) -> None:
        keys = {"public_key": "pub123", "private_key": "priv456"}
        vapid_file = tmp_path / "vapid.json"
        vapid_file.write_text(json.dumps(keys))

        result = get_or_create_vapid_keys(tmp_path)
        assert result == keys

    def test_generates_keys_when_file_missing(self, tmp_path: Path) -> None:
        mock_vapid = MagicMock()
        # Mock the EC public key object
        mock_pub_key = MagicMock()
        mock_pub_key.public_bytes.return_value = b"\x04" + b"\x01" * 64  # uncompressed point
        mock_vapid.public_key = mock_pub_key
        # Mock the private key
        mock_priv_numbers = MagicMock()
        mock_priv_numbers.private_value = int.from_bytes(b"\x02" * 32, "big")
        mock_vapid.private_key.private_numbers.return_value = mock_priv_numbers

        with patch("py_vapid.Vapid", return_value=mock_vapid):
            result = get_or_create_vapid_keys(tmp_path)

        assert "public_key" in result
        assert "private_key" in result
        # File should be written
        vapid_file = tmp_path / "vapid.json"
        assert vapid_file.exists()
        saved = json.loads(vapid_file.read_text())
        assert saved["public_key"] == result["public_key"]

    def test_regenerates_on_corrupt_json(self, tmp_path: Path) -> None:
        vapid_file = tmp_path / "vapid.json"
        vapid_file.write_text("not valid json!!!")

        mock_vapid = MagicMock()
        mock_pub_key = MagicMock()
        mock_pub_key.public_bytes.return_value = b"\x04" + b"\xaa" * 64
        mock_vapid.public_key = mock_pub_key
        mock_priv_numbers = MagicMock()
        mock_priv_numbers.private_value = int.from_bytes(b"\xbb" * 32, "big")
        mock_vapid.private_key.private_numbers.return_value = mock_priv_numbers

        with patch("py_vapid.Vapid", return_value=mock_vapid):
            result = get_or_create_vapid_keys(tmp_path)

        assert "public_key" in result
        assert "private_key" in result

    def test_regenerates_on_missing_keys_in_json(self, tmp_path: Path) -> None:
        vapid_file = tmp_path / "vapid.json"
        vapid_file.write_text(json.dumps({"public_key": "only-pub"}))

        mock_vapid = MagicMock()
        mock_pub_key = MagicMock()
        mock_pub_key.public_bytes.return_value = b"\x04" + b"\xcc" * 64
        mock_vapid.public_key = mock_pub_key
        mock_priv_numbers = MagicMock()
        mock_priv_numbers.private_value = int.from_bytes(b"\xdd" * 32, "big")
        mock_vapid.private_key.private_numbers.return_value = mock_priv_numbers

        with patch("py_vapid.Vapid", return_value=mock_vapid):
            result = get_or_create_vapid_keys(tmp_path)

        assert "private_key" in result

    def test_creates_parent_directory(self, tmp_path: Path) -> None:
        nested = tmp_path / "subdir" / "deep"

        mock_vapid = MagicMock()
        mock_pub_key = MagicMock()
        mock_pub_key.public_bytes.return_value = b"\x04" + b"\xee" * 64
        mock_vapid.public_key = mock_pub_key
        mock_priv_numbers = MagicMock()
        mock_priv_numbers.private_value = int.from_bytes(b"\xff" * 32, "big")
        mock_vapid.private_key.private_numbers.return_value = mock_priv_numbers

        with patch("py_vapid.Vapid", return_value=mock_vapid):
            get_or_create_vapid_keys(nested)

        assert (nested / "vapid.json").exists()
