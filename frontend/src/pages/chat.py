import time

import streamlit as st

st.title("チャット")

if "messages" not in st.session_state:
    st.session_state.messages = []

# 履歴表示
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])


def fake_stream_response(user_text: str):
    """ダミーのストリーミング応答。FastAPI 連携時に差し替える。"""
    text = f"あなたの入力は「{user_text}」です。これはストリーミング応答のサンプルです。"
    for token in text:
        yield token
        time.sleep(0.03)


if prompt := st.chat_input("メッセージを入力"):
    st.session_state.messages.append({"role": "user", "content": prompt})

    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        response_text = st.write_stream(fake_stream_response(prompt))

    st.session_state.messages.append({"role": "assistant", "content": response_text})
