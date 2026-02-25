import os
import io
import json
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import requests
import pdfplumber
from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi,
    BroadcastRequest, TextMessage  # ★ PushMessageRequest を BroadcastRequest に変更
)

# --- 設定項目 ---
CHANNEL_ACCESS_TOKEN = os.getenv('CHANNEL_ACCESS_TOKEN')
# USER_ID = os.getenv('USER_ID') # ★ BroadcastAPIでは不要になるためコメントアウト（または削除）可能
MEMORY_FILE = 'menu_memory.json'
TIMING_FILE = 'timing_stats.json' 
STATUS_FILE = 'user_status.json'  

# --- 制御用関数 ---
def is_service_active():
    """サービスのオン/オフ状態を確認する"""
    if os.path.exists(STATUS_FILE):
        try:
            with open(STATUS_FILE, 'r') as f:
                data = json.load(f)
                return data.get('status') != 'stopped'
        except Exception:
            pass
    return True

def load_timing_offset():
    """前回の処理にかかった時間（秒）を読み込む"""
    if os.path.exists(TIMING_FILE):
        try:
            with open(TIMING_FILE, 'r') as f:
                data = json.load(f)
                return data.get('process_duration', 0)
        except Exception:
            pass
    return 0 

def save_timing_offset(duration):
    """今回の処理にかかった時間を保存する"""
    data = {
        "process_duration": duration,
        "updated_at": datetime.now().isoformat()
    }
    try:
        with open(TIMING_FILE, 'w') as f:
            json.dump(data, f, indent=4)
        print(f"★ 処理時間({duration:.2f}秒)を記録しました。次回はこの分だけ早く起動します。")
    except Exception as e:
        print(f"タイミング保存エラー: {e}")

def wait_until_target_time(force_mode):
    """フィードバック制御付き待機関数"""
    jst = ZoneInfo("Asia/Tokyo")
    now = datetime.now(jst)
    
    if force_mode:
        print("★ 手動モードのため、時刻調整をスキップします。")
        return None

    target = None
    if now.hour == 6:
        target = now.replace(hour=7, minute=0, second=0, microsecond=0)
    elif now.hour == 11:
        target = now.replace(hour=12, minute=0, second=0, microsecond=0)
    elif now.hour == 16:
        target = now.replace(hour=17, minute=0, second=0, microsecond=0)
    
    if target:
        offset = load_timing_offset()
        adjusted_target = target - timedelta(seconds=offset)
        delta = (adjusted_target - now).total_seconds()
        
        if delta > 0:
            print(f"現在時刻: {now.strftime('%H:%M:%S')}")
            print(f"目標時刻: {target.strftime('%H:%M:%S')}")
            print(f"予測処理時間: {offset:.2f}秒 → 補正後起床時刻: {adjusted_target.strftime('%H:%M:%S')}")
            print(f"調整のため {delta:.2f} 秒間待機します...")
            time.sleep(delta)
        else:
            print("補正後の目標時刻を過ぎているため、即時実行します。")
            
    return target

# --- メニュー抽出ロジック ---
def make_url_from_date(date_obj):
    year_str = str(date_obj.year)
    month_str = f"{date_obj.month:02d}"
    day_str = f"{date_obj.day:02d}"
    return f"https://www.numazu-ct.ac.jp/wp-content/uploads/{year_str}/{month_str}/kondate-{year_str}{month_str}{day_str}.pdf"

def get_monday(date):
    return date - timedelta(days=date.weekday())

def load_memory(target_monday_str):
    if os.path.exists(MEMORY_FILE):
        try:
            with open(MEMORY_FILE, 'r') as f:
                data = json.load(f)
                if data.get('week_start') == target_monday_str:
                    return data.get('url')
        except Exception:
            pass
    return None

def save_memory(target_monday_str, url):
    data = { "week_start": target_monday_str, "url": url, "saved_at": datetime.now().isoformat() }
    try:
        with open(MEMORY_FILE, 'w') as f:
            json.dump(data, f, indent=4)
    except Exception:
        pass

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
                break
        if col_index_for_today == -1: raise ValueError(f"日付({day_str_to_find})が見つかりません。")
        menu_asa = (kondate_table[1][col_index_for_today] or "").replace('\n', ' ') or "記載なし"
        menu_hiru = (kondate_table[8][col_index_for_today] or "").replace('\n', ' ') or "記載なし"
        menu_yoru = (kondate_table[15][col_index_for_today] or "").replace('\n', ' ') or "記載なし"
    return menu_asa, menu_hiru, menu_yoru

