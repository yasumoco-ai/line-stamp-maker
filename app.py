import streamlit as st
from PIL import Image
from openai import OpenAI
from pathlib import Path
import tempfile
import os
from stamp_generator import create_stamp_zip
from batch_parser import parse_stamp_block

st.set_page_config(page_title="LINEスタンプメーカー", page_icon="🎨", layout="wide")
st.title("🎨 LINEスタンプメーカー")

# --- Sidebar ---
with st.sidebar:
    st.header("⚙️ 設定")
    api_key = st.text_input("OpenAI APIキー", type="password", placeholder="sk-...")
    st.caption("セッション内のみ使用。保存されません。")
    st.divider()
    st.markdown("**LINEスタンプ規格**")
    st.markdown("- サイズ：370×320px\n- 形式：PNG\n- 枚数：8〜40枚")
    st.divider()
    st.markdown("**💰 APIコスト目安**")
    st.markdown("gpt-image-1\n- 1枚あたり約 $0.04〜0.08\n- 8枚セットで約 $0.3〜0.6")

if not api_key:
    st.info("サイドバーにOpenAI APIキーを入力してください。")
    st.stop()

client = OpenAI(api_key=api_key)


# ======================================================
# 共通生成関数（タブより前に定義）
# ======================================================
def _build_full_prompt(config: dict) -> str:
    """プロンプトブロックの全要素をそのままAIに渡す文字列を構築。"""
    parts = [
        "LINEスタンプ風イラスト。1024×1024ピクセル、背景は透明。"
        "キャラクターは中央に大きく配置。",
    ]
    if config.get("character_desc"):
        parts.append(f"【キャラクター設定】\n{config['character_desc']}")
    if config.get("art_style"):
        parts.append(f"【画風】\n{config['art_style']}")
    if config.get("phrase"):
        phrase = config["phrase"]
        text_style = config.get("text_style", "")
        serif_block = f'【セリフ】「{phrase}」'
        if text_style:
            serif_block += f"\n・{text_style}"
        parts.append(serif_block)
    if config.get("expression"):
        parts.append(f"【表情・ポーズ】\n{config['expression']}")
    return "\n\n".join(parts)


def _run_batch_generation(client, stamp_configs, output_dir, progress_callback,
                          ai_text=False, ref_image=None):
    from stamp_generator import generate_character_image, add_styled_text, build_image_prompt
    import base64, io, zipfile
    from PIL import Image as PILImage
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    generated_paths = []

    for i, config in enumerate(stamp_configs):
        if progress_callback:
            progress_callback(i, len(stamp_configs), f"「{config['phrase']}」を生成中…")

        if ai_text:
            prompt = _build_full_prompt(config)
            if ref_image is not None:
                # 元絵あり → images.edit でキャラクター一貫性を保つ
                buf = io.BytesIO()
                ref_image.convert("RGB").save(buf, format="PNG")
                buf.seek(0)
                response = client.images.edit(
                    model="gpt-image-1",
                    image=("reference.png", buf, "image/png"),
                    prompt=prompt,
                    size="1024x1024",
                    background="transparent",
                    n=1,
                )
            else:
                # 元絵なし → images.generate
                response = client.images.generate(
                    model="gpt-image-1",
                    prompt=prompt,
                    size="1024x1024",
                    background="transparent",
                    n=1,
                )
            from stamp_generator import STAMP_W, STAMP_H
            img_b64 = response.data[0].b64_json
            stamp = PILImage.open(io.BytesIO(base64.b64decode(img_b64))).convert("RGBA")
            stamp = stamp.resize((STAMP_W, STAMP_H), PILImage.LANCZOS)
        else:
            char_img = generate_character_image(
                client,
                config.get("character_desc", ""),
                config.get("art_style", ""),
                config.get("expression", ""),
                ref_image=ref_image,
            )
            stamp = add_styled_text(char_img, config["phrase"], config.get("text_style", ""))

        filename = out / f"{i+1:02d}.png"
        stamp.save(filename, "PNG")
        generated_paths.append(filename)

    tab_src = Image.open(generated_paths[0]).resize((96, 74)) if generated_paths \
        else Image.new("RGBA", (96, 74), (200, 200, 200, 255))
    tab_path = out / "tab.png"
    tab_src.save(tab_path, "PNG")

    # main.png（240×240、01.pngを縮小）
    main_src = Image.open(generated_paths[0]).resize((240, 240), PILImage.LANCZOS) if generated_paths \
        else PILImage.new("RGBA", (240, 240), (200, 200, 200, 255))
    main_path = out / "main.png"
    main_src.save(main_path, "PNG")

    zip_path = str(out) + ".zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        for p in generated_paths:
            zf.write(p, p.name)
        zf.write(tab_path, "tab.png")
        zf.write(main_path, "main.png")
    return zip_path


