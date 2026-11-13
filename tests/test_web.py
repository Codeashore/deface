import asyncio
from pathlib import Path

import pytest

gr = pytest.importorskip("gradio")

from deface import api
from deface.web import create_ui


@pytest.fixture
def process():
    demo = create_ui(api.app)
    return next(fn.fn for fn in demo.fns.values() if fn.fn.__name__ == "process")


@pytest.mark.parametrize("filename", ["photo.png", "clip.mov"])
def test_web_uses_api_and_caches_download(process, monkeypatch, tmp_path, filename):
    calls = []

    def detect(**kwargs):
        calls.append(kwargs)
        Path(kwargs["opath"]).write_bytes(b"processed-media")

    monkeypatch.setattr(api, "get_detector", lambda: object())
    monkeypatch.setattr(api, "image_detect", detect)
    monkeypatch.setattr(api, "video_detect", detect)
    source = tmp_path / filename
    source.write_bytes(b"input-media")

    result = asyncio.run(process(str(source), 24, 0.3, 1.4, True))
    download = Path(result[2]["value"])

    assert download.read_bytes() == b"processed-media"
    assert download.name == f"{source.stem}_anonymized{'.mp4' if source.suffix == '.mov' else '.png'}"
    assert result[0]["visible"] is (source.suffix == ".png")
    assert result[1]["visible"] is (source.suffix == ".mov")
    assert calls[0]["replacewith"] == "mosaic"
    assert calls[0]["mosaicsize"] == 24
    assert calls[0]["threshold"] == 0.3
    assert not Path(calls[0]["opath"]).exists()


def test_web_reports_api_processing_failure(process, monkeypatch, tmp_path):
    def fail(**kwargs):
        raise ValueError("Invalid image")

    monkeypatch.setattr(api, "get_detector", lambda: object())
    monkeypatch.setattr(api, "image_detect", fail)
    source = tmp_path / "bad.png"
    source.write_bytes(b"invalid")

    with pytest.raises(gr.Error, match="处理失败"):
        asyncio.run(process(str(source), 20, 0.2, 1.3, False))


def test_web_requires_upload(process):
    with pytest.raises(gr.Error, match="请先上传"):
        asyncio.run(process(None, 20, 0.2, 1.3, False))
