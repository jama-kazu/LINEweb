# dateutilライブラリからrelativedeltaをインポート
from dateutil.relativedelta import relativedelta

def generate_menu_url(target_date):
    """
    特定の日付に基づいて、その週の月曜日の日付を使った献立表PDFのURLを生成する。
    """
    monday = target_date - timedelta(days=target_date.weekday())
    
    filename_year = str(monday.year)
    filename_month = f"{monday.month:02d}"
    filename_day = f"{monday.day:02d}"
    
    # --- ▼▼▼ ここからが修正箇所 ▼▼▼ ---
    
    #基準となる日付を計算
    date_for_folder = monday - timedelta(days=7) 
    
    # 条件判定：基準日の「日」が14日以下か？
    if date_for_folder.day <= 14:
        # 条件が真の場合、基準日に1ヶ月を足す
        # relativedeltaが年またぎを自動で処理してくれる
        date_for_folder = date_for_folder + relativedelta(months=1)

    # 最終的に決まった日付からフォルダの年月を生成
    folder_year = str(date_for_folder.year)
    folder_month = f"{date_for_folder.month:02d}"
    
    # --- ▲▲▲ ここまで修正 ▲▲▲ ---
    
    return f"https://www.numazu-ct.ac.jp/wp-content/uploads/{folder_year}/{folder_month}/kondate-{filename_year}{filename_month}{filename_day}.pdf"
