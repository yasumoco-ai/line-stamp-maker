import streamlit as st
from PIL import Image
from openai import OpenAI
import tempfile
import os
from stamp_generator import create_stamp_zip

st.set_page_config(page_title="LINEスタンプメーカー", page_icon="🎨", layout="wide")

st.title("🎨 LINEスタンプメーカー")
st.caption("キャラクター設定・セリフ・ポーズをAIに丸ごと渡して、スタンプを1枚ずつ生成します")

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

# ==============================
# Step 1: キャラクター共通設定
# ==============================
st.header("① キャラクター共通設定")

col_img, col_desc = st.columns([1, 2])

with col_img:
    uploaded = st.file_uploader("元画像（任意・PNG/JPG）", type=["png", "jpg", "jpeg"])
    ref_image = None
    if uploaded:
        ref_image = Image.open(uploaded).convert("RGBA")
        st.image(ref_image, caption="参照キャラクター", width=200)
    st.caption("画像があればAIが参照します。なくてもテキスト設定だけで生成できます。")

with col_desc:
    character_desc = st.text_area(
        "キャラクター設定（見た目・性格など）",
        height=180,
        placeholder="""例：
まんまるでふわふわしたミントグリーンのフクロウ
白い胸毛、淡い水色〜ミントグリーンの羽
オレンジ色の小さなくちばしと足
目はとても大きく、キラキラした青い瞳
ほっぺはほんのりピンク""",
    )

    art_style = st.text_area(
        "画風・スタイル（共通）",
        height=120,
        placeholder="""例：
水彩絵の具のような柔らかいタッチ、にじみ感、アナログ感
絵本のような暖かい空気感
クリーンな線画、パステルカラー、高品質なかわいいマスコットデザイン""",
    )

# ==============================
# Step 2: スタンプごとの設定
# ==============================
st.header("② スタンプの設定（セリフ・文字スタイル・ポーズ）")

num_stamps = st.slider("スタンプ枚数", min_value=1, max_value=24, value=4)

stamp_configs = []
for i in range(num_stamps):
    with st.expander(f"スタンプ {i+1}", expanded=(i < 3)):
        c1, c2, c3 = st.columns(3)
        with c1:
            phrase = st.text_input("セリフ", key=f"phrase_{i}", placeholder="例：海行きたい！")
        with c2:
            text_style = st.text_input(
                "文字スタイル",
                key=f"ts_{i}",
                placeholder="例：スカイブルー〜ターコイズ、白いふち取り、元気いっぱいポップ体",
            )
        with c3:
            expression = st.text_area(
                "表情・ポーズ・エフェクト",
                key=f"expr_{i}",
                height=100,
                placeholder="""例：
浮き輪を体に通してウィングを高く上げてジャンプ
目をキラキラ最大限に輝かせて全力笑顔
頭にサングラス、周囲に波しぶきや貝殻""",
            )
        stamp_configs.append({
            "phrase": phrase,
            "text_style": text_style,
            "expression": expression,
        })

# ==============================
# Step 3: 生成
# ==============================
st.header("③ 生成")

valid_configs = [c for c in stamp_configs if c["phrase"].strip()]

if not valid_configs:
    st.warning("最低1つセリフを入力してください。")
else:
    if st.button(
        f"🚀 スタンプを生成する（{len(valid_configs)}枚）",
        type="primary",
        use_container_width=True,
    ):
        progress_bar = st.progress(0)
        status_text = st.empty()

        def update_progress(current, total, message):
            progress_bar.progress(current / total)
            status_text.text(f"[{current+1}/{total}] {message}")

        preview_cols = st.columns(min(len(valid_configs), 4))

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = os.path.join(tmpdir, "stamps")
            try:
                zip_path = create_stamp_zip(
                    client=client,
                    ref_image=ref_image,
                    character_desc=character_desc,
                    art_style=art_style,
                    stamp_configs=valid_configs,
                    output_path=output_dir,
                    progress_callback=update_progress,
                )
                progress_bar.progress(1.0)
                status_text.text("✅ 生成完了！")

                # プレビュー表示
                from pathlib import Path
                stamp_files = sorted(Path(output_dir).glob("stamp_*.png"))
                for idx, sf in enumerate(stamp_files):
                    with preview_cols[idx % 4]:
                        st.image(str(sf), use_container_width=True)

                with open(zip_path, "rb") as f:
                    zip_bytes = f.read()

                st.success(f"✨ {len(valid_configs)}枚のスタンプが完成しました！")
                st.download_button(
                    label="📦 ZIPをダウンロード",
                    data=zip_bytes,
                    file_name="line_stamps.zip",
                    mime="application/zip",
                    use_container_width=True,
                )
                st.caption("ZIPをLINE Creators Marketへアップロードしてください。")

            except Exception as e:
                import traceback
                st.error(f"エラーが発生しました:\n\n```\n{e}\n```")
                st.code(traceback.format_exc(), language="text")
                progress_bar.empty()
                status_text.empty()

st.divider()
st.caption("LINE Creators Market → https://creator.line.me/")
