import sqlite3
import os
import sys
from datetime import datetime

class KipoDB:
    def __init__(self):
        # [V2.4.6] 사용자 요청에 따른 데이터 고정 경로 적용
        from get_setting import get_base_path
        self.script_dir = get_base_path()
            
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
                    trade_data.get('trade_date') or datetime.now().strftime("%Y%m%d"),
                    trade_data.get('time') or trade_data.get('trade_time', ''),
                    trade_data.get('type', ''),
                    trade_data.get('code', ''),
                    trade_data.get('name', ''),
                    trade_data.get('qty', 0),
                    trade_data.get('price', 0.0),
                    trade_data.get('amount', 0.0),
                    trade_data.get('pl_rt', 0.0),
                    trade_data.get('pnl_amt', 0.0),
                    trade_data.get('tax', 0.0),
                    trade_data.get('strat_mode', '') or trade_data.get('strat_key', ''),
                    str(trade_data.get('seq', ''))
                ))
                conn.commit()
        except Exception as e:
            print(f"⚠️ [KipoDB] 매매 기록 실패: {e}")

    def sync_trade_from_hts(self, t):
        """[수정 v2.2.1] HTS 데이터를 DB와 대조하여 없으면 삽입 (전략 매칭 강화)"""
        try:
            t_date = t.get('trade_date') or t.get('date') or datetime.now().strftime("%Y%m%d")
            t_time = t.get('trade_time') or t.get('buy_time') or t.get('time', '')
            t_type = t.get('type', 'BUY')
            t_code = t.get('code', '').replace('A', '') # A 제거
            t_qty = int(float(t.get('qty') or t.get('buy_qty') or t.get('sel_qty') or 0))
            
            # 시간 보정
            if t_time and ':' not in t_time and len(t_time) == 6:
                t_time = f"{t_time[:2]}:{t_time[2:4]}:{t_time[4:]}"

            # [전략 매칭 로직] stock_conditions.json에서 전략 유추
            strat_mode = t.get('strat_mode') or t.get('strat_key', 'none')
            if strat_mode == 'none':
                try:
                    # check_n_buy.py 의 load_json_safe를 사용하거나 직접 읽기
                    base_path = self.script_dir
                    mapping_file = os.path.join(base_path, 'stock_conditions.json')
                    if os.path.exists(mapping_file):
                        import json
                        with open(mapping_file, 'r', encoding='utf-8') as f:
                            mapping = json.load(f)
                            if t_code in mapping:
                                strat_mode = mapping[t_code].get('strat', 'none')
                except: pass

            t['strat_mode'] = strat_mode

            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT id FROM trades 
                    WHERE trade_date = ? AND code = ? AND type = ? AND qty = ? AND trade_time = ?
                ''', (t_date, t_code, t_type, t_qty, t_time))
                
                if not cursor.fetchone():
                    self.insert_trade(t)
                    return True
            return False
        except Exception as e:
            print(f"⚠️ [KipoDB] HTS 싱크 중 오류: {e}")
            return False

    def get_trades_by_range(self, start_date, end_date):
        """[신규 v2.2.1] 특정 기간(YYYYMMDD)의 매매 내역 반환"""
        try:
            with self._get_connection() as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT * FROM trades 
                    WHERE trade_date BETWEEN ? AND ? 
                    ORDER BY trade_date ASC, trade_time ASC
                ''', (start_date, end_date))
                rows = cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            print(f"⚠️ [KipoDB] 기간별 내역 조회 실패: {e}")
            return []

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

    def get_last_trade_by_code(self, code):
        """[신규 v5.0.6] 특정 종목의 가장 최근 매매 내역 1건 반환"""
        try:
            code = code.replace('A', '')
            with self._get_connection() as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                # 가장 최근 ID 순으로 1건 조회
                cursor.execute('SELECT * FROM trades WHERE code = ? ORDER BY id DESC LIMIT 1', (code,))
                row = cursor.fetchone()
                return dict(row) if row else None
        except Exception as e:
            print(f"⚠️ [KipoDB] 종목별 최근 내역 조회 실패: {e}")
            return None

# 싱글톤 인스턴스
kipo_db = KipoDB()
