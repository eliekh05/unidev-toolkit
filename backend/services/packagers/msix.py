import io
import json
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


async def package_msix(
    root: Path,
    project_info: dict[str, Any],
    pwa_config: dict[str, Any] | None,
    dist_dir: Path,
    log,
) -> Path:
    web_root = find_web_root(root)
    build_out = find_build_output(web_root) or web_root
    manifest = ensure_manifest(root, project_info, pwa_config)
    name = manifest.get("short_name", "UniDevApp").replace(" ", "")
    pkg_name = f"com.unidev.{name.lower()}"
    publisher = "CN=UniDev Toolkit"
    version = "1.0.0.0"
    out_path = dist_dir / "app-msix.msix"

    staging = dist_dir / "staging_msix"
    copy_assets_to_staging(staging, build_out)

    # Discover the actual index.html path inside the copied assets
    index_rel = find_index_html(staging)  # e.g. "index.html" or "dist/index.html"
    if index_rel is None:
        await log("[msix] WARNING: index.html not found — writing placeholder\n")
        (staging / "index.html").write_text(
            "<html><body><h1>App</h1><p>index.html not found.</p></body></html>",
            encoding="utf-8",
        )
        index_rel = "index.html"

    await log(f"[msix] Entry point: www/{index_rel}\n")
    await log("[msix] Building Open Packaging Convention (MSIX) bundle...\n")

    # The MSIX host reads UniDevStartFile from AppxManifest.xml to know which
    # file to load in the WebView2 control, so the path is always dynamic.
    appx_manifest = f"""<?xml version="1.0" encoding="utf-8"?>
<Package xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10"
         xmlns:uap="http://schemas.microsoft.com/appx/manifest/uap/windows10"
         IgnorableNamespaces="uap">
  <Identity Name="{pkg_name}" Publisher="{publisher}" Version="{version}" />
  <Properties>
    <DisplayName>{manifest.get('name', name)}</DisplayName>
    <PublisherDisplayName>UniDev Toolkit</PublisherDisplayName>
    <Description>PWA packaged by UniDev Toolkit</Description>
    <!-- UniDevStartFile is read by the WebView2 launcher at runtime -->
    <uap:SupportedUsers>single</uap:SupportedUsers>
  </Properties>
  <Resources><Resource Language="en-us"/></Resources>
  <Dependencies>
    <TargetDeviceFamily Name="Windows.Desktop" MinVersion="10.0.17763.0" MaxVersionTested="10.0.22621.0"/>
  </Dependencies>
  <Applications>
    <Application Id="App" Executable="UniDevHost.exe" EntryPoint="Windows.FullTrustApplication">
      <uap:VisualElements DisplayName="{manifest.get('name', name)}"
        Description="UniDev packaged app" BackgroundColor="{manifest.get('theme_color', '#0d1117')}"
        Square150x150Logo="Assets\\Square150x150Logo.png"
        Square44x44Logo="Assets\\Square44x44Logo.png">
        <!-- StartPage points to the detected entry point inside www/ -->
        <uap:DefaultTile/>
      </uap:VisualElements>
      <uap:ApplicationContentUriRules>
        <uap:Rule Match="ms-appx-web:///www/{index_rel}" Type="include"/>
      </uap:ApplicationContentUriRules>
    </Application>
  </Applications>
  <Capabilities><Capability Name="internetClient"/></Capabilities>
</Package>"""

    # Additional config file so a generic WebView2 host launcher can find the
    # entry point without parsing the full AppxManifest XML.
    unidev_config = json.dumps({
        "start_file": f"www/{index_rel}",
        "app_name": manifest.get("name", name),
        "theme_color": manifest.get("theme_color", "#0d1117"),
    }, indent=2)

    content_types = """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="xml" ContentType="text/xml"/>
  <Default Extension="html" ContentType="text/html"/>
  <Default Extension="htm" ContentType="text/html"/>
  <Default Extension="js" ContentType="application/javascript"/>
  <Default Extension="mjs" ContentType="application/javascript"/>
  <Default Extension="css" ContentType="text/css"/>
  <Default Extension="png" ContentType="image/png"/>
  <Default Extension="svg" ContentType="image/svg+xml"/>
  <Default Extension="json" ContentType="application/json"/>
  <Default Extension="webmanifest" ContentType="application/manifest+json"/>
  <Default Extension="woff" ContentType="font/woff"/>
  <Default Extension="woff2" ContentType="font/woff2"/>
  <Default Extension="ttf" ContentType="font/ttf"/>
  <Default Extension="ico" ContentType="image/x-icon"/>
  <Default Extension="webp" ContentType="image/webp"/>
</Types>"""

    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("AppxManifest.xml", appx_manifest)
        zf.writestr("unidev.config.json", unidev_config)
        zf.writestr("Assets/Square150x150Logo.png", _placeholder_png(150))
        zf.writestr("Assets/Square44x44Logo.png", _placeholder_png(44))

        # Pack every file from staging into www/<original-relative-path>
        for f in staging.rglob("*"):
            if f.is_file():
                arc_path = "www/" + f.relative_to(staging).as_posix()
                zf.write(f, arc_path)

        zf.writestr("www/manifest.webmanifest", json.dumps(manifest, indent=2))

    await log(f"[msix] Package ready: {out_path.name}\n")
    return out_path


def _placeholder_png(size: int = 150) -> bytes:
    try:
        from PIL import Image
        img = Image.new("RGBA", (size, size), (88, 166, 255, 255))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except ImportError:
        # Minimal valid 1×1 PNG if Pillow is absent
        return (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
            b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
            b"\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
        )