tab_batch, tab_manual = st.tabs(["📋 バッチ入力（プロンプトを貼り付け）", "✏️ 手動入力"])


# ======================================================
# TAB 1: バッチ入力
# ======================================================
with tab_batch:
    st.markdown("#### プロンプトブロックをそのまま貼り付けてください")
    st.caption(
        "「========No.1「セリフ」========」の区切り形式で複数スタンプを一括生成できます。"
        "【キャラクター設定】【画風】【セリフ】【表情・ポーズ】を自動認識します。"
    )

    # 元絵アップロード
    col_ref, col_hint = st.columns([1, 2])
    with col_ref:
        batch_ref_upload = st.file_uploader(
            "元絵（任意）", type=["png", "jpg", "jpeg"], key="batch_ref"
        )
        batch_ref_image = None
        if batch_ref_upload:
            batch_ref_image = Image.open(batch_ref_upload).convert("RGBA")
            st.image(batch_ref_image, caption="参照キャラクター", width=160)
    with col_hint:
        st.info(
            "**元絵を添付するとキャラクターが安定します**\n\n"
            "添付あり → `images.edit`（元絵のキャラを参照して生成）\n"
            "添付なし → `images.generate`（プロンプトのみで生成）"
        )

    batch_text = st.text_area(
        "プロンプトブロック",
        height=300,
        placeholder="""========================================
No.1「あっつい〜！」
========================================

【キャラクター設定：ナミダスコ】
・まんまるでふわふわしたミントグリーンのフクロウ
...

【セリフ】「あっつい〜！」
・色：オレンジレッド〜コーラル、白いふち取り

【表情・ポーズ】
・全身がぐにゃ〜っと溶けてとろけるような脱力ポーズ

========================================
No.2「海行きたい！」
========================================
...""",
    )

    # テキスト生成モード選択
    text_mode = st.radio(
        "テキスト（セリフ）の生成方法",
        ["🤖 AIに全部任せる（セリフもAIが描画）", "🖊️ Pillowで確実描画（セリフを後で合成）"],
        help="AIモードはより自然なテキストデザインになりますが、日本語の文字が化ける場合があります。",
    )
    ai_text_mode = text_mode.startswith("🤖")

    # プレビュー
    if batch_text.strip():
        parsed = parse_stamp_block(batch_text)
        if parsed:
            st.success(f"{len(parsed)}枚のスタンプを検出しました")
            with st.expander("検出内容を確認", expanded=False):
                for s in parsed:
                    st.markdown(f"**No.{s['number']} 「{s['phrase']}」**")
                    st.markdown(f"- 文字スタイル: `{s['text_style'] or '（未指定）'}`")
                    st.markdown(f"- 表情・ポーズ: {s['expression'][:80]}...")
                    st.divider()
        else:
            st.warning("スタンプが検出できませんでした。フォーマットを確認してください。")
            parsed = []
    else:
        parsed = []

    if parsed and st.button("🚀 バッチ生成する", type="primary", use_container_width=True, key="batch_btn"):
        progress_bar = st.progress(0)
        status_text = st.empty()

        def batch_progress(current, total, message):
            progress_bar.progress(current / total)
            status_text.text(f"[{current+1}/{total}] {message}")

        preview_cols = st.columns(min(len(parsed), 4))

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = os.path.join(tmpdir, "stamps")
            try:
                # バッチの場合、各スタンプから character_desc / art_style を取得
                # （複数スタンプで異なる場合は各スタンプのものを使う）
                stamp_configs = [
                    {
                        "phrase": s["phrase"],
                        "text_style": s["text_style"],
                        "expression": s["expression"],
                        "character_desc": s["character_desc"],
                        "art_style": s["art_style"],
                    }
                    for s in parsed
                ]

                zip_path = _run_batch_generation(
                    client, stamp_configs, output_dir, batch_progress,
                    ai_text=ai_text_mode,
                    ref_image=batch_ref_image,
                )
                progress_bar.progress(1.0)
                status_text.text("✅ 生成完了！")

                stamp_files = sorted(Path(output_dir).glob("[0-9]*.png"))
                for idx, sf in enumerate(stamp_files):
                    with preview_cols[idx % 4]:
                        st.image(str(sf), use_container_width=True)

                with open(zip_path, "rb") as f:
                    zip_bytes = f.read()

                st.success(f"✨ {len(parsed)}枚のスタンプが完成しました！")
                st.download_button(
                    label="📦 ZIPをダウンロード",
                    data=zip_bytes,
                    file_name="line_stamps.zip",
                    mime="application/zip",
                    use_container_width=True,
                )
            except Exception as e:
                import traceback
                st.error(f"エラー: {e}")
                st.code(traceback.format_exc(), language="text")
                progress_bar.empty()
                status_text.empty()


