#これは朝7:00に朝昼晩のメニュー、昼12:00に昼食のメニュー、夕18:00に夕食のメニューをLINEで自動送信してくれるプログラムであ～る
import os
import io
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo

import requests
import pdfplumber

from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    PushMessageRequest,
    TextMessage
)

# --- 設定項目 ---
CHANNEL_ACCESS_TOKEN = os.getenv('CHANNEL_ACCESS_TOKEN')
USER_ID = os.getenv('USER_ID')

def generate_menu_url(target_date):
    """
    特定の日付に基づいて、その週の月曜日の日付を使った献立表PDFのURLを生成する。
    【役割】URLのルールに基づいて文字列を生成するだけ。アクセスはしない。
    """
    monday = target_date - timedelta(days=target_date.weekday())
    
    filename_year = str(monday.year)
    filename_month = f"{monday.month:02d}"
    filename_day = f"{monday.day:02d}"
    
    # 献立表が前月のフォルダにある場合を考慮、フォルダーの"月"だけは2週間前
    date_for_folder = monday - timedelta(days=7)
    folder_year = str(date_for_folder.year)
    date_for_folder = monday - timedelta(weeks=2)
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
        
        header_row = kondate_table[0]
        day_str_to_find = str(target_date.day)
        col_index_for_today = -1

        for i, header_text in enumerate(header_row):
            if day_str_to_find in (header_text or ""):
                col_index_for_today = i
                print(f"→ 日付'{day_str_to_find}'をヘッダー'{header_text}'(列番号{i})で発見。")
                break
        
        if col_index_for_today == -1:
            raise ValueError(f"献立表のヘッダーに今日の日付({day_str_to_find})が見つかりませんでした。")

        menu_asa = (kondate_table[1][col_index_for_today] or "").replace('\n', ' ') or "記載なし"
        menu_hiru = (kondate_table[8][col_index_for_today] or "").replace('\n', ' ') or "記載なし"
        # 【修正】夕食の行番号を以前の[16]に戻しました。もし[15]が正しい場合は修正してください。
        menu_yoru = (kondate_table[15][col_index_for_today] or "").replace('\n', ' ') or "記載なし"

    return menu_asa, menu_hiru, menu_yoru

def main(request):
    """
    メインの実行関数
    """
    line_bot_api_client = None
    if CHANNEL_ACCESS_TOKEN:
        configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)
        line_bot_api_client = ApiClient(configuration)

    message_text = ""
    jst = ZoneInfo("Asia/Tokyo")
    now_jst = datetime.now(jst)
    today = now_jst.date()
    pdf_content = None
    pdf_url = ""
    
    # 【修正】過去の週を遡ってPDFを探すロジックを復活させます
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
            menu_asa, menu_hiru, menu_yoru = parse_menu_from_pdf(pdf_content, today)
            
            if now_jst.hour == 6 or now_jst.hour == 7:
                message_text = (
                    f"【本日の寮食メニュー ({today.strftime('%-m/%-d')})】\n\n"
                    f"■ 朝食\n{menu_asa}\n\n"
                    f"■ 昼食\n{menu_hiru}\n\n"
                    f"■ 夕食\n{menu_yoru}"
                )
            elif now_jst.hour == 11 or now_jst.hour == 12:
                message_text = (
                    f"【お昼の寮食メニュー ({today.strftime('%-m/%-d')})】\n\n"
                    f"■ 昼食\n{menu_hiru}"
                )
            elif now_jst.hour == 17 or now_jst.hour == 18:
                message_text = (
                    f"【夜ご飯の寮食メニュー ({today.strftime('%-m/%-d')})】\n\n"
                    f"■ 夕食\n{menu_yoru}"
                )
            else:
                message_text = (
                    f"【これはTEST送信である ({today})】\n"
                    f"{now_jst}\n\n"
                    f"■ 朝食\n{menu_asa}\n\n"
                    f"■ 昼食\n{menu_hiru}\n\n"
                    f"■ 夕食\n{menu_yoru}"                    
                )
            
        except ValueError as e:
            message_text = (
                f"【お知らせ】\n献立表の解析に失敗しました。\n"
                f"理由: {e}\n\n"
                f"▼解析しようとしたPDFのURL\n{pdf_url}"
            )
    else:
        message_text = f"【お知らせ】\n直近3週間の献立表PDFが見つかりませんでした。\n最後に試したURL: {pdf_url}"

    if message_text:
        if not line_bot_api_client or not USER_ID:
            print("環境変数が設定されていないため、LINE送信をスキップします。")
            print(f"送信予定だったメッセージ:\n{message_text}")
            return 'Success (skipped LINE push)', 200

        try:
            line_bot_api = MessagingApi(line_bot_api_client)
            line_bot_api.push_message(PushMessageRequest(to=USER_ID, messages=[TextMessage(text=message_text)]))
            print("LINEメッセージを送信しました。")
        except Exception as e:
            print(f"LINE送信中にエラーが発生しました: {e}")
            
    else:
        print("送信するメッセージがありません。時間外か、PDFの取得・解析に失敗しました。")

    return 'Success', 200

if __name__ == '__main__':
    main(None)