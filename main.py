from fastapi import FastAPI, File, UploadFile, BackgroundTasks, HTTPException, Form
from fastapi.responses import FileResponse
import os
import uuid
import subprocess
import asyncio

app = FastAPI()

# ========= 配置 =========
UPLOAD_DIR = "/tmp/uploads"
OUTPUT_DIR = "/tmp/outputs"
FFMPEG_PATH = "ffmpeg"
# 支持的输入/输出扩展名（输出用于验证和 MIME）
AUDIO_EXTS = ('.ogg', '.ape', '.flac', '.mp3', '.wav', '.m4a')
SUPPORTED_OUTPUTS = {
    'wav': 'audio/wav',
    'mp3': 'audio/mpeg',
    'ogg': 'audio/ogg',
    'flac': 'audio/flac',
    'm4a': 'audio/mp4',
    'aac': 'audio/aac',
    'opus': 'audio/opus',
}
MAX_SIZE = 20 * 1024 * 1024  # 建议先限制 20MB
MAX_CONCURRENT = 2  # 最大并发转换数

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

# 并发信号量（防止 CPU 被打爆）
semaphore = asyncio.Semaphore(MAX_CONCURRENT)


# ========= 工具函数 =========
async def save_file_with_limit(upload_file: UploadFile, path: str):
    size = 0
    with open(path, "wb") as f:
        while chunk := await upload_file.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_SIZE:
                raise HTTPException(status_code=413, detail="文件超过 20MB 限制")
            f.write(chunk)


def cleanup(paths):
    for p in paths:
        if os.path.exists(p):
            os.remove(p)


def run_ffmpeg(input_path, output_path, fmt):
    # 根据目标格式选择编码器和参数
    base_cmd = [FFMPEG_PATH, "-y", "-i", input_path]
    # 统一采样率和声道，方便后续处理
    common = ["-ar", "16000", "-ac", "1"]

    fmt = fmt.lower()
    if fmt == 'wav':
        codec = ['-c:a', 'pcm_s16le']
    elif fmt == 'mp3':
        codec = ['-c:a', 'libmp3lame', '-b:a', '192k']
    elif fmt == 'ogg':
        codec = ['-c:a', 'libvorbis', '-b:a', '192k']
    elif fmt == 'flac':
        codec = ['-c:a', 'flac']
    elif fmt in ('m4a', 'aac'):
        codec = ['-c:a', 'aac', '-b:a', '192k']
    elif fmt == 'opus':
        codec = ['-c:a', 'libopus', '-b:a', '128k']
    else:
        codec = []

    cmd = base_cmd + common + codec + [output_path]

    subprocess.run(
        cmd,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=120  # 防止卡死
    )


# ========= API =========
@app.post("/convert/")
async def convert(background_tasks: BackgroundTasks, file: UploadFile = File(...), format: str = Form('wav')):
    # 验证输入是音频并验证输出格式支持
    ext = os.path.splitext(file.filename)[-1].lower()
    if not (file.content_type.startswith('audio/') or ext in AUDIO_EXTS):
        raise HTTPException(status_code=400, detail="不支持的输入文件类型")

    fmt = (format or 'wav').lower()
    if fmt not in SUPPORTED_OUTPUTS:
        raise HTTPException(status_code=400, detail=f"不支持的输出格式: {fmt}")

    uid = str(uuid.uuid4())
    input_path = os.path.join(UPLOAD_DIR, f"{uid}{ext}")
    output_path = os.path.join(OUTPUT_DIR, f"{uid}.{fmt}")

    await save_file_with_limit(file, input_path)

    async with semaphore:  # 控制并发
        try:
            run_ffmpeg(input_path, output_path, fmt)
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