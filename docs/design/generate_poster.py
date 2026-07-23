"""
生成 PyCoder VS Code 风格重设计海报
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

OUTPUT_DIR = Path("C:/Users/Administrator/Desktop/pycode/docs/design")
DARK_IMG = OUTPUT_DIR / "2_2.png"
LIGHT_IMG = OUTPUT_DIR / "2_128.png"
POSTER = OUTPUT_DIR / "pycoder_vscode_redesign_poster.png"

# 画布尺寸
WIDTH, HEIGHT = 1920, 1080
MARGIN = 40
HEADER_H = 130
FOOTER_H = 170
IMG_AREA_H = HEIGHT - HEADER_H - FOOTER_H

# 颜色
def hex_color(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))

BG = hex_color("#1E1E1E")
ACCENT = hex_color("#007ACC")
TEXT_PRIMARY = hex_color("#E0E0E0")
TEXT_SECONDARY = hex_color("#A0A0A0")
CARD_BG = hex_color("#252526")
BORDER = hex_color("#3C3C3C")

# 加载图片
dark = Image.open(DARK_IMG)
light = Image.open(LIGHT_IMG)

# 计算等比例缩放后尺寸，目标高度 IMG_AREA_H - MARGIN*2
max_h = IMG_AREA_H - MARGIN * 2
max_w = (WIDTH - MARGIN * 3) // 2

def fit_size(img: Image.Image, max_w: int, max_h: int) -> tuple[int, int]:
    w, h = img.size
    scale = min(max_w / w, max_h / h, 1.0)
    return int(w * scale), int(h * scale)

dw, dh = fit_size(dark, max_w, max_h)
lw, lh = fit_size(light, max_w, max_h)

dark_resized = dark.resize((dw, dh), Image.LANCZOS)
light_resized = light.resize((lw, lh), Image.LANCZOS)

# 创建画布
canvas = Image.new("RGB", (WIDTH, HEIGHT), BG)
draw = ImageDraw.Draw(canvas)

# 加载字体
try:
    font_title = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 42)
    font_subtitle = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 20)
    font_tag = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 18)
    font_footer = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 16)
    font_en = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 14)
except Exception:
    font_title = ImageFont.load_default()
    font_subtitle = font_title
    font_tag = font_title
    font_footer = font_title
    font_en = font_title

# 顶部标题
draw.text((MARGIN, 50), "PyCoder IDE", font=font_title, fill=TEXT_PRIMARY)
draw.text((MARGIN, 102), "VS Code 风格重设计方案  |  AI 编程智能体的现代化桌面 IDE 界面", font=font_subtitle, fill=TEXT_SECONDARY)

# 标题右侧标签
tags = ["FastAPI", "Electron", "React", "Monaco Editor", "AI Agent"]
tag_x = WIDTH - MARGIN
for tag in reversed(tags):
    bbox = draw.textbbox((0, 0), tag, font=font_tag)
    tag_w = bbox[2] - bbox[0]
    tag_x -= tag_w + 20
    # 标签背景
    draw.rounded_rectangle([tag_x, 55, tag_x + tag_w + 16, 55 + 28], radius=4, fill=CARD_BG, outline=BORDER)
    draw.text((tag_x + 8, 58), tag, font=font_tag, fill=TEXT_SECONDARY)
    tag_x -= 12

# 图片区域背景卡片
card_y = HEADER_H
img_y = card_y + MARGIN
img_x1 = MARGIN + (max_w - dw) // 2
img_x2 = WIDTH - MARGIN - max_w + (max_w - lw) // 2

# 绘制暗色主题卡片
card1_rect = [MARGIN, card_y, MARGIN + max_w, card_y + IMG_AREA_H]
draw.rounded_rectangle(card1_rect, radius=8, fill=CARD_BG, outline=BORDER)
canvas.paste(dark_resized, (img_x1, img_y))

# 暗色主题标签
draw.rounded_rectangle([MARGIN + 16, card_y + 16, MARGIN + 16 + 110, card_y + 16 + 28], radius=4, fill=ACCENT)
draw.text((MARGIN + 26, card_y + 19), "Dark+", font=font_tag, fill=(255, 255, 255))

# 绘制 Light 主题卡片
card2_rect = [WIDTH - MARGIN - max_w, card_y, WIDTH - MARGIN, card_y + IMG_AREA_H]
draw.rounded_rectangle(card2_rect, radius=8, fill=CARD_BG, outline=BORDER)
canvas.paste(light_resized, (img_x2, img_y))

# Light 主题标签
draw.rounded_rectangle([WIDTH - MARGIN - max_w + 16, card_y + 16, WIDTH - MARGIN - max_w + 16 + 120, card_y + 16 + 28], radius=4, fill=hex_color("#6E6E6E"))
draw.text((WIDTH - MARGIN - max_w + 26, card_y + 19), "Light+", font=font_tag, fill=(255, 255, 255))

# 底部设计要点
footer_y = HEIGHT - FOOTER_H + 30
points = [
    ("界面布局", "经典 VS Code 五区结构：菜单栏、活动栏、边栏、编辑区、底层面板"),
    ("视觉风格", "Dark+/Light+ 双主题，蓝色强调 #007ACC，JetBrains Mono 等宽字体"),
    ("交互设计", "命令面板、可拖拽面板、Tab 切换、快捷键、上下文菜单"),
    ("功能适配", "文件树、AI 聊天、终端输出、Git 状态、模型切换、状态栏"),
    ("响应式适配", "面板可折叠、最小宽度保护、暗色/亮色主题无缝切换"),
]

col_width = (WIDTH - MARGIN * 2 - 40) // 3
cols = 3
for i, (title, desc) in enumerate(points):
    if i >= 5:
        break
    col = i % cols
    row = i // cols
    x = MARGIN + col * (col_width + 20)
    y = footer_y + row * 70
    draw.text((x, y), f"● {title}", font=font_tag, fill=TEXT_PRIMARY)
    draw.text((x, y + 26), desc, font=font_footer, fill=TEXT_SECONDARY)

# 保存
canvas.save(POSTER, "PNG", quality=95)
print(f"Poster saved to: {POSTER}")
