import os
import base64
import zipfile
import math
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from openai import OpenAI
import io

STAMP_W, STAMP_H = 370, 320

FONT_DIR = Path(__file__).parent
_BUNDLED = {
    "regular": FONT_DIR / "NotoSansJP-Regular.otf",
    "bold":    FONT_DIR / "NotoSansJP-Bold.otf",
}
_SYSTEM_FONTS = {
    "regular": [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/System/Library/Fonts/ヒラギノ丸ゴ ProN W4.ttc",
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
    bundled = _BUNDLED.get(weight, _BUNDLED["regular"])
    if bundled.exists():
        f = ImageFont.truetype(str(bundled), size)
        _font_cache[key] = f
        return f
    for fp in _SYSTEM_FONTS.get(weight, _SYSTEM_FONTS["regular"]):
        if os.path.exists(fp):
            try:
                f = ImageFont.truetype(fp, size)
                _font_cache[key] = f
                return f
            except Exception:
                continue
    fallback = _BUNDLED["regular"]
    if fallback.exists():
        f = ImageFont.truetype(str(fallback), size)
        _font_cache[key] = f
        return f
    raise RuntimeError("フォントが見つかりません")


# ── テキストスタイルのキーワード→色マッピング ──────────────────
_COLOR_KEYWORDS: list[tuple[list[str], tuple, tuple]] = [
    (["スカイブルー", "空色", "水色"],       (100, 200, 255), (0, 130, 220)),
    (["ターコイズ", "エメラルド"],            (0, 210, 200),  (0, 155, 155)),
    (["オレンジレッド", "コーラル"],          (255, 90, 50),  (220, 40, 20)),
    (["オレンジ", "橙"],                     (255, 170, 0),  (220, 100, 0)),
    (["レッド", "赤"],                       (220, 30, 30),  (160, 0, 0)),
    (["イエロー", "黄色", "黄"],             (255, 230, 0),  (220, 160, 0)),
    (["ピンク"],                             (255, 100, 160),(220, 40, 120)),
    (["パープル", "紫", "バイオレット"],      (180, 80, 220), (120, 40, 180)),
    (["グリーン", "緑", "ライム"],           (60, 200, 80),  (0, 140, 40)),
    (["ミント", "ミントグリーン"],            (100, 220, 180),(0, 170, 140)),
    (["ホワイト", "白"],                     (240, 240, 240),(200, 200, 200)),
    (["ゴールド", "金色", "金"],             (255, 210, 0),  (180, 130, 0)),
]
_DEFAULT_GRAD = ((50, 50, 50), (20, 20, 20))


def _parse_text_style(text_style: str) -> dict:
    """text_styleの文字列からスタイル情報を抽出。"""
    grad = _DEFAULT_GRAD
    for keywords, c1, c2 in _COLOR_KEYWORDS:
        if any(kw in text_style for kw in keywords):
            grad = (c1, c2)
            break

    outline_color = (255, 255, 255)
    outline_w = 5

    bold = any(kw in text_style for kw in ["ボールド", "太字", "ゴシック", "ポップ", "元気"])

    return {
        "grad": list(grad),
        "outline": outline_color,
        "outline_w": outline_w,
        "weight": "bold" if bold else "regular",
        "effect": "bounce" if bold else "standard",
        "shadow": (0, 0, 0, 130),
    }


# ── テキスト描画ユーティリティ ─────────────────────────────────
def _make_gradient(size, c1, c2):
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


def _char_width(ch: str, font: ImageFont.FreeTypeFont) -> int:
    d = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    bb = d.textbbox((0, 0), ch, font=font)
    return bb[2] - bb[0]


def _total_width(text: str, font: ImageFont.FreeTypeFont) -> int:
    return sum(_char_width(c, font) for c in text)


def _wrap(text: str, font: ImageFont.FreeTypeFont, max_w: int) -> list[str]:
    lines, cur = [], ""
    d = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    for ch in text:
        test = cur + ch
        bb = d.textbbox((0, 0), test, font=font)
        if bb[2] - bb[0] > max_w and cur:
            lines.append(cur)
            cur = ch
        else:
            cur = test
    if cur:
        lines.append(cur)
    return lines


def _auto_size(text: str, weight: str, max_size: int, max_w: int) -> tuple[int, list[str]]:
    for sz in range(max_size, 30, -2):
        font = get_font(weight, sz)
        lines = _wrap(text, font, max_w)
        if len(lines) <= 2:
            return sz, lines
    font = get_font(weight, 32)
    return 32, _wrap(text, font, max_w)


def _draw_chars(draw, text, font, x0, y0, effect, fill):
    x = x0
    for i, ch in enumerate(text):
        if effect == "wavy":
            dy = int(math.sin(i * 1.3) * 7)
        elif effect == "bounce":
            dy = int(abs(math.sin(i * 1.0)) * -6)
        else:
            dy = 0
        draw.text((x, y0 + dy), ch, font=font, fill=fill)
        x += _char_width(ch, font)


def add_styled_text(stamp: Image.Image, phrase: str, text_style: str) -> Image.Image:
    """Pillowでグラデーション＋縁取り＋影のテキストをスタンプに合成。"""
    if not phrase.strip():
        return stamp

    style = _parse_text_style(text_style)
    weight = style["weight"]
    ow = style["outline_w"]
    margin = 14
    max_w = STAMP_W - margin * 2 - ow * 2

    font_size, lines = _auto_size(phrase, weight, 76, max_w)
    font = get_font(weight, font_size)
    effect = style["effect"]
    line_h = font_size + 10
    total_h = line_h * len(lines)
    y_base = STAMP_H - total_h - margin - ow

    for li, line in enumerate(lines):
        tw = _total_width(line, font)
        x0 = (STAMP_W - tw) // 2
        y0 = y_base + li * line_h

        # 影
        if style.get("shadow"):
            sh = Image.new("RGBA", stamp.size, (0, 0, 0, 0))
            sd = ImageDraw.Draw(sh)
            _draw_chars(sd, line, font, x0 + 4, y0 + 4, effect, style["shadow"])
            sh = sh.filter(ImageFilter.GaussianBlur(radius=4))
            stamp = Image.alpha_composite(stamp, sh)

        # 縁取り
        ol = Image.new("RGBA", stamp.size, (0, 0, 0, 0))
        od = ImageDraw.Draw(ol)
        oc = style["outline"] + (255,)
        for dx in range(-ow, ow + 1):
            for dy in range(-ow, ow + 1):
                if abs(dx) + abs(dy) >= ow:
                    _draw_chars(od, line, font, x0 + dx, y0 + dy, effect, oc)
        stamp = Image.alpha_composite(stamp, ol)

        # グラデーション本文
        mask = Image.new("L", stamp.size, 0)
        md = ImageDraw.Draw(mask)
        _draw_chars(md, line, font, x0, y0, effect, 255)
        grad = _make_gradient(stamp.size, style["grad"][0], style["grad"][1]).convert("RGBA")
        gl = Image.new("RGBA", stamp.size, (0, 0, 0, 0))
        gl.paste(grad, mask=mask)
        stamp = Image.alpha_composite(stamp, gl)

    return stamp


# ── 画像生成 ────────────────────────────────────────────────────
def build_image_prompt(
    character_desc: str,
    art_style: str,
    expression: str,
) -> str:
    """テキストなし・キャラクター＋ポーズのみのプロンプトを構築。"""
    parts = [
        "LINEスタンプ風イラスト。1024×1024ピクセル、白背景。"
        "キャラクターは中央に大きく配置。テキストや文字は描かないこと。"
        "表情とポーズは大げさにオーバーアクションで。"
    ]
    if character_desc.strip():
        parts.append(f"【キャラクター設定】\n{character_desc.strip()}")
    if art_style.strip():
        parts.append(f"【画風】\n{art_style.strip()}")
    if expression.strip():
        parts.append(f"【表情・ポーズ・エフェクト】\n{expression.strip()}")
    return "\n\n".join(parts)


def generate_character_image(
    client: OpenAI,
    character_desc: str,
    art_style: str,
    expression: str,
    ref_image: Image.Image | None = None,
) -> Image.Image:
    prompt = build_image_prompt(character_desc, art_style, expression)

    # 参照画像なし → generate（ポーズの自由度が高い）
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
    out = Path(output_path)
    out.mkdir(parents=True, exist_ok=True)
    generated_paths = []

    for i, config in enumerate(stamp_configs):
        phrase = config.get("phrase", "")
        text_style = config.get("text_style", "")
        expression = config.get("expression", "")

        if progress_callback:
            progress_callback(i, len(stamp_configs), f"「{phrase}」を生成中…")

        # Step1: キャラクター＋ポーズをAIで生成（テキストなし）
        char_img = generate_character_image(
            client, character_desc, art_style, expression, ref_image
        )

        # Step2: Pillowでセリフを確実に描画
        stamp = add_styled_text(char_img, phrase, text_style)

        filename = out / f"stamp_{i+1:02d}.png"
        stamp.save(filename, "PNG")
        generated_paths.append(filename)

    # タブ画像
    tab_src = Image.open(generated_paths[0]).resize((96, 74)) if generated_paths else Image.new("RGBA", (96, 74), (200, 200, 200, 255))
    tab_path = out / "tab.png"
    tab_src.save(tab_path, "PNG")

    zip_path = str(out) + ".zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        for p in generated_paths:
            zf.write(p, p.name)
        zf.write(tab_path, "tab.png")

    return zip_path
