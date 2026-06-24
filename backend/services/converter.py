"""
converter.py  –  bidirectional file conversion for UniDev Toolkit

Supported conversion families
──────────────────────────────
Images   : PNG ↔ JPG/JPEG/GIF/BMP/WEBP/ICO/TIFF/PPM/PGM/PBM
Audio    : any ↔ any  (via ffmpeg – graceful error when unavailable)
Video    : any ↔ any  (via ffmpeg – graceful error when unavailable)
Data     : JSON ↔ YAML  /  JSON ↔ XML  /  CSV ↔ TSV  /  CSV ↔ JSON
Docs     : MD → HTML  /  HTML → MD  /  TXT ↔ MD
Code     : any code → highlighted HTML  /  code → TXT  /  code → MD
           code ↔ code passthrough (commented stub – explicit, not silent)
PDF      : PDF → TXT  /  TXT/MD → PDF
"""
from __future__ import annotations

import csv
import io
import json
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import yaml
from PIL import Image
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import TextLexer, get_lexer_by_name, guess_lexer
from pygments.util import ClassNotFound

# ──────────────────────────────────────────────────────────────────────────────
# Extension sets
# ──────────────────────────────────────────────────────────────────────────────
IMAGE_EXTS = {"png", "jpg", "jpeg", "gif", "bmp", "webp", "ico", "tiff", "tif", "ppm", "pgm", "pbm"}
AUDIO_EXTS = {"mp3", "wav", "flac", "ogg", "oga", "aac", "m4a", "wma", "aiff", "aif", "opus", "amr"}
VIDEO_EXTS = {"mp4", "avi", "mkv", "mov", "wmv", "flv", "webm", "m4v", "mpeg", "mpg", "3gp", "ogv", "ts"}
CODE_EXTS = {
    "py", "js", "ts", "java", "c", "cpp", "go", "rs", "swift", "kt", "rb", "php",
    "cs", "lua", "sh", "bash", "zsh", "fish", "css", "scss", "sass", "less",
    "sql", "vue", "svelte", "dart", "scala", "r", "m", "mm", "hs", "ex", "exs",
    "erl", "elm", "clj", "cljs", "fs", "fsx", "ml", "mli", "nim", "zig", "v",
    "vhd", "vhdl", "sv", "sol", "tf", "hcl", "groovy", "pl", "pm", "ps1",
}
TEXT_DATA_EXTS = {
    "json", "yaml", "yml", "xml", "csv", "tsv", "md", "markdown",
    "html", "htm", "txt", "toml", "ini", "env", "conf", "cfg",
}

# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────
def _json_to_yaml(text: str) -> str:
    return yaml.dump(json.loads(text), default_flow_style=False, allow_unicode=True)

def _yaml_to_json(text: str) -> str:
    return json.dumps(yaml.safe_load(text), indent=2, ensure_ascii=False)

def _json_to_xml(text: str, root_tag: str = "root") -> str:
    data = json.loads(text)
    def build(parent: ET.Element, key: str, value: Any) -> None:
        child = ET.SubElement(parent, str(key))
        if isinstance(value, dict):
            for k, v in value.items():
                build(child, k, v)
        elif isinstance(value, list):
            for i, item in enumerate(value):
                build(child, f"item_{i}", item)
        else:
            child.text = str(value) if value is not None else ""
    root = ET.Element(root_tag)
    if isinstance(data, dict):
        for k, v in data.items():
            build(root, k, v)
    else:
        build(root, "value", data)
    return ET.tostring(root, encoding="unicode", xml_declaration=False)

def _xml_to_json(text: str) -> str:
    root = ET.fromstring(text)
    def parse(node: ET.Element) -> Any:
        children = list(node)
        if not children:
            return node.text or ""
        result: dict[str, Any] = {}
        for child in children:
            val = parse(child)
            if child.tag in result:
                existing = result[child.tag]
                if not isinstance(existing, list):
                    result[child.tag] = [existing]
                result[child.tag].append(val)
            else:
                result[child.tag] = val
        return result
    return json.dumps(parse(root), indent=2, ensure_ascii=False)

