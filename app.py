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
import io
from uuid import uuid4
import qrcode

# --- 💡 修正点1: ページ設定は必ず一番最初に書く必要があります ---
st.set_page_config(page_title="腰椎分離症チェック", page_icon="🦴")

# --- 1. 初期設定と準備 ---
with open("questions.json", "r", encoding="utf-8") as f:
    questions = json.load(f)

# フォントの自動ダウンロード（サーバーにファイルがなくても自動で解決します）
FONT_PATH = "NotoSansJP-Regular.ttf"
if not os.path.exists(FONT_PATH):
    try:
        with st.spinner("初回起動用の日本語フォントを準備中..."):
            url = "https://github.com/google/fonts/raw/main/ofl/notosansjp/NotoSansJP%5Bwght%5D.ttf"
            urllib.request.urlretrieve(url, FONT_PATH)
    except Exception as e:
        st.error(f"フォントのダウンロードに失敗しました: {e}")

SUPABASE_URL = "https://ogtteowmytkeritzgcvn.supabase.co"
SUPABASE_KEY = "sb_publishable_TcG-AwawQ_TSM9sTHHhs7w_qNVEQOV2"

def init_supabase() -> Client:
    if "supabase_client" not in st.session_state:
        st.session_state["supabase_client"] = create_client(
            SUPABASE_URL,
            SUPABASE_KEY
        )

    return st.session_state["supabase_client"]


try:
    supabase: Client = init_supabase()
except Exception as e:
    st.error(f"Supabaseの接続設定を確認してください: {e}")
    st.stop()

if "user" not in st.session_state:
    st.session_state.user = None

def logout():
    # Supabaseからログアウト
    supabase.auth.sign_out()

    # このブラウザセッションに保存された情報を削除
    st.session_state.user = None
    st.session_state.pop("supabase_client", None)
    st.session_state.pop("current_member", None)
    st.session_state.pop("parent_id", None)
    st.session_state.pop("generated_period_report", None)
    st.session_state.pop("generated_consultation_report", None)
    st.session_state.pop("daily_record_date", None)
    st.session_state.pop("monthly_check_date", None)
    st.session_state.pop("pending_daily_edit_date", None)
    st.session_state.pop("pending_monthly_edit_date", None)
    st.session_state.pop("daily_form_revision", None)
    st.session_state.pop("monthly_form_revision", None)

    # ログイン画面へ戻る
    st.rerun()
# --- 診察用PDFのStorage設定 ---
REPORT_BUCKET = "reports"

# QRコードの有効時間：10分
SIGNED_URL_EXPIRES_SECONDS = 600


def upload_report_pdf(pdf_bytes: bytes) -> tuple[str, str, bytes]:
    """
    PDFをSupabase Storageへ保存し、
    署名付きURLとQRコード画像を作成する。
    """

    # ログイン中のユーザーを取得
    user = st.session_state.get("user")

    if user is None:
        raise RuntimeError(
            "ログイン情報を確認できません。再度ログインしてください。"
        )

    # 保存場所を作成
    # 例：ユーザーUUID/ランダムなファイル名.pdf
    storage_path = f"{user.id}/{uuid4().hex}.pdf"

    # Supabase StorageにはBytesIOではなくPDFのbytes本体を渡す。
    # BytesIOを渡すと、環境によっては
    # "expected str, bytes or os.PathLike object, not BytesIO"
    # となるため、生成済みのbytesをそのまま使用する。

    # reportsバケットへPDFをアップロード
    supabase.storage.from_(REPORT_BUCKET).upload(
        path=storage_path,
        file=pdf_bytes,
        file_options={
            "content-type": "application/pdf",
            "cache-control": "3600",
            "upsert": "false",
        },
    )

    # 10分間有効な署名付きURLを発行
    signed_response = (
        supabase.storage
        .from_(REPORT_BUCKET)
        .create_signed_url(
            storage_path,
            SIGNED_URL_EXPIRES_SECONDS,
        )
    )

    # Supabaseの応答からURLを取得
    signed_url = None

    if isinstance(signed_response, dict):
        signed_url = (
            signed_response.get("signedURL")
            or signed_response.get("signedUrl")
            or signed_response.get("signed_url")
        )

    if not signed_url:
        raise RuntimeError(
            f"署名付きURLを取得できませんでした: {signed_response}"
        )

    # URLをQRコード画像へ変換
    qr_image = qrcode.make(signed_url)

    qr_buffer = io.BytesIO()
    qr_image.save(qr_buffer, format="PNG")

    # 保存先、署名付きURL、QR画像を返す
    return storage_path, signed_url, qr_buffer.getvalue()


def normalize_pdf_text(value, default: str) -> str:
    """PDFへ出力する文字列を1行の安全な文字列へ整える。"""
    if value is None:
        return default

    text = str(value).replace("\r", " ").replace("\n", " ").strip()
    text = " ".join(text.split())
    return text or default


def wrap_pdf_text(pdf: FPDF, text: str, max_width: float) -> list[str]:
    """日本語を含む文字列を、指定幅に収まるよう文字単位で折り返す。"""
    usable_width = max(max_width - 4, 1)
    lines: list[str] = []
    current = ""

    for char in text:
        candidate = current + char
        if not current or pdf.get_string_width(candidate) <= usable_width:
            current = candidate
        else:
            lines.append(current)
            current = char

    if current:
        lines.append(current)

    return lines or [""]


def draw_period_report_header(pdf: FPDF, widths: list[float]) -> None:
    """指定期間レポートの表ヘッダーを描画する。"""
    headers = ["日付", "痛みレベル", "装着時間", "練習内容"]
    start_x = pdf.l_margin
    start_y = pdf.get_y()
    header_height = 10
    x = start_x

    pdf.set_font("NotoSans", size=9)
    for width, header in zip(widths, headers):
        pdf.rect(x, start_y, width, header_height)
        pdf.set_xy(x, start_y)
        pdf.cell(width, header_height, text=header, align="C")
        x += width

    pdf.set_xy(start_x, start_y + header_height)


def draw_period_report_row(
    pdf: FPDF,
    values: list[str],
    widths: list[float],
) -> None:
    """文章量に応じて高さを伸ばし、複数行で表の1行を描画する。"""
    line_height = 5.5
    wrapped_values = [
        wrap_pdf_text(pdf, value, width)
        for value, width in zip(values, widths)
    ]
    row_height = max(10.0, max(len(lines) for lines in wrapped_values) * line_height + 4)

    # 残りのページに収まらない場合は改ページし、ヘッダーを再表示する。
    if pdf.get_y() + row_height > pdf.h - pdf.b_margin:
        pdf.add_page()
        draw_period_report_header(pdf, widths)

    start_x = pdf.l_margin
    start_y = pdf.get_y()
    x = start_x

    pdf.set_font("NotoSans", size=9)
    for width, lines in zip(widths, wrapped_values):
        pdf.rect(x, start_y, width, row_height)
        for line_index, line in enumerate(lines):
            pdf.set_xy(
                x + 2,
                start_y + 2 + line_index * line_height,
            )
            # 事前に折り返した1行ずつを描画するため、
            # multi_cellによる二重折り返しを防げる。
            pdf.cell(
                width - 4,
                line_height,
                text=line,
                border=0,
                align="L",
            )
        x += width

    pdf.set_xy(start_x, start_y + row_height)


