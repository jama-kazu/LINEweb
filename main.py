import os
import datetime
import requests
import io
import pdfplumber

# LINE SDK v3のインポートに変更
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    PushMessageRequest,
    TextMessage
)

# 必要なものをdatetimeから直接インポート
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo

# --- 設定項目 ---
CHANNEL_ACCESS_TOKEN = os.getenv('CHANNEL_ACCESS_TOKEN')
USER_ID = os.getenv('USER_ID')

def generate_menu_url(target_date):
    """
    特定の日付に基づいて、その週の月曜日の日付を使った献立表PDFのURLを生成する。
    """
    monday = target_date - timedelta(days=target_date.weekday())
    
    filename_year = str(monday.year)
    filename_month = f"{monday.month:02d}"
    filename_day = f"{monday.day:02d}"
    
    date_for_folder = monday - timedelta(days=7)
    folder_year = str(date_for_folder.year)
    folder_month = f"{date_for_folder.month:02d}"
    
    return f"https://www.numazu-ct.ac.jp/wp-content/uploads/{folder_year}/{folder_month}/kondate-{filename_year}{filename_month}{filename_day}.pdf"

def parse_menu_from_pdf(pdf_content, target_date):
    """
    PDFのバイトデータから、特定の日付の献立を解析して文字列を返す。
    """
    pdf_file = io.BytesIO(pdf_content)
    with pdfplumber.open(pdf_file) as pdf:
        page = pdf.pages[0]
        tables = page.extract_tables()

        if not tables:
            raise ValueError("PDFからテーブルが抽出できませんでした。")

        kondate_table = tables[0]
        col_index_for_today = target_date.weekday() + 1

        if col_index_for_today > len(kondate_table[0]) - 1:
            raise ValueError("本日は献立の記載がありません（土日または祝日の可能性があります）。")

        header_date = kondate_table[0][col_index_for_today]
        if str(target_date.day) not in header_date:
            raise ValueError(f"テーブルのヘッダー({header_date})が今日の日付({target_date.day})と一致しません。")
        
        menu_asa = (kondate_table[1][col_index_for_today] or "").replace('\n', ' ') or "記載なし"
        menu_hiru = (kondate_table[2][col_index_for_today] or "").replace('\n', ' ') or "記載なし"
        menu_yoru = (kondate_table[3][col_index_for_today] or "").replace('\n', ' ') or "記載なし"

        return (
            f"【本日の寮食メニュー ({target_date.strftime('%-m/%-d')})】\n\n"
            f"■ 朝食\n{menu_asa}\n\n"
            f"■ 昼食\n{menu_hiru}\n\n"
            f"■ 夕食\n{menu_yoru}"
        )

def main(request):
    """
    メインの実行関数
    """
    message_text = ""
    
    jst = ZoneInfo("Asia/Tokyo")
    now_jst = datetime.now(jst)
    today = now_jst.date()

    pdf_content = None
    # 3週間前まで試行
    for i in range(3):
        check_date = today - timedelta(weeks=i)
        pdf_url = generate_menu_url(check_date)
        print(f"URLを試行中: {pdf_url}")

        try:
            response = requests.get(pdf_url, timeout=10)
            response.raise_for_status()
            pdf_content = response.content
            print(f"→ PDFを発見！ URL: {pdf_url}")
            break
        except requests.exceptions.HTTPError:
            print("→ 見つかりません。次の週を試します。")
            continue
    
    if pdf_content:
        try:
            message_text = parse_menu_from_pdf(pdf_content, today)
        except ValueError as e:
            message_text = f"【お知らせ】\n献立表PDFはありましたが、本日の献立を解析できませんでした。\n理由: {e}"
    else:
        # 3週間探しても見つからなかった場合、最後に試行したURLをメッセージに含める
        message_text = f"【お知らせ】\n直近の献立表PDFが見つかりませんでした。\n最後に試したURL: {pdf_url}"

    # --- LINE送信処理 (v3の書き方に変更) ---
    if not CHANNEL_ACCESS_TOKEN or not USER_ID:
        print("環境変数 CHANNEL_ACCESS_TOKEN または USER_ID が設定されていません。")
        print(f"送信予定だったメッセージ:\n{message_text}")
        return 'Success (skipped LINE push)', 200

    configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)
    try:
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            line_bot_api.push_message(
                PushMessageRequest(
                    to=USER_ID,
                    messages=[TextMessage(text=message_text)]
                )
            )
        print("LINEメッセージを送信しました。")
    except Exception as e:
        print(f"LINE送信中にエラーが発生しました: {e}")

    return 'Success', 200

# --- ローカルでのテスト用 ---
if __name__ == '__main__':
    main(None)