def _csv_to_json(text: str, delimiter: str = ",") -> str:
    rows = list(csv.DictReader(io.StringIO(text), delimiter=delimiter))
    return json.dumps(rows, indent=2)

def _json_to_csv(text: str) -> str:
    data = json.loads(text)
    if not isinstance(data, list) or not data:
        raise ValueError("JSON must be an array of objects to convert to CSV")
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=list(data[0].keys()))
    writer.writeheader()
    writer.writerows(data)
    return output.getvalue()

def _csv_to_tsv(text: str) -> str:
    reader = csv.reader(io.StringIO(text))
    output = io.StringIO()
    writer = csv.writer(output, delimiter="\t")
    for row in reader:
        writer.writerow(row)
    return output.getvalue()

def _tsv_to_csv(text: str) -> str:
    reader = csv.reader(io.StringIO(text), delimiter="\t")
    output = io.StringIO()
    writer = csv.writer(output)
    for row in reader:
        writer.writerow(row)
    return output.getvalue()

def _md_to_html(text: str) -> str:
    try:
        import markdown  # type: ignore
        body = markdown.markdown(text, extensions=["fenced_code", "tables", "toc"])
    except ImportError:
        # Minimal fallback
        lines = text.splitlines()
        parts: list[str] = []
        in_code = False
        for line in lines:
            if line.startswith("```"):
                in_code = not in_code
                parts.append("<pre><code>" if in_code else "</code></pre>")
            elif in_code:
                parts.append(line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
            elif line.startswith("# "):   parts.append(f"<h1>{line[2:]}</h1>")
            elif line.startswith("## "):  parts.append(f"<h2>{line[3:]}</h2>")
            elif line.startswith("### "): parts.append(f"<h3>{line[4:]}</h3>")
            elif line.strip() == "":     parts.append("<br/>")
            else:                        parts.append(f"<p>{line}</p>")
        body = "\n".join(parts)
    return f"<!DOCTYPE html><html><head><meta charset='utf-8'></head><body>\n{body}\n</body></html>"

def _html_to_md(text: str) -> str:
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(text, "lxml")
        for tag in soup(["script", "style"]):
            tag.decompose()
        body = soup.body or soup
        lines: list[str] = []
        for el in body.descendants:
            if not hasattr(el, "name"):
                continue
            if el.name == "h1":   lines.append(f"# {el.get_text(strip=True)}")
            elif el.name == "h2": lines.append(f"## {el.get_text(strip=True)}")
            elif el.name == "h3": lines.append(f"### {el.get_text(strip=True)}")
            elif el.name == "p":
                t = el.get_text(strip=True)
                if t: lines.append(t)
            elif el.name == "pre": lines.append(f"```\n{el.get_text()}\n```")
            elif el.name == "li": lines.append(f"- {el.get_text(strip=True)}")
        return "\n\n".join(lines) if lines else body.get_text("\n", strip=True)
    except Exception:
        return text

def _code_to_highlighted_html(text: str, ext: str) -> str:
    try:
        lexer = get_lexer_by_name(ext)
    except ClassNotFound:
        try:
            lexer = guess_lexer(text)
        except ClassNotFound:
            lexer = TextLexer()
    return highlight(text, lexer, HtmlFormatter(full=True, style="monokai"))

def _convert_image(content: bytes, target_ext: str) -> bytes:
    img = Image.open(io.BytesIO(content))
    te = target_ext.lower()
    if te in ("jpg", "jpeg") and img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    elif te == "ico":
        img = img.resize((256, 256), Image.Resampling.LANCZOS)
    out = io.BytesIO()
    fmt_map = {
        "jpg": "JPEG", "jpeg": "JPEG", "png": "PNG", "gif": "GIF",
        "bmp": "BMP", "webp": "WEBP", "ico": "ICO", "tiff": "TIFF",
        "tif": "TIFF", "ppm": "PPM", "pgm": "PGM", "pbm": "PBM",
    }
    fmt = fmt_map.get(te, te.upper())
    kwargs: dict[str, Any] = {}
    if fmt == "JPEG":
        kwargs["quality"] = 90
    img.save(out, format=fmt, **kwargs)
    return out.getvalue()

def _ffmpeg_available() -> bool:
    return bool(shutil.which("ffmpeg"))

def _ffmpeg_convert(content: bytes, source_ext: str, target_ext: str) -> bytes:
    if not _ffmpeg_available():
        raise ValueError(
            f"ffmpeg is not installed on this server — "
            f"audio/video conversion (.{source_ext} → .{target_ext}) is unavailable. "
            "Install ffmpeg to enable this feature."
        )
    with tempfile.NamedTemporaryFile(suffix=f".{source_ext}", delete=False) as src:
        src.write(content)
        src_path = src.name
    out_path = src_path + f".out.{target_ext}"
    try:
        proc = subprocess.run(
            ["ffmpeg", "-y", "-i", src_path, out_path],
            capture_output=True,
            timeout=180,
        )
        if proc.returncode != 0:
            raise ValueError(
                f"ffmpeg conversion failed:\n{proc.stderr.decode(errors='replace')[-800:]}"
            )
        return Path(out_path).read_bytes()
    finally:
        Path(src_path).unlink(missing_ok=True)
        Path(out_path).unlink(missing_ok=True)

def _pdf_to_text(content: bytes) -> str:
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(content))
        return "\n\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception as e:
        raise ValueError(f"PDF text extraction failed: {e}") from e

