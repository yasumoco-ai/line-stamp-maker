import os
import base64
import zipfile
import math
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

# size = 1行に収まらない時の折り返し後の最大サイズ上限。auto_font_size()で実際のサイズを決定。
# effect: "wavy"=波打ち / "bounce"=バウンス / "standard"=通常
REACTION_STYLES = {
    "笑顔・喜び": {
        "effect": "bounce",
        "grad": [(255, 200, 0), (255, 120, 0)],
        "outline": (255, 255, 255), "outline_w": 4,
        "shadow": (180, 80, 0, 120), "size": 72, "weight": "bold",
    },
    "爆笑": {
        "effect": "bounce",
        "grad": [(255, 230, 0), (255, 100, 0)],
        "outline": (255, 50, 0), "outline_w": 6,
        "shadow": (150, 60, 0, 160), "size": 76, "weight": "bold",
    },
    "驚き": {
        "effect": "wavy",
        "grad": [(0, 230, 255), (0, 100, 220)],
        "outline": (255, 255, 255), "outline_w": 5,
        "shadow": (0, 50, 150, 150), "size": 74, "weight": "bold",
    },
    "感動・泣き": {
        "effect": "wavy",
        "grad": [(120, 180, 255), (60, 100, 220)],
        "outline": (255, 255, 255), "outline_w": 4,
        "shadow": (40, 60, 180, 100), "size": 68, "weight": "regular",
    },
    "怒り": {
        "effect": "bounce",
        "grad": [(255, 60, 0), (180, 0, 0)],
        "outline": (255, 220, 0), "outline_w": 7,
        "shadow": (100, 0, 0, 180), "size": 80, "weight": "bold",
    },
    "恥ずかしい": {
        "effect": "wavy",
        "grad": [(255, 140, 180), (255, 80, 140)],
        "outline": (255, 255, 255), "outline_w": 4,
        "shadow": (180, 60, 100, 100), "size": 68, "weight": "regular",
    },
    "困り顔": {
        "effect": "standard",
        "grad": [(160, 120, 220), (100, 80, 180)],
        "outline": (255, 255, 255), "outline_w": 4,
        "shadow": (60, 40, 120, 100), "size": 68, "weight": "regular",
    },
    "ドヤ顔": {
        "effect": "bounce",
        "grad": [(255, 215, 0), (220, 150, 0)],
        "outline": (140, 60, 0), "outline_w": 5,
        "shadow": (100, 60, 0, 160), "size": 74, "weight": "bold",
    },
    "眠い": {
        "effect": "wavy",
        "grad": [(180, 200, 230), (140, 160, 210)],
        "outline": (255, 255, 255), "outline_w": 3,
        "shadow": (80, 100, 160, 80), "size": 66, "weight": "regular",
    },
    "ラブ": {
        "effect": "bounce",
        "grad": [(255, 100, 160), (255, 50, 120)],
        "outline": (255, 220, 235), "outline_w": 4,
        "shadow": (180, 30, 80, 120), "size": 72, "weight": "bold",
    },
    "OK・サムズアップ": {
        "effect": "bounce",
        "grad": [(60, 210, 100), (0, 160, 60)],
        "outline": (255, 255, 255), "outline_w": 5,
        "shadow": (0, 80, 30, 140), "size": 74, "weight": "bold",
    },
    "NG・手を振る": {
        "effect": "bounce",
        "grad": [(220, 40, 40), (160, 0, 0)],
        "outline": (255, 255, 255), "outline_w": 5,
        "shadow": (80, 0, 0, 140), "size": 74, "weight": "bold",
    },
}

DEFAULT_STYLE = {
    "effect": "standard",
    "grad": [(60, 60, 60), (30, 30, 30)],
    "outline": (255, 255, 255), "outline_w": 4,
    "shadow": (0, 0, 0, 100), "size": 70, "weight": "regular",
}

FONT_DIR = Path(__file__).parent

# リポジトリ同梱フォント（最優先）
_BUNDLED = {
    "regular": FONT_DIR / "NotoSansJP-Regular.otf",
    "bold":    FONT_DIR / "NotoSansJP-Bold.otf",
}

# システムフォント（フォールバック）
_SYSTEM = {
    "regular": [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/System/Library/Fonts/ヒラギノ丸ゴ ProN W4.ttc",
        "/System/Library/Fonts/Hiragino Maru Gothic ProN.ttc",
    ],
    "bold": [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
        "/System/Library/Fonts/ヒラギノ角ゴシック W8.ttc",
    ],
}

_font_cache: dict = {}


def get_font(weight: str, size: int) -> ImageFont.FreeTypeFont:
    key = (weight, size)
    if key in _font_cache:
        return _font_cache[key]

    # 1. 同梱フォントを最優先
    bundled = _BUNDLED.get(weight, _BUNDLED["regular"])
    if bundled.exists():
        f = ImageFont.truetype(str(bundled), size)
        _font_cache[key] = f
        return f

    # 2. システムフォント
    for fp in _SYSTEM.get(weight, _SYSTEM["regular"]):
        if os.path.exists(fp):
            try:
                f = ImageFont.truetype(fp, size)
                _font_cache[key] = f
                return f
            except Exception:
                continue

    # 3. regular の同梱フォントで代替
    fallback = _BUNDLED["regular"]
    if fallback.exists():
        f = ImageFont.truetype(str(fallback), size)
        _font_cache[key] = f
        return f

    raise RuntimeError("日本語フォントが見つかりません")


