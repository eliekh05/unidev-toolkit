import asyncio
import shutil
import subprocess
import zipfile
from pathlib import Path
from typing import Any

from services.packagers.common import copy_assets_to_staging, ensure_manifest, find_build_output, find_web_root


async def package_dmg(
    root: Path,
    project_info: dict[str, Any],
    pwa_config: dict[str, Any] | None,
    dist_dir: Path,
    log,
) -> Path:
    web_root = find_web_root(root)
    build_out = find_build_output(web_root) or web_root
    manifest = ensure_manifest(root, project_info, pwa_config)
    app_name = manifest.get("short_name", "UniDevApp").replace(" ", "")
    out_path = dist_dir / "app.dmg"

    staging = dist_dir / "staging_dmg"
    app_bundle = staging / f"{app_name}.app" / "Contents"
    www = app_bundle / "Resources" / "www"
    www.mkdir(parents=True)
    copy_assets_to_staging(www, build_out)

    info_plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>{manifest.get('name', app_name)}</string>
  <key>CFBundleIdentifier</key><string>com.unidev.{app_name.lower()}</string>
  <key>CFBundleVersion</key><string>1.0.0</string>
  <key>CFBundlePackageType</key><string>APPL</string>
</dict></plist>"""
    (app_bundle / "Info.plist").write_text(info_plist, encoding="utf-8")
    (app_bundle / "MacOS").mkdir(exist_ok=True)
    launcher = app_bundle / "MacOS" / app_name
    launcher.write_text("#!/bin/bash\nopen \"$(dirname \"$0\")/../Resources/www/index.html\"\n", encoding="utf-8")
    launcher.chmod(0o755)

    await log("[dmg] Creating macOS disk image...\n")

    if shutil.which("hdiutil"):
        dmg_staging = dist_dir / "dmg_staging"
        if dmg_staging.exists():
            shutil.rmtree(dmg_staging)
        shutil.copytree(staging, dmg_staging)
        proc = await asyncio.create_subprocess_exec(
            "hdiutil", "create", "-volname", app_name, "-srcfolder", str(dmg_staging),
            "-ov", "-format", "UDZO", str(out_path),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        )
        out, _ = await proc.communicate()
        await log(out.decode(errors="replace"))
        if proc.returncode == 0 and out_path.exists():
            await log(f"[dmg] Native DMG created: {out_path.name}\n")
            return out_path

    if shutil.which("genisoimage"):
        iso_path = dist_dir / "temp.iso"
        proc = await asyncio.create_subprocess_exec(
            "genisoimage", "-V", app_name, "-D", "-R", "-apple", "-no-pad",
            "-o", str(iso_path), str(staging),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        )
        out, _ = await proc.communicate()
        await log(out.decode(errors="replace"))
        if proc.returncode == 0:
            shutil.move(iso_path, out_path)
            await log(f"[dmg] ISO-based image created: {out_path.name}\n")
            return out_path

    await log("[dmg] Using portable app bundle archive (extract on macOS)...\n")
    bundle_zip = dist_dir / f"{app_name}.app.zip"
    shutil.make_archive(str(bundle_zip.with_suffix("")), "zip", staging)
    shutil.move(bundle_zip, out_path)
    await log(f"[dmg] App bundle archive ready: {out_path.name}\n")
    return out_path
