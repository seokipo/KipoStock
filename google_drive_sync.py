import os
import json
import datetime
import pandas as pd
from config import google_sheet_id

class GoogleSheetSync:
    def __init__(self):
        self.sheet_id = google_sheet_id
        self.credential_file = "service_account.json"
        self.scope = [
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive"
        ]
        self.client = None

    def _login(self):
        """gspread를 사용하여 구글 서비스 계정으로 로그인합니다."""
        try:
            import gspread
            from google.oauth2.service_account import Credentials
            
            if not os.path.exists(self.credential_file):
                return False, f"보안 파일({self.credential_file})이 없어요, 자기야! 가이드보고 넣어줘!"
                
            creds = Credentials.from_service_account_file(self.credential_file, scopes=self.scope)
            self.client = gspread.authorize(creds)
            return True, "로그인 성공"
        except Exception as e:
            return False, f"로그인 에러: {e}"

    async def sync_all_trades_today(self, chat_cmd_obj):
        """당일 매매 내역 전체를 구글 시트에 누적(append) 방식으로 기록합니다."""
        try:
            # 1. 로그인
            success, msg = self._login()
            if not success: return False, msg
            
            # 2. 오늘 데이터 가져오기
            # chat_command.py의 today()는 이제 processed_data 리스트를 반환함
            data_list = await chat_cmd_obj.today(sync_only=True)
            if not data_list or not isinstance(data_list, list):
                return False, "📭 동기화할 매매 내역이 없습니다."
            
            # 3. 시트 열기
            sheet = self.client.open_by_key(self.sheet_id).get_worksheet(0) # 첫 번째 시트
            
            # 4. 기존 데이터 가져와서 중복 체크 (날짜 + 종목코드 조합)
            existing_data = sheet.get_all_values()
            today_str = datetime.datetime.now().strftime("%Y-%m-%d")
            
            # [날짜, 종목코드] 조합으로 기존 키 세트 생성
            # 헤더 제외하고 0번: 날짜, 5번: 종목코드
            existing_keys = set()
            if len(existing_data) > 1:
                for row in existing_data[1:]:
                    if len(row) > 5:
                        existing_keys.add(f"{row[0]}_{row[5]}")
            
            new_rows = []
            for trade in data_list:
                code = trade.get('code', '')
                key = f"{today_str}_{code}"
                if key not in existing_keys:
                    new_rows.append(self.format_trade_row(trade))
            
            if not new_rows:
                return True, "이미 모든 최신 데이터가 구글 드라이브에 동기화되어 있습니다."
            
            # 5. 데이터 추가
            sheet.append_rows(new_rows, value_input_option='USER_ENTERED')
            
            return True, f"총 {len(new_rows)}개의 매매 내역이 구글 시트에 추가되었습니다! 🚀"

        except Exception as e:
            return False, f"구글 시트 작업 중 에러 발생: {e}"

    def format_trade_row(self, row_data):
        """구글 시트 헤더 순서에 맞게 데이터를 포맷팅합니다."""
        # 순서: 날짜, 매수시간, 매수전략, 조건식, 종목명, 종목코드, 매수평균가, 매수수량, 매수금, 매도평균가, 매도수량, 매도금액, 세금, 손익금액, 수익률(%)
        today_str = datetime.datetime.now().strftime("%Y-%m-%d")
        
        return [
            today_str,
            row_data.get('buy_time', '--'),
            row_data.get('strat_nm', '--'),
            row_data.get('cond_name', '--'),
            row_data.get('name', '--'),
            row_data.get('code', '--'),
            row_data.get('buy_avg', 0),
            row_data.get('buy_qty', 0),
            row_data.get('buy_amt', 0),
            row_data.get('sel_avg', 0),
            row_data.get('sel_qty', 0),
            row_data.get('sel_amt', 0),
            row_data.get('tax', 0),
            row_data.get('pnl', 0),
            f"{row_data.get('pnl_rt', 0.0):.2f}%"
        ]
