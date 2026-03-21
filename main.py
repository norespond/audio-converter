from fastapi import FastAPI, File, UploadFile, BackgroundTasks, HTTPException, Form
from fastapi.responses import FileResponse
import os
import uuid
import subprocess
import asyncio

app = FastAPI()

UPLOAD_DIR = "/tmp/uploads"
OUTPUT_DIR = "/tmp/outputs"
FFMPEG_PATH = "ffmpeg"
SUPPORTED_OUTPUTS = {
    'wav': 'audio/wav',
    'mp3': 'audio/mpeg',
    'ogg': 'audio/ogg',
    'flac': 'audio/flac',
    'm4a': 'audio/mp4',
    'aac': 'audio/aac',
    'opus': 'audio/opus',
}
MAX_SIZE = 40 * 1024 * 1024
MAX_CONCURRENT = 2

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)
semaphore = asyncio.Semaphore(MAX_CONCURRENT)


async def save_file_with_limit(upload_file: UploadFile, path: str):
    size = 0
    with open(path, "wb") as f:
        while chunk := await upload_file.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_SIZE:
                raise HTTPException(status_code=413, detail="文件超过 40MB 限制")
            f.write(chunk)


def cleanup(paths):
    for p in paths:
        if os.path.exists(p):
            os.remove(p)


def run_ffmpeg(input_path, output_path, fmt, bitrate=None, sample_rate=None, channels=None):
    base_cmd = [FFMPEG_PATH, "-y", "-i", input_path]

    # 用户参数
    if sample_rate:
        base_cmd += ["-ar", str(sample_rate)]
    if channels:
        base_cmd += ["-ac", str(channels)]
    if bitrate:
        base_cmd += ["-b:a", bitrate]

    codec_map = {
        'wav': ['-c:a', 'pcm_s16le'],
        'mp3': ['-c:a', 'libmp3lame'],
        'ogg': ['-c:a', 'libvorbis'],
        'flac': ['-c:a', 'flac'],
        'm4a': ['-c:a', 'aac'],
        'aac': ['-c:a', 'aac'],
        'opus': ['-c:a', 'libopus'],
    }
    codec = codec_map.get(fmt, [])
    cmd = base_cmd + codec + [output_path]

    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)

# ========= API =========
@app.post("/convert/")
async def convert(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    format: str = Form('wav'),
    bitrate: str = Form(None),
    sample_rate: int = Form(None),
    channels: int = Form(None)
):
    ext = os.path.splitext(file.filename)[-1].lower()
    if not file.content_type.startswith('audio/'):
        raise HTTPException(status_code=400, detail="不支持的输入文件类型")

    fmt = format.lower()
    if fmt not in SUPPORTED_OUTPUTS:
        raise HTTPException(status_code=400, detail=f"不支持的输出格式: {fmt}")

    uid = str(uuid.uuid4())
    input_path = os.path.join(UPLOAD_DIR, f"{uid}{ext}")
    output_path = os.path.join(OUTPUT_DIR, f"{uid}.{fmt}")

    await save_file_with_limit(file, input_path)

    async with semaphore:
        try:
            run_ffmpeg(input_path, output_path, fmt, bitrate, sample_rate, channels)
        except subprocess.TimeoutExpired:
            cleanup([input_path])
            raise HTTPException(status_code=500, detail="转换超时")
        except subprocess.CalledProcessError:
            cleanup([input_path])
            raise HTTPException(status_code=500, detail="音频转换失败")

    background_tasks.add_task(cleanup, [input_path, output_path])

    return FileResponse(
        output_path,
        media_type=SUPPORTED_OUTPUTS.get(fmt, 'application/octet-stream'),
        filename=f"{os.path.splitext(file.filename)[0]}.{fmt}"
    )


@app.get("/ui")
def ui():
    index_path = os.path.join(os.path.dirname(__file__), "static", "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path, media_type="text/html")
    raise HTTPException(status_code=404, detail="UI not found")


@app.get("/")
def health():
    return {"status": "ok"}