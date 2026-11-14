import logging
import os
import shutil
import tempfile
import threading
from functools import lru_cache
from pathlib import Path
from typing import Literal

import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from deface.centerface import CenterFace
from deface.deface import image_detect, video_detect


logger = logging.getLogger(__name__)

IMAGE_TYPES = {
    ".bmp": "image/bmp",
    ".jpeg": "image/jpeg",
    ".jpg": "image/jpeg",
    ".png": "image/png",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".webp": "image/webp",
}
VIDEO_TYPES = {".avi", ".m4v", ".mkv", ".mov", ".mp4", ".webm"}
MAX_UPLOAD_BYTES = int(os.getenv("DEFACE_MAX_UPLOAD_MB", "1024")) * 1024 * 1024
PROCESSING_LOCK = threading.Lock()

app = FastAPI(title="deface API", version="1.0.0")


@lru_cache(maxsize=1)
def get_detector():
    return CenterFace(in_shape=None, backend="auto")


def save_upload(upload: UploadFile, path: Path):
    size = 0
    with path.open("wb") as output:
        while chunk := upload.file.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                raise HTTPException(status_code=413, detail="Uploaded file is too large")
            output.write(chunk)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/anonymize", response_class=FileResponse)
def anonymize(
    file: UploadFile = File(...),
    threshold: float = Form(0.2, ge=0.0, le=1.0),
    mask_scale: float = Form(1.3, ge=1.0, le=3.0),
    mosaic_size: int = Form(20, ge=2, le=200),
    keep_audio: bool = Form(False),
    replacewith: Literal["mosaic", "blur", "solid", "none"] = Form("mosaic"),
):
    suffix = Path(file.filename or "").suffix.lower()
    if suffix in IMAGE_TYPES:
        media_type = "image"
        output_suffix = suffix
        output_content_type = IMAGE_TYPES[suffix]
    elif suffix in VIDEO_TYPES:
        media_type = "video"
        output_suffix = ".mp4"
        output_content_type = "video/mp4"
    else:
        supported = ", ".join(sorted(IMAGE_TYPES.keys() | VIDEO_TYPES))
        raise HTTPException(status_code=415, detail=f"Unsupported file type. Supported extensions: {supported}")

    temp_dir = Path(tempfile.mkdtemp(prefix="deface-api-"))
    input_path = temp_dir / f"input{suffix}"
    output_path = temp_dir / f"anonymized{output_suffix}"

    try:
        save_upload(file, input_path)
        with PROCESSING_LOCK:
            detector = get_detector()
            if media_type == "image":
                image_detect(
                    ipath=str(input_path),
                    opath=str(output_path),
                    centerface=detector,
                    threshold=threshold,
                    replacewith=replacewith,
                    mask_scale=mask_scale,
                    ellipse=False,
                    draw_scores=False,
                    enable_preview=False,
                    keep_metadata=False,
                    mosaicsize=mosaic_size,
                )
            else:
                video_detect(
                    ipath=str(input_path),
                    opath=str(output_path),
                    centerface=detector,
                    threshold=threshold,
                    enable_preview=False,
                    cam=False,
                    nested=False,
                    replacewith=replacewith,
                    mask_scale=mask_scale,
                    ellipse=False,
                    draw_scores=False,
                    ffmpeg_config={"codec": "libx264", "macro_block_size": 1},
                    keep_audio=keep_audio,
                    mosaicsize=mosaic_size,
                    disable_progress_output=True,
                )
        if not output_path.is_file():
            raise ValueError("No output was produced")
    except HTTPException:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise
    except Exception as exc:
        shutil.rmtree(temp_dir, ignore_errors=True)
        logger.exception("Failed to anonymize %s", file.filename)
        raise HTTPException(status_code=422, detail="Media processing failed") from exc

    stem = Path(file.filename or "media").stem
    return FileResponse(
        output_path,
        media_type=output_content_type,
        filename=f"{stem}_anonymized{output_suffix}",
        background=BackgroundTask(shutil.rmtree, temp_dir, ignore_errors=True),
    )


def run():
    uvicorn.run("deface.api:app", host="0.0.0.0", port=8000)
