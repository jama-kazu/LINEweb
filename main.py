import os
import io
import json
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
MEMORY_FILE = 'menu_memory.json'

def make_url_from_date(date_obj):
    """指定された日付の日付文字列を含むURLを生成する"""
    year_str = str(date_obj.year)
    month_str = f"{date_obj.month:02d}"
    day_str = f"{date_obj.day:02d}"
    return f"https://www.numazu-ct.ac.jp/wp-content/uploads/{year_str}/{month_str}/kondate-{year_str}{month_str}{day_str}.pdf"

def get_monday(date):
    """その週の月曜日を取得"""
    return date - timedelta(days=date.weekday())

def load_memory(target_monday_str):
    """記憶ファイルから、今週有効なURLがあれば読み込む"""
    if os.path.exists(MEMORY_FILE):
        try:
            with open(MEMORY_FILE, 'r') as f:
                data = json.load(f)
                if data.get('week_start') == target_monday_str:
                    return data.get('url')
        except Exception as e:
            print(f"メモリ読み込みエラー: {e}")
    return None

def save_memory(target_monday_str, url):
    """有効なURLをファイルに保存する"""
    data = {
        "week_start": target_monday_str,
        "url": url,
        "saved_at": datetime.now().isoformat()
    }
    try:
        with open(MEMORY_FILE, 'w') as f:
            json.dump(data, f, indent=4)
        print("★ 有効なURLをメモリファイルに保存しました。")
    except Exception as e:
        print(f"メモリ保存エラー: {e}")

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
    
    target_monday_str = get_monday(today).strftime('%Y-%m-%d')
    
    pdf_content, pdf_url = None, ""
    force_url = os.getenv('FORCE_PDF_URL')
    should_save = False
    
    # 1. 強制URLモード
    if force_url:
        print(f"★ 強制指定されたURLを使用します: {force_url}")
        pdf_url = force_url
        should_save = True

    # 2. 記憶メモリモード
    else:
        saved_url = load_memory(target_monday_str)
        if saved_url:
            print(f"★ 記憶されていた有効なURLを使用します: {saved_url}")
            pdf_url = saved_url
        else:
            # 3. 自動探索モード (月曜と火曜を探す)
            print("記憶データなし。月曜日と火曜日のURLを探索します。")
            
            for i in range(3):
                base_date = today - timedelta(weeks=i)
                monday_date = get_monday(base_date)
                tuesday_date = monday_date + timedelta(days=1)
                
                candidates = [monday_date, tuesday_date]
                found_in_week = False
                for check_date in candidates:
                    temp_url = make_url_from_date(check_date)
                    print(f"URLを試行中: {temp_url}")
                    try:
                        response = requests.get(temp_url, timeout=10)
                        response.raise_for_status()
                        pdf_content = response.content
                        pdf_url = temp_url
                        print(f"→ PDFを発見！ URL: {pdf_url}")
                        found_in_week = True
                        should_save = True
                        break 
                    except requests.exceptions.HTTPError:
                        continue
                
                if found_in_week:
                    break
                else:
                    print("→ この週は見つかりません。次の週を試します。")

    # --- PDF取得 ---
    if pdf_url and not pdf_content:
        try:
            response = requests.get(pdf_url, timeout=10)
            response.raise_for_status()
            pdf_content = response.content
        except Exception as e:
            print(f"PDFダウンロードエラー: {e}")
            message_text = f"【エラー】\nURLからPDFを取得できませんでした。\nURL: {pdf_url}"
            pdf_content = None

    message_text = ""
    if pdf_content:
        try:
            menu_asa, menu_hiru, menu_yoru = parse_menu_from_pdf(pdf_content, today)
            
            if should_save:
                save_memory(target_monday_str, pdf_url)

            if force_url:
                 message_text = (f"【修正版: 本日の寮食メニュー ({today.strftime('%-m/%-d')})】\n"
                                 f"※指定URLを学習しました\n\n"
                                 f"■ 朝食\n{menu_asa}\n\n■ 昼食\n{menu_hiru}\n\n■ 夕食\n{menu_yoru}")
            else:
                hour = now_jst.hour
                if 4 <= hour < 10:
                    message_text = (f"【本日の寮食メニュー ({today.strftime('%-m/%-d')})】\n\n■ 朝食\n{menu_asa}\n\n■ 昼食\n{menu_hiru}\n\n■ 夕食\n{menu_yoru}")
                elif 10 <= hour < 15:
                    message_text = (f"【お昼の寮食メニュー ({today.strftime('%-m/%-d')})】\n\n■ 昼食\n{menu_hiru}")
                elif 15 <= hour < 22:
                    message_text = (f"【夜ご飯の寮食メニュー ({today.strftime('%-m/%-d')})】\n\n■ 夕食\n{menu_yoru}")

        except ValueError as e:
            message_text = f"【お知らせ】\n献立表の解析に失敗しました。\n理由: {e}\n\n▼試したURL\n{pdf_url}"
    elif not message_text:
        message_text = f"【お知らせ】\n直近3週間の献立表PDFが見つかりませんでした。\n(月/火曜日を探索しました)\n最後に試したURL: {pdf_url}"

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
        print(f"送信対象の時間外か、処理が完了しませんでした。(現在時刻: {now_jst.hour}時)")

if __name__ == '__main__':
    main()
