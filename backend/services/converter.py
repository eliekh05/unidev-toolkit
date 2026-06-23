import asyncio
import io
import csv
import json
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import yaml
from PIL import Image
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_by_name, guess_lexer, TextLexer
from pygments.util import ClassNotFound

IMAGE_EXTS = {"png", "jpg", "jpeg", "gif", "bmp", "webp", "ico", "tiff", "tif", "ppm", "pgm", "pbm"}
AUDIO_EXTS = {"mp3", "wav", "flac", "ogg", "oga", "aac", "m4a", "wma", "aiff", "aif", "opus", "amr"}
VIDEO_EXTS = {"mp4", "avi", "mkv", "mov", "wmv", "flv", "webm", "m4v", "mpeg", "mpg", "3gp", "ogv", "ts"}
CODE_EXTS = {
    "py", "js", "ts", "java", "c", "cpp", "go", "rs", "swift", "kt", "rb", "php", "cs", "lua", "sh",
    "html", "css", "scss", "sass", "less", "sql", "vue", "svelte", "dart", "scala", "r", "m", "mm",
}
TEXT_DATA_EXTS = {"json", "yaml", "yml", "xml", "csv", "tsv", "md", "markdown", "html", "htm", "txt", "toml"}


def _safe_json_loads(text: str) -> Any:
    return json.loads(text)


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
    return ET.tostring(root, encoding="unicode")


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
        return text
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=data[0].keys())
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
    lines = text.splitlines()
    html_lines = ["<!DOCTYPE html>", "<html><head><meta charset='utf-8'><title>Document</title></head><body>"]
    in_code = False
    for line in lines:
        if line.startswith("```"):
            in_code = not in_code
            html_lines.append("<pre><code>" if in_code else "</code></pre>")
            continue
        if in_code:
            html_lines.append(line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
        elif line.startswith("# "):
            html_lines.append(f"<h1>{line[2:]}</h1>")
        elif line.startswith("## "):
            html_lines.append(f"<h2>{line[3:]}</h2>")
        elif line.startswith("### "):
            html_lines.append(f"<h3>{line[4:]}</h3>")
        elif line.strip() == "":
            html_lines.append("<br/>")
        else:
            html_lines.append(f"<p>{line}</p>")
    html_lines.append("</body></html>")
    return "\n".join(html_lines)


def _html_to_md(text: str) -> str:
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(text, "lxml")
        for tag in soup(["script", "style"]):
            tag.decompose()
        body = soup.body or soup
        lines: list[str] = []
        for el in body.descendants:
            if el.name == "h1":
                lines.append(f"# {el.get_text(strip=True)}")
            elif el.name == "h2":
                lines.append(f"## {el.get_text(strip=True)}")
            elif el.name == "h3":
                lines.append(f"### {el.get_text(strip=True)}")
            elif el.name == "p":
                t = el.get_text(strip=True)
                if t:
                    lines.append(t)
            elif el.name == "pre":
                lines.append(f"```\n{el.get_text()}\n```")
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
    if target_ext.lower() in ("jpg", "jpeg") and img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    elif target_ext.lower() == "ico":
        img = img.resize((256, 256), Image.Resampling.LANCZOS)
    out = io.BytesIO()
    fmt_map = {
        "jpg": "JPEG", "jpeg": "JPEG", "png": "PNG", "gif": "GIF", "bmp": "BMP",
        "webp": "WEBP", "ico": "ICO", "tiff": "TIFF", "tif": "TIFF", "ppm": "PPM",
        "pgm": "PGM", "pbm": "PBM",
    }
    fmt = fmt_map.get(target_ext.lower(), target_ext.upper())
    save_kwargs: dict[str, Any] = {}
    if fmt == "JPEG":
        save_kwargs["quality"] = 90
    img.save(out, format=fmt, **save_kwargs)
    return out.getvalue()


def _ffmpeg_convert(content: bytes, source_ext: str, target_ext: str) -> bytes:
    if not shutil.which("ffmpeg"):
        raise ValueError("ffmpeg not installed — audio/video conversion unavailable")
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=f".{source_ext}", delete=False) as src:
        src.write(content)
        src_path = src.name
    out_path = src_path + f".out.{target_ext}"
    try:
        proc = subprocess.run(
            ["ffmpeg", "-y", "-i", src_path, out_path],
            capture_output=True,
            timeout=120,
        )
        if proc.returncode != 0:
            raise ValueError(proc.stderr.decode(errors="replace")[-500:])
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
        raise ValueError(f"PDF extraction failed: {e}") from e


def _text_to_pdf(text: str) -> bytes:
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.pdfgen import canvas
        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=letter)
        y = 750
        for line in text.splitlines():
            if y < 50:
                c.showPage()
                y = 750
            c.drawString(50, y, line[:100])
            y -= 14
        c.save()
        return buf.getvalue()
    except ImportError:
        raise ValueError("PDF generation requires reportlab")


def _code_passthrough_with_comment(text: str, source_ext: str, target_ext: str) -> str:
    header = (
        f"// Converted from .{source_ext} to .{target_ext}\n"
        f"// Cross-language conversion preserves structure as comments.\n"
        f"// Review and adapt manually for production use.\n\n"
    )
    commented = "\n".join(f"// {line}" if line.strip() else "" for line in text.splitlines())
    return header + commented


