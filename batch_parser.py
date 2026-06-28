import re


def parse_stamp_block(text: str) -> list[dict]:
    """
    ========...======== / No.X「セリフ」 / ========...======== の区切りで
    テキストブロックを複数スタンプ設定に分解する。

    Returns: [{"number": int, "phrase": str, "text_style": str,
               "expression": str, "character_desc": str, "art_style": str}, ...]
    """
    separator_pattern = re.compile(
        r'={8,}[^\n]*\n\s*No\.(\d+)\s*[「『]([^」』\n]+)[」』][^\n]*\n\s*={8,}',
        re.MULTILINE
    )
    matches = list(separator_pattern.finditer(text))
    if not matches:
        return []

    stamps = []
    for i, match in enumerate(matches):
        number = int(match.group(1))
        # 二重かっこ「「...」」などに対応：前後の余分な括弧を除去
        phrase = match.group(2).strip().lstrip('「『').rstrip('」』')

        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        content = text[start:end].strip()

        character_desc = _extract_section(content, "キャラクター設定")
        art_style      = _extract_section(content, "画風")
        serif_block    = _extract_section(content, "セリフ")
        expression     = _extract_section(content, "表情・ポーズ")

        # セリフブロックから色・書体の指定だけ抜く（「セリフ」本文行は除外）
        text_style_lines = []
        for line in serif_block.splitlines():
            stripped = line.strip().lstrip("・")
            if stripped.startswith("色：") or "書体" in stripped or "フォント" in stripped \
               or "ふち" in stripped or "デザイン" in stripped or "ゆら" in stripped \
               or stripped.startswith("文字"):
                text_style_lines.append(stripped)
        text_style = " ".join(text_style_lines)

        stamps.append({
            "number": number,
            "phrase": phrase,
            "text_style": text_style,
            "expression": expression,
            "character_desc": character_desc,
            "art_style": art_style,
        })

    return stamps


def _extract_section(content: str, section_name: str) -> str:
    """【セクション名...】〜次の【 or 末尾 までを抽出。
    見出し行の同行テキスト（「セリフ」本文など）はスキップして次行以降を返す。
    """
    pattern = re.compile(
        rf'【{re.escape(section_name)}[^】]*】[^\n]*\n(.*?)(?=\n【|\Z)',
        re.DOTALL
    )
    m = pattern.search(content)
    if not m:
        return ""
    return m.group(1).strip()
