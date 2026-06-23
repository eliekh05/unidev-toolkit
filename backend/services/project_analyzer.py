import json
import re
from pathlib import Path
from typing import Any


PWA_INDICATORS = [
    "manifest.json",
    "manifest.webmanifest",
    "site.webmanifest",
    "sw.js",
    "service-worker.js",
    "workbox-config.js",
]


def detect_pwa(root: Path) -> dict[str, Any]:
    result: dict[str, Any] = {
        "has_pwa": False,
        "manifest": None,
        "manifest_path": None,
        "icons": [],
        "service_worker": None,
        "prompt_enable_pwa": False,
        "missing_fields": [],
    }

    manifest_paths = []
    for pattern in ["**/manifest.json", "**/manifest.webmanifest", "**/site.webmanifest"]:
        manifest_paths.extend(root.glob(pattern))

    for mp in manifest_paths[:1]:
        try:
            data = json.loads(mp.read_text(encoding="utf-8"))
            result["has_pwa"] = True
            result["manifest"] = data
            result["manifest_path"] = str(mp.relative_to(root))
            required = ["name", "short_name", "start_url", "display", "icons"]
            result["missing_fields"] = [f for f in required if f not in data or not data[f]]
            icons = data.get("icons", [])
            for icon in icons:
                icon_path = icon.get("src", "")
                full = root / icon_path.lstrip("/")
                if full.exists():
                    result["icons"].append({"src": icon_path, "sizes": icon.get("sizes"), "exists": True})
                else:
                    result["icons"].append({"src": icon_path, "sizes": icon.get("sizes"), "exists": False})
        except (json.JSONDecodeError, OSError):
            pass

    for sw_name in ["sw.js", "service-worker.js", "serviceWorker.js"]:
        sw_files = list(root.glob(f"**/{sw_name}"))
        if sw_files:
            result["service_worker"] = str(sw_files[0].relative_to(root))
            result["has_pwa"] = True
            break

    if not result["has_pwa"]:
        result["prompt_enable_pwa"] = True

    return result


def detect_project_type(root: Path) -> dict[str, Any]:
    files = {p.name for p in root.rglob("*") if p.is_file()}
    rel_paths = {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()}

    info: dict[str, Any] = {
        "type": "unknown",
        "framework": None,
        "package_manager": None,
        "platforms": [],
        "confidence": 0.5,
    }

    if (root / "package.json").exists():
        info["package_manager"] = "npm"
        try:
            pkg = json.loads((root / "package.json").read_text())
            deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
            if "electron" in deps:
                info["type"] = "electron"
                info["framework"] = "Electron"
                info["confidence"] = 0.95
            elif "react-native" in deps:
                info["type"] = "react-native"
                info["framework"] = "React Native"
            elif "@capacitor/core" in deps:
                info["type"] = "capacitor"
                info["framework"] = "Capacitor"
            elif "cordova" in deps or (root / "config.xml").exists():
                info["type"] = "cordova"
                info["framework"] = "Cordova"
            elif "@tauri-apps/api" in deps:
                info["type"] = "tauri"
                info["framework"] = "Tauri"
            elif "next" in deps:
                info["type"] = "web"
                info["framework"] = "Next.js"
            elif "react" in deps or "vue" in deps or "svelte" in deps:
                info["type"] = "web"
                info["framework"] = deps.get("react") and "React" or deps.get("vue") and "Vue" or "Svelte"
            else:
                info["type"] = "web"
                info["framework"] = "Node.js"
        except (json.JSONDecodeError, OSError):
            pass

    if (root / "pubspec.yaml").exists():
        info["type"] = "flutter"
        info["framework"] = "Flutter"
        info["confidence"] = 0.95

    if (root / "android" / "build.gradle").exists() or (root / "android" / "build.gradle.kts").exists():
        info["platforms"].append("android")
        if info["type"] == "unknown":
            info["type"] = "android-native"

    if any("ios" in p for p in rel_paths) and any(p.endswith("Info.plist") for p in rel_paths):
        info["platforms"].append("ios")
        if info["type"] == "unknown":
            info["type"] = "ios-native"

    if any(p.endswith(".csproj") for p in rel_paths):
        info["type"] = "dotnet"
        info["framework"] = ".NET"
        info["platforms"].append("windows")

    pwa = detect_pwa(root)
    if pwa["has_pwa"] and info["type"] in ("web", "unknown"):
        info["type"] = "pwa"
        info["framework"] = info.get("framework") or "PWA"

    info["pwa"] = pwa
    return info
