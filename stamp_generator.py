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

# フォント種別: "sans"=ゴシック / "sans-bold"=ゴシック太 / "round"=丸ゴシック /
#              "round-bold"=丸ゴシック太 / "serif"=明朝
_BUNDLED: dict[str, list[Path]] = {
    "sans":       [FONT_DIR / "NotoSansJP-Regular.otf"],
    "sans-bold":  [FONT_DIR / "NotoSansJP-Bold.otf"],
    "round":      [FONT_DIR / "MPLUSRounded-Regular.ttf"],
    "round-bold": [FONT_DIR / "MPLUSRounded-Bold.ttf"],
    "serif":      [FONT_DIR / "NotoSerifJP-Regular.otf"],
}
_SYSTEM_FONTS: dict[str, list[str]] = {
    "sans":      ["/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
                  "/System/Library/Fonts/ヒラギノ丸ゴ ProN W4.ttc"],
    "sans-bold": ["/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
                  "/System/Library/Fonts/ヒラギノ角ゴシック W8.ttc"],
    "serif":     ["/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc"],
}
_font_cache: dict = {}


def get_font(style_key: str, size: int) -> ImageFont.FreeTypeFont:
    key = (style_key, size)
    if key in _font_cache:
        return _font_cache[key]

    for path in _BUNDLED.get(style_key, _BUNDLED["sans"]):
        if path.exists():
            f = ImageFont.truetype(str(path), size)
            _font_cache[key] = f
            return f

    for fp in _SYSTEM_FONTS.get(style_key, _SYSTEM_FONTS["sans"]):
        if os.path.exists(fp):
            try:
                f = ImageFont.truetype(fp, size)
                _font_cache[key] = f
                return f
            except Exception:
                continue

    # 最終フォールバック
    fallback = _BUNDLED["sans"][0]
    f = ImageFont.truetype(str(fallback), size)
    _font_cache[key] = f
    return f


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


_FONT_KEYWORDS: list[tuple[list[str], str]] = [
    (["丸ゴシック", "まるごしっく", "丸文字", "ポップ", "ふわふわ", "かわいい", "ラウンド", "pop"], "round-bold"),
    (["丸ゴシック細", "ポップ細", "やわらか"],                                                     "round"),
    (["明朝", "みんちょう", "serif", "和風", "筆"],                                                "serif"),
    (["ゴシック太", "太字", "ボールド", "インパクト", "強調"],                                      "sans-bold"),
    (["ゴシック", "gothic", "sans"],                                                              "sans"),
]

# フチ色キーワード（"フチ"付きで色キーワードとの衝突を回避）
_OUTLINE_KEYWORDS: list[tuple[list[str], tuple]] = [
    (["黄フチ", "黄色フチ", "きいろフチ", "イエローフチ", "金フチ"], (255, 230, 0)),
    (["赤フチ", "赤いフチ", "レッドフチ", "オレンジフチ"],           (255, 60, 60)),
    (["黒フチ", "ブラックフチ"],                                     (0, 0, 0)),
    (["ピンクフチ"],                                                  (255, 100, 160)),
    (["白フチ", "ホワイトフチ"],                                      (255, 255, 255)),
]


def _detect_font_key(text_style: str) -> str:
    for keywords, font_key in _FONT_KEYWORDS:
        if any(kw in text_style for kw in keywords):
            return font_key
    return "sans"


