#これは指定時刻に寮食メニューをLINEで自動送信してくれるプログラム
import os
import io
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo
# --- 追加ライブラリ ---
from dateutil.relativedelta import relativedelta

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
    """
    monday = target_date - timedelta(days=target_date.weekday())
    
    # ファイル名は、該当日付の週の月曜日を基準に生成
    filename_year = str(monday.year)
    filename_month = f"{monday.month:02d}"
    filename_day = f"{monday.day:02d}"
    
    # --- ▼▼▼ ご要望のロジックを反映 ▼▼▼ ---
    # フォルダの年月を決めるための基準日を計算
    base_date_for_folder = monday - timedelta(days=7)
    
    # もし基準日の「日」が14日以下なら、月に1ヶ月を足す
    if base_date_for_folder.day <= 14:
        # relativedeltaを使い、年またぎも安全に計算
        final_date_for_folder = base_date_for_folder + relativedelta(months=1)
    else:
        final_date_for_folder = base_date_for_folder

    # 最終的に決まった日付からフォルダの年月を生成
    folder_year = str(final_date_for_folder.year)
    folder_month = f"{final_date_for_folder.month:02d}"
    # --- ▲▲▲ ここまで修正 ▲▲▲ ---
    
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
    
    # 過去3週間まで遡ってPDFを探す安定したロジック
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
            
            # GitHub Actionsの遅延に対応した柔軟な時刻判定
            # 朝 (6:50通知のため、6時台と7時台をカバー)
            if now_jst.hour == 6 or now_jst.hour == 7:
                message_text = (
                    f"【本日の寮食メニュー ({today.strftime('%-m/%-d')})】\n\n"
                    f"■ 朝食\n{menu_asa}\n\n"
                    f"■ 昼食\n{menu_hiru}\n\n"
                    f"■ 夕食\n{menu_yoru}"
                )
            # 昼 (11:45通知のため、11時台と12時台をカバー)
            elif now_jst.hour == 11 or now_jst.hour == 12:
                message_text = (
                    f"【お昼の寮食メニュー ({today.strftime('%-m/%-d')})】\n\n"
                    f"■ 昼食\n{menu_hiru}"
                )
            # 夕 (16:50通知のため、16時台と17時台をカバー)
            elif now_jst.hour == 16 or now_jst.hour == 17:
                message_text = (
                    f"【夜ご飯の寮食メニュー ({today.strftime('%-m/%-d')})】\n\n"
                    f"■ 夕食\n{menu_yoru}"
                )
            else:
                pass
            
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
