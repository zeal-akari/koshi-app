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

    # モード自動判定（データベースの値を基準にします）
    is_diag = saved_profile.get("is_diagnosed", False) if saved_profile else False

    if current_member == "➕ 新しいメンバーを追加":
        titles = ["👤 メンバー情報"]
    elif is_diag:
        titles = ["👤 メンバー情報", "📅 毎日の記録", "📈 経過観察の推移"]
    else:
        titles = ["👤 メンバー情報", "📝 毎月のチェック", "📈 成長と推移", "🏥 受診用シート作成"]

    tabs = st.tabs(titles)

    # --- ① 👤 メンバー情報 ---
    with tabs[titles.index("👤 メンバー情報")]:
        is_new_member = (current_member == "➕ 新しいメンバーを追加")
        
        if is_new_member:
            st.header("👤 新しいメンバーの登録")
            edit_nickname = st.text_input("ニックネーム（例：お兄ちゃん、たろう、次男）", value="")
        else:
            st.header(f"👤 {current_member} さんの情報設定")
            edit_nickname = current_member

        default_year = int(saved_profile["birth_year"]) if saved_profile else 2012
        default_height = float(saved_profile["init_height"]) if saved_profile else 150.0
        default_weight = float(saved_profile["init_weight"]) if saved_profile else 45.0
        default_sport = saved_profile["sport"] if saved_profile else ""
        
        d_is_diagnosed = saved_profile.get("is_diagnosed", False) if saved_profile else False
        d_diagnosis_name = saved_profile.get("diagnosis_name", "") if saved_profile else ""
        d_corset_status = saved_profile.get("corset_status", "無し") if saved_profile else "無し"
        d_corset_type = saved_profile.get("corset_type", "") if saved_profile else ""

        this_year = datetime.datetime.now().year
        birth_year = st.number_input("生年（西暦）", min_value=this_year-30, max_value=this_year, value=default_year, disabled=not is_new_member)
        init_height = st.number_input("登録時の身長 (cm)", min_value=100.0, max_value=250.0, value=default_height, step=0.1, disabled=not is_new_member)
        init_weight = st.number_input("登録時の体重 (kg)", min_value=20.0, max_value=200.0, value=default_weight, step=0.1, disabled=not is_new_member)
        sport = st.text_input("活動しているスポーツ（例：野球、サッカー）", value=default_sport)
        
        st.markdown("---")
        st.subheader("🏥 モード切り替え設定")
        is_diagnosed = st.checkbox("医師から分離症と診断されました（経過観察モードを起動）", value=d_is_diagnosed)
        
        # 💡 【修正の核心】すでに経過観察モード（d_is_diagnosedがTrue）のときだけ入力欄を出す
        if d_is_diagnosed:
            st.error("🩺 **現在【経過観察モード】が有効です**")
            st.write("診断名やコルセットの基本情報を入力・変更してください。")
            diagnosis_name = st.text_input("診断名（例：第五腰椎分離症）", value=d_diagnosis_name)
            
            c_options = ["無し", "有り", "制作中"]
            c_index = c_options.index(d_corset_status) if d_corset_status in c_options else 0
            corset_status = st.radio("コルセットの有無", c_options, index=c_index, horizontal=True)
            
            if corset_status in ["有り", "制作中"]:
                corset_type = st.text_input("コルセットの種類（例：硬性コルセット）", value=d_corset_type)
            else:
                corset_type = ""
        else:
            # まだ通常モードのときは入力欄を隠す
            if is_diagnosed:
                st.success("👍 チェックを入れました！下のボタンを押すと【経過観察モード】に切り替わります。診断名などは切り替わった後に入力します。")
            diagnosis_name = ""
            corset_status = "無し"
            corset_type = ""
        
        if is_new_member:
            st.markdown("---")
            consent = st.checkbox("【同意のお願い】入力されたデータは、個人を特定できない匿名データとして集計し、スポーツ障害の予防研究や統計データとして活用されることに同意します。（必須）")
        else:
            consent = True

        button_text = "新しいメンバーを登録する" if is_new_member else "設定を更新してモードを適用する"
        if st.button(button_text, type="primary"):
            if not edit_nickname:
                st.error("ニックネームを入力してください。")
            elif is_new_member and not consent:
                st.error("⚠️ 同意チェックが必要です。")
            else:
                try:
                    profile_data = {
                        "parent_id": st.session_state["parent_id"],
                        "nickname": edit_nickname,
                        "birth_year": birth_year,
                        "init_height": init_height,
                        "init_weight": init_weight,
                        "sport": sport,
                        "is_diagnosed": is_diagnosed,
                        # 通常モードからの切り替え時は空、適用後は画面の入力値を保存
                        "diagnosis_name": diagnosis_name if d_is_diagnosed else "",
                        "corset_status": corset_status if d_is_diagnosed else "無し",
                        "corset_type": corset_type if d_is_diagnosed else "",
                        "updated_at": str(datetime.datetime.now())
                    }
                    supabase.table("user_profile").upsert(profile_data, on_conflict="parent_id,nickname").execute()
                    st.success("✨ 設定を保存しました！")
                    st.session_state["current_member"] = edit_nickname
                    st.rerun()
                except Exception as e:
                    st.error(f"保存エラー: {e}")

    # --- ② 📅 毎日の記録（経過観察モード専用） ---
    if "📅 毎日の記録" in titles:
        with tabs[titles.index("📅 毎日の記録")]:
            st.error("🩺 **【治療・経過観察モード】毎日の記録**")
            st.markdown(f"**診断名:** `{saved_profile.get('diagnosis_name', '未登録')}` ｜ **コルセット:** `{saved_profile.get('corset_status', '無し')} ({saved_profile.get('corset_type', '-')})`")
            
            st.subheader("【1】今日の腰の痛み")
            pain_options = [
                "1. 全く痛くない",
                "2. 痛みはないが違和感がある",
                "3. 動かすと少し痛い",
                "4. 動かすととても痛い",
                "5. 動かなくても痛い。動けないほど痛い"
            ]
            daily_pain_level = st.radio("現在の状態に一番近いものを選択してください：", pain_options, key="daily_pain_input", label_visibility="collapsed")
            
            c_time = "なし"
            if d_corset_status in ["有り", "制作中"]:
                st.subheader("【2】本日のコルセット装着時間")
                c_time = st.text_input("装着時間（例：お風呂以外ずっと、12時間 など）")
            
            st.subheader("【3】今日の運動・リハビリの状況")
            has_practice_display = st.radio("今日は運動やリハビリをしましたか？", ["しない", "した"], horizontal=True)
            has_practice = "有り" if has_practice_display == "した" else "無し"
            
            p_time, p_intensity, p_content = "なし", "なし", "なし"
            if has_practice == "有り":
                st.markdown("---")
                p_time = st.text_input("運動・リハビリの時間（例：30分、1時間）")
                p_intensity = st.radio("運動の強度", ["軽い（ストレッチ・体幹等）", "中等度（ジョギング・部分合流）", "高い（通常練習・試合）"], horizontal=True)
                p_content = st.text_input("具体的なリハビリ・運動内容（例：ストレッチ、体幹トレ、軽いパス練習）")
            
            st.markdown("---")
            if st.button("今日の経過を記録する", type="primary"):
                try:
                    daily_data = {
                        "user_id": child_user_id,
                        "checked_at": str(datetime.date.today()),
                        "pain_level": daily_pain_level,
                        "has_practice": has_practice,
                        "practice_time": p_time,
                        "practice_intensity": p_intensity,
                        "practice_pain": "なし",
                        "practice_content": p_content,
                        "corset_time": c_time
                    }
                    supabase.table("daily_history").insert(daily_data).execute()
                    st.success("✨ 本日の経過観察データを安全に保存しました！")
                except Exception as e:
                    st.error(f"毎日データ保存エラー: {e}")

    # --- ③ 📝 毎月のチェック（通常モード専用） ---
    if "📝 毎月のチェック" in titles:
        with tabs[titles.index("📝 毎月のチェック")]:
            st.header(f"📝 {current_member} さんの定期セルフチェック")
            
            last_height, last_weight = init_height, init_weight
            try:
                res_latest = supabase.table("koshi_history").select("height, weight").eq("user_id", child_user_id).order("checked_at", desc=True).limit(1).execute()
                if res_latest.data:
                    last_height = float(res_latest.data[0]["height"])
                    last_weight = float(res_latest.data[0]["weight"])
            except Exception:
                pass

            st.subheader("【1】身長・体重の記録")
            not_measured_height = st.checkbox("身長は今回は測っていない")
            current_height = st.number_input("現在の身長 (cm)", value=last_height, disabled=not_measured_height)
            not_measured_weight = st.checkbox("体重は今回は測っていない")
            current_weight = st.number_input("現在の体重 (kg)", value=last_weight, disabled=not_measured_weight)

            st.subheader("【2】練習の頻度について")
            days_per_week = st.selectbox("最近、週に何回くらい練習していますか？", ["週1日", "週2日", "週3日", "週4日", "週5日", "週6日", "毎日（週7日）", "お休みしている"])
            hours_per_day = st.selectbox("1日あたり、何時間くらい練習していますか？", ["1時間未満", "1〜2時間", "2〜3時間", "3〜4時間", "4時間以上", "お休みしている"])
            
            st.subheader("【3】動作セルフチェック")
            answers = {}
            for q in questions["self_check"]:
                st.markdown(f"### {q['text']}")
                answers[q["id"]] = st.radio("回答を選択してください：", q["options"], key=f"check_{q['id']}", label_visibility="collapsed")
                st.markdown("---")
                
            st.subheader("【4】簡易問診")
            daily_pain_options = {"全く痛みはない": 0, "たまある": 1, "頻繁に痛くなる": 2}
            daily_pain = st.radio("日常生活で腰に痛みが出ますか？", list(daily_pain_options.keys()), key="daily_pain")
            sports_pain_options = {"全く痛みはない": 0, "たまにある": 1, "頻繁に痛くなる": 3}
            sports_pain = st.radio("スポーツ（運動時）で腰に痛みが出ますか？", list(sports_pain_options.keys()), key="sports_pain")

            monshin_score = daily_pain_options[daily_pain] + sports_pain_options[sports_pain]
            is_alert = (answers.get("kemp") == "ハッキリと痛い" or answers.get("one_leg") in ["片側だけ痛い", "両方痛い"] or monshin_score >= 3)

            if st.button("今月のチェック結果を保存する", type="primary"):
                st.subheader("【判定結果】")
                if monshin_score == 0: st.success("💚 **心配ない**")
                elif monshin_score in [1, 2]: st.warning("⚠️ **少し心配です、様子を確認して必要に応じて整形外科の受診をお勧めします。**")
                else: st.error("🚨 **早めに整形外科の受診をお勧めします**")
                
                if is_alert and monshin_score < 3:
                    st.error("⚠️ **※動作チェックで痛みが出ているため、整形外科の受診もご検討ください**")
                if is_alert:
                    st.info("💡 **「🏥 受診用シート作成」タブを開くと、病院提出用のレポートを作成できます。**")

                try:
                    data = {
                        "user_id": child_user_id, "checked_at": str(datetime.date.today()), "height": current_height, "weight": current_weight,
                        "sport": sport, "days_per_week": days_per_week, "hours_per_day": hours_per_day,
                        "kemp_pain": answers.get("kemp", "未記録"), "one_leg_pain": answers.get("one_leg", "未記録"), "duration": f"日常:{daily_pain} / 運動:{sports_pain}"
                    }
                    supabase.table("koshi_history").insert(data).execute()
                    st.success(f"✨ 毎月のデータを保存しました！")
                except Exception as e:
                    st.warning(f"データ保存エラー: {e}")

    # --- ④ 📈 履歴・推移の処理 ---
    main_chart_title = "📈 経過観察の推移" if is_diag else "📈 成長と推移"
    with tabs[titles.index(main_chart_title)]:
        st.header(f"📈 {current_member} さんの記録履歴")
        
        if is_diag:
            try:
                daily_res = supabase.table("daily_history").select("*").eq("user_id", child_user_id).order("checked_at").execute()
                if daily_res.data:
                    df_daily = pd.DataFrame(daily_res.data)
                    df_daily["checked_at"] = pd.to_datetime(df_daily["checked_at"])
                    df_daily["pain_score"] = df_daily["pain_level"].str.extract(r'(\d+)').astype(int)
                    
                    st.subheader("📉 日々の腰の痛みレベル推移 (1〜5)")
                    daily_chart = alt.Chart(df_daily).mark_line(point=True, color='#d62728').encode(
                        x=alt.X('checked_at:T', title='日付', axis=alt.Axis(format='%Y/%m/%d')),
                        y=alt.Y('pain_score:Q', title='痛みレベル', scale=alt.Scale(domain=[1, 5]), axis=alt.Axis(tickMinStep=1))
                    ).properties(width='container', height=250)
                    st.altair_chart(daily_chart, use_container_width=True)
                    
                    st.subheader("📋 毎日の経過観察ログ（詳細）")
                    df_daily_sorted = df_daily.sort_values(by="checked_at", ascending=False)
                    df_daily_sorted["checked_at_str"] = df_daily_sorted["checked_at"].dt.strftime('%Y/%m/%d')
                    df_daily_sorted = df_daily_sorted.set_index("checked_at_str")
                    
                    cols = ["pain_level", "corset_time", "has_practice", "practice_time", "practice_intensity", "practice_content"]
                    # カラム存在チェック
                    existing_cols = [c for c in cols if c in df_daily_sorted.columns]
                    display_daily_df = df_daily_sorted[existing_cols].copy()
                    st.dataframe(display_daily_df.fillna("-"))
                else:
                    st.info("まだ毎日の経過観察記録がありません。")
            except Exception:
                pass
        else:
            try:
                response = supabase.table("koshi_history").select("*").eq("user_id", child_user_id).order("checked_at").execute()
                if response.data:
                    df = pd.DataFrame(response.data)
                    df["checked_at"] = pd.to_datetime(df["checked_at"])
                    
                    st.subheader("📏 身長の推移 (cm)")
                    height_chart = alt.Chart(df).mark_line(point=True, color='#1f77b4').encode(
                        x=alt.X('checked_at:T', title='日付', axis=alt.Axis(format='%Y/%m/%d')),
                        y=alt.Y('height:Q', title='身長', scale=alt.Scale(domain=[100, 250]))
                    ).properties(width='container', height=200)
                    st.altair_chart(height_chart, use_container_width=True)
                    
                    st.subheader("📋 過去の定期チェック履歴")
                    df_sorted = df.sort_values(by="checked_at", ascending=False)
                    df_sorted["checked_at_str"] = df_sorted["checked_at"].dt.strftime('%Y/%m/%d')
                    df_sorted = df_sorted.set_index("checked_at_str")
                    display_df = df_sorted[["sport", "days_per_week", "hours_per_day", "kemp_pain", "one_leg_pain", "duration"]].copy()
                    display_df.columns = ["スポーツ", "週の頻度", "1日の練習時間", "体を反らせたとき", "片脚立ちで反る", "日常/運動の痛み"]
                    st.dataframe(display_df.fillna("未記録"))
                else:
                    st.info("まだ毎月の定期チェック記録がありません。")
            except Exception:
                pass

    # --- ⑤ 🏥 受診用シート作成（通常モード専用） ---
    if "🏥 受診用シート作成" in titles:
        with tabs[titles.index("🏥 受診用シート作成")]:
            st.header(f"🏥 {current_member} さんの受診用シート作成")
            st.write("整形外科を受診する際に、医師に現在の状況を正確に伝えるためのレポート（PDF）を作成します。")
            
            detailed_answers = {}
            for q in questions["detailed_monshin"]:
                st.markdown(f"**{q['text']}**")
                detailed_answers[q["id"]] = st.radio("回答を選択してください：", q["options"], key=f"tab5_detailed_{q['id']}", label_visibility="collapsed")
                st.markdown("---")
                
            if st.button("📄 病院提出用PDFを作成・ダウンロード", type="primary"):
                try:
                    res_latest = supabase.table("koshi_history").select("*").eq("user_id", child_user_id).order("checked_at", desc=True).limit(1).execute()
                    if not res_latest.data:
                        st.error("⚠️ まだ「毎月のチェック」の記録がありません。先にタブ2でチェックを保存してください。")
                    else:
                        latest = res_latest.data[0]
                        pdf = FPDF()
                        pdf.add_page()
                        pdf.add_font("NotoSans", "", FONT_PATH)
                        pdf.set_font("NotoSans", size=16)
                        pdf.cell(200, 10, text="腰椎分離症セルフチェック 診察提出用レポート", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")
                        pdf.ln(10)
                        pdf.set_font("NotoSans", size=11)
                        pdf.cell(200, 8, text=f"対象メンバー: {current_member}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
                        pdf.cell(200, 8, text=f"基本情報: 身長 {latest['height']} cm / 体重 {latest['weight']} kg / スポーツ {latest['sport']}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
                        pdf.cell(200, 8, text=f"反らせた時の痛み: {latest.get('kemp_pain', '未記録')} / 片脚立ち痛み: {latest.get('one_leg_pain', '未記録')}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
                        pdf.ln(5)
                        for q in questions["detailed_monshin"]:
                            pdf.cell(200, 8, text=f"Q. {q['text']}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
                            pdf.cell(200, 8, text=f"   => {detailed_answers[q['id']]}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
                        
                        pdf_output = pdf.output()
                        st.download_button(label="📥 PDFをダウンロードする", data=bytes(pdf_output), file_name=f"koshi_report_{current_member}.pdf", mime="application/pdf")
                except Exception as e:
                    st.error(f"エラー: {e}")

if st.session_state.user is None:
    show_auth_page()
else:
    show_main_app()