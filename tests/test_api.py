from io import BytesIO
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from deface import api


client = TestClient(api.app)


def test_health():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_anonymize_image(monkeypatch):
    calls = []

    def fake_image_detect(**kwargs):
        calls.append(kwargs)
        Path(kwargs["opath"]).write_bytes(b"processed-image")

    monkeypatch.setattr(api, "get_detector", lambda: object())
    monkeypatch.setattr(api, "image_detect", fake_image_detect)

    response = client.post(
        "/anonymize",
        files={"file": ("face.jpg", b"image", "image/jpeg")},
        data={"mosaic_size": "24"},
    )

    assert response.status_code == 200
    assert response.content == b"processed-image"
    assert response.headers["content-type"] == "image/jpeg"
    assert calls[0]["replacewith"] == "mosaic"
    assert calls[0]["mosaicsize"] == 24


def test_anonymize_video_returns_mp4(monkeypatch):
    calls = []

    def fake_video_detect(**kwargs):
        calls.append(kwargs)
        Path(kwargs["opath"]).write_bytes(b"processed-video")

    monkeypatch.setattr(api, "get_detector", lambda: object())
    monkeypatch.setattr(api, "video_detect", fake_video_detect)

    response = client.post(
        "/anonymize",
        files={"file": ("clip.mkv", b"video", "video/x-matroska")},
        data={"keep_audio": "true"},
    )

    assert response.status_code == 200
    assert response.content == b"processed-video"
    assert response.headers["content-type"] == "video/mp4"
    assert calls[0]["replacewith"] == "mosaic"
    assert calls[0]["keep_audio"] is True
    assert calls[0]["ffmpeg_config"]["macro_block_size"] == 1


def test_rejects_unsupported_file():
    response = client.post(
        "/anonymize",
        files={"file": ("notes.txt", b"text", "text/plain")},
    )

    assert response.status_code == 415


def test_rejects_invalid_mosaic_size():
    response = client.post(
        "/anonymize",
        files={"file": ("face.png", b"image", "image/png")},
        data={"mosaic_size": "1"},
    )

    assert response.status_code == 422


@pytest.mark.parametrize("mode", ["mosaic", "blur", "solid", "none"])
@pytest.mark.parametrize("filename", ["face.jpg", "clip.mp4"])
def test_anonymize_modes(monkeypatch, mode, filename):
    calls = []

    def detect(**kwargs):
        calls.append(kwargs)
        Path(kwargs["opath"]).write_bytes(b"processed")

    monkeypatch.setattr(api, "get_detector", lambda: object())
    monkeypatch.setattr(api, "image_detect", detect)
    monkeypatch.setattr(api, "video_detect", detect)
    response = client.post(
        "/anonymize", files={"file": (filename, b"media")}, data={"replacewith": mode},
    )

    assert response.status_code == 200
    assert calls[0]["replacewith"] == mode


@pytest.mark.parametrize("mode", ["img", "unknown"])
def test_rejects_unsupported_mode(mode):
    response = client.post(
        "/anonymize", files={"file": ("face.jpg", b"image")}, data={"replacewith": mode},
    )

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "replacewith"]


def test_rgba_png_preserves_transparency(monkeypatch):
    class Detector:
        def __call__(self, frame, threshold):
            return np.array([[4, 4, 20, 20, 0.9]]), None

    monkeypatch.setattr(api, 'get_detector', lambda: Detector())
    original = np.random.default_rng(0).integers(0, 256, (24, 24, 4), dtype=np.uint8)
    original[4:20, 4:20, 3] = 255
    source = BytesIO()
    Image.fromarray(original).save(source, format='PNG')

    response = client.post(
        '/anonymize',
        files={'file': ('screenshot.png', source.getvalue(), 'image/png')},
        data={'mosaic_size': '5', 'mask_scale': '1'},
    )

    assert response.status_code == 200
    assert response.headers['content-type'] == 'image/png'
    result = np.array(Image.open(BytesIO(response.content)))
    np.testing.assert_array_equal(result[:, :, 3], original[:, :, 3])
    assert np.any(result[4:20, 4:20, :3] != original[4:20, 4:20, :3])