def safe_option_index(options: list[str], value, default: int = 0) -> int:
    """保存済みの値が選択肢にない場合も安全に初期位置を返す。"""
    try:
        return options.index(value)
    except (ValueError, TypeError):
        return default


def get_date_records(
    table_name: str,
    user_id: str,
    record_date: datetime.date,
    observation_session_id: str | None = None,
) -> list[dict]:
    """指定した利用者・日付の記録を取得する。"""
    query = (
        supabase.table(table_name)
        .select("*")
        .eq("user_id", user_id)
        .eq("checked_at", str(record_date))
    )
    if observation_session_id is not None:
        query = query.eq(
            "observation_session_id",
            observation_session_id,
        )

    response = query.execute()
    return response.data or []


def save_date_record(
    table_name: str,
    existing_records: list[dict],
    data: dict,
) -> str:
    """
    同日の記録があれば更新し、なければ新規登録する。
    id列がある場合は、過去にできた同日重複も1件へ整理する。
    """
    if not existing_records:
        supabase.table(table_name).insert(data).execute()
        return "inserted"

    target = existing_records[-1]
    target_id = target.get("id")

    if target_id is not None:
        (
            supabase.table(table_name)
            .update(data)
            .eq("id", target_id)
            .execute()
        )

        duplicate_ids = [
            row.get("id")
            for row in existing_records[:-1]
            if row.get("id") is not None
        ]
        for duplicate_id in duplicate_ids:
            (
                supabase.table(table_name)
                .delete()
                .eq("id", duplicate_id)
                .execute()
            )
    else:
        update_query = (
            supabase.table(table_name)
            .update(data)
            .eq("user_id", data["user_id"])
            .eq("checked_at", data["checked_at"])
        )
        if data.get("observation_session_id") is not None:
            update_query = update_query.eq(
                "observation_session_id",
                data["observation_session_id"],
            )
        update_query.execute()

    return "updated"


def delete_date_records(
    table_name: str,
    existing_records: list[dict],
    user_id: str,
    record_date: datetime.date,
    observation_session_id: str | None = None,
) -> None:
    """指定日の記録を削除する。"""
    record_ids = [
        row.get("id")
        for row in existing_records
        if row.get("id") is not None
    ]

    if record_ids:
        for record_id in record_ids:
            (
                supabase.table(table_name)
                .delete()
                .eq("id", record_id)
                .execute()
            )
    else:
        delete_query = (
            supabase.table(table_name)
            .delete()
            .eq("user_id", user_id)
            .eq("checked_at", str(record_date))
        )
        if observation_session_id is not None:
            delete_query = delete_query.eq(
                "observation_session_id",
                observation_session_id,
            )
        delete_query.execute()


def parse_pain_duration(value) -> tuple[str, str]:
    """通常モードで保存している日常痛・運動痛を分解する。"""
    default_daily = "全く痛みはない"
    default_sports = "全く痛みはない"

    if not value:
        return default_daily, default_sports

    text_value = str(value)
    marker = " / 運動:"
    if text_value.startswith("日常:") and marker in text_value:
        daily_part, sports_part = text_value.split(marker, 1)
        daily_value = daily_part.replace("日常:", "", 1).strip()
        sports_value = sports_part.strip()
        return (
            daily_value or default_daily,
            sports_value or default_sports,
        )

    return default_daily, default_sports



def get_observation_sessions(user_id: str) -> list[dict]:
    """利用者の経過観察セッションを新しい順で取得する。"""
    response = (
        supabase.table("observation_sessions")
        .select("*")
        .eq("user_id", user_id)
        .order("session_number", desc=True)
        .execute()
    )
    return response.data or []


def get_active_observation_session(user_id: str) -> dict | None:
    """現在継続中の経過観察セッションを取得する。"""
    response = (
        supabase.table("observation_sessions")
        .select("*")
        .eq("user_id", user_id)
        .eq("status", "active")
        .order("session_number", desc=True)
        .limit(1)
        .execute()
    )
    return response.data[0] if response.data else None


def create_observation_session(
    user_id: str,
    started_at: datetime.date | None = None,
) -> dict:
    """新しい経過観察セッションを開始する。"""
    sessions = get_observation_sessions(user_id)
    next_number = max(
        [int(row.get("session_number") or 0) for row in sessions],
        default=0,
    ) + 1

    start_date = started_at or datetime.date.today()
    response = (
        supabase.table("observation_sessions")
        .insert(
            {
                "user_id": user_id,
                "session_number": next_number,
                "started_at": str(start_date),
                "ended_at": None,
                "status": "active",
                "updated_at": str(datetime.datetime.now()),
            }
        )
        .execute()
    )
    if not response.data:
        raise RuntimeError("新しい経過観察を作成できませんでした。")
    return response.data[0]


def resume_observation_session(session_id: str) -> dict:
    """終了済みの経過観察セッションを再開する。"""
    response = (
        supabase.table("observation_sessions")
        .update(
            {
                "status": "active",
                "ended_at": None,
                "updated_at": str(datetime.datetime.now()),
            }
        )
        .eq("id", session_id)
        .execute()
    )
    if not response.data:
        raise RuntimeError("前回の経過観察を再開できませんでした。")
    return response.data[0]


def close_observation_session(
    session_id: str,
    ended_at: datetime.date | None = None,
) -> None:
    """現在の経過観察セッションを終了する。"""
    end_date = ended_at or datetime.date.today()
    (
        supabase.table("observation_sessions")
        .update(
            {
                "status": "closed",
                "ended_at": str(end_date),
                "updated_at": str(datetime.datetime.now()),
            }
        )
        .eq("id", session_id)
        .execute()
    )


