# Deface 接口文档

Deface 提供图片和视频人脸马赛克处理接口。调用方上传文件，等待处理完成后接收处理后的文件；服务不返回文件路径或任务 ID。

## 启动服务

在项目根目录执行：

```bash
uv sync
uv run deface-api
```

本机默认地址为 `http://127.0.0.1:8000`。启动后可通过以下地址查看接口：

- Swagger UI：`http://127.0.0.1:8000/docs`
- OpenAPI JSON：`http://127.0.0.1:8000/openapi.json`

`deface-api` 默认监听 `0.0.0.0:8000`，当前接口没有鉴权。若部署到其他机器或开放网络，应通过网络限制或网关鉴权控制访问。

也可使用 `uv run --group web deface-web` 启动带 Gradio 验证页面的服务。它默认监听 `127.0.0.1:8000`，同时提供相同的 `/health`、`/anonymize` 和 `/docs`。两种启动方式使用同一端口，选择一种即可。

## 健康检查

### `GET /health`

请求示例：

```bash
curl http://127.0.0.1:8000/health
```

成功返回 `200 OK`：

```json
{"status": "ok"}
```

此接口仅表示服务可以响应请求，不会检查模型推理或视频编码是否正常。

## 人脸马赛克处理

### `POST /anonymize`

上传一个图片或视频文件，对检测到的人脸应用矩形马赛克。请求类型为 `multipart/form-data`，所有参数均放在表单中。

| 字段 | 类型 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- | --- |
| `file` | 文件 | 是 | 无 | 要处理的图片或视频，一次上传一个文件 |
| `mosaic_size` | 整数 | 否 | `20` | 马赛克块边长，单位为像素，范围 `2–200`；越大颗粒越粗 |
| `threshold` | 浮点数 | 否 | `0.2` | 人脸检测阈值，范围 `0–1`；降低可能减少漏检，但也可能增加误检 |
| `mask_scale` | 浮点数 | 否 | `1.3` | 人脸区域扩展系数，范围 `1–3` |
| `keep_audio` | 布尔值 | 否 | `false` | 是否尝试保留视频音轨；图片处理时无影响 |

格式通过上传文件名的扩展名识别，扩展名不区分大小写：

| 输入 | 支持的扩展名 | 输出 |
| --- | --- | --- |
| 图片 | `.jpg`、`.jpeg`、`.png`、`.bmp`、`.webp`、`.tif`、`.tiff` | 相同扩展名的图片 |
| 视频 | `.mp4`、`.mov`、`.avi`、`.mkv`、`.webm`、`.m4v` | MP4，视频编码为 H.264 |

扩展名受支持并不保证文件一定能解码；实际支持情况还取决于文件内容和编码格式。视频默认不保留音轨；设置 `keep_audio=true` 时会尝试直接复制源音轨，某些音轨可能与 MP4 容器不兼容。图片默认不保留原始 EXIF 元数据。

默认上传大小上限为 **1024 MiB**。可在启动服务前设置环境变量 `DEFACE_MAX_UPLOAD_MB`（单位为 MiB），例如：

```bash
DEFACE_MAX_UPLOAD_MB=512 uv run deface-api
```

### 图片调用示例

```bash
curl --fail-with-body -X POST 'http://127.0.0.1:8000/anonymize' \
  -F 'file=@examples/city.jpg' \
  -F 'mosaic_size=20' \
  -F 'threshold=0.2' \
  -F 'mask_scale=1.3' \
  --output city_anonymized.jpg
```

### 视频调用示例

```bash
curl --fail-with-body -X POST 'http://127.0.0.1:8000/anonymize' \
  -F 'file=@input.mov' \
  -F 'mosaic_size=30' \
  -F 'keep_audio=true' \
  --output input_anonymized.mp4
```

`--output` 指定的是**调用方**保存文件的路径。视频处理是同步请求，较长视频可能需要等待较久；调用方应根据视频长度设置超时时间。

### 成功响应

成功时返回 `200 OK`，响应体为处理后文件的二进制内容，并非 JSON。例如：

```http
HTTP/1.1 200 OK
Content-Type: video/mp4
Content-Disposition: attachment; filename="input_anonymized.mp4"

<MP4 文件二进制内容>
```

图片响应的 `Content-Type` 对应图片格式，如 `image/jpeg` 或 `image/png`；视频响应为 `video/mp4`。响应头中的下载文件名通常是原文件名加 `_anonymized`，视频扩展名统一为 `.mp4`。文件名包含非 ASCII 字符时，`Content-Disposition` 可能使用编码后的 `filename*`。

服务在内部使用临时文件；正常发送响应后会清理临时文件。调用方如需持久保存，须将响应内容写入自己的存储。

### Python 调用示例

以下示例使用 `requests`（需在调用方环境安装），以流式方式保存响应，避免将整个结果一次性读入内存：

```python
from pathlib import Path

import requests

source = Path("input.mp4")
output = Path("input_anonymized.mp4")

with source.open("rb") as video:
    with requests.post(
        "http://127.0.0.1:8000/anonymize",
        files={"file": (source.name, video, "video/mp4")},
        data={"mosaic_size": 20, "keep_audio": "false"},
        stream=True,
        timeout=(15, 3600),  # 连接和读取超时，按实际视频处理时间调整
    ) as response:
        response.raise_for_status()
        with output.open("wb") as result:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    result.write(chunk)

print(f"已保存：{output}")
```

### 错误响应

错误响应通常为 JSON，具体校验错误的 `detail` 可能是字符串或数组。

| 状态码 | 常见原因 |
| --- | --- |
| `413` | 上传文件超过配置的大小上限 |
| `415` | 文件扩展名不在支持列表中 |
| `422` | 缺少必填文件、参数超出范围、文件无法处理或媒体编码不受支持 |
| `500` | 服务内部未预期的错误 |

例如，上传扩展名不受支持的文件时，响应中的 `detail` 会列出支持的扩展名：

```json
{"detail": "Unsupported file type. Supported extensions: ..."}
```

媒体处理失败时的示例：

```json
{"detail": "Media processing failed"}
```

## 使用限制

- 当前接口只接收完整文件，不支持 RTSP、RTMP 或摄像头实时流，也没有任务进度查询接口。
- 单个服务进程内推理使用锁串行执行；并发请求可能等待前一个任务完成。视频处理速度取决于时长、帧率、分辨率和机器性能。
- 人脸检测存在漏检和误检的可能，处理结果需根据使用场景检查。马赛克大小也会影响遮挡效果。
