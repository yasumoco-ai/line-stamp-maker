import os
import base64
import zipfile
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from openai import OpenAI
import io
import re

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


def image_to_base64(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def generate_expression_image(
    client: OpenAI, ref_image: Image.Image, reaction_label: str, reaction_desc: str
) -> Image.Image:
    """Generate character with specified expression using gpt-image-1."""
    ref_b64 = image_to_base64(ref_image)

    prompt = (
        f"Create a LINE messenger sticker style illustration of this original character "
        f"with a {reaction_desc}. "
        f"Keep the character design, colors, and style identical to the reference image. "
        f"White or transparent background. "
        f"Cute, expressive, sticker-friendly art style. "
        f"No text, no border, clean edges."
    )

    response = client.images.generate(
        model="gpt-image-1",
        prompt=prompt,
        size="1024x1024",
        n=1,
    )

    img_b64 = response.data[0].b64_json
    img_bytes = base64.b64decode(img_b64)
    return Image.open(io.BytesIO(img_bytes)).convert("RGBA")


def add_text_to_stamp(img: Image.Image, text: str) -> Image.Image:
    """Overlay phrase text onto sticker image in LINE sticker format."""
    stamp = img.resize((STAMP_W, STAMP_H), Image.LANCZOS).convert("RGBA")
    draw = ImageDraw.Draw(stamp)

    font_size = 28
    font = None
    font_candidates = [
        "/System/Library/Fonts/ヒラギノ丸ゴ ProN W4.ttc",
        "/System/Library/Fonts/Hiragino Maru Gothic ProN.ttc",
        "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc",
        "/System/Library/Fonts/Arial Unicode MS.ttf",
    ]
    for fp in font_candidates:
        if os.path.exists(fp):
            try:
                font = ImageFont.truetype(fp, font_size)
                break
            except Exception:
                continue
    if font is None:
        font = ImageFont.load_default()

    margin = 10
    max_width = STAMP_W - margin * 2

    # Wrap text
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

    line_h = font_size + 4
    total_h = line_h * len(lines) + 8
    text_y = STAMP_H - total_h - margin

    # Draw shadow then text
    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=font)
        text_w = bbox[2] - bbox[0]
        x = (STAMP_W - text_w) // 2
        y = text_y + i * line_h
        # Outline
        for dx in [-2, 0, 2]:
            for dy in [-2, 0, 2]:
                draw.text((x + dx, y + dy), line, font=font, fill=(255, 255, 255, 220))
        draw.text((x, y), line, font=font, fill=(30, 30, 30, 255))

    return stamp


def create_stamp_zip(
    client: OpenAI,
    ref_image: Image.Image,
    stamp_configs: list[dict],
    output_path: str,
    progress_callback=None,
) -> str:
    """
    stamp_configs: [{"phrase": str, "reaction": str}, ...]
    Returns path to the created ZIP file.
    """
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
        except Exception as e:
            # Fallback: use reference image directly
            expr_img = ref_image.copy().convert("RGBA")

        stamp = add_text_to_stamp(expr_img, phrase)

        filename = out / f"stamp_{i+1:02d}.png"
        stamp.save(filename, "PNG")
        generated_paths.append(filename)

    # Create tab image (96x74)
    tab_img = ref_image.resize((96, 74), Image.LANCZOS)
    tab_path = out / "tab.png"
    tab_img.save(tab_path, "PNG")

    # ZIP everything
    zip_path = str(out) + ".zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        for p in generated_paths:
            zf.write(p, p.name)
        zf.write(tab_path, "tab.png")

    return zip_path
