from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from conversion import (
    ALLOWED_BITRATES,
    ALLOWED_CHANNELS,
    ALLOWED_RETENTION_MINUTES,
    ALLOWED_SAMPLE_RATES,
    DEFAULT_FAMILY,
    DEFAULT_RETENTION_MINUTES,
    build_download_filename,
    build_ffmpeg_command,
    convert_document_file,
    convert_image_file,
    get_family,
    infer_family_from_content_type,
    infer_family_from_filename,
    list_capabilities,
    normalize_format,
    output_media_type,
    parse_option,
)

app = FastAPI()
app.state.retention_tasks = {}

BASE_DIR = Path(__file__).resolve().parent
TEMP_ROOT = Path(tempfile.gettempdir()) / "file-converter"
UPLOAD_DIR = TEMP_ROOT / "uploads"
OUTPUT_DIR = TEMP_ROOT / "outputs"

MAX_SIZE = 40 * 1024 * 1024
MAX_CONCURRENT = 2

BUNDLED_FFMPEG = BASE_DIR / "ffmpeg.exe" if os.name == "nt" else BASE_DIR / "ffmpeg"
FFMPEG_PATH = os.getenv("FFMPEG_PATH") or (
    str(BUNDLED_FFMPEG) if BUNDLED_FFMPEG.exists() else shutil.which("ffmpeg") or "ffmpeg"
)

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
semaphore = asyncio.Semaphore(MAX_CONCURRENT)

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_ts() -> float:
    return utc_now().timestamp()


def to_iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def metadata_path(token: str) -> Path:
    return OUTPUT_DIR / f"{token}.json"


def output_path(token: str, fmt: str) -> Path:
    return OUTPUT_DIR / f"{token}.{fmt}"


async def save_file_with_limit(upload_file: UploadFile, path: Path):
    size = 0
    with path.open("wb") as f:
        while chunk := await upload_file.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_SIZE:
                raise HTTPException(status_code=413, detail="文件超过 40MB 限制")
            f.write(chunk)


def cleanup(paths):
    for p in paths:
        try:
            path = Path(p)
            if path.exists():
                path.unlink()
        except OSError:
            pass


def read_metadata(token: str):
    path = metadata_path(token)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def write_metadata(token: str, metadata: dict):
    metadata_path(token).write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


async def delete_output_record(token: str):
    metadata = read_metadata(token)
    if not metadata:
        return

    cleanup([OUTPUT_DIR / metadata["output_file"], metadata_path(token)])


async def delayed_delete(token: str, expires_at: float):
    delay = max(0.0, expires_at - utc_ts())
    if delay > 0:
        await asyncio.sleep(delay)
    await delete_output_record(token)


def schedule_delayed_delete(token: str, expires_at: float):
    task = asyncio.create_task(delayed_delete(token, expires_at))
    app.state.retention_tasks[token] = task

    def _cleanup_task(_task):
        app.state.retention_tasks.pop(token, None)

    task.add_done_callback(_cleanup_task)
    return task


