import os
import datetime
import requests
import io
import pdfplumber
import webbrowser
from linebot import LineBotApi
from linebot.models import TextSendMessage
import os # ← osをインポートするのを忘れないように

# --- 設定項目 ---
# GitHub Secretsから安全に読み込む
CHANNEL_ACCESS_TOKEN = os.getenv('CHANNEL_ACCESS_TOKEN')
USER_ID = os.getenv('USER_ID')

today = datetime.date.today()
# today.weekday() は月曜日が0、日曜日が6なので、今日の日付から曜日の日数分だけ引くと月曜日の日付がわかる
monday = today - datetime.timedelta(days=today.weekday())
year = monday.year
month1 = f"{monday.month:02d}" # 5月なら "05" のようにゼロ埋め
month2 = f"{monday.month:02d}" # 5月なら "05" のようにゼロ埋め
day = f"{monday.day:02d}"

def get_menu_pdf_url_for_today():
    """
    今日の日付が含まれる週の、献立表PDFのURLを生成する関数。
    献立表のURLが「その週の月曜日の日付」で生成されていると仮定する。
    """
    
    # URLの形式に沿って組み立てる
    # 例: https://www.numazu-ct.ac.jp/wp-content/uploads/2025/05/kondate-20250519.pdf
    pdf_url = f"https://www.numazu-ct.ac.jp/wp-content/uploads/{year}/{month1}/kondate-{year}{month2}{day}.pdf"
    
    return pdf_url

def main(request):
    """
    メインの実行関数
    """
    line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)
    today = datetime.date.today()
    
    try:
        # 1. 今日の献立表PDFのURLを取得
        pdf_url = get_menu_pdf_url_for_today()

        response = requests.get(pdf_url, timeout=5)
        if response.status_code == 200:
            pass
        else:
            month1 = int(month1)
            month1 -= 1
            month1 = f"{month1:02d}"
            #print(f"型: {type(month)}")
            pdf_url = f"https://www.numazu-ct.ac.jp/wp-content/uploads/{year}/{month1}/kondate-{year}{month2}{day}.pdf"

        # 2. URLからPDFファイルをダウンロード
        response = requests.get(pdf_url)
        # もしPDFが見つからなかった場合(404エラーなど)は、エラーメッセージを出す
        response.raise_for_status() 
        
        # 3. PDFから献立表テーブルを抽出
        menu_text = ""
        found = False
        
        pdf_file = io.BytesIO(response.content)
        with pdfplumber.open(pdf_file) as pdf:
            # 献立表は最初のページにあると仮定
            page = pdf.pages[0]
            # ページ内のテーブルを全て抽出（通常は1つだけ）
            tables = page.extract_tables()

            if not tables:
                raise ValueError("PDFからテーブルを抽出できませんでした。")

            # 最初のテーブルを献立表として扱う
            kondate_table = tables[0]
            
            # 4. 今日の曜日に対応する列からメニューを取得
            # weekday()は月曜=0, 火曜=1...。テーブルの列は0列目が「朝昼夕」、1列目が「月曜」...なので+1する
            col_index_for_today = today.weekday() + 1

            # テーブルのヘッダーから、今日の日付が正しいか念のため確認
            # ヘッダー例: '5/19\n（月）'
            header_date = kondate_table[0][col_index_for_today]
            if str(today.day) not in header_date:
                # 祝日などでレイアウトがずれている可能性
                raise ValueError(f"テーブルの{col_index_for_today}列目のヘッダー({header_date})が今日の日付と一致しません。")

            # 朝食、昼食、夕食はそれぞれ1, 2, 3行目にあると仮定
            # or "記載なし" は、セルが空欄だった場合の対策
            menu_asa = kondate_table[1][col_index_for_today].replace('\n', ' ') or "記載なし"
            menu_hiru = kondate_table[2][col_index_for_today].replace('\n', ' ') or "記載なし"
            menu_yoru = kondate_table[3][col_index_for_today].replace('\n', ' ') or "記載なし"

            # 5. 送信するメッセージを作成
            message_text = (
                f"【本日の寮食メニュー ({today.strftime('%-m/%-d')})】\n\n"
                f"■ 朝食\n{menu_asa}\n\n"
                f"■ 昼食\n{menu_hiru}\n\n"
                f"■ 夕食\n{menu_yoru}"
            )

    except requests.exceptions.HTTPError as e:
        # PDFが見つからなかった場合 (404 Not Foundなど)
        message_text = f"【お知らせ】\n本日の献立表PDFが見つかりませんでした。\nURL: {pdf_url}"
        print(f"HTTPエラー: {e}")
    except Exception as e:
        # その他の予期せぬエラー
        message_text = f"Botの実行中にエラーが発生しました。\n管理者にご連絡ください。\nエラー内容: {e}"
        print(f"エラーが発生しました: {e}")

    # 6. LINEにメッセージを送信
    line_bot_api.push_message(USER_ID, TextSendMessage(text=message_text))

    return 'Success', 200

# --- ローカルでのテスト用 ---
if __name__ == '__main__':
    # 実行すると、設定したUSER_IDにLINEメッセージが飛ぶ
    main(None)
    print("処理を実行しました。LINEを確認してください。")