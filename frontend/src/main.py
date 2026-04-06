import streamlit as st

st.set_page_config(page_title="Reflection App", layout="wide")

home = st.Page("pages/home.py", title="ホーム", icon="🏠")
chat = st.Page("pages/chat.py", title="チャット", icon="💬")
settings = st.Page("pages/settings.py", title="設定", icon="⚙️")

pg = st.navigation(
    {
        "メニュー": [home, chat, settings],
    },
    position="sidebar",
)

st.sidebar.title("機能一覧")

pg.run()
