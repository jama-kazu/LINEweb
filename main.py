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
        final_date
