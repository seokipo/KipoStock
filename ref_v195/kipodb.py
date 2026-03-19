import sqlite3
import os
import sys
from datetime import datetime

class KipoDB:
    def __init__(self):
        if getattr(sys, 'frozen', False):
            self.script_dir = os.path.dirname(sys.executable)
        else:
            self.script_dir = os.path.dirname(os.path.abspath(__file__))
            
        self.data_dir = os.path.join(self.script_dir, 'LogData')
        if not os.path.exists(self.data_dir):
            try: os.makedirs(self.data_dir)
            except: pass
            
        self.db_path = os.path.join(self.data_dir, 'kipostock_data.db')
        self._init_db()

    def _get_connection(self):
        return sqlite3.connect(self.db_path)

    def _init_db(self):
        """데이터베이스 테이블 생성"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                # 매매 일지 테이블
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS trades (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        trade_date TEXT,
                        trade_time TEXT,
                        type TEXT,
                        code TEXT,
                        name TEXT,
                        qty INTEGER,
                        price REAL,
                        amount REAL,
                        pl_rt REAL,
                        pnl_amt REAL,
                        tax REAL,
                        strat_mode TEXT,
                        seq TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                conn.commit()
                # print("✅ [KipoDB] SQLite 데이터베이스 초기화 성공")
        except Exception as e:
            print(f"⚠️ [KipoDB] 데이터베이스 초기화 실패: {e}")

    def insert_trade(self, trade_data):
        """매매 내역 저장"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO trades (
                        trade_date, trade_time, type, code, name, 
                        qty, price, amount, pl_rt, pnl_amt, tax, strat_mode, seq
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    datetime.now().strftime("%Y%m%d"),
                    trade_data.get('time', ''),
                    trade_data.get('type', ''),
                    trade_data.get('code', ''),
                    trade_data.get('name', ''),
                    trade_data.get('qty', 0),
                    trade_data.get('price', 0.0),
                    trade_data.get('amount', 0.0),
                    trade_data.get('pl_rt', 0.0),
                    trade_data.get('pnl_amt', 0.0),
                    trade_data.get('tax', 0.0),
                    trade_data.get('strat_mode', ''),
                    str(trade_data.get('seq', ''))
                ))
                conn.commit()
        except Exception as e:
            print(f"⚠️ [KipoDB] 매매 기록 실패: {e}")

    def get_all_trades(self, limit=1000):
        """저장된 모든 매매 내역 반환 (최근순)"""
        try:
            with self._get_connection() as conn:
                conn.row_factory = sqlite3.Row # 결과를 딕셔너리 형태로 받기 위함
                cursor = conn.cursor()
                cursor.execute('SELECT * FROM trades ORDER BY id DESC LIMIT ?', (limit,))
                rows = cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            print(f"⚠️ [KipoDB] 전체 내역 조회 실패: {e}")
            return []

    def get_trades_by_date(self, trade_date):
        """특정 날짜의 매매 내역 반환 (YYYYMMDD 형식)"""
        try:
            with self._get_connection() as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute('SELECT * FROM trades WHERE trade_date = ? ORDER BY id DESC', (trade_date,))
                rows = cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            print(f"⚠️ [KipoDB] 날짜별 내역 조회 실패: {e}")
            return []

# 싱글톤 인스턴스
kipo_db = KipoDB()
