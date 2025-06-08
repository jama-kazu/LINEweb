import os
import datetime
import requests
import io
import pdfplumber
from linebot import LineBotApi
from linebot.models import TextSendMessage
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo # Python 3.9以降で推奨される標準ライブラリ

# --- 設定項目 ---
# 環境変数から安全に読み込むのが望ましい
CHANNEL_ACCESS_TOKEN = os.getenv('CHANNEL_ACCESS_TOKEN')
USER_ID = os.getenv('USER_ID')

def generate_menu_url(target_date):
    """
    特定の日付に基づいて、その週の月曜日の日付を使った献立表PDFのURLを生成する。
    「ファイルは前月のフォルダに格納される」というルールを適用する。
    """

    # target_dateから、その週の月曜日を計算
    monday = target_date - datetime.timedelta(days=target_date.weekday())
    
    # ファイル名用の年月日
    filename_year = str(monday.year)
    filename_month = f"{monday.month:02d}"
    filename_day = f"{monday.day:02d}"
    
    # フォルダパス用の年月（前月のフォルダにあるというルールを適用）
    date_for_folder = monday - datetime.timedelta(days=7)
    folder_year = str(date_for_folder.year)
    folder_month = f"{date_for_folder.month:02d}"
    
    # URLを組み立てて返す
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
        col_index_for_today = target_date.weekday() + 1 # 月曜=1, 火曜=2...

        # 土日(5,6)は献立がないので、列が存在しない場合はエラーとする
        if col_index_for_today > len(kondate_table[0]) -1:
            raise ValueError("本日は献立の記載がありません（土日または祝日の可能性があります）。")

        # ヘッダーの日付を簡易チェック
        header_date = kondate_table[0][col_index_for_today]
        if str(target_date.day) not in header_date:
            raise ValueError(f"テーブルのヘッダー({header_date})が今日の日付({target_date.day})と一致しません。")
        
        # or "記載なし" は、セルが空欄だった場合の対策
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
    line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)
    today = datetime.date.today()
    message_text = ""
    pdf_url = ""

    jst = ZoneInfo("Asia/Tokyo")
    now_jst = datetime.now(jst)
    today = now_jst.date()

    # 1. 献立表PDFを探す (今週→先週→先々週と3回試行)
    pdf_content = None
    for i in range(3):
        target_date = today - datetime.timedelta(weeks=i)
        pdf_url = generate_menu_url(target_date)
        print(f"URLを試行中: {pdf_url}")

        try:
            response = requests.get(pdf_url, timeout=10)
            response.raise_for_status() # 404などのエラーがあればここで例外を発生させる
            pdf_content = response.content
            print("→ PDFを発見！")
            break # 成功したらループを抜ける
        except requests.exceptions.HTTPError:
            print("→ 見つかりません。次の週を試します。")
            continue # 見つからなければ次のループへ
    
    # 2. PDFが見つかったかどうかで処理を分岐
    if pdf_content:
        try:
            # PDFから今日の献立を解析
            message_text = parse_menu_from_pdf(pdf_content, today)
        except ValueError as e:
            # PDFの解析に失敗した場合 (祝日など)
            message_text = f"【お知らせ】\n献立表PDFはありましたが、本日の献立を解析できませんでした。\n理由: {e}"
    else:
        # 3週間探してもPDFが見つからなかった場合
        message_text = f"【お知らせ】\n直近の献立表PDFが見つかりませんでした。"

    # 3. 最終的なメッセージをLINEに送信
    try:
        line_bot_api.push_message(USER_ID, TextSendMessage(text=message_text))
        print("LINEメッセージを送信しました。")
    except Exception as e:
        print(f"LINE送信中にエラーが発生しました: {e}")

    return 'Success', 200

# --- ローカルでのテスト用 ---
if __name__ == '__main__':
    main(None)