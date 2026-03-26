from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


def _frontend_source_files(frontend_root: Path) -> list[Path]:
    paths = [
        frontend_root / "index.html",
        frontend_root / "package.json",
        frontend_root / "package-lock.json",
        frontend_root / "vite.config.ts",
        frontend_root / "postcss.config.cjs",
        frontend_root / "tailwind.config.cjs",
        frontend_root / "tsconfig.json",
        frontend_root / "tsconfig.node.json",
    ]

    for relative_dir in ("src", "public"):
        directory = frontend_root / relative_dir
        if directory.is_dir():
            paths.extend(path for path in directory.rglob("*") if path.is_file())

    return [path for path in paths if path.exists()]


class FrontendBuildHook(BuildHookInterface):
    PLUGIN_NAME = "custom"

    def initialize(self, version: str, build_data: dict[str, object]) -> None:
        project_root = Path(self.root)
        frontend_root = project_root / "frontend"
        output_dir = project_root / "backend" / "web"
        output_index = output_dir / "index.html"
        source_files = _frontend_source_files(frontend_root)

        if output_index.exists() and source_files:
            latest_source_mtime = max(path.stat().st_mtime for path in source_files)
            if output_index.stat().st_mtime >= latest_source_mtime:
                return

        package_json = frontend_root / "package.json"
        if not package_json.exists():
            if output_index.exists():
                return
            raise RuntimeError("Frontend sources are missing and no packaged web assets were found.")

        npm = shutil.which("npm")
        if npm is None:
            if output_index.exists():
                return
            raise RuntimeError("npm is required to build packaged frontend assets.")

        if not (frontend_root / "node_modules").is_dir():
            subprocess.run([npm, "ci"], cwd=frontend_root, check=True)

        env = os.environ.copy()
        env.setdefault("CI", "1")
        subprocess.run([npm, "run", "build"], cwd=frontend_root, check=True, env=env)

        if not output_index.exists():
            raise RuntimeError("Frontend build completed without producing backend/web/index.html.")


def get_build_hook() -> type[FrontendBuildHook]:
    return FrontendBuildHook