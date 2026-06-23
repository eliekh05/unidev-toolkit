import asyncio
import os
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Any, AsyncGenerator, Callable, Awaitable

import httpx

from services.build_log import emit
from services.packagers import create_package
from services.project_analyzer import detect_project_type
from services.format_registry import get_build_targets

LogFn = Callable[[str], Awaitable[None]]


async def _log(msg: str, log_fn: LogFn | None = None) -> None:
    if log_fn:
        await log_fn(msg)
    await emit(msg)


async def clone_repo(url: str, token: str | None = None) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="unidev_"))
    clone_url = url
    if token and "github.com" in url:
        clone_url = url.replace("https://", f"https://{token}@")
    elif token and "gitlab.com" in url:
        clone_url = url.replace("https://", f"https://oauth2:{token}@")

    proc = await asyncio.create_subprocess_exec(
        "git", "clone", "--depth", "1", clone_url, str(tmp / "repo"),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    out, _ = await proc.communicate()
    if proc.returncode != 0:
        shutil.rmtree(tmp, ignore_errors=True)
        raise RuntimeError(f"Git clone failed:\n{out.decode(errors='replace')}")
    return tmp / "repo"


def extract_upload(content: bytes, filename: str) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="unidev_upload_"))
    lower = filename.lower()
    if lower.endswith(".zip"):
        with zipfile.ZipFile(__import__("io").BytesIO(content)) as zf:
            zf.extractall(tmp)
        items = list(tmp.iterdir())
        if len(items) == 1 and items[0].is_dir():
            return items[0]
        return tmp
    if lower.endswith((".tar.gz", ".tgz")):
        import tarfile
        with tarfile.open(fileobj=__import__("io").BytesIO(content), mode="r:gz") as tf:
            tf.extractall(tmp)
        items = list(tmp.iterdir())
        if len(items) == 1 and items[0].is_dir():
            return items[0]
        return tmp
    raise ValueError("Upload must be a .zip or .tar.gz archive")


def analyze_local_path(path: str) -> tuple[Path, dict[str, Any]]:
    root = Path(path).resolve()
    if not root.exists():
        raise FileNotFoundError(f"Path not found: {path}")
    return root, detect_project_type(root)


async def analyze_remote(url: str, token: str | None = None) -> tuple[Path, dict[str, Any]]:
    repo_path = await clone_repo(url, token)
    return repo_path, detect_project_type(repo_path)


def analyze_upload(content: bytes, filename: str) -> tuple[Path, dict[str, Any]]:
    root = extract_upload(content, filename)
    return root, detect_project_type(root)


BUILD_STEPS: dict[str, dict[str, str]] = {
    "web": {
        "pre": "npm install --legacy-peer-deps 2>/dev/null || npm install",
        "build": "npm run build 2>/dev/null || npm run build:prod 2>/dev/null || echo 'No build script — using source files'",
    },
    "electron": {
        "pre": "npm install",
        "build": "npm run build 2>/dev/null; npx electron-builder --{target} 2>/dev/null || echo 'electron-builder skipped in this environment'",
    },
    "flutter": {
        "pre": "flutter pub get",
        "build": "flutter build {target_flutter}",
    },
    "capacitor": {
        "pre": "npm install && npx cap sync",
        "build": "npm run build",
    },
    "pwa": {
        "pre": "npm install --legacy-peer-deps 2>/dev/null || true",
        "build": "npm run build 2>/dev/null || true",
    },
    "react-native": {
        "pre": "npm install",
        "build": "echo 'Use native toolchain for RN release builds'",
    },
    "tauri": {
        "pre": "npm install",
        "build": "npm run tauri build 2>/dev/null || echo 'Tauri build requires Rust toolchain'",
    },
    "dotnet": {
        "pre": "dotnet restore",
        "build": "dotnet publish -c Release",
    },
}


