# main.py
import os
import io
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from flask import Flask, request, abort

# 必要なライブラリ
import requests
import pdfplumber
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi,
    ReplyMessageRequest, TextMessage
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent

# --- Flaskアプリの初期化 ---
app = Flask(__name__)

# --- LINE Botの認証情報を環境変数から取得 ---
CHANNEL_ACCESS_TOKEN = os.getenv('CHANNEL_ACCESS_TOKEN', '')
CHANNEL_SECRET = os.getenv('CHANNEL_SECRET', '')

configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)

# --- 献立取得ロジック（ここまでの成果物を統合） ---
def generate_menu_url(target_date):
    monday = target_date - timedelta(days=target_date.weekday())
    year_str = str(monday.year)
    month_str = f"{monday.month:02d}"
    day_str = f"{monday.day:02d}"
    return f"https://www.numazu-ct.ac.jp/wp-content/uploads/{year_str}/{month_str}/kondate-{year_str}{month_str}{day_str}.pdf"

def parse_menu_from_pdf(pdf_content, target_date):
    pdf_file = io.BytesIO(pdf_content)
    with pdfplumber.open(pdf_file) as pdf:
        page = pdf.pages[0]
        tables = page.extract_tables()
        if not tables:
            raise ValueError("PDFからテーブルが抽出できませんでした。")
        kondate_table = tables[0]
        header_row = kondate_table[0]
        day_str_to_find = str(target_date.day)
        col_index_for_today = -1
        for i, header_text in enumerate(header_row):
            if day_str_to_find in (header_text or ""):
                col_index_for_today = i
                break
        if col_index_for_today == -1:
            raise ValueError(f"献立表のヘッダーに今日の日付({day_str_to_find})が見つかりませんでした。")
        menu_asa = (kondate_table[1][col_index_for_today] or "").replace('\n', ' ') or "記載なし"
        menu_hiru = (kondate_table[8][col_index_for_today] or "").replace('\n', ' ') or "記載なし"
        menu_yoru = (kondate_table[15][col_index_for_today] or "").replace('\n', ' ') or "記載なし"
    return (
        f"【本日の寮食メニュー ({target_date.strftime('%-m/%-d')})】\n\n"
        f"■ 朝食\n{menu_asa}\n\n"
        f"■ 昼食\n{menu_hiru}\n\n"
        f"■ 夕食\n{menu_yoru}"
    )

def get_today_menu_text():
    """今日の献立を取得して、最終的なメッセージ文字列を生成する関数"""
    jst = ZoneInfo("Asia/Tokyo")
    today = datetime.now(jst).date()
    pdf_content = None
    pdf_url = ""
    for i in range(3):
        check_date = today - timedelta(weeks=i)
        pdf_url = generate_menu_url(check_date)
        try:
            response = requests.get(pdf_url, timeout=10)
            response.raise_for_status()
            pdf_content = response.content
            break
        except requests.exceptions.HTTPError:
            continue
    if pdf_content:
        try:
            return parse_menu_from_pdf(pdf_content, today)
        except ValueError as e:
            return f"【お知らせ】\n献立表の解析に失敗しました。\n理由: {e}\n\n▼試したURL\n{pdf_url}"
    else:
        return f"【お知らせ】\n直近3週間の献立表PDFが見つかりませんでした。\n最後に試したURL: {pdf_url}"

# --- Webhookのメイン処理 ---
@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

# --- メッセージ受信時の処理 ---
@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    """ユーザーからテキストメッセージを受け取った時の処理"""
    if event.message.text.strip() == "メニュー":
        reply_text = get_today_menu_text()
    else:
        reply_text = "「メニュー」と送信してね！"

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply_text)]
            )
        )

# GCFで実行するための設定
# このファイルが直接実行された場合は何もしない
if __name__ == "__main__":
    # ローカルでのテスト用。デプロイ時は使われない。
    # app.run(port=8080, debug=True)
    pass