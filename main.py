from fastapi import FastAPI, File, UploadFile, BackgroundTasks, HTTPException
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
AUDIO_EXTS = ('.ogg', '.ape', '.flac', '.mp3', '.wav', '.m4a')
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


def run_ffmpeg(input_path, output_path):
    cmd = [
        FFMPEG_PATH,
        "-y",
        "-i", input_path,
        "-ar", "16000",
        "-ac", "1",
        output_path
    ]

    subprocess.run(
        cmd,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=60  # 防止卡死
    )


# ========= API =========
@app.post("/convert_wav/")
async def convert_wav(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    ext = os.path.splitext(file.filename)[-1].lower()
    if ext not in AUDIO_EXTS:
        raise HTTPException(status_code=400, detail="不支持的音频格式")

    uid = str(uuid.uuid4())
    input_path = os.path.join(UPLOAD_DIR, f"{uid}{ext}")
    output_path = os.path.join(OUTPUT_DIR, f"{uid}.wav")

    await save_file_with_limit(file, input_path)

    async with semaphore:  # 控制并发
        try:
            run_ffmpeg(input_path, output_path)
        except subprocess.TimeoutExpired:
            cleanup([input_path])
            raise HTTPException(status_code=500, detail="转换超时")
        except subprocess.CalledProcessError:
            cleanup([input_path])
            raise HTTPException(status_code=500, detail="音频转换失败")

    background_tasks.add_task(cleanup, [input_path, output_path])

    return FileResponse(
        output_path,
        media_type="audio/wav",
        filename=f"{os.path.splitext(file.filename)[0]}.wav"
    )


@app.get("/")
def health():
    return {"status": "ok"}