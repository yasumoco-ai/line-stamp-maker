import os
import base64
import zipfile
import urllib.request
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from openai import OpenAI
import io

STAMP_W, STAMP_H = 370, 320

REACTIONS = {
    "笑顔・喜び": "smiling happily, joyful expression",
    "爆笑": "laughing out loud, tears of joy",
    "驚き": "surprised, shocked expression, wide eyes",
    "感動・泣き": "moved to tears, crying with happiness",
    "怒り": "angry, furious expression",
    "恥ずかしい": "embarrassed, blushing",
    "困り顔": "troubled, worried expression",
    "ドヤ顔": "smug, proud, confident smirk",
    "眠い": "sleepy, drowsy eyes",
    "ラブ": "love-struck, heart eyes",
    "OK・サムズアップ": "thumbs up, OK gesture",
    "NG・手を振る": "waving hand, declining gesture",
}

# リアクション別テキストスタイル
REACTION_STYLES = {
    "笑顔・喜び": {
        "color": (255, 160, 0),
        "outline": (255, 255, 255),
        "outline_w": 3,
        "size": 34,
        "weight": "regular",
        "shadow": True,
    },
    "爆笑": {
        "color": (255, 220, 0),
        "outline": (255, 100, 0),
        "outline_w": 4,
        "size": 42,
        "weight": "bold",
        "shadow": True,
    },
    "驚き": {
        "color": (0, 200, 255),
        "outline": (0, 60, 180),
        "outline_w": 4,
        "size": 40,
        "weight": "bold",
        "shadow": True,
    },
    "感動・泣き": {
        "color": (80, 140, 230),
        "outline": (255, 255, 255),
        "outline_w": 3,
        "size": 30,
        "weight": "regular",
        "shadow": False,
    },
    "怒り": {
        "color": (220, 20, 20),
        "outline": (255, 220, 0),
        "outline_w": 5,
        "size": 46,
        "weight": "bold",
        "shadow": True,
    },
    "恥ずかしい": {
        "color": (255, 100, 160),
        "outline": (255, 255, 255),
        "outline_w": 3,
        "size": 28,
        "weight": "regular",
        "shadow": False,
    },
    "困り顔": {
        "color": (130, 100, 190),
        "outline": (255, 255, 255),
        "outline_w": 3,
        "size": 28,
        "weight": "regular",
        "shadow": False,
    },
    "ドヤ顔": {
        "color": (255, 200, 0),
        "outline": (160, 60, 0),
        "outline_w": 4,
        "size": 38,
        "weight": "bold",
        "shadow": True,
    },
    "眠い": {
        "color": (160, 180, 220),
        "outline": (255, 255, 255),
        "outline_w": 2,
        "size": 26,
        "weight": "regular",
        "shadow": False,
    },
    "ラブ": {
        "color": (255, 60, 130),
        "outline": (255, 200, 220),
        "outline_w": 3,
        "size": 34,
        "weight": "regular",
        "shadow": False,
    },
    "OK・サムズアップ": {
        "color": (30, 190, 80),
        "outline": (255, 255, 255),
        "outline_w": 4,
        "size": 38,
        "weight": "bold",
        "shadow": True,
    },
    "NG・手を振る": {
        "color": (200, 30, 30),
        "outline": (255, 255, 255),
        "outline_w": 4,
        "size": 38,
        "weight": "bold",
        "shadow": True,
    },
}

DEFAULT_STYLE = {
    "color": (30, 30, 30),
    "outline": (255, 255, 255),
    "outline_w": 3,
    "size": 30,
    "weight": "regular",
    "shadow": False,
}

FONT_DIR = Path(__file__).parent

FONT_SOURCES = {
    "regular": {
        "system": [
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
            "/System/Library/Fonts/ヒラギノ丸ゴ ProN W4.ttc",
            "/System/Library/Fonts/Hiragino Maru Gothic ProN.ttc",
        ],
        "local": FONT_DIR / "NotoSansCJKjp-Regular.otf",
        "url": "https://github.com/googlefonts/noto-cjk/raw/main/Sans/OTF/Japanese/NotoSansCJKjp-Regular.otf",
    },
    "bold": {
        "system": [
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
            "/System/Library/Fonts/ヒラギノ角ゴシック W8.ttc",
        ],
        "local": FONT_DIR / "NotoSansCJKjp-Bold.otf",
        "url": "https://github.com/googlefonts/noto-cjk/raw/main/Sans/OTF/Japanese/NotoSansCJKjp-Bold.otf",
    },
}

_font_cache: dict = {}