def format_observation_session(session: dict) -> str:
    """画面表示用の経過観察セッション名を作る。"""
    number = session.get("session_number", "-")
    started_at = session.get("started_at") or "開始日不明"
    ended_at = session.get("ended_at") or "継続中"
    return f"第{number}回　{started_at} ～ {ended_at}"


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
            except Exception:
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
                st.error(f"登録に失敗しました: {e}")

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

    current_member = st.sidebar.selectbox("操作する人を選んでください：", options, index=selected_index)

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

    # --- モード判定 ---
    d_is_diagnosed = saved_profile.get("is_diagnosed", False) if saved_profile else False
    d_diagnosis_name = saved_profile.get("diagnosis_name", "") if saved_profile else ""
    d_corset_status = saved_profile.get("corset_status", "無し") if saved_profile else "無し"
    d_corset_type = saved_profile.get("corset_type", "") if saved_profile else ""
    d_corset_date = saved_profile.get("corset_date", "") if saved_profile else ""

    is_diag = d_is_diagnosed

    observation_sessions: list[dict] = []
    active_observation_session: dict | None = None
    if current_member != "➕ 新しいメンバーを追加":
        try:
            observation_sessions = get_observation_sessions(
                child_user_id
            )
            active_observation_session = next(
                (
                    row
                    for row in observation_sessions
                    if row.get("status") == "active"
                ),
                None,
            )

            # 既に治療モードだった利用者にセッションがない場合は、
            # 既存機能を止めないため現在の経過観察を自動作成する。
            if is_diag and active_observation_session is None:
                active_observation_session = create_observation_session(
                    child_user_id
                )
                observation_sessions = get_observation_sessions(
                    child_user_id
                )
        except Exception as e:
            st.error(
                "経過観察セッションを読み込めませんでした。"
                "SupabaseのSQL更新が完了しているか確認してください。"
                f" 詳細: {e}"
            )
            st.stop()

    active_observation_session_id = (
        str(active_observation_session.get("id"))
        if active_observation_session
        else None
    )

    # 💡 タブ構成の自動切り替え
    if current_member == "➕ 新しいメンバーを追加":
        titles = ["👤 メンバー情報"]
    elif is_diag:
        titles = ["🏥 治療・コルセット設定", "📅 毎日の記録", "📈 経過観察の推移", "👤 基本情報"]
    else:
        titles = ["👤 メンバー情報", "📝 毎月のチェック", "📈 成長と推移", "🏥 受診用シート作成"]

    tabs = st.tabs(titles)

    # ==========================================
    # 【モード1】治療・コルセット設定
    # ==========================================
    if "🏥 治療・コルセット設定" in titles:
        with tabs[titles.index("🏥 治療・コルセット設定")]:
            st.header(f"🏥 {current_member} さんの治療設定")
            if active_observation_session:
                st.success(
                    "現在の経過観察: "
                    + format_observation_session(
                        active_observation_session
                    )
                )
            st.info("診断名やコルセットの状況を入力し、保存してください。内容が変わったらここでいつでも更新できます。")
            
            diagnosis_name = st.text_input("診断名（例：第五腰椎分離症）", value=d_diagnosis_name)
            
            c_options = ["無し", "有り", "制作中"]
            c_index = c_options.index(d_corset_status) if d_corset_status in c_options else 0
            corset_status = st.radio("コルセットの有無", c_options, index=c_index, horizontal=True)
            
            if corset_status in ["有り", "制作中"]:
                corset_type = st.text_input("コルセットの種類（例：硬性コルセット）", value=d_corset_type)
                corset_date = st.text_input("コルセット装着（開始）日（例：2024年4月1日）", value=d_corset_date)
            else:
                corset_type = ""
                corset_date = ""
                
            if st.button("🔄 治療情報を更新する", type="primary"):
                try:
                    supabase.table("user_profile").update({
                        "diagnosis_name": diagnosis_name,
                        "corset_status": corset_status,
                        "corset_type": corset_type,
                        "corset_date": corset_date
                    }).eq("parent_id", st.session_state["parent_id"]).eq("nickname", current_member).execute()
                    st.success("✨ 治療情報を更新しました！隣の「📅 毎日の記録」タブから日々の記録をつけてください。")
                except Exception as e:
                    st.error(f"更新エラー: {e}")

            st.markdown("---")
            st.subheader("🏁 治療の終了")
            st.write("医師から完治または治療終了と診断された場合は、ボタンを押して通常モードに戻ります。")
            if st.button("✨ 治療が終了しました（通常モードへ戻る）", use_container_width=True):
                try:
                    if active_observation_session_id:
                        close_observation_session(
                            active_observation_session_id
                        )
                    supabase.table("user_profile").update({"is_diagnosed": False}).eq("parent_id", st.session_state["parent_id"]).eq("nickname", current_member).execute()
                    st.session_state.pop(
                        "generated_period_report",
                        None,
                    )
                    st.rerun()
                except Exception as e:
                    st.error(f"モード切り替えエラー: {e}")

    # ==========================================
    # 【モード2】毎日の記録
    # ==========================================
    if "📅 毎日の記録" in titles:
        with tabs[titles.index("📅 毎日の記録")]:
            st.error("🩺 **【治療・経過観察モード】毎日の記録**")

            flash_message = st.session_state.pop("daily_record_flash", None)
            if flash_message:
                st.success(flash_message)

            pending_daily_date = st.session_state.pop(
                "pending_daily_edit_date",
                None,
            )
            if pending_daily_date is not None:
                st.session_state["daily_record_date"] = pending_daily_date

            if "daily_record_date" not in st.session_state:
                st.session_state["daily_record_date"] = datetime.date.today()

            daily_record_date = st.date_input(
                "記録日",
                max_value=datetime.date.today(),
                key="daily_record_date",
                help="過去の日付を選ぶと、その日の記録を編集できます。",
            )

            try:
                existing_daily_records = get_date_records(
                    "daily_history",
                    child_user_id,
                    daily_record_date,
                    active_observation_session_id,
                )
            except Exception as e:
                existing_daily_records = []
                st.warning(f"既存記録の確認に失敗しました: {e}")

            existing_daily = (
                existing_daily_records[-1]
                if existing_daily_records
                else None
            )

            if existing_daily:
                st.info(
                    f"{daily_record_date:%Y年%m月%d日}の記録があります。"
                    "保存すると新規追加ではなく、この日の記録を更新します。"
                )
                if len(existing_daily_records) > 1:
                    st.warning(
                        "この日には過去の重複記録があります。"
                        "更新すると、可能な範囲で1件に整理します。"
                    )
            else:
                st.caption("1人につき1日1件として保存します。")

            disp_corset = f"{d_corset_status}"
            if d_corset_status in ["有り", "制作中"]:
                disp_corset += (
                    f" ({d_corset_type} / 装着日: "
                    f"{d_corset_date if d_corset_date else '未入力'})"
                )

            st.markdown(
                f"**診断名:** "
                f"`{d_diagnosis_name if d_diagnosis_name else '未入力'}`"
                f" ｜ **コルセット:** `{disp_corset}`"
            )

            daily_form_revision = st.session_state.get(
                "daily_form_revision",
                0,
            )
            widget_suffix = (
                f"{child_user_id}_{daily_record_date.isoformat()}_"
                f"{daily_form_revision}"
            )
            pain_options = [
                "1. 全く痛くない",
                "2. 痛みはないが違和感がある",
                "3. 動かすと少し痛い",
                "4. 動かすととても痛い",
                "5. 動かなくても痛い。動けないほど痛い",
            ]
            saved_pain = (
                existing_daily.get("pain_level")
                if existing_daily
                else pain_options[0]
            )

            st.subheader("【1】腰の痛み")
            daily_pain_level = st.radio(
                "現在の状態に一番近いものを選択してください：",
                pain_options,
                index=safe_option_index(pain_options, saved_pain),
                key=f"daily_pain_input_{widget_suffix}",
                label_visibility="collapsed",
            )

            c_time = (
                str(existing_daily.get("corset_time") or "なし")
                if existing_daily
                else "なし"
            )
            if d_corset_status in ["有り", "制作中"]:
                st.subheader("【2】コルセット装着時間")
                c_time = st.text_input(
                    "装着時間（例：お風呂以外ずっと、12時間 など）",
                    value=(
                        str(existing_daily.get("corset_time") or "")
                        if existing_daily
                        else ""
                    ),
                    key=f"daily_corset_time_{widget_suffix}",
                )

            st.subheader("【3】運動・リハビリの状況")
            saved_has_practice = (
                existing_daily.get("has_practice")
                if existing_daily
                else "無し"
            )
            has_practice_options = ["しない", "した"]
            has_practice_default = (
                "した" if saved_has_practice == "有り" else "しない"
            )
            has_practice_display = st.radio(
                "この日は運動やリハビリをしましたか？",
                has_practice_options,
                index=safe_option_index(
                    has_practice_options,
                    has_practice_default,
                ),
                horizontal=True,
                key=f"daily_has_practice_{widget_suffix}",
            )
            has_practice = (
                "有り" if has_practice_display == "した" else "無し"
            )

            p_time, p_intensity, p_content = "なし", "なし", "なし"
            if has_practice == "有り":
                st.markdown("---")
                p_time = st.text_input(
                    "運動・リハビリの時間（例：30分、1時間）",
                    value=(
                        str(existing_daily.get("practice_time") or "")
                        if existing_daily
                        else ""
                    ),
                    key=f"daily_practice_time_{widget_suffix}",
                )

                intensity_options = [
                    "軽い（ストレッチ・体幹等）",
                    "中等度（ジョギング・部分合流）",
                    "高い（通常練習・試合）",
                ]
                saved_intensity = (
                    existing_daily.get("practice_intensity")
                    if existing_daily
                    else intensity_options[0]
                )
                p_intensity = st.radio(
                    "運動の強度",
                    intensity_options,
                    index=safe_option_index(
                        intensity_options,
                        saved_intensity,
                    ),
                    horizontal=True,
                    key=f"daily_practice_intensity_{widget_suffix}",
                )
                p_content = st.text_input(
                    "具体的なリハビリ・運動内容"
                    "（例：ストレッチ、体幹トレ、軽いパス練習）",
                    value=(
                        str(existing_daily.get("practice_content") or "")
                        if existing_daily
                        else ""
                    ),
                    key=f"daily_practice_content_{widget_suffix}",
                )

            st.markdown("---")
            save_col, delete_col = st.columns(2)

            with save_col:
                save_label = (
                    "この日の経過を更新する"
                    if existing_daily
                    else "この日の経過を記録する"
                )
                if st.button(
                    save_label,
                    type="primary",
                    use_container_width=True,
                    key=f"save_daily_{widget_suffix}",
                ):
                    try:
                        daily_data = {
                            "user_id": child_user_id,
                            "checked_at": str(daily_record_date),
                            "observation_session_id": (
                                active_observation_session_id
                            ),
                            "pain_level": daily_pain_level,
                            "has_practice": has_practice,
                            "practice_time": p_time,
                            "practice_intensity": p_intensity,
                            "practice_pain": (
                                existing_daily.get("practice_pain") or "なし"
                                if existing_daily
                                else "なし"
                            ),
                            "practice_content": p_content,
                            "corset_time": c_time,
                        }
                        action = save_date_record(
                            "daily_history",
                            existing_daily_records,
                            daily_data,
                        )
                        if action == "updated":
                            st.success("✨ この日の経過記録を更新しました。")
                        else:
                            st.success("✨ この日の経過記録を保存しました。")
                    except Exception as e:
                        st.error(f"毎日データ保存エラー: {e}")

            with delete_col:
                if existing_daily:
                    if st.button(
                        "この日の記録を削除",
                        use_container_width=True,
                        key=f"delete_daily_{widget_suffix}",
                    ):
                        try:
                            delete_date_records(
                                "daily_history",
                                existing_daily_records,
                                child_user_id,
                                daily_record_date,
                                active_observation_session_id,
                            )
                            st.session_state["daily_form_revision"] = (
                                daily_form_revision + 1
                            )
                            st.session_state["daily_record_flash"] = (
                                f"{daily_record_date:%Y年%m月%d日}"
                                "の記録を削除しました。"
                            )
                            st.rerun()
                        except Exception as e:
                            st.error(f"記録の削除エラー: {e}")
                else:
                    st.button(
                        "この日の記録を削除",
                        disabled=True,
                        use_container_width=True,
                        key=f"delete_daily_disabled_{widget_suffix}",
                    )

    # ==========================================
    # 【共通】メンバー情報 / 基本情報
    # ==========================================
    if "👤 メンバー情報" in titles or "👤 基本情報" in titles:
        tab_name = "👤 メンバー情報" if "👤 メンバー情報" in titles else "👤 基本情報"
        with tabs[titles.index(tab_name)]:
            is_new_member = (current_member == "➕ 新しいメンバーを追加")
            
            if is_new_member:
                st.header("👤 新しいメンバーの登録")
                edit_nickname = st.text_input("ニックネーム（例：お兄ちゃん、たろう、次男）", value="")
            else:
                st.header(f"👤 {current_member} さんの基本情報")
                edit_nickname = current_member

            default_year = int(saved_profile["birth_year"]) if saved_profile else 2012
            default_height = float(saved_profile["init_height"]) if saved_profile else 150.0
            default_weight = float(saved_profile["init_weight"]) if saved_profile else 45.0
            default_sport = saved_profile["sport"] if saved_profile else ""
            
            if saved_profile and "updated_at" in saved_profile:
                try:
                    raw_date = pd.to_datetime(saved_profile["updated_at"])
                    st.info(f"📅 登録日: **{raw_date.strftime('%Y年%m月%d日')}**")
                except: pass

            this_year = datetime.datetime.now().year
            birth_year = st.number_input("生年（西暦）", min_value=this_year-30, max_value=this_year, value=default_year, disabled=not is_new_member)
            init_height = st.number_input("登録時の身長 (cm)", min_value=100.0, max_value=250.0, value=default_height, step=0.1, disabled=not is_new_member)
            init_weight = st.number_input("登録時の体重 (kg)", min_value=20.0, max_value=200.0, value=default_weight, step=0.1, disabled=not is_new_member)
            sport = st.text_input("活動しているスポーツ（例：野球、サッカー）", value=default_sport)
            
            if is_new_member:
                st.markdown("---")
                consent = st.checkbox("【同意のお願い】入力されたデータは匿名データとして集計・活用されることに同意します。（必須）")
            else:
                consent = True

            if st.button("新しいメンバーを登録する" if is_new_member else "基本情報を更新する", type="primary"):
                if not edit_nickname:
                    st.error("ニックネームを入力してください。")
                elif is_new_member and not consent:
                    st.error("⚠️ 同意チェックが必要です。")
                else:
                    try:
                        profile_data = {
                            "parent_id": st.session_state["parent_id"], "nickname": edit_nickname, "birth_year": birth_year,
                            "init_height": init_height, "init_weight": init_weight, "sport": sport,
                            "updated_at": str(datetime.datetime.now())
                        }
                        if is_new_member:
                            profile_data["is_diagnosed"] = False
                            
                        supabase.table("user_profile").upsert(profile_data, on_conflict="parent_id,nickname").execute()
                        st.success(f"✨ 情報を保存しました！")
                        st.session_state["current_member"] = edit_nickname
                        st.rerun()
                    except Exception as e:
                        st.error(f"保存エラー: {e}")

            if not is_new_member and not is_diag:
                st.markdown("---")
                st.subheader("🩺 治療・経過観察モードへの切り替え")
                st.write(
                    "医師から分離症と診断された場合は、"
                    "前回の経過観察を再開するか、"
                    "新しい経過観察を開始できます。"
                )

                closed_sessions = [
                    row
                    for row in observation_sessions
                    if row.get("status") == "closed"
                ]

                if closed_sessions:
                    start_mode = st.radio(
                        "開始方法",
                        [
                            "前回の経過観察を再開",
                            "新しい経過観察を開始",
                        ],
                        key=f"observation_start_mode_{child_user_id}",
                    )
                else:
                    start_mode = "新しい経過観察を開始"
                    st.info(
                        "過去の経過観察はありません。"
                        "新しい経過観察を開始します。"
                    )

                selected_previous_session = None
                if start_mode == "前回の経過観察を再開":
                    selected_previous_session = st.selectbox(
                        "再開する経過観察",
                        closed_sessions,
                        format_func=format_observation_session,
                        key=f"previous_observation_{child_user_id}",
                    )

                button_label = (
                    "前回の経過観察を再開する"
                    if start_mode == "前回の経過観察を再開"
                    else "新しい経過観察を開始する"
                )
                if st.button(
                    button_label,
                    type="secondary",
                    use_container_width=True,
                    key=f"start_observation_{child_user_id}",
                ):
                    try:
                        if (
                            start_mode
                            == "前回の経過観察を再開"
                            and selected_previous_session
                        ):
                            resume_observation_session(
                                str(selected_previous_session["id"])
                            )
                        else:
                            create_observation_session(child_user_id)

                        supabase.table("user_profile").update({"is_diagnosed": True}).eq("parent_id", st.session_state["parent_id"]).eq("nickname", current_member).execute()
                        st.session_state.pop(
                            "generated_period_report",
                            None,
                        )
                        st.session_state.pop(
                            "daily_record_date",
                            None,
                        )
                        st.rerun()
                    except Exception as e:
                        st.error(f"モード切り替えエラー: {e}")
            
            if not is_new_member:
                st.markdown("---")
                with st.expander("メンバー記録の削除"):
                    st.warning(f"この操作は元に戻せません。")
                    if st.button(f"🗑️ {current_member} さんを削除する"):
                        try:
                            supabase.table("koshi_history").delete().eq("user_id", child_user_id).execute()
                            supabase.table("daily_history").delete().eq("user_id", child_user_id).execute()
                            supabase.table("observation_sessions").delete().eq("user_id", child_user_id).execute()
                            supabase.table("user_profile").delete().eq("parent_id", st.session_state["parent_id"]).eq("nickname", current_member).execute()
                            st.success(f"✔️ 削除しました。")
                            st.session_state["current_member"] = "➕ 新しいメンバーを追加"
                            st.rerun()
                        except Exception as e:
                            st.error(f"削除エラー: {e}")

    # ==========================================
    # 【通常モード用】定期チェックと受診用シート
    # ==========================================
    if "📝 毎月のチェック" in titles:
        with tabs[titles.index("📝 毎月のチェック")]:
            st.header(f"📝 {current_member} さんの定期セルフチェック")
            st.caption(
                "最低でも月1回のチェックをおすすめします。"
                "必要に応じて毎日チェックしても問題ありません。"
                "同じ日に再保存した場合は、その日の記録を更新します。"
            )

            flash_message = st.session_state.pop(
                "monthly_check_flash",
                None,
            )
            if flash_message:
                st.success(flash_message)

            today = datetime.date.today()
            first_day_this_month = today.replace(day=1)
            if today.month == 12:
                first_day_next_month = datetime.date(
                    today.year + 1,
                    1,
                    1,
                )
            else:
                first_day_next_month = datetime.date(
                    today.year,
                    today.month + 1,
                    1,
                )
            last_day_this_month = (
                first_day_next_month - datetime.timedelta(days=1)
            )

            try:
                month_result = (
                    supabase.table("koshi_history")
                    .select("checked_at")
                    .eq("user_id", child_user_id)
                    .gte("checked_at", str(first_day_this_month))
                    .lte("checked_at", str(last_day_this_month))
                    .execute()
                )
                month_count = len(month_result.data or [])
                if month_count == 0:
                    st.warning(
                        "今月はまだセルフチェックを行っていません。"
                        "体調確認のため、月1回以上のチェックをおすすめします。"
                    )
                else:
                    st.info(
                        f"今月は{month_count}回チェック済みです。"
                        "必要に応じて何度でもチェックできます。"
                    )
            except Exception:
                pass

            pending_check_date = st.session_state.pop(
                "pending_monthly_edit_date",
                None,
            )
            if pending_check_date is not None:
                st.session_state["monthly_check_date"] = pending_check_date

            if "monthly_check_date" not in st.session_state:
                st.session_state["monthly_check_date"] = today

            check_date = st.date_input(
                "チェック日",
                max_value=today,
                key="monthly_check_date",
                help="過去の日付を選ぶと、その日のチェックを編集できます。",
            )

            try:
                existing_check_records = get_date_records(
                    "koshi_history",
                    child_user_id,
                    check_date,
                )
            except Exception as e:
                existing_check_records = []
                st.warning(f"既存記録の確認に失敗しました: {e}")

            existing_check = (
                existing_check_records[-1]
                if existing_check_records
                else None
            )

            if existing_check:
                st.info(
                    f"{check_date:%Y年%m月%d日}のチェック記録があります。"
                    "保存すると新規追加ではなく、この日の記録を更新します。"
                )
                if len(existing_check_records) > 1:
                    st.warning(
                        "この日には過去の重複記録があります。"
                        "更新すると、可能な範囲で1件に整理します。"
                    )

            last_height, last_weight = init_height, init_weight
            try:
                res_latest = (
                    supabase.table("koshi_history")
                    .select("height, weight")
                    .eq("user_id", child_user_id)
                    .order("checked_at", desc=True)
                    .limit(1)
                    .execute()
                )
                if res_latest.data:
                    last_height = float(
                        res_latest.data[0].get("height") or last_height
                    )
                    last_weight = float(
                        res_latest.data[0].get("weight") or last_weight
                    )
            except Exception:
                pass

            if existing_check:
                last_height = float(
                    existing_check.get("height") or last_height
                )
                last_weight = float(
                    existing_check.get("weight") or last_weight
                )

            monthly_form_revision = st.session_state.get(
                "monthly_form_revision",
                0,
            )
            widget_suffix = (
                f"{child_user_id}_{check_date.isoformat()}_"
                f"{monthly_form_revision}"
            )

            st.subheader("【1】身長・体重の記録")
            not_measured_height = st.checkbox(
                "身長は今回は測っていない",
                key=f"check_height_unmeasured_{widget_suffix}",
            )
            current_height = st.number_input(
                "現在の身長 (cm)",
                value=last_height,
                min_value=100.0,
                max_value=250.0,
                step=0.1,
                disabled=not_measured_height,
                key=f"check_height_{widget_suffix}",
            )
            not_measured_weight = st.checkbox(
                "体重は今回は測っていない",
                key=f"check_weight_unmeasured_{widget_suffix}",
            )
            current_weight = st.number_input(
                "現在の体重 (kg)",
                value=last_weight,
                min_value=20.0,
                max_value=200.0,
                step=0.1,
                disabled=not_measured_weight,
                key=f"check_weight_{widget_suffix}",
            )

            st.subheader("【2】練習の頻度について")
            days_options = [
                "週1日",
                "週2日",
                "週3日",
                "週4日",
                "週5日",
                "週6日",
                "毎日（週7日）",
                "お休みしている",
            ]
            hours_options = [
                "1時間未満",
                "1〜2時間",
                "2〜3時間",
                "3〜4時間",
                "4時間以上",
                "お休みしている",
            ]
            saved_days = (
                existing_check.get("days_per_week")
                if existing_check
                else days_options[0]
            )
            saved_hours = (
                existing_check.get("hours_per_day")
                if existing_check
                else hours_options[0]
            )
            days_per_week = st.selectbox(
                "最近、週に何回くらい練習していますか？",
                days_options,
                index=safe_option_index(days_options, saved_days),
                key=f"check_days_{widget_suffix}",
            )
            hours_per_day = st.selectbox(
                "1日あたり、何時間くらい練習していますか？",
                hours_options,
                index=safe_option_index(hours_options, saved_hours),
                key=f"check_hours_{widget_suffix}",
            )

            st.subheader("【3】動作セルフチェック")
            answers = {}
            for q in questions["self_check"]:
                saved_answer = None
                if existing_check:
                    if q["id"] == "kemp":
                        saved_answer = existing_check.get("kemp_pain")
                    elif q["id"] == "one_leg":
                        saved_answer = existing_check.get("one_leg_pain")

                st.markdown(f"### {q['text']}")
                answers[q["id"]] = st.radio(
                    "回答を選択してください：",
                    q["options"],
                    index=safe_option_index(
                        q["options"],
                        saved_answer,
                    ),
                    key=f"check_{q['id']}_{widget_suffix}",
                    label_visibility="collapsed",
                )
                st.markdown("---")

            st.subheader("【4】簡易問診")
            daily_pain_options = {
                "全く痛みはない": 0,
                "たまにある": 1,
                "頻繁に痛くなる": 2,
            }
            sports_pain_options = {
                "全く痛みはない": 0,
                "たまにある": 1,
                "頻繁に痛くなる": 3,
            }
            saved_daily_pain, saved_sports_pain = parse_pain_duration(
                existing_check.get("duration")
                if existing_check
                else None
            )

            daily_pain = st.radio(
                "日常生活で腰に痛みが出ますか？",
                list(daily_pain_options.keys()),
                index=safe_option_index(
                    list(daily_pain_options.keys()),
                    saved_daily_pain,
                ),
                key=f"daily_pain_{widget_suffix}",
            )
            sports_pain = st.radio(
                "スポーツ（運動時）で腰に痛みが出ますか？",
                list(sports_pain_options.keys()),
                index=safe_option_index(
                    list(sports_pain_options.keys()),
                    saved_sports_pain,
                ),
                key=f"sports_pain_{widget_suffix}",
            )

            monshin_score = (
                daily_pain_options[daily_pain]
                + sports_pain_options[sports_pain]
            )
            is_alert = (
                answers.get("kemp") == "ハッキリと痛い"
                or answers.get("one_leg")
                in ["片側だけ痛い", "両方痛い"]
                or monshin_score >= 3
            )

            save_col, delete_col = st.columns(2)

            with save_col:
                save_label = (
                    "この日のチェック結果を更新する"
                    if existing_check
                    else "この日のチェック結果を保存する"
                )
                if st.button(
                    save_label,
                    type="primary",
                    use_container_width=True,
                    key=f"save_check_{widget_suffix}",
                ):
                    st.subheader("【判定結果】")
                    if monshin_score == 0:
                        st.success("💚 **心配ない**")
                    elif monshin_score in [1, 2]:
                        st.warning(
                            "⚠️ **少し心配です。様子を確認して、"
                            "必要に応じて整形外科の受診をお勧めします。**"
                        )
                    else:
                        st.error(
                            "🚨 **早めに整形外科の受診をお勧めします**"
                        )

                    if is_alert and monshin_score < 3:
                        st.error(
                            "⚠️ **動作チェックで痛みが出ているため、"
                            "整形外科の受診もご検討ください。**"
                        )
                    if is_alert:
                        st.info(
                            "💡 **「🏥 受診用シート作成」タブを開くと、"
                            "病院提出用のレポートを作成できます。**"
                        )

                    try:
                        data = {
                            "user_id": child_user_id,
                            "checked_at": str(check_date),
                            "height": current_height,
                            "weight": current_weight,
                            "sport": (
                                existing_check.get("sport") or sport
                                if existing_check
                                else sport
                            ),
                            "days_per_week": days_per_week,
                            "hours_per_day": hours_per_day,
                            "kemp_pain": answers.get(
                                "kemp",
                                "未記録",
                            ),
                            "one_leg_pain": answers.get(
                                "one_leg",
                                "未記録",
                            ),
                            "duration": (
                                f"日常:{daily_pain} / 運動:{sports_pain}"
                            ),
                        }
                        action = save_date_record(
                            "koshi_history",
                            existing_check_records,
                            data,
                        )
                        if action == "updated":
                            st.success(
                                "✨ この日のセルフチェックを更新しました。"
                            )
                        else:
                            st.success(
                                "✨ この日のセルフチェックを保存しました。"
                            )
                    except Exception as e:
                        st.warning(f"データ保存エラー: {e}")

            with delete_col:
                if existing_check:
                    if st.button(
                        "この日のチェックを削除",
                        use_container_width=True,
                        key=f"delete_check_{widget_suffix}",
                    ):
                        try:
                            delete_date_records(
                                "koshi_history",
                                existing_check_records,
                                child_user_id,
                                check_date,
                            )
                            st.session_state[
                                "monthly_form_revision"
                            ] = monthly_form_revision + 1
                            st.session_state["monthly_check_flash"] = (
                                f"{check_date:%Y年%m月%d日}"
                                "のセルフチェックを削除しました。"
                            )
                            st.rerun()
                        except Exception as e:
                            st.error(f"記録の削除エラー: {e}")
                else:
                    st.button(
                        "この日のチェックを削除",
                        disabled=True,
                        use_container_width=True,
                        key=f"delete_check_disabled_{widget_suffix}",
                    )

    if "🏥 受診用シート作成" in titles:
        with tabs[titles.index("🏥 受診用シート作成")]:
            st.header(f"🏥 {current_member} さんの受診用シート作成")
            detailed_answers = {}
            for q in questions["detailed_monshin"]:
                st.markdown(f"**{q['text']}**")
                detailed_answers[q["id"]] = st.radio(
                    "回答を選択してください：",
                    q["options"],
                    key=f"tab5_detailed_{q['id']}",
                    label_visibility="collapsed",
                )
                st.markdown("---")

            if st.button(
                "📄 病院提出用PDFを作成する",
                type="primary",
            ):
                try:
                    res_latest = (
                        supabase.table("koshi_history")
                        .select("*")
                        .eq("user_id", child_user_id)
                        .order("checked_at", desc=True)
                        .limit(1)
                        .execute()
                    )
                    if not res_latest.data:
                        st.session_state.pop(
                            "generated_consultation_report",
                            None,
                        )
                        st.error(
                            "⚠️ まだ「毎月のチェック」の記録がありません。"
                        )
                    else:
                        latest = res_latest.data[0]
                        pdf = FPDF()
                        pdf.add_page()
                        pdf.add_font("NotoSans", "", FONT_PATH)
                        pdf.set_font("NotoSans", size=16)
                        pdf.cell(
                            200,
                            10,
                            text=(
                                "腰椎分離症セルフチェック "
                                "診察提出用レポート"
                            ),
                            new_x=XPos.LMARGIN,
                            new_y=YPos.NEXT,
                            align="C",
                        )
                        pdf.ln(10)
                        pdf.set_font("NotoSans", size=11)
                        pdf.cell(
                            200,
                            8,
                            text=f"対象メンバー: {current_member}",
                            new_x=XPos.LMARGIN,
                            new_y=YPos.NEXT,
                        )
                        pdf.cell(
                            200,
                            8,
                            text=(
                                f"基本情報: 身長 {latest['height']} cm / "
                                f"体重 {latest['weight']} kg / "
                                f"スポーツ {latest['sport']}"
                            ),
                            new_x=XPos.LMARGIN,
                            new_y=YPos.NEXT,
                        )
                        pdf.cell(
                            200,
                            8,
                            text=(
                                "反らせた時の痛み: "
                                f"{latest.get('kemp_pain', '未記録')} / "
                                "片脚立ち痛み: "
                                f"{latest.get('one_leg_pain', '未記録')}"
                            ),
                            new_x=XPos.LMARGIN,
                            new_y=YPos.NEXT,
                        )
                        pdf.ln(5)
                        for q in questions["detailed_monshin"]:
                            pdf.cell(
                                200,
                                8,
                                text=f"Q. {q['text']}",
                                new_x=XPos.LMARGIN,
                                new_y=YPos.NEXT,
                            )
                            pdf.cell(
                                200,
                                8,
                                text=(
                                    "   => "
                                    f"{detailed_answers[q['id']]}"
                                ),
                                new_x=XPos.LMARGIN,
                                new_y=YPos.NEXT,
                            )

                        pdf_bytes = bytes(pdf.output())
                        st.session_state[
                            "generated_consultation_report"
                        ] = {
                            "pdf_bytes": pdf_bytes,
                            "file_name": (
                                f"koshi_report_{current_member}_"
                                f"{datetime.date.today()}.pdf"
                            ),
                            "storage_path": None,
                            "signed_url": None,
                            "qr_png": None,
                            "member": current_member,
                        }

                        try:
                            storage_path, signed_url, qr_png = (
                                upload_report_pdf(pdf_bytes)
                            )
                            st.session_state[
                                "generated_consultation_report"
                            ].update(
                                {
                                    "storage_path": storage_path,
                                    "signed_url": signed_url,
                                    "qr_png": qr_png,
                                }
                            )
                            st.success(
                                "受診用PDFとQRコードを作成しました。"
                            )
                        except Exception as qr_error:
                            st.warning(
                                "受診用PDFは作成できましたが、"
                                "QRコードの作成に失敗しました。"
                                "PDFはそのままダウンロードできます。"
                                f" 詳細: {qr_error}"
                            )
                except Exception as e:
                    st.error(f"PDF作成エラー: {e}")

            consultation_report = st.session_state.get(
                "generated_consultation_report"
            )
            if (
                consultation_report
                and consultation_report.get("member") == current_member
            ):
                st.download_button(
                    label="📥 受診用PDFをダウンロード",
                    data=consultation_report["pdf_bytes"],
                    file_name=consultation_report["file_name"],
                    mime="application/pdf",
                    use_container_width=True,
                    key=(
                        "download_consultation_report_"
                        + (
                            consultation_report.get("storage_path")
                            or consultation_report["file_name"]
                        )
                    ),
                )

                if (
                    consultation_report.get("qr_png")
                    and consultation_report.get("signed_url")
                ):
                    st.markdown("---")
                    st.subheader("📱 医師へ提示するQRコード")
                    st.image(
                        consultation_report["qr_png"],
                        width=260,
                    )
                    st.link_button(
                        "受診用PDFをブラウザで開いて確認する",
                        consultation_report["signed_url"],
                        use_container_width=True,
                    )
                    st.caption(
                        "このQRコードは発行から10分間有効です。"
                        "期限切れになった場合は、もう一度"
                        "「病院提出用PDFを作成する」を押してください。"
                    )
                else:
                    st.info(
                        "QRコードは作成されていません。"
                        "PDFダウンロードは利用できます。"
                    )

    # ==========================================
    # 【共通】成長・経過観察のグラフ推移 & 💡 修正点2: PDFレイアウトの整理
    # ==========================================
    main_chart_title = "📈 経過観察の推移" if is_diag else "📈 成長と推移"
    if main_chart_title in titles:
        with tabs[titles.index(main_chart_title)]:
            st.header(f"📈 {current_member} さんの記録履歴")
            if is_diag and active_observation_session:
                st.caption(
                    "表示中の経過観察: "
                    + format_observation_session(
                        active_observation_session
                    )
                )
            
            if is_diag:
                try:
                    daily_res_query = (
                        supabase.table("daily_history")
                        .select("*")
                        .eq("user_id", child_user_id)
                    )
                    if active_observation_session_id:
                        daily_res_query = daily_res_query.eq(
                            "observation_session_id",
                            active_observation_session_id,
                        )
                    daily_res = daily_res_query.order(
                        "checked_at"
                    ).execute()
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
                        existing_cols = [c for c in cols if c in df_daily_sorted.columns]
                        display_daily_df = df_daily_sorted[existing_cols].copy()
                        st.dataframe(display_daily_df.fillna("-"))

                        unique_daily_dates = sorted(
                            {
                                value.date()
                                for value in df_daily["checked_at"]
                                if not pd.isna(value)
                            },
                            reverse=True,
                        )
                        if unique_daily_dates:
                            selected_daily_edit_date = st.selectbox(
                                "編集する記録日を選択",
                                unique_daily_dates,
                                format_func=lambda value: value.strftime(
                                    "%Y年%m月%d日"
                                ),
                                key=f"daily_history_edit_date_{child_user_id}",
                            )
                            if st.button(
                                "選択した日の記録を編集する",
                                key=f"daily_history_edit_button_{child_user_id}",
                            ):
                                st.session_state[
                                    "pending_daily_edit_date"
                                ] = selected_daily_edit_date
                                st.rerun()
                        
                        # --- 指定期間のPDFダウンロード機能 ---
                        st.markdown("---")
                        st.subheader("🖨️ 指定期間の記録レポートを作成")
                        col1, col2 = st.columns(2)
                        with col1:
                            start_date = st.date_input("開始日", datetime.date.today() - datetime.timedelta(days=7))
                        with col2:
                            end_date = st.date_input("終了日", datetime.date.today())
                        
                        if start_date > end_date:
                            st.error("開始日は終了日以前の日付を選択してください。")
                        elif st.button("📥 指定期間のPDFを作成する", type="primary"):
                            try:
                                res_pdf_query = (
                                    supabase.table("daily_history")
                                    .select("*")
                                    .eq("user_id", child_user_id)
                                    .gte("checked_at", str(start_date))
                                    .lte("checked_at", str(end_date))
                                )
                                if active_observation_session_id:
                                    res_pdf_query = res_pdf_query.eq(
                                        "observation_session_id",
                                        active_observation_session_id,
                                    )
                                res_pdf = res_pdf_query.order(
                                    "checked_at"
                                ).execute()

                                if not res_pdf.data:
                                    st.session_state.pop("generated_period_report", None)
                                    st.warning("指定期間内に記録がありません。")
                                else:
                                    # 横向きA4にして表の横幅を確保する。
                                    pdf = FPDF(orientation="L", format="A4")
                                    pdf.set_margins(10, 10, 10)
                                    pdf.set_auto_page_break(auto=True, margin=12)
                                    pdf.add_page()
                                    pdf.add_font("NotoSans", "", FONT_PATH)

                                    pdf.set_font("NotoSans", size=16)
                                    pdf.cell(
                                        pdf.epw,
                                        10,
                                        text=f"{current_member} さんの経過観察レポート",
                                        new_x=XPos.LMARGIN,
                                        new_y=YPos.NEXT,
                                        align="C",
                                    )
                                    pdf.set_font("NotoSans", size=11)
                                    pdf.cell(
                                        pdf.epw,
                                        10,
                                        text=f"期間: {start_date} 〜 {end_date}",
                                        new_x=XPos.LMARGIN,
                                        new_y=YPos.NEXT,
                                        align="C",
                                    )
                                    pdf.ln(5)

                                    # 横向きA4の印刷可能幅に合わせる。
                                    column_widths = [30, 75, 75, pdf.epw - 180]
                                    draw_period_report_header(pdf, column_widths)

                                    # 内容は省略せず、文章量に合わせて行の高さを自動調整する。
                                    for row in res_pdf.data:
                                        row_values = [
                                            normalize_pdf_text(
                                                row.get("checked_at"),
                                                "未入力",
                                            ),
                                            normalize_pdf_text(
                                                row.get("pain_level"),
                                                "未入力",
                                            ),
                                            normalize_pdf_text(
                                                row.get("corset_time"),
                                                "なし",
                                            ),
                                            normalize_pdf_text(
                                                row.get("practice_content"),
                                                "なし",
                                            ),
                                        ]
                                        draw_period_report_row(
                                            pdf,
                                            row_values,
                                            column_widths,
                                        )

                                    pdf_bytes = bytes(pdf.output())

                                    # 先にPDF情報を保存する。
                                    # QRコード作成に失敗しても、PDFはダウンロードできる。
                                    st.session_state["generated_period_report"] = {
                                        "pdf_bytes": pdf_bytes,
                                        "file_name": (
                                            f"report_{current_member}_"
                                            f"{start_date}_{end_date}.pdf"
                                        ),
                                        "storage_path": None,
                                        "signed_url": None,
                                        "qr_png": None,
                                        "member": current_member,
                                        "start_date": str(start_date),
                                        "end_date": str(end_date),
                                    }

                                    # QRコード作成だけを別処理にする。
                                    # Storageや署名付きURLでエラーが出ても、
                                    # 既存のPDFダウンロード機能は残る。
                                    try:
                                        storage_path, signed_url, qr_png = (
                                            upload_report_pdf(pdf_bytes)
                                        )

                                        st.session_state[
                                            "generated_period_report"
                                        ].update(
                                            {
                                                "storage_path": storage_path,
                                                "signed_url": signed_url,
                                                "qr_png": qr_png,
                                            }
                                        )

                                        st.success(
                                            "PDFとQRコードを作成しました。"
                                        )
                                    except Exception as qr_error:
                                        st.warning(
                                            "PDFは作成できましたが、"
                                            "QRコードの作成に失敗しました。"
                                            "PDFはそのままダウンロードできます。"
                                            f" 詳細: {qr_error}"
                                        )
                            except Exception as e:
                                st.error(f"PDF作成エラー: {e}")

                        generated_report = st.session_state.get(
                            "generated_period_report"
                        )

                        # 現在選択しているメンバー・期間のPDFだけ表示する
                        if (
                            generated_report
                            and generated_report.get("member") == current_member
                            and generated_report.get("start_date")
                            == str(start_date)
                            and generated_report.get("end_date")
                            == str(end_date)
                        ):
                            st.download_button(
                                label="📥 PDFをダウンロード",
                                data=generated_report["pdf_bytes"],
                                file_name=generated_report["file_name"],
                                mime="application/pdf",
                                use_container_width=True,
                                key=(
                                    "download_period_report_"
                                    + (
                                        generated_report.get("storage_path")
                                        or generated_report["file_name"]
                                    )
                                ),
                            )

                            # QRコード作成に成功した場合だけ表示する
                            if (
                                generated_report.get("qr_png")
                                and generated_report.get("signed_url")
                            ):
                                st.markdown("---")
                                st.subheader("📱 医師へ提示するQRコード")
                                st.image(
                                    generated_report["qr_png"],
                                    width=260,
                                )
                                st.link_button(
                                    "PDFをブラウザで開いて確認する",
                                    generated_report["signed_url"],
                                    use_container_width=True,
                                )
                                st.caption(
                                    "このQRコードは発行から10分間有効です。"
                                    "期限切れになった場合は、もう一度"
                                    "「指定期間のPDFを作成する」を押してください。"
                                )
                            else:
                                st.info(
                                    "QRコードは作成されていません。"
                                    "PDFダウンロードは利用できます。"
                                )
                    else:
                        st.info("まだ毎日の経過観察記録がありません。")
                except Exception: pass
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

                        unique_check_dates = sorted(
                            {
                                value.date()
                                for value in df["checked_at"]
                                if not pd.isna(value)
                            },
                            reverse=True,
                        )
                        if unique_check_dates:
                            selected_check_edit_date = st.selectbox(
                                "編集するチェック日を選択",
                                unique_check_dates,
                                format_func=lambda value: value.strftime(
                                    "%Y年%m月%d日"
                                ),
                                key=f"normal_history_edit_date_{child_user_id}",
                            )
                            if st.button(
                                "選択した日のチェックを編集する",
                                key=f"normal_history_edit_button_{child_user_id}",
                            ):
                                st.session_state[
                                    "pending_monthly_edit_date"
                                ] = selected_check_edit_date
                                st.rerun()
                    else:
                        st.info("まだ毎月の定期チェック記録がありません。")
                except Exception: pass

if st.session_state.user is None:
    show_auth_page()
else:
    show_main_app()