def _text_to_pdf(text: str) -> bytes:
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.pdfgen import canvas as rl_canvas
        buf = io.BytesIO()
        c = rl_canvas.Canvas(buf, pagesize=letter)
        y = 750
        for line in text.splitlines():
            if y < 50:
                c.showPage()
                y = 750
            c.drawString(50, y, line[:110])
            y -= 14
        c.save()
        return buf.getvalue()
    except ImportError:
        raise ValueError("PDF generation requires the reportlab package (pip install reportlab)")

def _code_passthrough_with_comment(text: str, source_ext: str, target_ext: str) -> str:
    """
    Cross-language code conversion is not automatically possible in general.
    This produces a clearly-labelled stub so the user knows exactly what they got.
    """
    border = "=" * 70
    header = (
        f"// {border}\n"
        f"// NOTICE: Structural code translation .{source_ext} → .{target_ext}\n"
        f"// Automatic cross-language conversion is not supported.\n"
        f"// The original source is preserved below as reference.\n"
        f"// Please adapt manually for the target language.\n"
        f"// {border}\n\n"
    )
    commented = "\n".join(
        (f"// {line}" if line.strip() else "") for line in text.splitlines()
    )
    return header + commented


# ──────────────────────────────────────────────────────────────────────────────
# Dispatch table
# ──────────────────────────────────────────────────────────────────────────────
CONVERTERS: dict[tuple[str, str], Any] = {
    ("json",     "yaml"):     _json_to_yaml,
    ("json",     "yml"):      _json_to_yaml,
    ("yaml",     "json"):     _yaml_to_json,
    ("yml",      "json"):     _yaml_to_json,
    ("yaml",     "yml"):      lambda t: t,
    ("yml",      "yaml"):     lambda t: t,
    ("json",     "xml"):      _json_to_xml,
    ("xml",      "json"):     _xml_to_json,
    ("csv",      "json"):     _csv_to_json,
    ("json",     "csv"):      _json_to_csv,
    ("csv",      "tsv"):      _csv_to_tsv,
    ("tsv",      "csv"):      _tsv_to_csv,
    ("md",       "html"):     _md_to_html,
    ("markdown", "html"):     _md_to_html,
    ("html",     "md"):       _html_to_md,
    ("html",     "markdown"): _html_to_md,
    ("html",     "txt"):      lambda t: _html_to_md(t),
    ("txt",      "md"):       lambda t: t,
    ("md",       "txt"):      lambda t: t,
}


# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────
def is_conversion_supported(source_ext: str, target_ext: str) -> bool:
    s = source_ext.lower().lstrip(".")
    t = target_ext.lower().lstrip(".")
    if s == t:
        return True
    if s in IMAGE_EXTS and t in IMAGE_EXTS:
        return True
    if (s, t) in CONVERTERS:
        return True
    if s in AUDIO_EXTS and t in AUDIO_EXTS:
        return True          # ffmpeg availability checked at convert time
    if s in VIDEO_EXTS and t in VIDEO_EXTS:
        return True
    if s == "pdf" and t in ("txt", "md"):
        return True
    if s in ("txt", "md") and t == "pdf":
        return True
    if t == "html" and s not in ("html", "htm"):
        return True          # code/md/plain → highlighted HTML
    if t in ("txt", "md") and s in ("html", "htm"):
        return True
    if s in CODE_EXTS and t in CODE_EXTS:
        return True          # passthrough stub
    if s in CODE_EXTS and t in ("txt", "md", "html"):
        return True
    return False


def get_supported_targets(source_ext: str) -> list[str]:
    s = source_ext.lower().lstrip(".")
    candidates: set[str] = set()

    if s in IMAGE_EXTS:       candidates.update(IMAGE_EXTS)
    if s in AUDIO_EXTS:       candidates.update(AUDIO_EXTS)
    if s in VIDEO_EXTS:       candidates.update(VIDEO_EXTS)
    if s in CODE_EXTS:
        candidates.update(CODE_EXTS)
        candidates.update(["txt", "md", "html"])
    if s in TEXT_DATA_EXTS:   candidates.update(TEXT_DATA_EXTS)

    for src, tgt in CONVERTERS:
        if src == s: candidates.add(tgt)
        if tgt == s: candidates.add(src)

    if s == "pdf":  candidates.update(["txt", "md"])
    candidates.add("pdf")
    candidates.discard(s)
    return sorted(t for t in candidates if is_conversion_supported(s, t))


def is_binary_ext(ext: str) -> bool:
    """Return True when the conversion output should be treated as binary (not UTF-8 text)."""
    ext = ext.lower().lstrip(".")
    return ext in IMAGE_EXTS | AUDIO_EXTS | VIDEO_EXTS | {"pdf", "ico", "wasm", "bin"}


def convert_file(
    content: bytes, source_ext: str, target_ext: str, filename: str = ""
) -> tuple[bytes, str]:
    s = source_ext.lower().lstrip(".")
    t = target_ext.lower().lstrip(".")
    base = Path(filename).stem if filename else "converted"

    if s == t:
        return content, f"{base}.{t}"

    if not is_conversion_supported(s, t):
        raise ValueError(f"Conversion from .{s} to .{t} is not supported")

    # ── Binary conversions ────────────────────────────────────────────────────
    if s in IMAGE_EXTS and t in IMAGE_EXTS:
        return _convert_image(content, t), f"{base}.{t}"

    if s in AUDIO_EXTS and t in AUDIO_EXTS:
        return _ffmpeg_convert(content, s, t), f"{base}.{t}"

    if s in VIDEO_EXTS and t in VIDEO_EXTS:
        return _ffmpeg_convert(content, s, t), f"{base}.{t}"

    if s == "pdf" and t in ("txt", "md"):
        return _pdf_to_text(content).encode("utf-8"), f"{base}.{t}"

    if s in ("txt", "md") and t == "pdf":
        return _text_to_pdf(content.decode("utf-8", errors="replace")), f"{base}.pdf"

    # ── Text conversions ──────────────────────────────────────────────────────
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        text = content.decode("latin-1", errors="replace")

    key = (s, t)
    if key in CONVERTERS:
        result = CONVERTERS[key](text)
        return (result if isinstance(result, bytes) else result.encode("utf-8")), f"{base}.{t}"

    if t == "html" and s not in ("html", "htm"):
        result = _md_to_html(text) if s in ("md", "markdown") else _code_to_highlighted_html(text, s)
        return result.encode("utf-8"), f"{base}.{t}"

    if t in ("txt", "md") and s in ("html", "htm"):
        result = _html_to_md(text) if t == "md" else text
        return result.encode("utf-8"), f"{base}.{t}"

    if s in CODE_EXTS and t in CODE_EXTS:
        return _code_passthrough_with_comment(text, s, t).encode("utf-8"), f"{base}.{t}"

    if s in CODE_EXTS and t in ("txt", "md"):
        return text.encode("utf-8"), f"{base}.{t}"

    raise ValueError(f"Conversion from .{s} to .{t} is not supported")
