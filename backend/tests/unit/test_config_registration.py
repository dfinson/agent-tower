"""Tests for configuration registration and persistence."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from backend.config import (
    CPLConfig,
    _update_repos_in_file,
    load_config,
    register_repo,
    save_config,
    unregister_repo,
)


@pytest.fixture
def config_path(tmp_path: Path) -> Path:
    return tmp_path / "config.yaml"


@pytest.fixture
def config() -> CPLConfig:
    return CPLConfig(repos=[])


class TestSaveConfig:
    def test_save_writes_settings(self, config: CPLConfig, config_path: Path) -> None:
        """save_config persists settings fields (not repos)."""
        config.runtime.max_concurrent_jobs = 5
        save_config(config, config_path)
        assert config_path.exists()

        with open(config_path) as f:
            raw = yaml.safe_load(f)
        assert raw["runtime"]["max_concurrent_jobs"] == 5

    def test_save_does_not_write_repos(self, config: CPLConfig, config_path: Path) -> None:
        """save_config must never overwrite the repos list in the file.

        This is the key regression guard: previously save_config wrote
        config.repos to the file, which meant a stale in-memory CPLConfig
        (loaded before repos were registered) could silently clear the list.
        """
        # Pre-populate repos in the file via the proper helper.
        _update_repos_in_file(["/repos/existing"], config_path)

        # Now save_config with a config that has no repos (simulates stale DI).
        config.repos = []
        save_config(config, config_path)

        # Repos must still be present in the file.
        with open(config_path) as f:
            raw = yaml.safe_load(f)
        assert raw["repos"] == ["/repos/existing"]

    def test_save_preserves_repos_already_in_file(self, config: CPLConfig, config_path: Path) -> None:
        """save_config called multiple times never loses repos."""
        _update_repos_in_file(["/repos/a", "/repos/b"], config_path)

        # Simulate an update_settings call that has no repos knowledge.
        config.repos = []
        save_config(config, config_path)
        save_config(config, config_path)

        loaded = load_config(config_path)
        assert "/repos/a" in loaded.repos
        assert "/repos/b" in loaded.repos

    def test_save_creates_parent_dirs(self, config: CPLConfig, tmp_path: Path) -> None:
        deep_path = tmp_path / "nested" / "dir" / "config.yaml"
        save_config(config, deep_path)
        assert deep_path.exists()


class TestRegisterRepo:
    def test_register_adds_to_list(
        self,
        config: CPLConfig,
        config_path: Path,
    ) -> None:
        result = register_repo(config, "/repos/test", config_path)
        assert result == str(Path("/repos/test").resolve())
        assert result in config.repos

    def test_register_idempotent(
        self,
        config: CPLConfig,
        config_path: Path,
    ) -> None:
        register_repo(config, "/repos/test", config_path)
        register_repo(config, "/repos/test", config_path)
        resolved = str(Path("/repos/test").resolve())
        assert config.repos.count(resolved) == 1

    def test_register_persists_to_file(
        self,
        config: CPLConfig,
        config_path: Path,
    ) -> None:
        register_repo(config, "/repos/test", config_path)
        with open(config_path) as f:
            raw = yaml.safe_load(f)
        resolved = str(Path("/repos/test").resolve())
        assert resolved in raw["repos"]

    def test_register_reads_from_file_not_stale_config(
        self,
        tmp_path: Path,
    ) -> None:
        """register_repo must not lose repos registered by a concurrent request.

        Reproduces the core bug: a stale CPLConfig (loaded before a repo was
        registered) used to overwrite the file's repos with its own empty list,
        erasing the concurrent registration.
        """
        config_path = tmp_path / "config.yaml"

        # Simulate a previous request that already registered /repos/existing.
        _update_repos_in_file(["/repos/existing"], config_path)

        # Now a new request arrives with a *stale* config (loaded before the
        # previous registration happened — repos is empty).
        stale_config = CPLConfig(repos=[])

        # Registering a new repo must NOT lose /repos/existing.
        register_repo(stale_config, "/repos/new", config_path)

        loaded = load_config(config_path)
        resolved_existing = str(Path("/repos/existing").resolve())
        resolved_new = str(Path("/repos/new").resolve())
        assert resolved_existing in loaded.repos, "existing repo was lost!"
        assert resolved_new in loaded.repos


class TestUnregisterRepo:
    def test_unregister_removes_from_list(
        self,
        config: CPLConfig,
        config_path: Path,
    ) -> None:
        # Use register_repo to set up file state (not save_config).
        register_repo(config, "/repos/test", config_path)
        resolved = str(Path("/repos/test").resolve())

        result = unregister_repo(config, "/repos/test", config_path)
        assert result == resolved
        assert resolved not in config.repos

    def test_unregister_nonexistent_raises(
        self,
        config: CPLConfig,
        config_path: Path,
    ) -> None:
        with pytest.raises(ValueError, match="not in the allowlist"):
            unregister_repo(config, "/repos/nonexistent", config_path)

    def test_unregister_reads_from_file_not_stale_config(
        self,
        tmp_path: Path,
    ) -> None:
        """unregister_repo removes from the current file state, not a stale config."""
        config_path = tmp_path / "config.yaml"
        _update_repos_in_file(["/repos/a", "/repos/b"], config_path)

        # Stale config only knows about /repos/a.
        stale_config = CPLConfig(repos=[str(Path("/repos/a").resolve())])

        # Unregistering /repos/a should remove it from the file, leaving /repos/b.
        unregister_repo(stale_config, "/repos/a", config_path)

        loaded = load_config(config_path)
        resolved_a = str(Path("/repos/a").resolve())
        resolved_b = str(Path("/repos/b").resolve())
        assert resolved_a not in loaded.repos
        assert resolved_b in loaded.repos, "/repos/b must not be lost!"


class TestLoadConfig:
    def test_load_missing_file_returns_defaults(self, tmp_path: Path) -> None:
        config = load_config(tmp_path / "does_not_exist.yaml")
        assert config.repos == []
        assert config.server.host == "127.0.0.1"

    def test_load_saved_config(self, config_path: Path) -> None:
        """Repos written by register_repo are round-tripped correctly."""
        cfg = CPLConfig(repos=[])
        register_repo(cfg, "/repos/a", config_path)
        loaded = load_config(config_path)
        assert str(Path("/repos/a").resolve()) in loaded.repos
