import json
from pathlib import Path
from functools import lru_cache

DATA_PATH = Path(__file__).parent.parent / "data" / "formats.json"


@lru_cache(maxsize=1)
def load_formats() -> dict:
    with open(DATA_PATH) as f:
        return json.load(f)


def get_all_extensions() -> list[str]:
    data = load_formats()
    extensions: set[str] = set()
    for cat in data["categories"].values():
        extensions.update(cat["extensions"])
    return sorted(extensions)


def detect_extension(filename: str) -> str:
    name = filename.lower().strip()
    if name == "dockerfile":
        return "dockerfile"
    if name.startswith("."):
        return name[1:]
    parts = name.rsplit(".", 1)
    return parts[-1] if len(parts) > 1 else "txt"


def get_category(ext: str) -> str | None:
    data = load_formats()
    ext = ext.lower().lstrip(".")
    for cat_id, cat in data["categories"].items():
        if ext in cat["extensions"]:
            return cat_id
    return None


def get_conversion_targets(ext: str) -> list[str]:
    from services.converter import get_supported_targets
    return get_supported_targets(ext)


def get_monaco_language(ext: str) -> str:
    data = load_formats()
    ext = ext.lower().lstrip(".")
    return data.get("monaco_languages", {}).get(ext, "plaintext")


def get_build_targets(project_type: str) -> list[str]:
    data = load_formats()
    return data.get("build_targets", {}).get(project_type, data["build_targets"]["unknown"])
