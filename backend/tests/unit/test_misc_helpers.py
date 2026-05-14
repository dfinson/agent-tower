"""Tests for pure helpers in node_builder, artifact_service, platform_adapter, tunnel_service."""

from __future__ import annotations

import json
import shutil
from unittest.mock import patch

import pytest

from backend.models.schemas.base import ArtifactType
from backend.services.adapters.platform_adapter import _validate_refs, detect_platform
from backend.services.artifacts.artifact_service import _classify_artifact, _guess_mime
from backend.services.sharing.tunnel_service import RemoteProvider, validate_remote_provider
from backend.services.trail.node_builder import _extract_snippet, classify_step

# ---------------------------------------------------------------------------
# _extract_snippet
# ---------------------------------------------------------------------------


class TestExtractSnippet:
    def test_none_args(self):
        assert _extract_snippet(None, None) == ""

    def test_invalid_json(self):
        assert _extract_snippet("not json", "Edit") == ""

    def test_non_dict(self):
        assert _extract_snippet("[1,2]", "Edit") == ""

    def test_old_new_str(self):
        args = json.dumps({"old_str": "foo", "new_str": "bar"})
        result = _extract_snippet(args, "Edit")
        assert "- foo" in result
        assert "+ bar" in result

    def test_old_string_variant(self):
        args = json.dumps({"oldString": "a\nb", "newString": "c\nd"})
        result = _extract_snippet(args, "Edit")
        assert "- a" in result
        assert "+ c" in result

    def test_content(self):
        args = json.dumps({"content": "line1\nline2"})
        result = _extract_snippet(args, "create")
        assert "+ line1" in result
        assert "+ line2" in result

    def test_file_text(self):
        args = json.dumps({"file_text": "hello\nworld"})
        result = _extract_snippet(args, "create")
        assert "+ hello" in result

    def test_new_text(self):
        args = json.dumps({"new_text": "abc"})
        result = _extract_snippet(args, "Write")
        assert "+ abc" in result

    def test_empty_args(self):
        assert _extract_snippet("{}", "Edit") == ""

    def test_truncates_long_content(self):
        lines = "\n".join(f"line{i}" for i in range(20))
        args = json.dumps({"content": lines})
        result = _extract_snippet(args, "create")
        # Should truncate to max_lines=8
        assert result.count("\n") <= 7  # 8 lines = 7 newlines


# ---------------------------------------------------------------------------
# classify_step
# ---------------------------------------------------------------------------


class TestClassifyStep:
    def test_files_written(self):
        assert classify_step({"files_written": ["a.py"]}) == "modify"

    def test_sha_changed(self):
        assert classify_step({"start_sha": "aaa", "end_sha": "bbb"}) == "modify"

    def test_sha_same(self):
        assert classify_step({"start_sha": "aaa", "end_sha": "aaa", "files_read": ["x.py"]}) == "explore"

    def test_files_read(self):
        assert classify_step({"files_read": ["x.py"]}) == "explore"

    def test_default_shell(self):
        assert classify_step({}) == "shell"


# ---------------------------------------------------------------------------
# artifact_service pure helpers
# ---------------------------------------------------------------------------


class TestGuessMime:
    @pytest.mark.parametrize(
        "filename,expected",
        [
            ("data.json", "application/json"),
            ("readme.md", "text/markdown"),
            ("image.png", "image/png"),
            ("photo.jpg", "image/jpeg"),
            ("doc.pdf", "application/pdf"),
            ("config.yaml", "text/yaml"),
            ("config.yml", "text/yaml"),
            ("page.html", "text/html"),
            ("data.csv", "text/csv"),
            ("schema.xml", "application/xml"),
            ("icon.svg", "image/svg+xml"),
            ("notes.txt", "text/plain"),
            ("app.log", "text/plain"),
            ("unknown.xyz", "application/octet-stream"),
        ],
    )
    def test_extensions(self, filename: str, expected: str):
        assert _guess_mime(filename) == expected


class TestClassifyArtifact:
    def test_document(self):
        assert _classify_artifact("readme.md") == ArtifactType.document
        assert _classify_artifact("notes.txt") == ArtifactType.document

    def test_custom(self):
        assert _classify_artifact("image.png") == ArtifactType.custom
        assert _classify_artifact("data.json") == ArtifactType.custom


# ---------------------------------------------------------------------------
# platform_adapter helpers
# ---------------------------------------------------------------------------


class TestValidateRefs:
    def test_valid(self):
        assert _validate_refs("main", "feature/branch-1") is True

    def test_invalid_space(self):
        assert _validate_refs("bad branch") is False


class TestDetectPlatform:
    def test_github(self):
        assert detect_platform("git@github.com:user/repo.git") == "github"

    def test_github_https(self):
        assert detect_platform("https://github.com/user/repo.git") == "github"

    def test_azure(self):
        assert detect_platform("https://dev.azure.com/org/project/_git/repo") == "azure_devops"

    def test_gitlab(self):
        assert detect_platform("https://gitlab.com/user/repo.git") == "gitlab"

    def test_none(self):
        assert detect_platform(None) is None

    def test_unknown(self):
        assert detect_platform("https://bitbucket.org/user/repo") is None


# ---------------------------------------------------------------------------
# tunnel_service validation
# ---------------------------------------------------------------------------


class TestValidateRemoteProvider:
    def test_local(self):
        assert validate_remote_provider(RemoteProvider.local) is None

    def test_devtunnel_available(self):
        with patch.object(shutil, "which", return_value="/usr/bin/devtunnel"):
            assert validate_remote_provider(RemoteProvider.devtunnel) is None

    def test_devtunnel_missing(self):
        with patch.object(shutil, "which", return_value=None):
            result = validate_remote_provider(RemoteProvider.devtunnel)
            assert result is not None
            assert "devtunnel" in result

    def test_cloudflare_missing_env(self):
        result = validate_remote_provider(
            RemoteProvider.cloudflare,
            cloudflare_token=None,
            cloudflare_hostname=None,
        )
        assert result is not None
        assert "CPL_CLOUDFLARE_HOSTNAME" in result

    def test_cloudflare_available(self):
        with patch.object(shutil, "which", return_value="/usr/bin/cloudflared"):
            result = validate_remote_provider(
                RemoteProvider.cloudflare,
                cloudflare_token="tok",
                cloudflare_hostname="host.example.com",
            )
            assert result is None

    def test_cloudflare_cli_missing(self):
        with patch.object(shutil, "which", return_value=None):
            result = validate_remote_provider(
                RemoteProvider.cloudflare,
                cloudflare_token="tok",
                cloudflare_hostname="host.example.com",
            )
            assert result is not None
            assert "cloudflared" in result
