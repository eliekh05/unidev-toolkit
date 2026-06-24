import json
from functools import lru_cache
from pathlib import Path

DATA_PATH = Path(__file__).parent.parent / "data" / "formats.json"

# Dotfiles and special names with no extension → language mapping
_SPECIAL_NAMES: dict[str, str] = {
    "dockerfile": "dockerfile",
    "makefile": "makefile",
    "gemfile": "ruby",
    "rakefile": "ruby",
    "vagrantfile": "ruby",
    "procfile": "plaintext",
    "brewfile": "ruby",
    "podfile": "ruby",
    ".gitignore": "plaintext",
    ".gitattributes": "plaintext",
    ".gitmodules": "ini",
    ".editorconfig": "ini",
    ".env": "plaintext",
    ".env.local": "plaintext",
    ".env.example": "plaintext",
    ".eslintrc": "json",
    ".babelrc": "json",
    ".prettierrc": "json",
    ".stylelintrc": "json",
    ".npmrc": "ini",
    ".nvmrc": "plaintext",
    ".rvmrc": "plaintext",
    ".htaccess": "plaintext",
    ".bashrc": "shell",
    ".bash_profile": "shell",
    ".zshrc": "shell",
    ".profile": "shell",
}

# Extension → Monaco language id (extends what's in formats.json)
_EXTRA_LANGUAGES: dict[str, str] = {
    "py": "python", "pyw": "python", "pyi": "python",
    "js": "javascript", "mjs": "javascript", "cjs": "javascript",
    "ts": "typescript", "tsx": "typescript",
    "jsx": "javascript",
    "java": "java", "kt": "kotlin", "kts": "kotlin",
    "c": "c", "h": "c",
    "cpp": "cpp", "cxx": "cpp", "cc": "cpp", "hpp": "cpp", "hxx": "cpp",
    "cs": "csharp",
    "go": "go",
    "rs": "rust",
    "rb": "ruby", "rake": "ruby",
    "php": "php",
    "swift": "swift",
    "scala": "scala",
    "r": "r", "rmd": "r",
    "lua": "lua",
    "dart": "dart",
    "sh": "shell", "bash": "shell", "zsh": "shell", "fish": "shell",
    "ps1": "powershell", "psm1": "powershell",
    "html": "html", "htm": "html", "xhtml": "html",
    "css": "css", "scss": "scss", "sass": "scss", "less": "less",
    "json": "json", "jsonc": "json", "json5": "json",
    "yaml": "yaml", "yml": "yaml",
    "xml": "xml", "svg": "xml", "plist": "xml", "xsd": "xml",
    "md": "markdown", "markdown": "markdown", "mdx": "markdown",
    "sql": "sql",
    "toml": "ini",
    "ini": "ini", "cfg": "ini", "conf": "ini",
    "dockerfile": "dockerfile",
    "graphql": "graphql", "gql": "graphql",
    "tf": "hcl", "hcl": "hcl",
    "sol": "sol",
    "vue": "html",
    "svelte": "html",
    "hs": "haskell",
    "fs": "fsharp", "fsx": "fsharp",
    "ex": "elixir", "exs": "elixir",
    "erl": "erlang", "hrl": "erlang",
    "clj": "clojure", "cljs": "clojure",
    "elm": "elm",
    "nim": "plaintext",
    "zig": "plaintext",
    "v": "verilog", "sv": "verilog", "vhd": "plaintext", "vhdl": "plaintext",
    "tex": "latex", "bib": "latex",
    "txt": "plaintext", "text": "plaintext", "log": "plaintext",
    "csv": "plaintext", "tsv": "plaintext",
    "env": "plaintext",
    "groovy": "groovy",
    "pl": "perl", "pm": "perl",
}


@lru_cache(maxsize=1)
def load_formats() -> dict:
    with open(DATA_PATH, encoding="utf-8") as f:
        return json.load(f)


def get_all_extensions() -> list[str]:
    data = load_formats()
    extensions: set[str] = set()
    for cat in data["categories"].values():
        extensions.update(cat["extensions"])
    return sorted(extensions)


def detect_extension(filename: str) -> str:
    """
    Return the normalised extension for *filename*.

    Handles:
    • Normal files: photo.png → png
    • Dotfiles:     .gitignore → gitignore  (kept as-is for lookup)
    • Special names: Dockerfile → dockerfile
    • No extension: README → txt
    """
    name = filename.strip()
    lower = name.lower()

    # Special whole-name matches (return without leading dot for dotfiles)
    if lower in _SPECIAL_NAMES:
        return lower.lstrip(".")

    # Dotfiles like .gitignore, .env
    if lower.startswith(".") and "." not in lower[1:]:
        return lower[1:]  # strip the leading dot

    parts = lower.rsplit(".", 1)
    if len(parts) == 2 and parts[1]:
        return parts[1]
    return "txt"


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
    ext = ext.lower().lstrip(".")
    if ext in _EXTRA_LANGUAGES:
        return _EXTRA_LANGUAGES[ext]
    data = load_formats()
    return data.get("monaco_languages", {}).get(ext, "plaintext")


def get_build_targets(project_type: str) -> list[str]:
    data = load_formats()
    return data.get("build_targets", {}).get(project_type, data["build_targets"]["unknown"])
