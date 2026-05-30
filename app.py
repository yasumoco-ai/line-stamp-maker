import streamlit as st
from PIL import Image
from openai import OpenAI
import tempfile
import os
from stamp_generator import REACTIONS, create_stamp_zip

st.set_page_config(page_title="LINEスタンプメーカー", page_icon="🎨", layout="centered")

st.title("🎨 LINEスタンプメーカー")
st.caption("オリジナルキャラクター画像＋セリフ → LINEスタンプ（ZIP）を自動生成")

# --- Sidebar: API Key ---
with st.sidebar:
    st.header("⚙️ 設定")
    api_key = st.text_input("OpenAI APIキー", type="password", placeholder="sk-...")
    st.caption("キーはこのセッション内のみ使用。保存されません。")
    st.divider()
    st.markdown("**LINEスタンプ規格**")
    st.markdown("- サイズ：370×320px\n- 形式：PNG\n- 枚数：8〜40枚")
    st.divider()
    st.markdown("**💰 APIコストの目安**")
    st.markdown("gpt-image-1使用\n- 1枚あたり約 $0.04〜0.08\n- 8枚セットで約 $0.3〜0.6")
    st.caption("OpenAI APIキーは各自でご用意ください")

if not api_key:
    st.info("サイドバーにOpenAI APIキーを入力してください。")
    st.stop()

client = OpenAI(api_key=api_key)

# --- Step 1: Upload character image ---
st.header("① キャラクター画像をアップロード")
uploaded = st.file_uploader("元画像（PNG / JPG）", type=["png", "jpg", "jpeg"])
ref_image = None
if uploaded:
    ref_image = Image.open(uploaded).convert("RGBA")
    st.image(ref_image, caption="アップロードされたキャラクター", width=250)

# --- Step 2: Define stamps ---
st.header("② スタンプの設定（セリフ＋リアクション）")

reaction_options = list(REACTIONS.keys())
num_stamps = st.slider("スタンプ枚数", min_value=2, max_value=24, value=8, step=1)

stamp_configs = []
cols_per_row = 2

for i in range(num_stamps):
    if i % cols_per_row == 0:
        cols = st.columns(cols_per_row)
    with cols[i % cols_per_row]:
        st.markdown(f"**スタンプ {i+1}**")
        phrase = st.text_input(f"セリフ", key=f"phrase_{i}", placeholder="例：ありがとう！")
        reaction = st.selectbox(f"リアクション", reaction_options, key=f"reaction_{i}")
        stamp_configs.append({"phrase": phrase, "reaction": reaction})

# --- Step 3: Generate ---
st.header("③ 生成")

if ref_image is None:
    st.warning("キャラクター画像をアップロードしてください。")
elif not any(c["phrase"].strip() for c in stamp_configs):
    st.warning("最低1つセリフを入力してください。")
else:
    valid_configs = [c for c in stamp_configs if c["phrase"].strip()]

    if st.button(f"🚀 スタンプを生成する（{len(valid_configs)}枚）", type="primary", use_container_width=True):
        progress_bar = st.progress(0)
        status_text = st.empty()

        def update_progress(current, total, message):
            progress_bar.progress((current) / total)
            status_text.text(f"[{current+1}/{total}] {message}")

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = os.path.join(tmpdir, "stamps")
            try:
                zip_path = create_stamp_zip(
                    client=client,
                    ref_image=ref_image,
                    stamp_configs=valid_configs,
                    output_path=output_dir,
                    progress_callback=update_progress,
                )
                progress_bar.progress(1.0)
                status_text.text("✅ 生成完了！")

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
                st.caption("ダウンロードしたZIPをLINE Creators Marketへアップロードしてください。")

            except Exception as e:
                st.error(f"エラーが発生しました: {e}")
                progress_bar.empty()
                status_text.empty()

st.divider()
st.caption("LINE Creators Market → https://creator.line.me/")
