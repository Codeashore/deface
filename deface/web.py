import logging
import tempfile
import time
from pathlib import Path

import gradio as gr
import httpx
import uvicorn

from deface.api import IMAGE_TYPES, MAX_UPLOAD_BYTES, VIDEO_TYPES, app


logger = logging.getLogger(__name__)

CSS = """
.gradio-container { max-width: 1120px !important; margin: auto !important; padding: 24px !important; }
#hero { text-align: center; padding: 24px 0 30px; }
#hero h1 { font-size: 42px; font-weight: 750; letter-spacing: -1.5px; line-height: 1.2; margin: 0 0 12px; }
#hero p { color: #64748b; font-size: 15px; margin: 0; }
#workspace { gap: 24px; align-items: stretch !important; }
#upload-panel, #result-panel {
    border: 1px solid #e2e8f0; border-radius: 18px; padding: 24px;
    background: var(--block-background-fill); box-shadow: 0 4px 24px #0f172a05; gap: 16px;
}
#upload-panel h3, #result-panel h3 { font-size: 16px; font-weight: 650; margin: 0; line-height: 28px; }
#media-upload { border: 1px dashed #b8d8cd; border-radius: 12px; }
#formats p { font-size: 12px; line-height: 1.8; color: #64748b; margin: 0; }
#actions { gap: 12px; flex-wrap: nowrap; }
#actions button { min-height: 44px; border-radius: 10px; }
#result-stage {
    flex: 1 !important; min-height: 350px; justify-content: center;
    border: 1px solid var(--block-border-color); border-radius: 12px;
    background: var(--background-fill-secondary); overflow: hidden; padding: 12px;
}
#empty-result { text-align: center; padding: 64px 16px; }
#empty-result h2 { font-size: 20px; font-weight: 600; margin: 0 0 12px; }
#empty-result p { color: #64748b; font-size: 13px; line-height: 1.9; }
#result-stage .block { border: 0; }
#result-meta { gap: 12px; flex: 0 0 auto !important; }
#result-note p { color: #64748b; font-size: 12px; line-height: 1.8; margin: 0; }
#footer { text-align: center; padding: 16px 0 8px; }
#footer p, #footer a { color: #64748b; font-size: 12px; }
@media (max-width: 720px) {
    .gradio-container { padding: 16px !important; }
    #hero { padding: 18px 0 24px; }
    #hero h1 { font-size: 36px; }
    #workspace { gap: 16px; }
    #upload-panel, #result-panel { padding: 18px; }
    #result-stage { min-height: 280px; }
}
"""


