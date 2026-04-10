import streamlit as st

st.set_page_config(page_title="Reflection App", layout="wide")

home = st.Page("pages/home.py", title="ホーム", icon="🏠")
chat = st.Page("pages/chat.py", title="チャット", icon="💬")
api_stream = st.Page("pages/api_stream.py", title="API ストリーミング", icon="📡")
a2a_stream = st.Page("pages/a2a_stream.py", title="A2A ストリーミング", icon="🤖")
settings = st.Page("pages/settings.py", title="設定", icon="⚙️")

pg = st.navigation(
    {
        "メニュー": [home, chat, settings],
        "Template 連携": [api_stream, a2a_stream],
    },
    position="sidebar",
)

st.sidebar.title("機能一覧")

pg.run()
