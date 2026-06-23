import zipfile
from pathlib import Path
from typing import Any

from services.packagers.common import copy_assets_to_staging, ensure_manifest, find_build_output, find_web_root


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
    out_path = dist_dir / "app.msix"

    staging = dist_dir / "staging_msix"
    copy_assets_to_staging(staging, build_out)

    await log("[msix] Building Open Packaging Convention (MSIX) bundle...\n")

    appx_manifest = f"""<?xml version="1.0" encoding="utf-8"?>
<Package xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10"
         xmlns:uap="http://schemas.microsoft.com/appx/manifest/uap/windows10"
         IgnorableNamespaces="uap">
  <Identity Name="{pkg_name}" Publisher="{publisher}" Version="{version}" />
  <Properties>
    <DisplayName>{manifest.get('name', name)}</DisplayName>
    <PublisherDisplayName>UniDev Toolkit</PublisherDisplayName>
    <Description>PWA packaged by UniDev Toolkit</Description>
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
        Square44x44Logo="Assets\\Square44x44Logo.png"/>
    </Application>
  </Applications>
  <Capabilities><Capability Name="internetClient"/></Capabilities>
</Package>"""

    content_types = """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="xml" ContentType="text/xml"/>
  <Default Extension="html" ContentType="text/html"/>
  <Default Extension="js" ContentType="application/javascript"/>
  <Default Extension="css" ContentType="text/css"/>
  <Default Extension="png" ContentType="image/png"/>
  <Default Extension="json" ContentType="application/json"/>
  <Default Extension="webmanifest" ContentType="application/manifest+json"/>
</Types>"""

    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("AppxManifest.xml", appx_manifest)
        zf.writestr("Assets/Square150x150Logo.png", _placeholder_png())
        zf.writestr("Assets/Square44x44Logo.png", _placeholder_png())
        for f in staging.rglob("*"):
            if f.is_file():
                zf.write(f, f"www/{f.relative_to(staging).as_posix()}")
        zf.writestr("www/manifest.webmanifest", __import__("json").dumps(manifest, indent=2))

    await log(f"[msix] Package ready: {out_path.name}\n")
    return out_path


def _placeholder_png() -> bytes:
    from PIL import Image
    import io
    img = Image.new("RGBA", (150, 150), (88, 166, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