CONVERTERS: dict[tuple[str, str], Any] = {
    ("json", "yaml"): _json_to_yaml,
    ("json", "yml"): _json_to_yaml,
    ("yaml", "json"): _yaml_to_json,
    ("yml", "json"): _yaml_to_json,
    ("json", "xml"): _json_to_xml,
    ("xml", "json"): _xml_to_json,
    ("csv", "json"): _csv_to_json,
    ("json", "csv"): _json_to_csv,
    ("csv", "tsv"): _csv_to_tsv,
    ("tsv", "csv"): _tsv_to_csv,
    ("md", "html"): _md_to_html,
    ("markdown", "html"): _md_to_html,
    ("html", "md"): _html_to_md,
    ("html", "markdown"): _html_to_md,
    ("html", "txt"): lambda t: _html_to_md(t),
}


def is_conversion_supported(source_ext: str, target_ext: str) -> bool:
    source_ext = source_ext.lower().lstrip(".")
    target_ext = target_ext.lower().lstrip(".")
    if source_ext == target_ext:
        return True
    if source_ext in IMAGE_EXTS and target_ext in IMAGE_EXTS:
        return True
    if (source_ext, target_ext) in CONVERTERS:
        return True
    if source_ext in AUDIO_EXTS and target_ext in AUDIO_EXTS and shutil.which("ffmpeg"):
        return True
    if source_ext in VIDEO_EXTS and target_ext in VIDEO_EXTS and shutil.which("ffmpeg"):
        return True
    if source_ext == "pdf" and target_ext in ("txt", "md"):
        return True
    if source_ext in ("txt", "md") and target_ext == "pdf":
        return True
    if target_ext == "html" and source_ext not in ("html", "htm"):
        return True
    if target_ext in ("txt", "md") and source_ext in ("html", "htm"):
        return True
    if source_ext in CODE_EXTS and target_ext in CODE_EXTS:
        return True
    if source_ext in CODE_EXTS and target_ext in ("txt", "md", "html", "json"):
        return True
    return False


def get_supported_targets(source_ext: str) -> list[str]:
    source_ext = source_ext.lower().lstrip(".")
    candidates: set[str] = set()

    if source_ext in IMAGE_EXTS:
        candidates.update(IMAGE_EXTS)
    if source_ext in AUDIO_EXTS:
        candidates.update(AUDIO_EXTS)
    if source_ext in VIDEO_EXTS:
        candidates.update(VIDEO_EXTS)
    if source_ext in CODE_EXTS:
        candidates.update(CODE_EXTS)
        candidates.update(["txt", "md", "html", "json"])
    if source_ext in TEXT_DATA_EXTS:
        candidates.update(TEXT_DATA_EXTS)

    for src, tgt in CONVERTERS:
        if src == source_ext:
            candidates.add(tgt)
        if tgt == source_ext:
            candidates.add(src)

    if source_ext == "pdf":
        candidates.update(["txt", "md"])
    candidates.add("pdf")

    candidates.discard(source_ext)
    return sorted(t for t in candidates if is_conversion_supported(source_ext, t))


def convert_file(content: bytes, source_ext: str, target_ext: str, filename: str = "") -> tuple[bytes, str]:
    source_ext = source_ext.lower().lstrip(".")
    target_ext = target_ext.lower().lstrip(".")

    if source_ext == target_ext:
        return content, filename or f"output.{target_ext}"

    if not is_conversion_supported(source_ext, target_ext):
        raise ValueError(f"Conversion from .{source_ext} to .{target_ext} is not supported")

    if source_ext in IMAGE_EXTS and target_ext in IMAGE_EXTS:
        return _convert_image(content, target_ext), f"converted.{target_ext}"

    if source_ext in AUDIO_EXTS and target_ext in AUDIO_EXTS:
        return _ffmpeg_convert(content, source_ext, target_ext), f"converted.{target_ext}"

    if source_ext in VIDEO_EXTS and target_ext in VIDEO_EXTS:
        return _ffmpeg_convert(content, source_ext, target_ext), f"converted.{target_ext}"

    if source_ext == "pdf" and target_ext in ("txt", "md"):
        return _pdf_to_text(content).encode("utf-8"), f"converted.{target_ext}"

    if source_ext in ("txt", "md") and target_ext == "pdf":
        text = content.decode("utf-8", errors="replace")
        return _text_to_pdf(text), "converted.pdf"

    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        text = content.decode("latin-1", errors="replace")

    key = (source_ext, target_ext)
    if key in CONVERTERS:
        result = CONVERTERS[key](text)
        if isinstance(result, str):
            return result.encode("utf-8"), f"converted.{target_ext}"

    if target_ext == "html" and source_ext not in ("html", "htm"):
        if source_ext in ("md", "markdown"):
            result = _md_to_html(text)
        else:
            result = _code_to_highlighted_html(text, source_ext)
        return result.encode("utf-8"), f"converted.{target_ext}"

    if target_ext in ("txt", "md") and source_ext in ("html", "htm"):
        result = _html_to_md(text) if target_ext == "md" else text
        return result.encode("utf-8"), f"converted.{target_ext}"

    if source_ext in CODE_EXTS and target_ext in CODE_EXTS:
        return _code_passthrough_with_comment(text, source_ext, target_ext).encode("utf-8"), f"converted.{target_ext}"

    if source_ext in CODE_EXTS and target_ext == "txt":
        return text.encode("utf-8"), "converted.txt"

    raise ValueError(f"Conversion from .{source_ext} to .{target_ext} is not supported")
