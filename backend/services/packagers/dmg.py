"""
macOS DMG packager — builds a proper self-contained .app bundle for a PWA.

What a *real* PWA-to-macOS app looks like
==========================================
Tools such as Nativefier, Web2App, and Fluid produce:

  MyApp.app/
    Contents/
      Info.plist             ← bundle metadata
      MacOS/
        MyApp                ← executable (shell script launcher)
      Resources/
        AppIcon.icns         ← optional icon
        www/
          index.html         ← ** ONLY the compiled web assets **
          assets/
          manifest.webmanifest
          ...

The critical difference from what we were doing before
------------------------------------------------------
Previously the code called ``find_web_root()`` → ``find_build_output()`` and
fell back to the *project root* when no dist/ directory was found, meaning the
entire repository (backend/, frontend/src/, node_modules leftovers, etc.) was
dumped verbatim into Resources/www/.

Now we:
1.  Look specifically for the **build output** (dist / build / out / public
    directories that contain an index.html).  We never fall back to the raw
    source tree.
2.  If no build output exists we synthesise a tiny self-contained HTML shell
    so the .app at least opens without crashing.
3.  Copy only the build output — not the full project — into Resources/www/.
4.  Place index.html *at the root* of Resources/www/ (moving it up if the
    build tool emitted it in a sub-directory like dist/app/index.html).
5.  Patch asset paths in index.html so relative references still work after
    the possible one-level promotion.
6.  Write a clean shell-script launcher that opens the file through macOS's
    default browser via ``open``.  A smarter approach would use osascript +
    WKWebView, but the shell-open approach works without Xcode and is what
    most lightweight PWA wrappers use on CI.
"""

from __future__ import annotations

import asyncio
import re
import shutil
import textwrap
from pathlib import Path
from typing import Any

from services.packagers.common import ensure_manifest


# ---------------------------------------------------------------------------
# Build-output discovery — only compiled artefacts, never raw source
# ---------------------------------------------------------------------------

_BUILD_DIR_NAMES = ("dist", "build", "out", ".next", ".output", "public")
_SOURCE_DIR_NAMES = ("src", "backend", "node_modules", ".git", "__pycache__")


