import asyncio
import shutil
import zipfile
from pathlib import Path
from typing import Any

from services.packagers.common import (
    copy_assets_to_staging,
    ensure_manifest,
    find_build_output,
    find_index_html,
    find_web_root,
)


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
    out_path = dist_dir / "app-dmg.dmg"

    # ── Build .app bundle layout ──────────────────────────────────────────────
    #   MyApp.app/
    #     Contents/
    #       Info.plist
    #       MacOS/
    #         MyApp           ← executable launcher script
    #       Resources/
    #         www/            ← ALL web assets copied here verbatim
    # ─────────────────────────────────────────────────────────────────────────
    staging    = dist_dir / "staging_dmg"
    contents   = staging / f"{app_name}.app" / "Contents"
    macos_dir  = contents / "MacOS"
    www        = contents / "Resources" / "www"
    www.mkdir(parents=True)
    macos_dir.mkdir(parents=True, exist_ok=True)

    # Copy all web assets under Resources/www (preserving sub-directory layout)
    copy_assets_to_staging(www, build_out)

    # Detect where index.html actually lives inside the copied assets
    index_rel = find_index_html(www)  # e.g. "index.html" or "dist/index.html"
    if index_rel is None:
        # Fallback: write a minimal index so the launcher never errors out
        await log("[dmg] WARNING: index.html not found in assets — writing placeholder\n")
        (www / "index.html").write_text(
            "<html><body><h1>App</h1><p>index.html not found.</p></body></html>",
            encoding="utf-8",
        )
        index_rel = "index.html"

    await log(f"[dmg] index.html detected at Resources/www/{index_rel}\n")

    # ── Info.plist ────────────────────────────────────────────────────────────
    # CFBundleExecutable MUST match the launcher filename exactly.
    info_plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>{manifest.get('name', app_name)}</string>
  <key>CFBundleIdentifier</key><string>com.unidev.{app_name.lower()}</string>
  <key>CFBundleVersion</key><string>1.0.0</string>
  <key>CFBundleShortVersionString</key><string>1.0.0</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>{app_name}</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>LSUIElement</key><false/>
</dict></plist>"""
    (contents / "Info.plist").write_text(info_plist, encoding="utf-8")

    # ── Launcher script ───────────────────────────────────────────────────────
    # Resolve index.html relative to the MacOS/ directory at runtime:
    #   MacOS/ → ../Resources/www/<index_rel>
    # Using `open` launches the file in the default browser (Safari/Chrome).
    launcher_path = macos_dir / app_name
    launcher_script = (
        "#!/usr/bin/env bash\n"
        'SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"\n'
        f'INDEX="$SCRIPT_DIR/../Resources/www/{index_rel}"\n'
        'if [ ! -f "$INDEX" ]; then\n'
        '  osascript -e \'tell application "System Events" to display dialog "\' \\\n'
        '    "Cannot find index.html. The application bundle may be corrupted." \\\n'
        '    \'with title "Launch Error" buttons {"OK"}\'\n'
        '  exit 1\n'
        'fi\n'
        'open "$INDEX"\n'
    )
    launcher_path.write_text(launcher_script, encoding="utf-8")
    launcher_path.chmod(0o755)

    await log("[dmg] Creating macOS disk image...\n")

    # ── Try native hdiutil (macOS build server) ───────────────────────────────
    if shutil.which("hdiutil"):
        dmg_staging = dist_dir / "dmg_staging"
        if dmg_staging.exists():
            shutil.rmtree(dmg_staging)
        shutil.copytree(staging, dmg_staging)
        proc = await asyncio.create_subprocess_exec(
            "hdiutil", "create",
            "-volname", app_name,
            "-srcfolder", str(dmg_staging),
            "-ov", "-format", "UDZO",
            str(out_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        out, _ = await proc.communicate()
        await log(out.decode(errors="replace"))
        if proc.returncode == 0 and out_path.exists():
            await log(f"[dmg] Native DMG created: {out_path.name}\n")
            return out_path

    # ── Try genisoimage (Linux CI) ────────────────────────────────────────────
    if shutil.which("genisoimage"):
        iso_path = dist_dir / "temp.iso"
        proc = await asyncio.create_subprocess_exec(
            "genisoimage", "-V", app_name, "-D", "-R", "-apple", "-no-pad",
            "-o", str(iso_path), str(staging),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        out, _ = await proc.communicate()
        await log(out.decode(errors="replace"))
        if proc.returncode == 0:
            shutil.move(str(iso_path), str(out_path))
            await log(f"[dmg] ISO-based image created: {out_path.name}\n")
            return out_path

    # ── Portable fallback: zip of the .app bundle ────────────────────────────
    await log("[dmg] hdiutil/genisoimage unavailable — creating portable .app.zip archive.\n")
    await log("[dmg] Extract the archive on macOS and double-click the .app to run.\n")
    # We still use the .dmg extension so the download URL stays consistent;
    # the file is a ZIP internally but macOS Finder will offer to extract it.
    shutil.make_archive(str(out_path.with_suffix("")), "zip", staging)
    zip_path = out_path.with_suffix(".zip")  # make_archive appends .zip
    if zip_path != out_path:
        shutil.move(str(zip_path), str(out_path))
    await log(f"[dmg] App bundle archive ready: {out_path.name}\n")
    return out_path