# ======================================================
# TAB 2: 手動入力
# ======================================================
with tab_manual:
    col_img, col_desc = st.columns([1, 2])
    with col_img:
        uploaded = st.file_uploader("元画像（任意・PNG/JPG）", type=["png", "jpg", "jpeg"])
        ref_image = None
        if uploaded:
            ref_image = Image.open(uploaded).convert("RGBA")
            st.image(ref_image, caption="参照キャラクター", width=200)

    with col_desc:
        character_desc = st.text_area(
            "キャラクター設定",
            height=160,
            placeholder="例：まんまるでふわふわしたミントグリーンのフクロウ…",
            key="manual_char",
        )
        art_style = st.text_area(
            "画風・スタイル",
            height=100,
            placeholder="例：水彩絵の具のような柔らかいタッチ、絵本のような空気感…",
            key="manual_art",
        )

    st.markdown("#### スタンプの設定")
    num_stamps = st.slider("スタンプ枚数", min_value=1, max_value=24, value=4, key="manual_num")
    stamp_configs_manual = []
    for i in range(num_stamps):
        with st.expander(f"スタンプ {i+1}", expanded=(i < 2)):
            c1, c2, c3 = st.columns(3)
            with c1:
                phrase = st.text_input("セリフ", key=f"m_phrase_{i}", placeholder="例：海行きたい！")
            with c2:
                text_style = st.text_input("文字スタイル", key=f"m_ts_{i}",
                    placeholder="例：スカイブルー、ポップ、白ふち取り")
            with c3:
                expression = st.text_area("表情・ポーズ", key=f"m_expr_{i}", height=100,
                    placeholder="例：浮き輪でジャンプ、キラキラ笑顔…")
            stamp_configs_manual.append({
                "phrase": phrase, "text_style": text_style, "expression": expression,
                "character_desc": character_desc, "art_style": art_style,
            })

    valid_manual = [c for c in stamp_configs_manual if c["phrase"].strip()]
    if not valid_manual:
        st.warning("セリフを入力してください。")
    elif st.button(f"🚀 生成する（{len(valid_manual)}枚）", type="primary",
                   use_container_width=True, key="manual_btn"):
        progress_bar2 = st.progress(0)
        status_text2 = st.empty()

        def manual_progress(current, total, message):
            progress_bar2.progress(current / total)
            status_text2.text(f"[{current+1}/{total}] {message}")

        preview_cols2 = st.columns(min(len(valid_manual), 4))
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = os.path.join(tmpdir, "stamps")
            try:
                zip_path = _run_batch_generation(client, valid_manual, output_dir, manual_progress)
                progress_bar2.progress(1.0)
                status_text2.text("✅ 生成完了！")
                stamp_files = sorted(Path(output_dir).glob("[0-9]*.png"))
                for idx, sf in enumerate(stamp_files):
                    with preview_cols2[idx % 4]:
                        st.image(str(sf), use_container_width=True)
                with open(zip_path, "rb") as f:
                    zip_bytes = f.read()
                st.success(f"✨ {len(valid_manual)}枚完成！")
                st.download_button("📦 ZIPをダウンロード", data=zip_bytes,
                    file_name="line_stamps.zip", mime="application/zip",
                    use_container_width=True)
            except Exception as e:
                import traceback
                st.error(f"エラー: {e}")
                st.code(traceback.format_exc(), language="text")

st.divider()
st.caption("LINE Creators Market → https://creator.line.me/")