async def run_shell(cmd: str, cwd: Path, log_fn: LogFn | None) -> int:
    await _log(f"$ {cmd}\n", log_fn)
    proc = await asyncio.create_subprocess_shell(
        cmd,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env={**os.environ, "CI": "true", "npm_config_yes": "true"},
    )
    assert proc.stdout
    while True:
        chunk = await proc.stdout.read(4096)
        if not chunk:
            break
        await _log(chunk.decode(errors="replace"), log_fn)
    return await proc.wait()


def _project_root_for_build(root: Path, project_info: dict[str, Any]) -> Path:
    for sub in ["frontend", "web", "app", "client", "."]:
        candidate = root / sub if sub != "." else root
        if (candidate / "package.json").exists():
            return candidate
    if (root / "pubspec.yaml").exists():
        return root
    return root


async def run_build_steps(root: Path, project_info: dict[str, Any], target: str, log_fn: LogFn | None) -> None:
    project_type = project_info.get("type", "unknown")
    steps = BUILD_STEPS.get(project_type, BUILD_STEPS.get("web", {}))
    work_root = _project_root_for_build(root, project_info)

    target_map = {"apk": "apk", "ipa": "ipa", "dmg": "macos", "msix": "windows"}
    flutter_target = {"apk": "apk", "ipa": "ipa", "dmg": "macos", "msix": "windows"}.get(target, "apk")

    if (work_root / "package.json").exists() or project_type in BUILD_STEPS:
        pre = steps.get("pre", "")
        if pre:
            await run_shell(pre, work_root, log_fn)
        build_cmd = steps.get("build", "").format(
            target=target,
            target_flutter=flutter_target,
        )
        if build_cmd:
            await run_shell(build_cmd, work_root, log_fn)

    if project_type == "electron" and target in ("dmg", "msix"):
        eb_target = "mac" if target == "dmg" else "win"
        await run_shell(
            f"npx electron-builder --{eb_target} --{target} 2>/dev/null || true",
            work_root,
            log_fn,
        )


async def run_build(
    root: Path,
    project_info: dict[str, Any],
    target: str,
    pwa_config: dict[str, Any] | None = None,
    log_fn: LogFn | None = None,
) -> AsyncGenerator[str, None]:
    project_type = project_info.get("type", "unknown")

    async def collect(msg: str) -> None:
        yield_buffer.append(msg)

    yield_buffer: list[str] = []

    async def logging(msg: str) -> None:
        yield_buffer.append(msg)
        await emit(msg)

    await logging(f"[build] Project type: {project_type} ({project_info.get('framework', 'unknown')})\n")
    await logging(f"[build] Target: .{target}\n")

    if pwa_config and not project_info.get("pwa", {}).get("has_pwa"):
        manifest_path = _project_root_for_build(root, project_info) / "manifest.webmanifest"
        manifest_path.write_text(__import__("json").dumps(pwa_config, indent=2), encoding="utf-8")
        await logging(f"[build] Created PWA manifest at {manifest_path.name}\n")

    await run_build_steps(root, project_info, target, logging)

    import tempfile
    output_dir = Path(tempfile.mkdtemp(prefix="unidev_pkg_"))
    packages_dir = output_dir / "out"
    packages_dir.mkdir(parents=True, exist_ok=True)

    await logging("[build] Creating platform package...\n")
    package_path = await create_package(root, project_info, target, pwa_config, packages_dir, logging)

    dest_name = f"app-{target}.{target}"
    final_path = packages_dir / dest_name
    if package_path != final_path:
        shutil.copy2(package_path, final_path)

    # Store reference on root for download handler compatibility
    persist_dir = root / ".unidev" / "packages"
    persist_dir.mkdir(parents=True, exist_ok=True)
    persisted = persist_dir / dest_name
    shutil.copy2(final_path, persisted)
    project_info["_package_path"] = str(persisted)

    await logging(f"[build] Package created: {final_path.name}\n")
    await logging("[build] Done.\n")

    for line in yield_buffer:
        yield line

    yield f"__PACKAGE__:{persisted}"


def get_available_targets(project_info: dict[str, Any]) -> list[str]:
    return get_build_targets(project_info.get("type", "unknown"))
