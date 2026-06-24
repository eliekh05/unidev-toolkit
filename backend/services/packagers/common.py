import json
import shutil
from pathlib import Path
from typing import Any


def find_web_root(root: Path) -> Path:
    for candidate in [root, root / "frontend", root / "web", root / "app", root / "client"]:
        if (candidate / "package.json").exists():
            return candidate
        if (candidate / "index.html").exists() and candidate != root:
            return candidate
    return root


def _is_build_artifact(path: Path) -> bool:
    parts = path.parts
    if "packages" in parts:
        return True
    name = path.name
    return name.startswith("staging_") or name.startswith("app-")


def find_build_output(web_root: Path) -> Path | None:
    for name in ["dist", "build", "out", "public"]:
        path = web_root / name
        if not path.exists():
            continue
        children = [
            p for p in path.iterdir()
            if not _is_build_artifact(p) and p.name not in ("packages",)
        ]
        for child in children:
            if child.is_dir() and (child / "index.html").exists():
                return child
        if (path / "index.html").exists():
            return path
        for child in children:
            if child.is_dir() and any(child.iterdir()):
                return child
        if children:
            return children[0]

    if (web_root / "index.html").exists():
        return web_root
    src = web_root / "src"
    if src.exists():
        return web_root
    return None


def find_index_html(staging: Path) -> str | None:
    """
    Recursively search the staged web assets for index.html and return its
    path *relative to the staging directory* using forward slashes.

    We prefer the shallowest match, then alphabetical order so that
    dist/index.html beats dist/subdir/index.html.
    """
    matches = sorted(staging.rglob("index.html"), key=lambda p: (len(p.parts), str(p)))
    if not matches:
        return None
    return matches[0].relative_to(staging).as_posix()


def ensure_manifest(root: Path, project_info: dict[str, Any], pwa_config: dict[str, Any] | None) -> dict[str, Any]:
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
