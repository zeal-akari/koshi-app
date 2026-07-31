# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## プロジェクト概要

koshi.appは、若年アスリートに多い**腰椎分離症**のセルフチェック・記録・管理を行うStreamlit製Webアプリです。保護者が複数の子ども（「メンバー」）を管理でき、「診断前のセルフチェック・経過観察」と「診断後の治療管理（コルセット、回復観察）」の2モードを持ちます。UI・コンテンツはすべて日本語です。

## コマンド

```bash
# 依存関係のインストール
pip install -r requirements.txt

# ローカルでの起動
streamlit run app.py
```

このリポジトリにはテスト一式・リンター・ビルド手順は設定されていません。

## デプロイ

Render上にデプロイされており（`render.yaml`）、以下のコマンドで起動します。
```bash
streamlit run app.py --server.port $PORT --server.address 0.0.0.0
```
Pythonバージョンは`.python-version`で固定（3.12）。`requirements.txt`内の`pandas`/`pyarrow`はバージョン固定されています（直近のコミット履歴の通り、新しいバージョンでのpyarrowセグフォルト／DataFrameクラッシュが理由）。安易に更新しないよう注意してください。

## アーキテクチャ

アプリ全体が単一ファイル`app.py`（約2100行）に実装されており、ヘルパー関数とページ描画関数がStreamlitスクリプトとして上から順に実行される構成です。

**データ・バックエンド**: Supabase（Postgres + Auth + Storage）を使用。クライアントは`init_supabase()`で生成し`st.session_state["supabase_client"]`にキャッシュされます。認証はSupabaseのメール/パスワード認証（`show_auth_page`）で、ログインユーザーのidが「親（parent）」アカウントとなります。

**中心的なドメインモデル**:
- 1つのSupabase認証ユーザー（親）が複数の**メンバー**（子ども）を持つことができ、ニックネームで識別されます。`child_user_id`は`f"{parent_id}_{nickname}"`として組み立てられ、各レコードの外部キーとして使われます。
- Supabaseテーブル: `user_profile`（メンバーごとのプロフィール：診断状況、コルセット情報）、`koshi_history`（毎月のセルフチェック記録）、`daily_history`（治療中の毎日の記録）、`observation_sessions`（回復経過観察の1クールを管理、開始・終了で追跡）。
- `questions.json`はセルフチェック・問診の質問内容（`self_check`、`monshin`、`detailed_monshin`）を定義しています。これらは動的に描画されるため、質問の追加・編集はコード変更なしでここを直接編集すれば反映されます。

**モードによるUI切り替え**: `show_main_app()`は、選択中メンバーの`user_profile`テーブルの`is_diagnosed`フラグに応じて表示するタブを切り替えます。
- 未診断 → セルフチェックフロー: 「メンバー情報」「毎月のチェック」「成長と推移」「受診用シート作成」（受診時に持参するPDFレポート＋QRコードを生成）。
- 診断済み → 治療フロー: 「治療・コルセット設定」「毎日の記録」「経過観察の推移」「基本情報」。

メンバーを診断済みモードへ切り替えると、`observation_sessions`のレコードが自動作成されます（`create_observation_session`）。これは、この機能導入前から診断済みだったユーザーの過去データを引き続き扱えるようにするためです。

**PDF・レポート生成**: `fpdf2`を使用し、同梱の日本語フォント（`NotoSansJP-Regular.ttf`、未配置の場合は初回起動時にGoogle Fontsから自動ダウンロード）でPDFを生成します。生成したPDFはSupabase Storageにアップロードし（`upload_report_pdf`）、署名付きURLをQRコード（`qrcode`）に変換することで、受診先でスマートフォンから開けるようにしています。

**グラフ**: 成長・推移グラフには`altair`を使用（`koshi_history`/`daily_history`から構築した`pandas`のDataFrameを描画）。

**機密情報の扱い**: SupabaseのURLとanon/publishableキーは`app.py`冒頭にハードコードされています（環境変数化されていません）。これはpublishableキーであるため意図的な設計であり、`.env`への切り出しが必要な機密情報として扱う必要はありません。