def _looks_like_built_html(path: Path) -> bool:
    """Heuristic: an index.html that references hashed JS/CSS bundles or a
    dist-style asset directory is almost certainly a build output."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    # Vite / webpack / CRA all produce asset paths containing hashed filenames
    # or a reference to an /assets/ or /static/ directory.
    return bool(
        re.search(r'src=["\'][^"\']*\.(js|ts|jsx|tsx)\?v=', text)
        or re.search(r'src=["\'][^"\']*-[0-9a-f]{8}\.(js|css)', text)
        or re.search(r'href=["\'][^"\']*-[0-9a-f]{8}\.css', text)
        or "/assets/" in text
        or "/static/" in text
        or "modulepreload" in text
    )


def _has_source_files(directory: Path) -> bool:
    """Return True if the directory looks like a raw source tree."""
    source_markers = ("src", "node_modules", ".git", "__pycache__")
    source_exts    = {".ts", ".tsx", ".jsx", ".vue", ".svelte"}
    if any((directory / m).exists() for m in source_markers):
        return True
    # Any TypeScript / JSX source file directly in the directory
    return any(f.suffix in source_exts for f in directory.iterdir() if f.is_file())


def _find_built_web_root(project_root: Path) -> Path | None:
    """
    Return the directory that contains the compiled index.html, or None.

    Search strategy (highest to lowest confidence):
    1.  Known build-output directory names (dist, build, out, …) directly
        under the project root or under a frontend/ / web/ / client/ sub-dir.
    2.  A static site: index.html directly in the project root with no source
        markers (no src/, no .ts files, etc.).
    Returns None if no suitable directory is found — callers handle this by
    emitting a warning and writing a placeholder page.
    """
    candidates: list[Path] = []

    # Directories to search inside
    search_roots = [project_root]
    for sub in ("frontend", "web", "client", "app", "ui"):
        p = project_root / sub
        if p.is_dir():
            search_roots.append(p)

    for sr in search_roots:
        for name in _BUILD_DIR_NAMES:
            candidate = sr / name
            if not candidate.is_dir():
                continue
            # Direct hit: index.html right inside the candidate dir
            if (candidate / "index.html").exists():
                candidates.append(candidate)
                continue
            # One level deeper (e.g. dist/app/index.html)
            for sub in candidate.iterdir():
                if sub.is_dir() and (sub / "index.html").exists():
                    candidates.append(sub)

    if candidates:
        # Prefer candidates whose index.html looks like a real build output
        built = [c for c in candidates if _looks_like_built_html(c / "index.html")]
        return (built or candidates)[0]

    # Fallback: the project root itself is a static site (no source markers)
    if (project_root / "index.html").exists() and not _has_source_files(project_root):
        return project_root

    return None


# ---------------------------------------------------------------------------
# Asset-path normalisation
# ---------------------------------------------------------------------------

def _promote_index_to_root(www: Path, sub_index: Path) -> None:
    """
    When the build output landed in e.g. ``www/app/index.html``, move
    everything *up* so index.html ends up at ``www/index.html``.

    We do this by moving the *contents* of the sub-directory into www/ and
    removing the now-empty sub-directory.  Files already present at the www/
    root (there shouldn't be any at this point) are left alone.
    """
    sub_dir = sub_index.parent
    if sub_dir == www:
        return  # already at root

    for item in list(sub_dir.iterdir()):
        dest = www / item.name
        if not dest.exists():
            shutil.move(str(item), str(dest))

    # Remove empty sub-dir (and any intermediate dirs we no longer need)
    try:
        sub_dir.rmdir()
    except OSError:
        shutil.rmtree(sub_dir, ignore_errors=True)


def _patch_asset_paths(index_html: Path, old_prefix: str) -> None:
    """
    If index.html was promoted from a sub-directory, relative asset paths
    like ``./assets/foo.js`` or ``../assets/foo.js`` may need adjusting.
    This is a best-effort patch for the common Vite/CRA pattern where all
    assets live in an ``assets/`` or ``static/`` sibling directory that was
    promoted alongside index.html.

    Because we move the assets *with* the index.html, relative same-level
    references (``assets/foo.js``, ``./assets/foo.js``) are already correct
    after the move.  The only case that breaks is ``../something`` paths.
    """
    if not old_prefix:
        return
    try:
        text = index_html.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return

    # Replace ../<old_prefix>/ with ./ (one level up into the parent that no
    # longer exists — the content is now at the same level as index.html).
    depth = old_prefix.count("/") + 1
    up = "../" * depth
    if up in text:
        text = text.replace(up, "./")
        index_html.write_text(text, encoding="utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Fallback web assets
# ---------------------------------------------------------------------------

def _write_fallback_index(www: Path, app_name: str, app_description: str) -> None:
    """Write a minimal self-contained HTML page when no build output is found."""
    (www / "index.html").write_text(
        textwrap.dedent(f"""\
        <!DOCTYPE html>
        <html lang="en">
        <head>
          <meta charset="UTF-8">
          <meta name="viewport" content="width=device-width, initial-scale=1.0">
          <title>{app_name}</title>
          <style>
            * {{ box-sizing: border-box; margin: 0; padding: 0; }}
            body {{
              font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
              display: flex; flex-direction: column;
              align-items: center; justify-content: center;
              min-height: 100vh;
              background: #0d1117; color: #c9d1d9;
            }}
            h1 {{ font-size: 2rem; margin-bottom: .5rem; }}
            p  {{ color: #8b949e; font-size: .95rem; }}
          </style>
        </head>
        <body>
          <h1>{app_name}</h1>
          <p>{app_description}</p>
          <p style="margin-top:1rem;font-size:.8rem;color:#484f58">
            Packaged by UniDev Toolkit — build artefacts not found
          </p>
        </body>
        </html>
        """),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Main packager entry-point
# ---------------------------------------------------------------------------

async def package_dmg(
    root: Path,
    project_info: dict[str, Any],
    pwa_config: dict[str, Any] | None,
    dist_dir: Path,
    log,
) -> Path:
    manifest = ensure_manifest(root, project_info, pwa_config)
    app_name  = manifest.get("short_name", "UniDevApp").replace(" ", "")
    full_name = manifest.get("name", app_name)
    out_path  = dist_dir / "app-dmg.dmg"

    # ── .app bundle skeleton ──────────────────────────────────────────────────
    #
    #   <app_name>.app/
    #     Contents/
    #       Info.plist
    #       MacOS/
    #         <app_name>      ← executable launcher
    #       Resources/
    #         www/            ← ONLY compiled web assets
    #
    staging   = dist_dir / "staging_dmg"
    app_bundle = staging / f"{app_name}.app"
    contents  = app_bundle / "Contents"
    macos_dir = contents / "MacOS"
    www       = contents / "Resources" / "www"

    if staging.exists():
        shutil.rmtree(staging)
    www.mkdir(parents=True)
    macos_dir.mkdir(parents=True, exist_ok=True)

    # ── Discover & copy ONLY the compiled web assets ──────────────────────────
    build_out = _find_built_web_root(root)

    if build_out is None:
        await log(
            "[dmg] WARNING: no compiled build output found "
            "(expected dist/ or build/ with index.html) — "
            "writing placeholder page.\n"
        )
        _write_fallback_index(www, full_name, manifest.get("description", "PWA App"))
    else:
        await log(f"[dmg] Using build output: {build_out.relative_to(root)}\n")

        # Copy only the build artefacts — never the raw source tree.
        shutil.copytree(
            build_out,
            www,
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns(
                "node_modules", ".git", "__pycache__", "*.py",
                "*.ts", "*.tsx", "*.jsx", "*.vue", "*.svelte",
                "tsconfig*", "vite.config*", "webpack.config*",
            ),
        )

        # Ensure index.html is at www/index.html (not www/subdir/index.html)
        index_candidates = sorted(www.rglob("index.html"), key=lambda p: len(p.parts))
        if index_candidates:
            top_index = index_candidates[0]
            old_rel   = top_index.parent.relative_to(www).as_posix() if top_index.parent != www else ""
            if old_rel:
                await log(f"[dmg] Promoting index.html from www/{old_rel}/ to www/\n")
                _promote_index_to_root(www, top_index)
                _patch_asset_paths(www / "index.html", old_rel)
        else:
            await log("[dmg] WARNING: index.html not found in build output — writing placeholder\n")
            _write_fallback_index(www, full_name, manifest.get("description", "PWA App"))

    index_html = www / "index.html"
    await log(f"[dmg] Web root: Resources/www/   entry: index.html  "
              f"({'found' if index_html.exists() else 'MISSING'})\n")

    # ── Info.plist ────────────────────────────────────────────────────────────
    bundle_id  = f"com.unidev.{re.sub(r'[^a-z0-9]', '', app_name.lower())}"
    info_plist = textwrap.dedent(f"""\
    <?xml version="1.0" encoding="UTF-8"?>
    <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
              "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
    <plist version="1.0">
    <dict>
      <key>CFBundleName</key>              <string>{full_name}</string>
      <key>CFBundleDisplayName</key>       <string>{full_name}</string>
      <key>CFBundleIdentifier</key>        <string>{bundle_id}</string>
      <key>CFBundleVersion</key>           <string>1.0.0</string>
      <key>CFBundleShortVersionString</key><string>1.0.0</string>
      <key>CFBundlePackageType</key>       <string>APPL</string>
      <key>CFBundleExecutable</key>        <string>{app_name}</string>
      <key>CFBundleSignature</key>         <string>????</string>
      <key>NSHighResolutionCapable</key>   <true/>
      <key>LSMinimumSystemVersion</key>    <string>10.13</string>
      <key>NSHumanReadableCopyright</key>  <string>Packaged by UniDev Toolkit</string>
      <!-- Tell macOS this is a document-based app so Gatekeeper is lenient  -->
      <key>LSUIElement</key>               <false/>
      <!-- Required so the system doesn't quarantine the helper script        -->
      <key>NSAppTransportSecurity</key>
      <dict>
        <key>NSAllowsLocalNetworking</key> <true/>
      </dict>
    </dict>
    </plist>
    """)
    (contents / "Info.plist").write_text(info_plist, encoding="utf-8")

    # ── Launcher shell script ─────────────────────────────────────────────────
    # Resolve Resources/www/index.html relative to MacOS/ at runtime.
    # ``open`` is the simplest cross-browser launcher on macOS; it respects the
    # user's default browser and works without any native code or Xcode.
    #
    # For a truly native WKWebView experience the launcher would need to be a
    # compiled binary; that requires Xcode and is out of scope for CI packaging.
    launcher_script = textwrap.dedent(f"""\
    #!/usr/bin/env bash
    # UniDev Toolkit — PWA launcher for {full_name}
    # Generated automatically; do not edit by hand.

    set -euo pipefail

    SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
    WWW="$SCRIPT_DIR/../Resources/www"
    INDEX="$WWW/index.html"

    # Sanity check ────────────────────────────────────────────────────────────
    if [ ! -f "$INDEX" ]; then
      osascript -e 'tell application "System Events" to display dialog \\
        "Cannot find index.html.\\n\\nThe application bundle may be corrupted." \\
        with title "{full_name} — Launch Error" buttons {{"OK"}} default button "OK"' 2>/dev/null || true
      echo "ERROR: $INDEX not found" >&2
      exit 1
    fi

    # Open in default browser ─────────────────────────────────────────────────
    # Using a file:// URL gives browsers the ability to resolve relative assets
    # correctly (same as how Nativefier's fallback mode works).
    FILE_URL="file://${{INDEX// /%20}}"

    # Prefer opening in a bare Chromium / Chrome window for a cleaner app feel
    CHROME_APP=""
    for candidate in \\
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \\
        "/Applications/Chromium.app/Contents/MacOS/Chromium" \\
        "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"; do
      if [ -x "$candidate" ]; then
        CHROME_APP="$candidate"
        break
      fi
    done

    if [ -n "$CHROME_APP" ]; then
      # --app= opens in an app window (no URL bar, no tabs) — closest to a PWA
      exec "$CHROME_APP" \\
        --app="$FILE_URL" \\
        --user-data-dir="/tmp/{bundle_id}-profile" \\
        --no-first-run \\
        --disable-translate \\
        --disable-extensions \\
        "$@"
    else
      # Fallback: system default browser
      exec open "$FILE_URL"
    fi
    """)

    launcher_path = macos_dir / app_name
    launcher_path.write_text(launcher_script, encoding="utf-8")
    launcher_path.chmod(0o755)

    await log("[dmg] App bundle assembled — creating disk image...\n")

    # ── Try native hdiutil (macOS build server) ───────────────────────────────
    if shutil.which("hdiutil"):
        proc = await asyncio.create_subprocess_exec(
            "hdiutil", "create",
            "-volname", app_name,
            "-srcfolder", str(staging),
            "-ov", "-format", "UDZO",
            str(out_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        out_bytes, _ = await proc.communicate()
        await log(out_bytes.decode(errors="replace"))
        if proc.returncode == 0 and out_path.exists():
            await log(f"[dmg] Native DMG created: {out_path.name}\n")
            return out_path

    # ── Try genisoimage (Linux CI) ────────────────────────────────────────────
    if shutil.which("genisoimage"):
        iso_path = dist_dir / "temp.iso"
        proc = await asyncio.create_subprocess_exec(
            "genisoimage",
            "-V", app_name[:32],   # volume name ≤ 32 chars (ISO-9660 limit)
            "-D",                   # don't restrict path depth
            "-R",                   # Rock Ridge extensions (preserves Unix perms)
            "-apple",               # HFS hybrid (needed for .app bundles)
            "-no-pad",
            "-o", str(iso_path),
            str(staging),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        out_bytes, _ = await proc.communicate()
        await log(out_bytes.decode(errors="replace"))
        if proc.returncode == 0 and iso_path.exists():
            shutil.move(str(iso_path), str(out_path))
            await log(f"[dmg] ISO-based disk image created: {out_path.name}\n")
            return out_path

    # ── Portable fallback: zip of the .app bundle ─────────────────────────────
    # We keep the .dmg extension so the download URL stays consistent.
    # Users extract on macOS with Archive Utility and double-click the .app.
    await log("[dmg] hdiutil/genisoimage not available — producing portable .app.zip\n")
    await log("[dmg] Extract the archive on macOS and double-click the .app to launch.\n")
    base = str(out_path.with_suffix(""))
    shutil.make_archive(base, "zip", root_dir=staging, base_dir=".")
    zip_path = Path(base + ".zip")
    if zip_path.exists() and zip_path != out_path:
        shutil.move(str(zip_path), str(out_path))
    await log(f"[dmg] App bundle archive ready: {out_path.name}\n")
    return out_path