def _make_gradient(size: tuple, c1: tuple, c2: tuple) -> Image.Image:
    """左→右のグラデーション画像を生成。"""
    w, h = size
    grad = Image.new("RGB", size)
    for x in range(w):
        t = x / max(w - 1, 1)
        r = int(c1[0] + (c2[0] - c1[0]) * t)
        g = int(c1[1] + (c2[1] - c1[1]) * t)
        b = int(c1[2] + (c2[2] - c1[2]) * t)
        for y in range(h):
            grad.putpixel((x, y), (r, g, b))
    return grad


def _draw_chars(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    x_start: int,
    y_base: int,
    effect: str,
    fill,
) -> None:
    """1文字ずつ描画。effectに応じてY位置を変化させる。"""
    x = x_start
    ref_draw = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    for i, ch in enumerate(text):
        if effect == "wavy":
            dy = int(math.sin(i * 1.3) * 7)
        elif effect == "bounce":
            dy = int(abs(math.sin(i * 1.0)) * -6)
        else:
            dy = 0
        draw.text((x, y_base + dy), ch, font=font, fill=fill)
        bbox = ref_draw.textbbox((0, 0), ch, font=font)
        x += bbox[2] - bbox[0]


def _text_total_width(text: str, font: ImageFont.FreeTypeFont) -> int:
    ref_draw = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    total = 0
    for ch in text:
        bbox = ref_draw.textbbox((0, 0), ch, font=font)
        total += bbox[2] - bbox[0]
    return total


def _wrap_text(text: str, font: ImageFont.FreeTypeFont, max_w: int) -> list[str]:
    lines, current = [], ""
    ref_draw = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    for ch in text:
        test = current + ch
        bbox = ref_draw.textbbox((0, 0), test, font=font)
        if bbox[2] - bbox[0] > max_w and current:
            lines.append(current)
            current = ch
        else:
            current = test
    if current:
        lines.append(current)
    return lines


def _auto_font_size(
    text: str, weight: str, max_size: int, max_w: int, max_lines: int = 2
) -> tuple[int, list[str]]:
    """テキストが max_w に収まる最大フォントサイズと折り返し行を返す。"""
    for size in range(max_size, 28, -2):
        font = get_font(weight, size)
        lines = _wrap_text(text, font, max_w)
        if len(lines) <= max_lines:
            return size, lines
    font = get_font(weight, 30)
    return 30, _wrap_text(text, font, max_w)


def add_text_to_stamp(img: Image.Image, text: str, reaction: str) -> Image.Image:
    stamp = img.resize((STAMP_W, STAMP_H), Image.LANCZOS).convert("RGBA")
    style = REACTION_STYLES.get(reaction, DEFAULT_STYLE)

    margin = 14
    ow = style["outline_w"]
    max_w = STAMP_W - margin * 2 - ow * 2

    # テキストが収まる最大サイズを自動決定
    font_size, lines = _auto_font_size(text, style["weight"], style["size"], max_w)
    font = get_font(style["weight"], font_size)

    effect = style["effect"]
    line_h = font_size + 10
    total_h = line_h * len(lines)
    y_base = STAMP_H - total_h - margin - ow

    for li, line in enumerate(lines):
        tw = _text_total_width(line, font)
        x0 = (STAMP_W - tw) // 2
        y0 = y_base + li * line_h

        # --- 1. ドロップシャドウ（ぼかし） ---
        if style.get("shadow"):
            shadow_layer = Image.new("RGBA", stamp.size, (0, 0, 0, 0))
            sd = ImageDraw.Draw(shadow_layer)
            _draw_chars(sd, line, font, x0 + 4, y0 + 4, effect, style["shadow"])
            shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(radius=4))
            stamp = Image.alpha_composite(stamp, shadow_layer)

        # --- 2. 縁取り ---
        ow = style["outline_w"]
        outline_layer = Image.new("RGBA", stamp.size, (0, 0, 0, 0))
        od = ImageDraw.Draw(outline_layer)
        oc = style["outline"] + (255,)
        for dx in range(-ow, ow + 1):
            for dy in range(-ow, ow + 1):
                if abs(dx) + abs(dy) >= ow:
                    _draw_chars(od, line, font, x0 + dx, y0 + dy, effect, oc)
        stamp = Image.alpha_composite(stamp, outline_layer)

        # --- 3. グラデーション本文 ---
        text_mask = Image.new("L", stamp.size, 0)
        td = ImageDraw.Draw(text_mask)
        _draw_chars(td, line, font, x0, y0, effect, 255)

        grad_img = _make_gradient(stamp.size, style["grad"][0], style["grad"][1])
        grad_rgba = grad_img.convert("RGBA")
        grad_layer = Image.new("RGBA", stamp.size, (0, 0, 0, 0))
        grad_layer.paste(grad_rgba, mask=text_mask)
        stamp = Image.alpha_composite(stamp, grad_layer)

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
    return Image.open(io.BytesIO(base64.b64decode(img_b64))).convert("RGBA")


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
