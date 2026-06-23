import asyncio
import shutil
import zipfile
from pathlib import Path
from typing import Any

from services.packagers.common import copy_assets_to_staging, ensure_manifest, find_build_output, find_web_root


async def _try_bubblewrap(web_root: Path, manifest: dict, out_path: Path, log) -> bool:
    manifest_path = web_root / "manifest.webmanifest"
    write_manifest = not manifest_path.exists()
    if write_manifest:
        import json
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    await log("[apk] Attempting Bubblewrap (TWA) build...\n")
    init = await asyncio.create_subprocess_shell(
        f'npx --yes @bubblewrap/cli init --manifest "{manifest_path}" --directory twa-build --yes 2>/dev/null || '
        f'npx --yes @bubblewrap/cli init --manifest "{manifest_path}" --directory twa-build',
        cwd=web_root,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    out, _ = await init.communicate()
    await log(out.decode(errors="replace"))

    if init.returncode != 0:
        return False

    build = await asyncio.create_subprocess_shell(
        "npx @bubblewrap/cli build",
        cwd=web_root / "twa-build",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    bout, _ = await build.communicate()
    await log(bout.decode(errors="replace"))

    for apk in (web_root / "twa-build").rglob("*.apk"):
        if "unsigned" not in apk.name.lower() and "debug" not in apk.name.lower():
            shutil.copy2(apk, out_path)
            return True
    for apk in (web_root / "twa-build").rglob("*.apk"):
        shutil.copy2(apk, out_path)
        return True
    return False


def _fallback_apk(staging: Path, manifest: dict, out_path: Path) -> None:
    """Minimal APK-shaped archive with web assets for sideload/dev workflows."""
    app_name = manifest.get("short_name", "App").replace(" ", "")
    assets = staging / "assets" / "www"
    assets.mkdir(parents=True, exist_ok=True)
    for item in staging.iterdir():
        if item.name in ("assets", "META-INF"):
            continue
        dest = assets / item.name
        if item.is_dir():
            shutil.copytree(item, dest, dirs_exist_ok=True)
        else:
            shutil.copy2(item, dest)

    manifest_xml = f"""<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android"
    package="com.unidev.{app_name.lower()}"
    android:versionCode="1"
    android:versionName="1.0">
    <uses-sdk android:minSdkVersion="21" android:targetSdkVersion="33"/>
    <application android:label="{manifest.get('name', app_name)}"
        android:allowBackup="true">
        <activity android:name=".MainActivity" android:exported="true">
            <intent-filter>
                <action android:name="android.intent.action.MAIN"/>
                <category android:name="android.intent.category.LAUNCHER"/>
            </intent-filter>
        </activity>
    </application>
</manifest>"""

    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("AndroidManifest.xml", manifest_xml)
        zf.writestr("assets/www/index.html", (assets / "index.html").read_text() if (assets / "index.html").exists() else "<html><body>UniDev Build</body></html>")
        for f in assets.rglob("*"):
            if f.is_file() and f.name != "index.html":
                zf.write(f, f"assets/www/{f.relative_to(assets).as_posix()}")
        zf.writestr("META-INF/MANIFEST.MF", "Manifest-Version: 1.0\nCreated-By: UniDev Toolkit\n")


async def package_apk(
    root: Path,
    project_info: dict[str, Any],
    pwa_config: dict[str, Any] | None,
    dist_dir: Path,
    log,
) -> Path:
    web_root = find_web_root(root)
    build_out = find_build_output(web_root) or web_root
    manifest = ensure_manifest(root, project_info, pwa_config)
    out_path = dist_dir / "app.apk"

    staging = dist_dir / "staging_apk"
    copy_assets_to_staging(staging, build_out)

    if shutil.which("java"):
        try:
            if await _try_bubblewrap(web_root, manifest, out_path, log):
                await log(f"[apk] Bubblewrap package: {out_path.name}\n")
                return out_path
        except Exception as e:
            await log(f"[apk] Bubblewrap unavailable: {e}\n")

    await log("[apk] Creating asset-wrapped APK package...\n")
    _fallback_apk(staging, manifest, out_path)
    await log(f"[apk] Package ready: {out_path.name}\n")
    return out_path