def _parse_text_style(text_style: str) -> dict:
    """text_styleの文字列からスタイル情報を抽出。"""
    grad = _DEFAULT_GRAD
    for keywords, c1, c2 in _COLOR_KEYWORDS:
        if any(kw in text_style for kw in keywords):
            grad = (c1, c2)
            break

    font_key = _detect_font_key(text_style)
    is_bold = "bold" in font_key

    # フチ色：明示指定があればそれを使い、なければ文字色の明暗で自動決定
    outline_color = None
    for keywords, color in _OUTLINE_KEYWORDS:
        if any(kw in text_style for kw in keywords):
            outline_color = color
            break

    if outline_color is None:
        # 文字色が暗い（デフォルト黒系 or 明示的に"黒"）場合は白フチ
        is_dark_text = (grad == _DEFAULT_GRAD or any(kw in text_style for kw in ["黒", "ブラック", "くろ"]))
        outline_color = (255, 255, 255) if is_dark_text else (0, 0, 0)

    # 暗い文字はフチを太めにして視認性を上げる
    is_dark_text_final = (grad == _DEFAULT_GRAD or any(kw in text_style for kw in ["黒", "ブラック", "くろ"]))
    outline_w = 7 if is_dark_text_final else 5

    effect = "bounce" if is_bold else "standard"
    if any(kw in text_style for kw in ["波", "ウェーブ", "wavy", "ゆらゆら"]):
        effect = "wavy"

    return {
        "grad": list(grad),
        "outline": outline_color,
        "outline_w": outline_w,
        "font_key": font_key,
        "effect": effect,
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


def _auto_size(text: str, font_key: str, max_size: int, max_w: int) -> tuple[int, list[str]]:
    for sz in range(max_size, 30, -2):
        font = get_font(font_key, sz)
        lines = _wrap(text, font, max_w)
        if len(lines) <= 2:
            return sz, lines
    font = get_font(font_key, 32)
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
    font_key = style["font_key"]
    ow = style["outline_w"]
    margin = 14
    max_w = STAMP_W - margin * 2 - ow * 2

    font_size, lines = _auto_size(phrase, font_key, 76, max_w)
    font = get_font(font_key, font_size)
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
        "LINE sticker illustration. 1024x1024px, transparent background. "
        "Character placed large at center. NO text or letters in image. "
        "MANDATORY: extremely dynamic and exaggerated pose, explosive energy, "
        "maximum movement and action, anime-style over-the-top expression, "
        "body in mid-action (jumping, spinning, leaping, flying), "
        "motion lines, hair and clothes flying, eyes wide and expressive, "
        "never static or standing still — always caught in maximum motion."
    ]
    if character_desc.strip():
        parts.append(f"CHARACTER:\n{character_desc.strip()}")
    if art_style.strip():
        parts.append(f"ART STYLE:\n{art_style.strip()}")
    if expression.strip():
        parts.append(f"POSE & EXPRESSION (execute with maximum exaggeration):\n{expression.strip()}")
    return "\n\n".join(parts)


def generate_character_image(
    client: OpenAI,
    character_desc: str,
    art_style: str,
    expression: str,
    ref_image: Image.Image | None = None,
) -> Image.Image:
    prompt = build_image_prompt(character_desc, art_style, expression)

    response = client.images.generate(
        model="gpt-image-1",
        prompt=prompt,
        size="1024x1024",
        background="transparent",
        n=1,
    )

    img_b64 = response.data[0].b64_json
    img = Image.open(io.BytesIO(base64.b64decode(img_b64))).convert("RGBA")
    return img.resize((STAMP_W, STAMP_H), Image.LANCZOS)


def _translate_to_english(api_key: str, character_desc: str,
                          art_style: str, expression: str) -> str:
    """日本語のキャラクター設定を英語に翻訳（日本語はASCIIエラーになるため必須）。"""
    from google import genai as gai
    gclient = gai.Client(api_key=api_key)
    resp = gclient.models.generate_content(
        model="gemini-2.0-flash",
        contents=(
            "Translate this LINE sticker character description from Japanese to English. "
            "Output only the English translation, concise, suitable for image generation.\n\n"
            f"Character: {character_desc}\nArt style: {art_style}\nPose/Expression: {expression}"
        ),
    )
    return resp.text.strip()


def _find_image_gen_model(gclient) -> str | None:
    """利用可能な画像生成対応モデルを動的に検索する（flash-expを優先）。"""
    try:
        for model in gclient.models.list():
            name = model.name.replace("models/", "")
            # flash-exp が最も安定した画像生成対応モデル
            if "flash-exp" in name and "image" not in name:
                return name
    except Exception:
        pass
    return None