def main():
    # ★ USER_IDのチェックを外し、CHANNEL_ACCESS_TOKENのみを必須に変更
    if not CHANNEL_ACCESS_TOKEN:
        print("環境変数不足(CHANNEL_ACCESS_TOKENがありません)")
        return

    # サービスが停止中ならここで終了
    if not is_service_active():
        print("サービスが「停止」状態のため、LINE送信処理をスキップして終了します。")
        return

    force_url = os.getenv('FORCE_PDF_URL')
    target_time = wait_until_target_time(force_url)
    process_start_time = time.time()

    # --- メイン処理 ---
    jst = ZoneInfo("Asia/Tokyo")
    now_jst = datetime.now(jst)
    today = now_jst.date()
    target_monday_str = get_monday(today).strftime('%Y-%m-%d')
    
    pdf_content, pdf_url = None, ""
    should_save = False
    
    if force_url:
        print(f"強制URL: {force_url}")
        pdf_url = force_url
        should_save = True
    else:
        saved_url = load_memory(target_monday_str)
        if saved_url:
            print(f"記憶URL使用: {saved_url}")
            pdf_url = saved_url
        else:
            print("探索開始")
            for i in range(3):
                base_date = today - timedelta(weeks=i)
                monday_date = get_monday(base_date)
                tuesday_date = monday_date + timedelta(days=1)
                candidates = [monday_date, tuesday_date]
                found = False
                for check_date in candidates:
                    temp_url = make_url_from_date(check_date)
                    try:
                        res = requests.get(temp_url, timeout=10)
                        res.raise_for_status()
                        pdf_content = res.content
                        pdf_url = temp_url
                        found = True
                        should_save = True
                        break 
                    except: continue
                if found: break

    if pdf_url and not pdf_content:
        try:
            res = requests.get(pdf_url, timeout=10)
            res.raise_for_status()
            pdf_content = res.content
        except Exception: pdf_content = None

    message_text = ""
    if pdf_content:
        try:
            menu_asa, menu_hiru, menu_yoru = parse_menu_from_pdf(pdf_content, today)
            if should_save: save_memory(target_monday_str, pdf_url)
            
            if force_url:
                 message_text = (f"【修正版 ({today.strftime('%-m/%-d')})】\n朝:{menu_asa}\n昼:{menu_hiru}\n夕:{menu_yoru}")
            else:
                h = now_jst.hour
                if 4 <= h < 10: message_text = (f"【本日 ({today.strftime('%-m/%-d')})】\n\n■ 朝食\n{menu_asa}\n\n■ 昼食\n{menu_hiru}\n\n■ 夕食\n{menu_yoru}")
                elif 10 <= h < 15: message_text = (f"【昼食 ({today.strftime('%-m/%-d')})】\n\n■ 昼食\n{menu_hiru}")
                elif 15 <= h < 22: message_text = (f"【夕食 ({today.strftime('%-m/%-d')})】\n\n■ 夕食\n{menu_yoru}")
        except Exception as e: message_text = f"解析失敗: {e}"
    elif not message_text:
        message_text = "献立PDFが見つかりませんでした。"

    if message_text:
        try:
            cfg = Configuration(access_token=CHANNEL_ACCESS_TOKEN)
            with ApiClient(cfg) as client:
                api = MessagingApi(client)
                # ★ 変更部分: PushMessageRequest を BroadcastRequest に変更し、toの指定を削除
                api.broadcast(BroadcastRequest(messages=[TextMessage(text=message_text)]))
            print("LINE一斉送信完了")
            
            # 送信完了後のフィードバック記録 (手動モード以外)
            if not force_url and target_time:
                process_end_time = time.time()
                duration = process_end_time - process_start_time
                save_timing_offset(duration)
                
        except Exception as e: print(f"LINE送信エラー: {e}")
    else:
        print("送信対象外")

if __name__ == '__main__':
    main()