def get_font(weight: str, size: int) -> ImageFont.FreeTypeFont:
    cache_key = (weight, size)
    if cache_key in _font_cache:
        return _font_cache[cache_key]

    src = FONT_SOURCES.get(weight, FONT_SOURCES["regular"])

    for fp in src["system"]:
        if os.path.exists(fp):
            try:
                f = ImageFont.truetype(fp, size)
                _font_cache[cache_key] = f
                return f
            except Exception:
                continue

    local = src["local"]
    if not local.exists():
        urllib.request.urlretrieve(src["url"], local)

    f = ImageFont.truetype(str(local), size)
    _font_cache[cache_key] = f
    return f


def _draw_text_with_style(
    draw: ImageDraw.ImageDraw,
    text: str,
    x: int,
    y: int,
    font: ImageFont.FreeTypeFont,
    style: dict,
) -> None:
    ow = style["outline_w"]
    outline_color = style["outline"] + (255,)
    text_color = style["color"] + (255,)

    # ドロップシャドウ
    if style.get("shadow"):
        shadow_color = (0, 0, 0, 100)
        draw.text((x + 3, y + 3), text, font=font, fill=shadow_color)

    # 縁取り（外側から内側へ）
    for dx in range(-ow, ow + 1):
        for dy in range(-ow, ow + 1):
            if abs(dx) + abs(dy) >= ow:
                draw.text((x + dx, y + dy), text, font=font, fill=outline_color)

    # 本文
    draw.text((x, y), text, font=font, fill=text_color)


def add_text_to_stamp(img: Image.Image, text: str, reaction: str) -> Image.Image:
    stamp = img.resize((STAMP_W, STAMP_H), Image.LANCZOS).convert("RGBA")
    draw = ImageDraw.Draw(stamp)

    style = REACTION_STYLES.get(reaction, DEFAULT_STYLE)
    font = get_font(style["weight"], style["size"])

    margin = 10
    max_width = STAMP_W - margin * 2

    # 折り返し
    lines = []
    current = ""
    for ch in text:
        test = current + ch
        bbox = draw.textbbox((0, 0), test, font=font)
        if bbox[2] - bbox[0] > max_width and current:
            lines.append(current)
            current = ch
        else:
            current = test
    if current:
        lines.append(current)

    line_h = style["size"] + 8
    total_h = line_h * len(lines)
    text_y = STAMP_H - total_h - margin - style["outline_w"]

    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=font)
        text_w = bbox[2] - bbox[0]
        x = (STAMP_W - text_w) // 2
        y = text_y + i * line_h
        _draw_text_with_style(draw, line, x, y, font, style)

    return stamp


def generate_expression_image(
    client: OpenAI, ref_image: Image.Image, reaction_label: str, reaction_desc: str
) -> Image.Image:
    buf = io.BytesIO()
    ref_image.convert("RGB").save(buf, format="PNG")
    buf.seek(0)

    prompt = (
        f"This is my original character. "
        f"Generate a LINE sticker version of this exact character showing a {reaction_desc}. "
        f"Preserve the character's appearance, colors, art style, and design exactly. "
        f"White background. Cute expressive sticker style. No text, no borders."
    )

    response = client.images.edit(
        model="gpt-image-1",
        image=("character.png", buf, "image/png"),
        prompt=prompt,
        size="1024x1024",
        n=1,
    )

    img_b64 = response.data[0].b64_json
    img_bytes = base64.b64decode(img_b64)
    return Image.open(io.BytesIO(img_bytes)).convert("RGBA")


def create_stamp_zip(
    client: OpenAI,
    ref_image: Image.Image,
    stamp_configs: list[dict],
    output_path: str,
    progress_callback=None,
) -> str:
    out = Path(output_path)
    out.mkdir(parents=True, exist_ok=True)

    generated_paths = []

    for i, config in enumerate(stamp_configs):
        phrase = config["phrase"]
        reaction = config["reaction"]
        reaction_desc = REACTIONS.get(reaction, "neutral expression")

        if progress_callback:
            progress_callback(i, len(stamp_configs), f"{reaction}「{phrase}」を生成中…")

        try:
            expr_img = generate_expression_image(client, ref_image, reaction, reaction_desc)
        except Exception:
            expr_img = ref_image.copy().convert("RGBA")

        stamp = add_text_to_stamp(expr_img, phrase, reaction)

        filename = out / f"stamp_{i+1:02d}.png"
        stamp.save(filename, "PNG")
        generated_paths.append(filename)

    tab_img = ref_image.resize((96, 74), Image.LANCZOS)
    tab_path = out / "tab.png"
    tab_img.save(tab_path, "PNG")

    zip_path = str(out) + ".zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        for p in generated_paths:
            zf.write(p, p.name)
        zf.write(tab_path, "tab.png")

    return zip_path