def generate_character_image_gemini(
    api_key: str,
    character_desc: str,
    art_style: str,
    expression: str,
) -> Image.Image:
    """Gemini で画像を生成する（モデルを動的検索＋Imagen 3フォールバック）。"""
    from google import genai as gai
    from google.genai import types as gtypes

    # 画像生成モデルは v1alpha でしか動かないものがある
    gclient = gai.Client(
        api_key=api_key,
        http_options=gtypes.HttpOptions(api_version="v1alpha"),
    )

    # 日本語→英語翻訳（ASCIIエラー回避）
    english = _translate_to_english(api_key, character_desc, art_style, expression)
    prompt = (
        "LINE sticker illustration. 1024x1024px, transparent background. "
        "Character placed large at center. NO text or letters in image. "
        "MANDATORY: extremely dynamic and exaggerated pose, explosive energy, "
        "maximum movement, anime-style over-the-top expression, never static.\n"
        + english
    )

    # 動的にモデルを検索して試す（flash-exp 系を優先）
    dynamic_model = _find_image_gen_model(gclient)
    candidates = []
    if dynamic_model:
        candidates.append(dynamic_model)
    # 固定フォールバックリスト（preview-image-generation は最後）
    for m in ["gemini-2.0-flash-exp",
              "gemini-2.0-flash-preview-image-generation",
              "gemini-2.0-flash",
              "gemini-1.5-flash"]:
        if m not in candidates:
            candidates.append(m)

    last_error = None
    for model_name in candidates:
        for api_ver in ["v1alpha", "v1beta"]:
            try:
                vc = gai.Client(
                    api_key=api_key,
                    http_options=gtypes.HttpOptions(api_version=api_ver),
                )
                response = vc.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=gtypes.GenerateContentConfig(
                        response_modalities=["IMAGE", "TEXT"]
                    ),
                )
                for part in response.candidates[0].content.parts:
                    if part.inline_data is not None:
                        img = Image.open(io.BytesIO(part.inline_data.data)).convert("RGBA")
                        return img.resize((STAMP_W, STAMP_H), Image.LANCZOS)
            except Exception as e:
                last_error = e
                continue

    # generateContent 全滅 → Imagen 3（課金ユーザー向け）
    for imagen_model in ["imagen-3.0-generate-002", "imagen-3.0-fast-generate-001",
                         "imagen-4.0-generate-preview-05-20"]:
        for api_ver in ["v1alpha", "v1beta"]:
            try:
                vc = gai.Client(
                    api_key=api_key,
                    http_options=gtypes.HttpOptions(api_version=api_ver),
                )
                response = vc.models.generate_images(
                    model=imagen_model,
                    prompt=prompt,
                    config=gtypes.GenerateImagesConfig(number_of_images=1),
                )
                img_bytes = response.generated_images[0].image.image_bytes
                img = Image.open(io.BytesIO(img_bytes)).convert("RGBA")
                return img.resize((STAMP_W, STAMP_H), Image.LANCZOS)
            except Exception as e:
                last_error = e

    raise ValueError(
        f"Geminiで画像生成できませんでした。\n"
        f"無料Gemini APIでは現在画像生成が利用できない可能性があります。\n"
        f"詳細: {last_error}"
    )


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

        filename = out / f"{i+1:02d}.png"
        stamp.save(filename, "PNG")
        generated_paths.append(filename)

    # タブ画像
    tab_src = Image.open(generated_paths[0]).resize((96, 74)) if generated_paths else Image.new("RGBA", (96, 74), (200, 200, 200, 255))
    tab_path = out / "tab.png"
    tab_src.save(tab_path, "PNG")

    # main.png（240×240、01.pngを縮小）
    main_src = Image.open(generated_paths[0]).resize((240, 240), Image.LANCZOS) if generated_paths else Image.new("RGBA", (240, 240), (200, 200, 200, 255))
    main_path = out / "main.png"
    main_src.save(main_path, "PNG")

    zip_path = str(out) + ".zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        for p in generated_paths:
            zf.write(p, p.name)
        zf.write(tab_path, "tab.png")
        zf.write(main_path, "main.png")

    return zip_path