async def restore_pending_outputs():
    app.state.retention_tasks = {}
    for meta_file in OUTPUT_DIR.glob("*.json"):
        try:
            metadata = json.loads(meta_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            cleanup([meta_file])
            continue

        token = metadata.get("token")
        output_file = metadata.get("output_file")
        expires_at = metadata.get("expires_at")
        if not token or not output_file or not expires_at:
            cleanup([meta_file])
            continue

        output_file_path = OUTPUT_DIR / output_file
        if expires_at <= utc_ts() or not output_file_path.exists():
            cleanup([output_file_path, meta_file])
            continue

        schedule_delayed_delete(token, float(expires_at))


def parse_int_field(value, allowed_values, field_name):
    try:
        return parse_option(value, allowed_values, field_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def assert_supported_content_type(file: UploadFile, family_key: str):
    family = get_family(family_key)
    if not family:
        raise HTTPException(status_code=400, detail=f"不支持的转换类型: {family_key}")

    suffix = Path(file.filename or "").suffix.lower().lstrip(".")
    content_type = file.content_type or ""
    if content_type.startswith(family.accept):
        return

    if suffix and suffix in family.extensions:
        return

    raise HTTPException(status_code=400, detail="上传文件类型与转换类型不匹配")


def serve_page(filename: str):
    path = BASE_DIR / "static" / filename
    if path.exists():
        return FileResponse(path, media_type="text/html")
    raise HTTPException(status_code=404, detail="UI not found")


@app.on_event("startup")
async def on_startup():
    await restore_pending_outputs()


@app.get("/capabilities")
def capabilities():
    return list_capabilities()


@app.post("/convert/")
async def convert(
    file: UploadFile = File(...),
    family: str = Form(""),
    format: str = Form(""),
    bitrate: str = Form(None),
    sample_rate: str = Form(None),
    channels: str = Form(None),
    retention_minutes: str = Form(str(DEFAULT_RETENTION_MINUTES)),
):
    if family:
        family_obj = get_family(family)
        if not family_obj:
            raise HTTPException(status_code=400, detail=f"不支持的转换类型: {family}")
    else:
        family_obj = (
            infer_family_from_content_type(file.content_type)
            or infer_family_from_filename(file.filename)
            or get_family(DEFAULT_FAMILY)
        )

    if not family_obj:
        raise HTTPException(status_code=400, detail="无法识别文件转换类型")

    assert_supported_content_type(file, family_obj.key)

    try:
        fmt = normalize_format(family_obj, format)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    bitrate_kbps = parse_int_field(bitrate, ALLOWED_BITRATES, "比特率")
    sample_rate_value = parse_int_field(sample_rate, ALLOWED_SAMPLE_RATES, "采样率")
    channels_value = parse_int_field(channels, ALLOWED_CHANNELS, "声道")
    retention_minutes_value = parse_int_field(
        retention_minutes,
        ALLOWED_RETENTION_MINUTES,
        "保存时长",
    )
    if retention_minutes_value is None:
        retention_minutes_value = DEFAULT_RETENTION_MINUTES

    if not family_obj.supports_bitrate:
        bitrate_kbps = None
    if not family_obj.supports_sample_rate:
        sample_rate_value = None
    if not family_obj.supports_channels:
        channels_value = None

    uid = str(uuid.uuid4())
    input_suffix = Path(file.filename or "input").suffix.lower() or ".bin"
    input_path = UPLOAD_DIR / f"{uid}{input_suffix}"
    output_file = f"{uid}.{fmt}"
    output_file_path = output_path(uid, fmt)
    download_name = build_download_filename(file.filename, fmt)

    try:
        await save_file_with_limit(file, input_path)
    except HTTPException:
        cleanup([input_path])
        raise
    finally:
        await file.close()

    async with semaphore:
        try:
            if family_obj.key == "image":
                convert_image_file(input_path, output_file_path, fmt)
            elif family_obj.key == "document":
                convert_document_file(input_path, output_file_path, fmt)
            else:
                cmd = build_ffmpeg_command(
                    FFMPEG_PATH,
                    input_path,
                    output_file_path,
                    family_obj.key,
                    fmt,
                    bitrate_kbps,
                    sample_rate_value,
                    channels_value,
                )
                subprocess.run(
                    cmd,
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=600,
                )
        except subprocess.TimeoutExpired:
            cleanup([input_path, output_file_path])
            raise HTTPException(status_code=500, detail="转换超时")
        except subprocess.CalledProcessError:
            cleanup([input_path, output_file_path])
            raise HTTPException(status_code=500, detail="文件转换失败")
        except (ValueError, OSError) as exc:
            cleanup([input_path, output_file_path])
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    cleanup([input_path])

    expires_at = utc_ts() + retention_minutes_value * 60
    metadata = {
        "token": uid,
        "family": family_obj.key,
        "output_file": output_file,
        "download_name": download_name,
        "format": fmt,
        "retention_minutes": retention_minutes_value,
        "created_at": utc_ts(),
        "expires_at": expires_at,
    }
    write_metadata(uid, metadata)
    schedule_delayed_delete(uid, expires_at)

    return {
        "status": "ok",
        "family": family_obj.key,
        "download_url": f"/download/{uid}",
        "download_name": download_name,
        "format": fmt,
        "retention_minutes": retention_minutes_value,
        "expires_at": to_iso(expires_at),
        "expires_in": retention_minutes_value * 60,
    }


@app.get("/download/{token}")
def download(token: str):
    metadata = read_metadata(token)
    if not metadata:
        raise HTTPException(status_code=410, detail="文件已过期或不存在")

    expires_at = float(metadata.get("expires_at", 0))
    if expires_at <= utc_ts():
        output_file = metadata.get("output_file")
        paths = [metadata_path(token)]
        if output_file:
            paths.insert(0, OUTPUT_DIR / output_file)
        cleanup(paths)
        raise HTTPException(status_code=410, detail="文件已过期或不存在")

    file_path = OUTPUT_DIR / metadata["output_file"]
    if not file_path.exists():
        cleanup([metadata_path(token)])
        raise HTTPException(status_code=410, detail="文件已过期或不存在")

    return FileResponse(
        file_path,
        media_type=output_media_type(metadata.get("family", DEFAULT_FAMILY), metadata.get("format", "")),
        filename=metadata.get("download_name", file_path.name),
        headers={"Cache-Control": "no-store"},
    )


@app.get("/ui")
def ui():
    return serve_page("index.html")


@app.get("/")
def home():
    return serve_page("index.html")


@app.get("/audio")
def audio_page():
    return serve_page("audio.html")


@app.get("/video")
def video_page():
    return serve_page("video.html")


@app.get("/image")
def image_page():
    return serve_page("image.html")


@app.get("/document")
def document_page():
    return serve_page("document.html")


@app.get("/health")
def health():
    return {"status": "ok"}
