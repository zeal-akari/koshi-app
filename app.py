import streamlit as st
import datetime
import json
from fpdf import FPDF
from fpdf.enums import XPos, YPos
import urllib.request
import os
import pandas as pd
import altair as alt
from supabase import create_client, Client

# --- 1. 初期設定と準備 ---
with open("questions.json", "r", encoding="utf-8") as f:
    questions = json.load(f)

FONT_PATH = "NotoSansJP-Regular.ttf"
if not os.path.exists(FONT_PATH):
    with st.spinner("初回起動用の日本語フォントをダウンロード中..."):
        url = "https://github.com/google/fonts/raw/main/ofl/notosansjp/NotoSansJP%5Bwght%5D.ttf"
        urllib.request.urlretrieve(url, FONT_PATH)

SUPABASE_URL = "https://ogtteowmytkeritzgcvn.supabase.co"
SUPABASE_KEY = "sb_publishable_TcG-AwawQ_TSM9sTHHhs7w_qNVEQOV2"

@st.cache_resource
def init_supabase():
    return create_client(SUPABASE_URL, SUPABASE_KEY)

try:
    supabase: Client = init_supabase()
except Exception:
    st.error("Supabaseの接続設定を確認してください。")

st.set_page_config(page_title="腰椎分離症チェック", page_icon="🦴")

if "user" not in st.session_state:
    st.session_state.user = None

def logout():
    supabase.auth.sign_out()
    st.session_state.user = None
    if "current_member" in st.session_state:
        del st.session_state["current_member"]
    if "parent_id" in st.session_state:
        del st.session_state["parent_id"]
    st.rerun()

def show_auth_page():
    st.title("🦴 腰椎分離症 セルフチェック")
    st.caption("自分だけの記録を安全に管理するためのログイン画面です。")
    
    tab1, tab2 = st.tabs(["ログイン", "新規アカウント登録"])
    
    with tab1:
        st.subheader("ログイン")
        email = st.text_input("メールアドレス", key="login_email")
        password = st.text_input("パスワード", type="password", key="login_password")
        if st.button("ログインする", type="primary"):
            try:
                res = supabase.auth.sign_in_with_password({"email": email, "password": password})
                st.session_state.user = res.user
                st.success("ログインしました！")
                st.rerun()
            except Exception as e:
                st.error("ログインに失敗しました。メールアドレスとパスワードを確認してください。")
                
    with tab2:
        st.subheader("新しいアカウントを作成")
        new_email = st.text_input("メールアドレス", key="sign_up_email")
        new_password = st.text_input("パスワード（6文字以上）", type="password", key="sign_up_password")
        if st.button("アカウントを作成する", type="primary"):
            try:
                res = supabase.auth.sign_up({"email": new_email, "password": new_password})
                st.session_state.user = res.user
                st.success("アカウントが作成されました！")
                st.rerun()
            except Exception as e:
                st.error(f"登録に失敗しました（パスワードは6文字以上必要です）: {e}")

