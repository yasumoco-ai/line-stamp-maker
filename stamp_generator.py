import os
import base64
import zipfile
import urllib.request
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
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

FONT_URL = "https://github.com/googlefonts/noto-cjk/raw/main/Sans/OTF/Japanese/NotoSansCJKjp-Regular.otf"
FONT_LOCAL = Path(__file__).parent / "NotoSansCJKjp-Regular.otf"


def get_font(size: int) -> ImageFont.FreeTypeFont:
    candidates = [
        # Streamlit Cloud (Linux) - apt packages.txt でインストール
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        str(FONT_LOCAL),
        # Mac
        "/System/Library/Fonts/ヒラギノ丸ゴ ProN W4.ttc",
        "/System/Library/Fonts/Hiragino Maru Gothic ProN.ttc",
        "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc",
    ]
    for fp in candidates:
        if os.path.exists(fp):
            try:
                return ImageFont.truetype(fp, size)
            except Exception:
                continue

    # フォントが見つからない場合はダウンロード
    if not FONT_LOCAL.exists():
        urllib.request.urlretrieve(FONT_URL, FONT_LOCAL)
    return ImageFont.truetype(str(FONT_LOCAL), size)


def generate_expression_image(
    client: OpenAI, ref_image: Image.Image, reaction_label: str, reaction_desc: str
) -> Image.Image:
    """images.edit でキャラクターの見た目を保ちながら表情を変える。"""
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


def add_text_to_stamp(img: Image.Image, text: str) -> Image.Image:
    """セリフテキストをスタンプ画像に重ねる。"""
    stamp = img.resize((STAMP_W, STAMP_H), Image.LANCZOS).convert("RGBA")
    draw = ImageDraw.Draw(stamp)

    font_size = 30
    font = get_font(font_size)

    margin = 12
    max_width = STAMP_W - margin * 2

    # 折り返し処理
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

    line_h = font_size + 6
    total_h = line_h * len(lines) + 8
    text_y = STAMP_H - total_h - margin

    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=font)
        text_w = bbox[2] - bbox[0]
        x = (STAMP_W - text_w) // 2
        y = text_y + i * line_h
        # 白縁取り
        for dx in [-2, -1, 0, 1, 2]:
            for dy in [-2, -1, 0, 1, 2]:
                if dx != 0 or dy != 0:
                    draw.text((x + dx, y + dy), line, font=font, fill=(255, 255, 255, 230))
        draw.text((x, y), line, font=font, fill=(20, 20, 20, 255))

    return stamp


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

        stamp = add_text_to_stamp(expr_img, phrase)

        filename = out / f"stamp_{i+1:02d}.png"
        stamp.save(filename, "PNG")
        generated_paths.append(filename)

    # タブ画像
    tab_img = ref_image.resize((96, 74), Image.LANCZOS)
    tab_path = out / "tab.png"
    tab_img.save(tab_path, "PNG")

    zip_path = str(out) + ".zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        for p in generated_paths:
            zf.write(p, p.name)
        zf.write(tab_path, "tab.png")

    return zip_path
