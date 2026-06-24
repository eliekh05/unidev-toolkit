from __future__ import annotations

import asyncio
import shutil
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from services.build_service import (
    analyze_local_path,
    analyze_remote,
    analyze_upload,
    get_available_targets,
    run_build,
)
from services.converter import convert_file, is_binary_ext, is_conversion_supported
from services.format_registry import (
    detect_extension,
    get_all_extensions,
    get_category,
    get_conversion_targets,
    get_monaco_language,
    load_formats,
)
from services.build_log import add_handler
from services.terminal import TerminalSession


# ──────────────────────────────────────────────────────────────────────────────
# Lifespan – background tasks
# ──────────────────────────────────────────────────────────────────────────────
@asynccontextmanager
async def _lifespan(_app: FastAPI):
    # Refresh format catalogue from Wikipedia in the background (non-blocking)
    loop = asyncio.get_event_loop()
    try:
        from services.format_scraper import refresh_formats
        loop.run_in_executor(None, refresh_formats)
    except Exception:
        pass  # format_scraper is optional; offline deploy still works
    yield


app = FastAPI(title="UniDev Toolkit", version="1.1.0", lifespan=_lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

WORKSPACE = Path(__import__("tempfile").gettempdir()) / "unidev_workspace"
WORKSPACE.mkdir(parents=True, exist_ok=True)

UPLOADS: dict[str, Path] = {}
terminal_sessions: dict[str, TerminalSession] = {}
_ws_broadcast: set[WebSocket] = set()


async def broadcast_terminal(text: str) -> None:
    dead: list[WebSocket] = []
    for ws in list(_ws_broadcast):
        try:
            await ws.send_text(text)
        except Exception:
            dead.append(ws)
    for ws in dead:
        _ws_broadcast.discard(ws)


add_handler(broadcast_terminal)


# ──────────────────────────────────────────────────────────────────────────────
# Request models
# ──────────────────────────────────────────────────────────────────────────────
class AnalyzeRequest(BaseModel):
    source_type: str
    url: str | None = None
    local_path: str | None = None
    upload_id: str | None = None
    token: str | None = None


class BuildRequest(BaseModel):
    source_type: str
    url: str | None = None
    local_path: str | None = None
    upload_id: str | None = None
    token: str | None = None
    target: str
    pwa_config: dict | None = None


async def _resolve_project(req: AnalyzeRequest | BuildRequest) -> tuple[Path, dict]:
    if req.source_type == "upload":
        if not req.upload_id or req.upload_id not in UPLOADS:
            raise HTTPException(400, "upload_id required — upload a project archive first")
        root = UPLOADS[req.upload_id]
        from services.project_analyzer import detect_project_type
        return root, detect_project_type(root)
    if req.source_type == "local":
        if not req.local_path:
            raise HTTPException(400, "local_path required")
        return analyze_local_path(req.local_path)
    if not req.url:
        raise HTTPException(400, "url required")
    return await analyze_remote(req.url, req.token)


# ──────────────────────────────────────────────────────────────────────────────
# Routes
# ──────────────────────────────────────────────────────────────────────────────
@app.get("/api/health")
async def health():
    return {"status": "ok", "version": "1.1.0"}


@app.get("/api/formats")
async def formats():
    data = load_formats()
    return {
        "extensions": get_all_extensions(),
        "categories": data["categories"],
        "monaco_languages": data.get("monaco_languages", {}),
    }


@app.get("/api/formats/detect")
async def detect_format(filename: str):
    ext = detect_extension(filename)
    return {
        "extension": ext,
        "category": get_category(ext),
        "conversion_targets": get_conversion_targets(ext),
        "monaco_language": get_monaco_language(ext),
        "is_binary": is_binary_ext(ext),
    }


@app.post("/api/build/upload")
async def upload_project(file: UploadFile = File(...)):
    content = await file.read()
    if len(content) > 100 * 1024 * 1024:
        raise HTTPException(400, "Archive must be under 100 MB")
    try:
        root, info = analyze_upload(content, file.filename or "project.zip")
    except ValueError as e:
        raise HTTPException(400, str(e))
    uid = str(uuid.uuid4())
    UPLOADS[uid] = root
    return {"upload_id": uid, "project": info, "available_targets": get_available_targets(info)}


@app.post("/api/convert")
async def convert(file: UploadFile = File(...), target_ext: str = Form(...)):
    content = await file.read()
    source_ext = detect_extension(file.filename or "file.txt")
    if not is_conversion_supported(source_ext, target_ext):
        raise HTTPException(400, f"Conversion .{source_ext} → .{target_ext} is not supported")
    try:
        result_bytes, out_name = convert_file(content, source_ext, target_ext, file.filename or "")
        out_path = WORKSPACE / out_name
        out_path.write_bytes(result_bytes)
        # Tell the browser whether to expect binary so it can show a preview
        is_bin = is_binary_ext(target_ext)
        media = "application/octet-stream"
        if target_ext in ("html", "htm"):
            media = "text/html"
        elif target_ext in ("json",):
            media = "application/json"
        resp = FileResponse(path=out_path, filename=out_name, media_type=media)
        resp.headers["X-Is-Binary"] = "1" if is_bin else "0"
        resp.headers["X-Source-Ext"] = source_ext
        resp.headers["X-Target-Ext"] = target_ext
        return resp
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/convert/text")
async def convert_text(body: dict):
    content = body.get("content", "").encode("utf-8")
    source_ext = body.get("source_ext", "txt")
    target_ext = body.get("target_ext", "txt")
    filename = body.get("filename", f"file.{source_ext}")
    if not is_conversion_supported(source_ext, target_ext):
        raise HTTPException(400, f"Conversion .{source_ext} → .{target_ext} is not supported")
    try:
        result_bytes, out_name = convert_file(content, source_ext, target_ext, filename)
        binary = is_binary_ext(target_ext)
        return {
            "content": result_bytes.decode("utf-8", errors="replace") if not binary else "",
            "filename": out_name,
            "binary": binary,
            "size": len(result_bytes),
        }
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/build/analyze")
async def analyze_build(req: AnalyzeRequest):
    try:
        root, info = await _resolve_project(req)
        return {"project": info, "available_targets": get_available_targets(info), "root": str(root)}
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except RuntimeError as e:
        raise HTTPException(400, str(e))


@app.post("/api/build/run")
async def build_run(req: BuildRequest):
    try:
        root, info = await _resolve_project(req)
        if req.target not in get_available_targets(info):
            raise HTTPException(400, f"Target .{req.target} not available for this project")
        logs: list[str] = []
        package_path: Path | None = None
        async for line in run_build(root, info, req.target, req.pwa_config):
            if line.startswith("__PACKAGE__:"):
                package_path = Path(line.split(":", 1)[1])
            else:
                logs.append(line)
        if package_path and package_path.exists():
            dest = WORKSPACE / package_path.name
            shutil.copy2(package_path, dest)
            return {
                "success": True,
                "logs": "".join(logs),
                "download_url": f"/api/build/download/{package_path.name}",
                "filename": package_path.name,
            }
        return {"success": False, "logs": "".join(logs), "detail": "Package was not created"}
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except RuntimeError as e:
        raise HTTPException(400, str(e))


@app.get("/api/build/download/{filename}")
async def download_package(filename: str):
    path = WORKSPACE / filename
    if not path.exists():
        raise HTTPException(404, "Package not found")
    return FileResponse(path, filename=filename)


@app.post("/api/editor/save")
async def editor_save(body: dict):
    content = body.get("content", "")
    filename = body.get("filename", "file.txt")
    ext = detect_extension(filename)
    path = WORKSPACE / filename
    path.write_text(content, encoding="utf-8")
    return {"saved": True, "path": str(path), "extension": ext, "language": get_monaco_language(ext)}


# ──────────────────────────────────────────────────────────────────────────────
# WebSocket terminal
# ──────────────────────────────────────────────────────────────────────────────
@app.websocket("/ws/terminal")
async def terminal_ws(websocket: WebSocket):
    await websocket.accept()
    _ws_broadcast.add(websocket)
    session_id = str(id(websocket))
    session = TerminalSession()
    read_task: asyncio.Task | None = None

    try:
        try:
            session.start(str(WORKSPACE))
        except OSError:
            await websocket.send_text(
                "\r\n\x1b[33mPTY unavailable — build logs still stream here.\x1b[0m\r\n"
            )

        terminal_sessions[session_id] = session

        async def reader():
            async for chunk in session.read_output():
                await websocket.send_text(chunk)

        read_task = asyncio.create_task(reader())

        while True:
            data = await websocket.receive_text()
            if data.startswith('{"type":"resize"'):
                import json as _json
                msg = _json.loads(data)
                session.resize(msg.get("cols", 80), msg.get("rows", 24))
            elif data.startswith('{"type":"write"'):
                import json as _json
                msg = _json.loads(data)
                session.write(msg.get("data", ""))
            else:
                session.write(data)

    except WebSocketDisconnect:
        pass
    finally:
        _ws_broadcast.discard(websocket)
        if read_task:
            read_task.cancel()
        session.close()
        terminal_sessions.pop(session_id, None)


# ──────────────────────────────────────────────────────────────────────────────
# Static frontend (served last so API routes take priority)
# ──────────────────────────────────────────────────────────────────────────────
STATIC_DIR = Path(__file__).parent.parent / "frontend" / "dist"
if STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