def create_ui(application):
    extensions = sorted(IMAGE_TYPES.keys() | VIDEO_TYPES)

    with gr.Blocks(title="Deface", fill_width=True, analytics_enabled=False, delete_cache=(3600, 86400)) as demo:
        gr.Markdown(
            "# Deface\n"
            "图片与视频人脸遮挡 · 上传、处理、预览与下载",
            elem_id="hero",
        )
        with gr.Row(equal_height=False, elem_id="workspace"):
            with gr.Column(scale=4, min_width=300, elem_id="upload-panel"):
                gr.Markdown("### 01　上传素材")
                upload = gr.File(
                    label="拖拽文件到这里，或点击上传",
                    file_types=extensions,
                    type="filepath",
                    height=190,
                    elem_id="media-upload",
                )
                gr.Markdown(
                    "图片：JPG / PNG / BMP / WebP / TIFF  \n"
                    "视频：MP4 / MOV / AVI / MKV / WebM / M4V  \n"
                    f"单文件上限 {MAX_UPLOAD_BYTES // (1024 * 1024)} MB",
                    elem_id="formats",
                )
                gr.Markdown("### 02　处理设置")
                replacewith = gr.Dropdown(
                    choices=[("马赛克", "mosaic"), ("模糊", "blur"), ("黑色遮挡", "solid"), ("不遮挡", "none")],
                    value="mosaic", label="处理方式",
                )
                mosaic_size = gr.Slider(2, 200, value=20, step=1, label="马赛克块大小", info="数值越大，颗粒越粗。")
                with gr.Accordion("高级设置", open=False):
                    threshold = gr.Slider(0, 1, value=0.2, step=0.01, label="检测置信度", info="降低可减少漏检，但可能增加误检。")
                    mask_scale = gr.Slider(1, 3, value=1.3, step=0.1, label="人脸覆盖范围", info="增大可覆盖人脸周围区域。")
                    keep_audio = gr.Checkbox(value=False, label="保留视频音轨")
                with gr.Row(elem_id="actions"):
                    submit = gr.Button("开始处理", variant="primary", scale=3)
                    clear = gr.Button("清空", variant="secondary", scale=1, min_width=80)
                with gr.Accordion("原始素材预览", open=False):
                    original_image = gr.Image(label="原始图片", visible=False, interactive=False, height=260)
                    original_video = gr.Video(label="原始视频", visible=False, interactive=False, height=260)
                    gr.Markdown("部分 TIFF 或视频编码无法在浏览器预览，仍可尝试处理。")
            with gr.Column(scale=6, min_width=320, elem_id="result-panel"):
                gr.Markdown("### 03　预览与下载")
                with gr.Column(elem_id="result-stage"):
                    empty = gr.Markdown("## 等待处理素材\n\n从左侧上传图片或视频，\n\n处理结果将在这里显示。", elem_id="empty-result")
                    result_image = gr.Image(label="处理结果", visible=False, interactive=False, height=400)
                    result_video = gr.Video(label="处理结果", visible=False, interactive=False, height=400)
                with gr.Column(elem_id="result-meta"):
                    download = gr.File(label="下载处理后的文件", interactive=False, visible=False)
                    status = gr.Textbox(value="等待上传素材", label="处理状态", interactive=False)
                    gr.Markdown("视频输出为 MP4，默认移除音轨。下载前请检查人脸遮挡效果。", elem_id="result-note")
        gr.Markdown(
            "[FastAPI 接口文档](/docs) · 文件在当前服务处理 · 结果缓存保留约 24 小时，请及时下载",
            elem_id="footer",
        )

        def preview(file):
            suffix = Path(file).suffix.lower() if file else ""
            return (
                gr.update(value=file if suffix in IMAGE_TYPES else None, visible=suffix in IMAGE_TYPES),
                gr.update(value=file if suffix in VIDEO_TYPES else None, visible=suffix in VIDEO_TYPES),
                gr.update(value=None, visible=False),
                gr.update(value=None, visible=False),
                gr.update(value=None, visible=False),
                gr.update(visible=True),
                "素材已就绪，点击开始处理" if file else "等待上传素材",
            )

        async def process(file, mosaic_size, threshold, mask_scale, keep_audio, replacewith="mosaic", progress=gr.Progress()):
            if not file:
                raise gr.Error("请先上传图片或视频。")
            source = Path(file)
            if source.suffix.lower() not in extensions:
                raise gr.Error("不支持此文件格式，请选择上方列出的图片或视频。")
            if source.stat().st_size > MAX_UPLOAD_BYTES:
                raise gr.Error("文件超过上传大小限制，请选择更小的文件。")

            started = time.monotonic()
            progress(None, desc="正在检测人脸并处理，视频可能需要较长时间…")
            try:
                # Exercise the existing HTTP endpoint in-process; no second inference implementation.
                transport = httpx.ASGITransport(app=application)
                async with httpx.AsyncClient(transport=transport, base_url="http://deface", timeout=None) as client:
                    with source.open("rb") as stream:
                        response = await client.post(
                            "/anonymize",
                            files={"file": (source.name, stream)},
                            data={
                                "mosaic_size": mosaic_size,
                                "threshold": threshold,
                                "mask_scale": mask_scale,
                                "keep_audio": keep_audio,
                                "replacewith": replacewith,
                            },
                        )
                if response.status_code != 200:
                    messages = {
                        413: "文件超过上传大小限制。",
                        415: "不支持此文件格式。",
                        422: "处理失败，请检查文件是否损坏或编解码器是否受支持，然后重试。",
                    }
                    raise gr.Error(messages.get(response.status_code, "服务处理失败，请重试。"))
                if not response.content:
                    raise gr.Error("返回文件为空，请重试。")
                is_video = source.suffix.lower() in VIDEO_TYPES
                suffix = ".mp4" if is_video else source.suffix.lower()
                with tempfile.TemporaryDirectory(prefix="deface-web-") as directory:
                    output = Path(directory) / f"{source.stem}_anonymized{suffix}"
                    output.write_bytes(response.content)
                    cached = download.move_resource_to_block_cache(str(output))
                elapsed = time.monotonic() - started
                return (
                    gr.update(value=None if is_video else cached, visible=not is_video),
                    gr.update(value=cached if is_video else None, visible=is_video),
                    gr.update(value=cached, visible=True),
                    gr.update(visible=False),
                    f"处理完成 · {len(response.content) / (1024 * 1024):.2f} MB · 耗时 {elapsed:.1f} 秒 · 可预览或下载",
                )
            except gr.Error:
                raise
            except Exception as exc:
                logger.exception("Gradio media processing failed")
                raise gr.Error("处理失败，请检查素材后重试。") from exc

        outputs = [result_image, result_video, download, empty, status]
        upload.change(preview, upload, [original_image, original_video, *outputs], api_name=False)
        replacewith.change(
            lambda mode: gr.update(visible=mode == "mosaic"), replacewith, mosaic_size, api_name=False,
        )
        submit.click(process, [upload, mosaic_size, threshold, mask_scale, keep_audio, replacewith], outputs, api_name=False)
        clear.click(
            lambda: [None, gr.update(value=20, visible=True), 0.2, 1.3, False, "mosaic"],
            outputs=[upload, mosaic_size, threshold, mask_scale, keep_audio, replacewith],
            api_name=False,
        )
    return demo.queue(default_concurrency_limit=1, max_size=8)


def create_app():
    return gr.mount_gradio_app(
        app,
        create_ui(app),
        path="/",
        theme=gr.themes.Soft(
            primary_hue="emerald", neutral_hue="slate", font=["system-ui", "sans-serif"],
        ).set(
            body_background_fill="#f5f7fa",
            block_background_fill="#ffffff",
            block_label_background_fill="transparent",
            block_label_text_color="#475569",
            block_label_shadow="none",
            block_shadow="none",
        ),
        css=CSS,
        max_file_size=MAX_UPLOAD_BYTES,
        footer_links=[],
    )


def run():
    uvicorn.run(create_app(), host="127.0.0.1", port=8000)
