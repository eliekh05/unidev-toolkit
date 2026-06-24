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


async def package_ipa(
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
    out_path = dist_dir / "app-ipa.ipa"

    # IPA layout:
    #   Payload/
    #     MyApp.app/
    #       Info.plist
    #       www/           ← web assets (preserving sub-directory layout)
    staging = dist_dir / "staging_ipa"
    payload = staging / "Payload" / f"{app_name}.app"
    www = payload / "www"
    www.mkdir(parents=True)

    copy_assets_to_staging(www, build_out)

    # Discover actual index.html location inside www/
    index_rel = find_index_html(www)  # e.g. "index.html" or "dist/index.html"
    if index_rel is None:
        await log("[ipa] WARNING: index.html not found — writing placeholder\n")
        (www / "index.html").write_text(
            "<html><body><h1>App</h1><p>index.html not found.</p></body></html>",
            encoding="utf-8",
        )
        index_rel = "index.html"

    await log(f"[ipa] Entry point: www/{index_rel}\n")

    # Info.plist — WKWebView-based wrapper needs WKAppBoundDomains or file:// access
    info_plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>{manifest.get('name', app_name)}</string>
  <key>CFBundleIdentifier</key><string>com.unidev.{app_name.lower()}</string>
  <key>CFBundleVersion</key><string>1.0.0</string>
  <key>CFBundleShortVersionString</key><string>1.0.0</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>{app_name}</string>
  <key>MinimumOSVersion</key><string>14.0</string>
  <key>UIRequiresFullScreen</key><true/>
  <key>UIStatusBarHidden</key><false/>
  <!-- WKWebView entry point — resolved by the native host at runtime -->
  <key>UniDevStartFile</key><string>www/{index_rel}</string>
</dict></plist>"""
    (payload / "Info.plist").write_text(info_plist, encoding="utf-8")

    await log("[ipa] Building iOS app archive (Payload bundle)...\n")

    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in staging.rglob("*"):
            if f.is_file():
                zf.write(f, f.relative_to(staging).as_posix())

    await log(f"[ipa] Package ready: {out_path.name}\n")
    await log("[ipa] Note: Sign with Xcode/Apple Developer for App Store distribution.\n")
    return out_path