def show_main_app():
    st.session_state["parent_id"] = st.session_state.user.id
    
    st.sidebar.success(f"👤 ログイン中:\n{st.session_state.user.email}")
    if st.sidebar.button("🚪 ログアウト"):
        logout()
    st.sidebar.markdown("---")

    st.title("🦴 腰椎分離症 セルフチェックアプリ")
    st.caption("※本アプリは診断を行うものではありません。目安としてご利用ください。")

    try:
        res = supabase.table("user_profile").select("nickname").eq("parent_id", st.session_state["parent_id"]).execute()
        nicknames = [row["nickname"] for row in res.data] if res.data else []
    except Exception:
        nicknames = []

    st.sidebar.header("👥 メンバー管理")
    options = nicknames + ["➕ 新しいメンバーを追加"]

    if "current_member" not in st.session_state:
        st.session_state["current_member"] = options[0] if nicknames else "➕ 新しいメンバーを追加"

    try:
        selected_index = options.index(st.session_state["current_member"])
    except ValueError:
        selected_index = 0

    current_member = st.sidebar.selectbox(
        "操作する人を選んでください：", 
        options, 
        index=selected_index
    )

    if current_member != st.session_state["current_member"]:
        st.session_state["current_member"] = current_member
        st.rerun()

    saved_profile = None
    if current_member != "➕ 新しいメンバーを追加":
        try:
            res_profile = supabase.table("user_profile").select("*").eq("parent_id", st.session_state["parent_id"]).eq("nickname", current_member).execute()
            if res_profile.data:
                saved_profile = res_profile.data[0]
        except Exception:
            pass

    child_user_id = f"{st.session_state['parent_id']}_{current_member}"

    tab1, tab2, tab3 = st.tabs(["👤 メンバー情報", "📝 毎月のチェック", "📈 成長と痛みの推移"])

    with tab1:
        is_new_member = (current_member == "➕ 新しいメンバーを追加")
        
        if is_new_member:
            st.header("👤 新しいメンバーの登録")
            edit_nickname = st.text_input("ニックネーム（例：お兄ちゃん、たろう、次男）", value="")
        else:
            st.header(f"👤 {current_member} さんの情報")
            edit_nickname = current_member

        default_year = int(saved_profile["birth_year"]) if saved_profile else 2012
        default_height = float(saved_profile["init_height"]) if saved_profile else 150.0
        default_weight = float(saved_profile["init_weight"]) if saved_profile else 45.0
        default_sport = saved_profile["sport"] if saved_profile else ""

        if saved_profile and "updated_at" in saved_profile:
            try:
                raw_date = pd.to_datetime(saved_profile["updated_at"])
                formatted_date = raw_date.strftime('%Y年%m月%d日')
                st.info(f"📅 登録日: **{formatted_date}**")
            except Exception:
                pass

        this_year = datetime.datetime.now().year
        birth_year = st.number_input("生年（西暦）", min_value=this_year-30, max_value=this_year, value=default_year, disabled=not is_new_member)
        age = this_year - birth_year
        st.info(f"💡 現在の計算年齢: **{age} 歳**")
        
        init_height = st.number_input("登録時の身長 (cm)", min_value=100.0, max_value=250.0, value=default_height, step=0.1, disabled=not is_new_member)
        init_weight = st.number_input("登録時の体重 (kg)", min_value=20.0, max_value=200.0, value=default_weight, step=0.1, disabled=not is_new_member)
        
        sport = st.text_input("活動しているスポーツ（例：野球、サッカー）", value=default_sport)
        
        if is_new_member:
            st.markdown("---")
            st.write("📈 **アプリのデータ活用について**")
            consent = st.checkbox("【同意のお願い】入力されたデータは、個人を特定できない匿名データとして集計し、スポーツ障害の予防研究や統計データとして活用されることに同意します。（必須）")
        else:
            consent = True

        button_text = "新しいメンバーを登録する" if is_new_member else "登録情報を更新する"
        if st.button(button_text):
            if not edit_nickname:
                st.error("ニックネームを入力してください。")
            elif is_new_member and not consent:
                st.error("⚠️ メンバーを登録するには、データ活用の同意チェックが必要です。")
            else:
                try:
                    profile_data = {
                        "parent_id": st.session_state["parent_id"],
                        "nickname": edit_nickname,
                        "birth_year": birth_year,
                        "init_height": init_height,
                        "init_weight": init_weight,
                        "sport": sport,
                        "updated_at": str(datetime.datetime.now())
                    }
                    supabase.table("user_profile").upsert(profile_data, on_conflict="parent_id,nickname").execute()
                    st.success(f"✨ {edit_nickname} さんの情報を保存しました！")
                    
                    st.session_state["current_member"] = edit_nickname
                    st.rerun()
                except Exception as e:
                    st.error(f"保存エラー: {e}")

        if not is_new_member:
            st.markdown("---")
            with st.expander("メンバー記録の削除"):
                st.warning(f"「{current_member}」さんのプロフィールと、過去の毎月の記録をすべて完全に削除します。この操作は元に戻せません。")
                if st.button(f"🗑️ {current_member} さんを削除する", type="primary"):
                    try:
                        supabase.table("koshi_history").delete().eq("user_id", child_user_id).execute()
                        supabase.table("user_profile").delete().eq("parent_id", st.session_state["parent_id"]).eq("nickname", current_member).execute()
                        st.success(f"✔️ {current_member} さんのデータをすべて削除しました。")
                        st.session_state["current_member"] = "➕ 新しいメンバーを追加"
                        st.rerun()
                    except Exception as e:
                        st.error(f"削除中にエラーが発生しました: {e}")

    with tab2:
        if current_member == "➕ 新しいメンバーを追加":
            st.warning("⚠️ 左側のメニュー、またはタブ1から、まずはメンバーの登録を行ってください。")
        else:
            st.header(f"📝 {current_member} さんのチェック記録")
            
            st.info("💡 活動しているスポーツが変わったり、追加された場合は、隣の「メンバー情報」タブから変更してください。")
            
            last_height = init_height
            last_weight = init_weight
            try:
                res_latest = supabase.table("koshi_history").select("height, weight").eq("user_id", child_user_id).order("checked_at", desc=True).limit(1).execute()
                if res_latest.data:
                    last_height = float(res_latest.data[0]["height"])
                    last_weight = float(res_latest.data[0]["weight"])
            except Exception:
                pass

            st.subheader("【1】身長・体重の記録")
            st.write("💡 測っていない項目はチェックを入れると、前回の記録をそのまま引き継ぎます。")
            
            not_measured_height = st.checkbox("身長は今回は測っていない")
            if not_measured_height:
                current_height = st.number_input("現在の身長 (cm)", value=last_height, disabled=True)
            else:
                current_height = st.number_input("現在の身長 (cm)", min_value=100.0, max_value=250.0, value=last_height, step=0.1)

            not_measured_weight = st.checkbox("体重は今回は測っていない")
            if not_measured_weight:
                current_weight = st.number_input("現在の体重 (kg)", value=last_weight, disabled=True)
            else:
                current_weight = st.number_input("現在の体重 (kg)", min_value=20.0, max_value=200.0, value=last_weight, step=0.1)

            st.subheader("【2】練習の頻度について")
            days_per_week = st.selectbox("最近、週に何回くらい練習や試合をしていますか？", ["週1日", "週2日", "週3日", "週4日", "週5日", "週6日", "毎日（週7日）", "お休みしている"])
            hours_per_day = st.selectbox("1日あたり、何時間くらい練習していますか？", ["1時間未満", "1〜2時間", "2〜3時間", "3〜4時間", "4時間以上", "お休みしている"])
            
            st.subheader("【3】動作セルフチェック")
            answers = {}
            for q in questions["self_check"]:
                st.markdown(f"### {q['text']}")
                if "video_url" in q:
                    with st.expander("🎬 正しいやり方の確認動画（ここをタップ）"):
                        st.video(q["video_url"])
                answers[q["id"]] = st.radio("回答を選択してください：", q["options"], key=f"check_{q['id']}", label_visibility="collapsed")
                st.markdown("---")
                
            # ==========================================
            # 💡 【大変更】新しい簡易問診と点数計算システム
            # ==========================================
            st.subheader("【4】簡易問診")
            
            daily_pain_options = {"全く痛みはない": 0, "たまにある": 1, "頻繁に痛くなる": 2}
            daily_pain = st.radio("日常生活で腰に痛みが出ますか？", list(daily_pain_options.keys()), key="daily_pain")
            
            sports_pain_options = {"全く痛みはない": 0, "たまにある": 1, "頻繁に痛くなる": 3}
            sports_pain = st.radio("スポーツ（運動時）で腰に痛みが出ますか？", list(sports_pain_options.keys()), key="sports_pain")

            # ユーザーには見えないところで点数を合計する
            monshin_score = daily_pain_options[daily_pain] + sports_pain_options[sports_pain]

            is_alert = False
            # ① 動作セルフチェックで痛みがある場合
            if answers.get("kemp") == "ハッキリと痛い" or answers.get("one_leg") in ["片側だけ痛い", "両方痛い"]:
                is_alert = True
            
            # ② 問診の合計スコアが3点以上の場合
            if monshin_score >= 3:
                is_alert = True

            detailed_answers = {}
            if is_alert:
                st.markdown("---")
                st.error("⚠️ **腰椎分離症のリスクが検出されました。より詳しい状態を教えてください。**")
                st.subheader("【5】詳しい追加問診")
                for q in questions["detailed_monshin"]:
                    detailed_answers[q["id"]] = st.radio(q["text"], q["options"], key=f"detailed_{q['id']}")

            st.markdown("---")
            
            if st.button("チェック結果を確定して保存する"):
                st.subheader("【判定結果】")
                
                # スコアに基づく判定メッセージ
                if monshin_score == 0:
                    st.success("💚 **心配ない**")
                elif monshin_score in [1, 2]:
                    st.warning("⚠️ **少し心配です、様子を確認して必要に応じて整形外科の受診をお勧めします。**")
                else:
                    st.error("🚨 **早めに整形外科の受診をお勧めします**")
                    
                # スコアが低くても動作チェックで引っかかった場合のフォローアップ
                if is_alert and monshin_score < 3:
                    st.error("⚠️ **※動作チェックで痛みが出ているため、整形外科の受診もご検討ください**")

                try:
                    data = {
                        "user_id": child_user_id,
                        "checked_at": str(datetime.date.today()),
                        "height": current_height,
                        "weight": current_weight,
                        "sport": sport,
                        "days_per_week": days_per_week,
                        "hours_per_day": hours_per_day,
                        "kemp_pain": answers.get("kemp", "未記録"),
                        "one_leg_pain": answers.get("one_leg", "未記録"),
                        # 💡 データベースを書き換えなくて済むよう、2つの回答を合体させて保存します
                        "duration": f"日常:{daily_pain} / 運動:{sports_pain}"
                    }
                    supabase.table("koshi_history").insert(data).execute()
                    st.success(f"✨ {current_member} さんのデータを安全に保存しました！")
                except Exception as e:
                    st.warning(f"データ保存エラー: {e}")

                st.subheader("🏥 病院提出用データのダウンロード")
                try:
                    pdf = FPDF()
                    pdf.add_page()
                    pdf.add_font("NotoSans", "", FONT_PATH)
                    
                    pdf.set_font("NotoSans", size=16)
                    pdf.cell(200, 10, text="腰椎分離症セルフチェック 診察提出用レポート", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")
                    pdf.set_font("NotoSans", size=10)
                    pdf.cell(200, 10, text=f"作成日: {datetime.date.today()}", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="R")
                    pdf.ln(5)
                    
                    pdf.set_font("NotoSans", size=11)
                    pdf.cell(100, 10, text="氏名（手書き）: ___________________________", new_x=XPos.RIGHT, new_y=YPos.TOP)
                    pdf.cell(100, 10, text="生年月日（手書き）: _____年 ___月 ___日", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
                    pdf.ln(5)
                    
                    pdf.set_font("NotoSans", size=12)
                    pdf.cell(200, 10, text="■ 基本情報", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
                    pdf.set_font("NotoSans", size=10)
                    pdf.cell(200, 8, text=f"・現在の身長 / 体重: {current_height} cm / {current_weight} kg", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
                    pdf.cell(200, 8, text=f"・行っているスポーツ: {sport} ({days_per_week} / 1日 {hours_per_day})", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
                    pdf.ln(5)
                    
                    pdf.set_font("NotoSans", size=12)
                    pdf.cell(200, 10, text="■ 症状・セルフチェック結果", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
                    pdf.set_font("NotoSans", size=10)
                    
                    for q in questions["self_check"]:
                        pdf.cell(200, 8, text=f"{q['text']}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
                        pdf.cell(200, 8, text=f"   => 回答: {answers[q['id']]}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
                    
                    # 新しい問診のPDF出力
                    pdf.cell(200, 8, text="日常生活で腰に痛みが出ますか？", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
                    pdf.cell(200, 8, text=f"   => 回答: {daily_pain}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
                    pdf.cell(200, 8, text="スポーツ（運動時）で腰に痛みが出ますか？", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
                    pdf.cell(200, 8, text=f"   => 回答: {sports_pain}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
                    
                    if is_alert:
                        pdf.ln(3)
                        pdf.set_font("NotoSans", size=12)
                        pdf.cell(200, 10, text="■ 詳しい追加問診結果（リスク検知による自動表示）", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
                        pdf.set_font("NotoSans", size=10)
                        for q in questions["detailed_monshin"]:
                            pdf.cell(200, 8, text=f"{q['text']}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
                            pdf.cell(200, 8, text=f"   => 回答: {detailed_answers[q['id']]}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
                    
                    pdf_output = pdf.output()
                    st.download_button(
                        label="📄 病院提出用PDFをダウンロード",
                        data=bytes(pdf_output),
                        file_name="koshi_check_report.pdf",
                        mime="application/pdf"
                    )
                except Exception as e:
                    st.error(f"PDF生成エラー: {e}")

    with tab3:
        if current_member == "➕ 新しいメンバーを追加":
            st.warning("⚠️ メンバーを選択してください。")
        else:
            st.header(f"📈 {current_member} さんの成長 ＆ 痛みの履歴")
            
            try:
                response = supabase.table("koshi_history").select("*").eq("user_id", child_user_id).order("checked_at").execute()
                
                if response.data:
                    df = pd.DataFrame(response.data)
                    df["checked_at"] = pd.to_datetime(df["checked_at"])
                    
                    st.subheader("📏 身長の伸びの推移 (cm)")
                    height_chart = alt.Chart(df).mark_line(point=True, color='#1f77b4').encode(
                        x=alt.X('checked_at:T', title='日付', axis=alt.Axis(format='%Y/%m/%d')),
                        y=alt.Y('height:Q', title='身長 (cm)', scale=alt.Scale(domain=[100, 250])),
                        tooltip=[alt.Tooltip('checked_at:T', title='日付', format='%Y/%m/%d'), alt.Tooltip('height:Q', title='身長 (cm)')]
                    ).properties(width='container', height=300)
                    st.altair_chart(height_chart, use_container_width=True)
                    
                    st.subheader("⚖️ 体重の推移 (kg)")
                    weight_chart = alt.Chart(df).mark_line(point=True, color='#ff7f0e').encode(
                        x=alt.X('checked_at:T', title='日付', axis=alt.Axis(format='%Y/%m/%d')),
                        y=alt.Y('weight:Q', title='体重 (kg)', scale=alt.Scale(domain=[20, 200])),
                        tooltip=[alt.Tooltip('checked_at:T', title='日付', format='%Y/%m/%d'), alt.Tooltip('weight:Q', title='体重 (kg)')]
                    ).properties(width='container', height=300)
                    st.altair_chart(weight_chart, use_container_width=True)
                    
                    st.subheader("📋 過去のチェック内容と痛みの状態")
                    df_sorted = df.sort_values(by="checked_at", ascending=False)
                    df_sorted["checked_at_str"] = df_sorted["checked_at"].dt.strftime('%Y/%m/%d')
                    df_sorted = df_sorted.set_index("checked_at_str")
                    
                    display_df = df_sorted[["sport", "days_per_week", "hours_per_day", "kemp_pain", "one_leg_pain", "duration"]].copy()
                    # 💡 表示する表の列名も「痛みの期間」から新しく変更しました
                    display_df.columns = ["スポーツ", "週の頻度", "1日の練習時間", "体を反らせたとき", "片脚立ちで反る", "日常/運動の痛み"]
                    
                    display_df = display_df.fillna("未記録")
                    
                    st.dataframe(display_df)
                    
                else:
                    st.info(f"まだ {current_member} さんの履歴がありません。今月のチェックを行うとここに表示されます。")
            except Exception as e:
                st.error(f"履歴の取得中にエラーが発生しました: {e}")

if st.session_state.user is None:
    show_auth_page()
else:
    show_main_app()