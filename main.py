import os
import io
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import requests
import pdfplumber
from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi,
    PushMessageRequest, TextMessage
)

# --- 設定項目 ---
CHANNEL_ACCESS_TOKEN = os.getenv('CHANNEL_ACCESS_TOKEN')
USER_ID = os.getenv('USER_ID')

def generate_menu_url(target_date):
    monday = target_date - timedelta(days=target_date.weekday())
    year_str, month_str, day_str = str(monday.year), f"{monday.month:02d}", f"{monday.day:02d}"
    return f"https://www.numazu-ct.ac.jp/wp-content/uploads/{year_str}/{month_str}/kondate-{year_str}{month_str}{day_str}.pdf"

def parse_menu_from_pdf(pdf_content, target_date):
    pdf_file = io.BytesIO(pdf_content)
    with pdfplumber.open(pdf_file) as pdf:
        page = pdf.pages[0]
        tables = page.extract_tables()
        if not tables: raise ValueError("PDFからテーブルが抽出できませんでした。")
        
        kondate_table = tables[0]
        header_row = kondate_table[0]
        day_str_to_find = str(target_date.day)
        col_index_for_today = -1

        search_pattern = f"{day_str_to_find}日"

        for i, header_text in enumerate(header_row):
            if search_pattern in (header_text or ""):
                col_index_for_today = i
                print(f"→ 日付'{day_str_to_find}'をヘッダー'{header_text}'(列番号{i})で発見。")
                break
        
        if col_index_for_today == -1: 
            raise ValueError(f"献立表ヘッダーに今日の日付({day_str_to_find})が見つかりませんでした。")
        
        menu_asa = (kondate_table[1][col_index_for_today] or "").replace('\n', ' ') or "記載なし"
        menu_hiru = (kondate_table[8][col_index_for_today] or "").replace('\n', ' ') or "記載なし"
        menu_yoru = (kondate_table[15][col_index_for_today] or "").replace('\n', ' ') or "記載なし"
    
    return menu_asa, menu_hiru, menu_yoru

def main():
    if not CHANNEL_ACCESS_TOKEN or not USER_ID:
        print("環境変数 CHANNEL_ACCESS_TOKEN または USER_ID が設定されていません。")
        return

    jst = ZoneInfo("Asia/Tokyo")
    now_jst = datetime.now(jst)
    today = now_jst.date()
    
    pdf_content, pdf_url = None, ""

    # ★変更点: 外部からURLが指定されているか確認
    force_url = os.getenv('FORCE_PDF_URL')

    if force_url:
        print(f"★ 強制指定されたURLを使用します: {force_url}")
        pdf_url = force_url
        try:
            response = requests.get(pdf_url, timeout=10)
            response.raise_for_status()
            pdf_content = response.content
            print(f"→ 指定URLのPDFダウンロードに成功しました。")
        except Exception as e:
            print(f"→ 指定URLのダウンロードに失敗しました: {e}")
            message_text = f"【エラー】\n指定されたURLからPDFを取得できませんでした。\nURL: {force_url}"
            # ここで強制終了せずに、エラー通知を送る処理へ流す
    else:
        # 通常の自動探索
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

    message_text = ""
    if pdf_content:
        try:
            menu_asa, menu_hiru, menu_yoru = parse_menu_from_pdf(pdf_content, today)
            
            # 手動実行時は時刻に関わらず全メニューを表示するロジックにする
            if force_url:
                 message_text = (f"【修正版: 本日の寮食メニュー ({today.strftime('%-m/%-d')})】\n"
                                 f"※指定されたURLから再取得しました\n\n"
                                 f"■ 朝食\n{menu_asa}\n\n■ 昼食\n{menu_hiru}\n\n■ 夕食\n{menu_yoru}")
            else:
                hour = now_jst.hour
                if 6 <= hour < 8:
                    message_text = (f"【本日の寮食メニュー ({today.strftime('%-m/%-d')})】\n\n■ 朝食\n{menu_asa}\n\n■ 昼食\n{menu_hiru}\n\n■ 夕食\n{menu_yoru}")
                elif 11 <= hour < 13:
                    message_text = (f"【お昼の寮食メニュー ({today.strftime('%-m/%-d')})】\n\n■ 昼食\n{menu_hiru}")
                elif 16 <= hour < 18:
                    message_text = (f"【夜ご飯の寮食メニュー ({today.strftime('%-m/%-d')})】\n\n■ 夕食\n{menu_yoru}")

        except ValueError as e:
            message_text = f"【お知らせ】\n献立表の解析に失敗しました。\n理由: {e}\n\n▼試したURL\n{pdf_url}"
    elif not force_url: # force_url指定で失敗した場合は既にmessage_textが入っているため
        message_text = f"【お知らせ】\n直近3週間の献立表PDFが見つかりませんでした。\n最後に試したURL: {pdf_url}"

    if message_text:
        try:
            configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)
            with ApiClient(configuration) as api_client:
                line_bot_api = MessagingApi(api_client)
                line_bot_api.push_message(PushMessageRequest(to=USER_ID, messages=[TextMessage(text=message_text)]))
            print("LINEメッセージを送信しました。")
        except Exception as e:
            print(f"LINE送信中にエラーが発生しました: {e}")
    else:
        print("送信対象の時間外か、処理が正常に完了しませんでした。")

if __name__ == '__main__':
    main()
