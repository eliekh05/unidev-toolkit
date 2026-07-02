"""
Shared utilities for all platform packagers.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Project-root / web-root detection
# ---------------------------------------------------------------------------

def find_web_root(root: Path) -> Path:
    """Return the directory that contains package.json (or index.html for
    static sites).  Never returns a directory that only has source files."""
    for candidate in [root, root / "frontend", root / "web", root / "app", root / "client"]:
        if (candidate / "package.json").exists():
            return candidate
        if (candidate / "index.html").exists() and candidate != root:
            return candidate
    return root


# ---------------------------------------------------------------------------
# Build-output detection
# ---------------------------------------------------------------------------

_BUILD_DIR_NAMES = ("dist", "build", "out", ".next", ".output")
# Directories whose *presence* tells us we are looking at raw source, not a build
_SOURCE_ONLY_MARKERS = ("src", "node_modules", ".git", "tsconfig.json", "vite.config.ts",
                        "vite.config.js", "webpack.config.js", "package.json")


def _is_build_artifact(path: Path) -> bool:
    parts = path.parts
    if "packages" in parts:
        return True
    name = path.name
    return name.startswith("staging_") or name.startswith("app-")


def find_build_output(web_root: Path) -> Path | None:
    """
    Return the compiled output directory (containing index.html), or None.

    This function intentionally returns None rather than falling back to
    ``web_root`` itself when no build output is found — callers that need a
    fallback should handle it explicitly so they can warn the user instead of
    silently including raw source files.
    """
    for name in _BUILD_DIR_NAMES:
        path = web_root / name
        if not path.exists():
            continue
        children = [
            p for p in path.iterdir()
            if not _is_build_artifact(p) and p.name not in ("packages",)
        ]
        # Direct hit
        if (path / "index.html").exists():
            return path
        # One level deeper
        for child in children:
            if child.is_dir() and (child / "index.html").exists():
                return child

    # Static site: index.html at the root and no build-output dir
    if (web_root / "index.html").exists():
        # Only treat this as a valid build output if it is NOT a raw source dir
        source_markers = any((web_root / m).exists() for m in ("src",))
        if not source_markers:
            return web_root

    return None


# ---------------------------------------------------------------------------
# Helpers used by multiple packagers
# ---------------------------------------------------------------------------

def find_index_html(staging: Path) -> str | None:
    """
    Return the path of index.html relative to *staging*, using forward
    slashes, preferring the shallowest match.
    """
    matches = sorted(staging.rglob("index.html"), key=lambda p: (len(p.parts), str(p)))
    if not matches:
        return None
    return matches[0].relative_to(staging).as_posix()


def ensure_manifest(
    root: Path,
    project_info: dict[str, Any],
    pwa_config: dict[str, Any] | None,
) -> dict[str, Any]:
    pwa = project_info.get("pwa", {})
    if pwa.get("manifest"):
        return pwa["manifest"]
    if pwa_config:
        return pwa_config
    name = root.name.replace("-", " ").title()
    return {
        "name": name,
        "short_name": name[:12],
        "start_url": "/",
        "display": "standalone",
        "background_color": "#ffffff",
        "theme_color": "#0d1117",
        "icons": [{"src": "icon-192.png", "sizes": "192x192", "type": "image/png"}],
    }


def copy_assets_to_staging(staging: Path, source: Path) -> None:
    if staging.exists():
        shutil.rmtree(staging)
    if source.is_dir():
        shutil.copytree(
            source,
            staging,
            ignore=shutil.ignore_patterns("packages", "staging_*", "node_modules", ".git"),
        )
    else:
        staging.mkdir(parents=True, exist_ok=True)


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
