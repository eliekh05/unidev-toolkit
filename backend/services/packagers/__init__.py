from pathlib import Path
from typing import Any

from services.packagers.apk import package_apk
from services.packagers.dmg import package_dmg
from services.packagers.ipa import package_ipa
from services.packagers.msix import package_msix

PACKAGERS = {
    "apk": package_apk,
    "ipa": package_ipa,
    "dmg": package_dmg,
    "msix": package_msix,
}


async def create_package(
    root: Path,
    project_info: dict[str, Any],
    target: str,
    pwa_config: dict[str, Any] | None,
    dist_dir: Path,
    log,
) -> Path:
    packager = PACKAGERS.get(target)
    if not packager:
        raise RuntimeError(f"No packager for .{target}")
    return await packager(root, project_info, pwa_config, dist_dir, log)
