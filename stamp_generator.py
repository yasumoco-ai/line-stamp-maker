import base64
import zipfile
from pathlib import Path
from PIL import Image
from openai import OpenAI
import io

STAMP_W, STAMP_H = 370, 320

BASE_INSTRUCTION = """LINEスタンプ風イラスト。1024×1024ピクセル、背景は白（またはほぼ白）。
キャラクターは中央〜やや下寄りに大きく配置。
クリーンな線画、パステルカラー、高品質なかわいいマスコットデザイン。
表情とポーズは大げさにオーバーアクションで。"""


def build_prompt(
    character_desc: str,
    art_style: str,
    phrase: str,
    text_style: str,
    expression: str,
) -> str:
    parts = [BASE_INSTRUCTION]

    if character_desc.strip():
        parts.append(f"【キャラクター設定】\n{character_desc.strip()}")

    if art_style.strip():
        parts.append(f"【画風】\n{art_style.strip()}")

    if phrase.strip():
        parts.append(f'【セリフ】「{phrase.strip()}」')
        if text_style.strip():
            parts.append(f"・文字スタイル：{text_style.strip()}")

    if expression.strip():
        parts.append(f"【表情・ポーズ】\n{expression.strip()}")

    return "\n\n".join(parts)


def generate_stamp_image(
    client: OpenAI,
    prompt: str,
    ref_image: Image.Image | None = None,
) -> Image.Image:
    """フルプロンプトでスタンプ1枚を生成。ref_imageがあればedit、なければgenerate。"""
    if ref_image is not None:
        buf = io.BytesIO()
        ref_image.convert("RGB").save(buf, format="PNG")
        buf.seek(0)
        response = client.images.edit(
            model="gpt-image-1",
            image=("character.png", buf, "image/png"),
            prompt=prompt,
            size="1024x1024",
            n=1,
        )
    else:
        response = client.images.generate(
            model="gpt-image-1",
            prompt=prompt,
            size="1024x1024",
            n=1,
        )

    img_b64 = response.data[0].b64_json
    img = Image.open(io.BytesIO(base64.b64decode(img_b64))).convert("RGBA")
    return img.resize((STAMP_W, STAMP_H), Image.LANCZOS)


def create_stamp_zip(
    client: OpenAI,
    ref_image: Image.Image | None,
    character_desc: str,
    art_style: str,
    stamp_configs: list[dict],
    output_path: str,
    progress_callback=None,
) -> str:
    """
    stamp_configs: [{"phrase": str, "text_style": str, "expression": str}, ...]
    """
    out = Path(output_path)
    out.mkdir(parents=True, exist_ok=True)
    generated_paths = []

    for i, config in enumerate(stamp_configs):
        phrase = config.get("phrase", "")
        text_style = config.get("text_style", "")
        expression = config.get("expression", "")

        if progress_callback:
            progress_callback(i, len(stamp_configs), f"「{phrase}」を生成中…")

        prompt = build_prompt(character_desc, art_style, phrase, text_style, expression)

        try:
            stamp = generate_stamp_image(client, prompt, ref_image)
        except Exception as e:
            if ref_image is not None:
                stamp = ref_image.resize((STAMP_W, STAMP_H), Image.LANCZOS).convert("RGBA")
            else:
                stamp = Image.new("RGBA", (STAMP_W, STAMP_H), (240, 240, 240, 255))

        filename = out / f"stamp_{i+1:02d}.png"
        stamp.save(filename, "PNG")
        generated_paths.append(filename)

    # タブ画像
    if ref_image is not None:
        tab_img = ref_image.resize((96, 74), Image.LANCZOS)
    else:
        tab_img = generated_paths[0] and Image.open(generated_paths[0]).resize((96, 74))
    tab_path = out / "tab.png"
    tab_img.save(tab_path, "PNG")

    zip_path = str(out) + ".zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        for p in generated_paths:
            zf.write(p, p.name)
        zf.write(tab_path, "tab.png")

    return zip_path
