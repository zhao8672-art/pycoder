# PyCoder Multimodal Module

PyCoder 的多模态支持在 `pycoder/multimodal/` 子包中, **不**在仓库根.

## 真实位置

| 文件 | 用途 | 大小 |
|------|------|------|
| `pycoder/multimodal/vision_client.py` | GPT-4V / DeepSeek-VL 视觉模型 | 4 KB |
| `pycoder/multimodal/ocr_engine.py` | OCR (Tesseract → PaddleOCR → GLM) | 5 KB |
| `pycoder/multimodal/image_analyzer.py` | 图像元数据分析 | 3 KB |
| `pycoder/multimodal/tool_definitions.py` | 工具定义 (供 LLM 调用) | 4 KB |

## 依赖

```toml
# requirements.txt / requirements.in (已声明)
Pillow~=10.4.0       # 图像处理
pytesseract~=0.3.13  # OCR 引擎
pdfplumber~=0.11.0   # PDF 解析
```

可选依赖 (按需安装):
- `opencv-python` — 高级图像处理 (可选)
- `paddleocr` — 中文 OCR (可选)

## API 端点

- `POST /api/multimodal/upload`   — 上传图片 / PDF
- `POST /api/multimodal/analyze`  — 图像分析
- `POST /api/multimodal/ocr`      — 文字识别
- `POST /api/multimodal/vision`   — 视觉模型查询
- `POST /api/multimodal/screenshot` — 截图分析
