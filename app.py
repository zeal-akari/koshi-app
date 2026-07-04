import streamlit as st
import datetime
import json
from fpdf import FPDF
from fpdf.enums import XPos, YPos
import os
import pandas as pd
import altair as alt
from supabase import create_client, Client

with open("questions.json", "r", encoding="utf-8") as f:
    questions = json.load(f)

FONT_PATH = "NotoSansJP-Regular.ttf"
if not os.path.exists(FONT_PATH):
    st.error(f"フォントが見つかりません")
    st.stop()

SUPABASE_URL = "https://ogtteowmytkeritzgcvn.supabase.co"
SUPABASE_KEY = "sb_publishable_TcG-AwawQ_TSM9sTHHhs7w_qNVEQOV2"

@st.cache_resource
def init_supabase():
    return create_client(SUPABASE_URL, SUPABASE_KEY)

supabase = init_supabase()
st.set_page_config(page_title="腰椎分離症チェック", page_icon="🦴")

if "user" not in st.session_state:
    st.session_state.user = None

def show_main_app():
    st.session_state["parent_id"] = st.session_state.user.id
    st.title("🦴 腰椎分離症 セルフチェックアプリ")
    if st.button("ログアウト"):
        supabase.auth.sign_out()
        st.session_state.user = None
        st.rerun()

if st.session_state.user is None:
    st.title("ログイン")
    email = st.text_input("メール")
    password = st.text_input("パスワード", type="password")
    if st.button("ログイン"):
        res = supabase.auth.sign_in_with_password({"email": email, "password": password})
        st.session_state.user = res.user
        st.rerun()
else:
    show_main_app()