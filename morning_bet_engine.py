# morning_bet_engine.py
# 자기야! 시초가의 폭발적인 에너지를 담을 전용 엑셀러레이터야! 🚀🌅

import asyncio
from get_setting import get_setting
from market_hour import MarketHour
import time

class MorningBetEngine:
    def __init__(self, api_core, news_sniper):
        self.api = api_core
        self.news_sniper = news_sniper
        self.is_running = False
        
        # 관리 중인 시초가 후보군 (종목코드: 정보)
        self.candidate_stocks = {}
        
        # 1주 고정 매수 기록 (중복 방지)
        self.bet_history = set()

    def load_parameters(self):
        """UI에서 설정한 시초가 파라미터 로드"""
        self.enabled = get_setting('morning_bet_enabled', False)
        self.source_type = get_setting('morning_source_type', 0) # 0: A(검색식), 1: B(스캔)
        self.gap_min = float(get_setting('morning_gap_min', 3.0))
        self.gap_max = float(get_setting('morning_gap_max', 10.0))
        self.break_rt = float(get_setting('morning_break_rt', 1.0))
        self.morning_time_limit = get_setting('morning_time', '09:10')
        self.ai_filter = get_setting('morning_ai_filter', True)

    def is_within_time_limit(self):
        """현재 시간이 설정된 morning_time_limit(예: 09:10) 이내인지 확인"""
        from datetime import datetime
        now = datetime.now()
        
        try:
            limit_h, limit_m = map(int, self.morning_time_limit.split(':'))
            # 8시 50분부터 진입 허용 (장전 스캔 대비)
            if now.hour == 8 and now.minute >= 50:
                return True
            if now.hour == 9 and now.minute <= limit_m:
                return True
        except:
            if now.hour == 9 and now.minute <= 10: # 디폴트 09:10
                return True
        return False

    async def scan_expected_volume(self):
        """[소싱 B] 8시 55분부터 예상 체결량 상위 스캔 (추후 API 연동 필요)"""
        while self.is_running:
            try:
                if self.is_within_time_limit() and self.source_type == 1:
                    # TODO: 키움증권 TR(예: opt10001 또는 예상체결 등락률 상위) 호출 로직
                    pass
            except Exception as e:
                print(f"⚠️ Morning Bet Scan Error: {e}")
            await asyncio.sleep(5)  # 5초 간격 스캔

    def process_realtime_signal(self, jmcode, current_price, open_price, prev_close):
        """[소싱 A] 실시간 조건검색식(rt_search)에서 호출되는 분석/진입 로직"""
        if not self.enabled:
            return False
            
        if not self.is_within_time_limit():
            return False
            
        if jmcode in self.bet_history:
            return False

        # 1. 갭 상승 조건 판단
        if prev_close > 0:
            gap_rt = ((open_price - prev_close) / prev_close) * 100
            if not (self.gap_min <= gap_rt <= self.gap_max):
                return False

        # 2. 시가 돌파 조건 판단
        if open_price > 0 and current_price > 0:
            break_rt = ((current_price - open_price) / open_price) * 100
            if break_rt >= self.break_rt:
                # 조건 만족! 진입 준비
                
                # 3. AI 필터 (선택 사항)
                if self.ai_filter:
                    name = self._get_stock_name(jmcode)
                    # TODO: news_sniper 연동하여 호재 판정 확인 로직
                    print(f"🌅 [Morning Bet] AI 호재 판정 대기 중: {name}({jmcode})")
                    return False # 임시 차단 (추후 비동기 검증 후 진입)
                    
                self.execute_bet(jmcode)
                return True
                
        return False

    def execute_bet(self, jmcode):
        """최종 매수 실행 (리스크 최소화: 1주 고정)"""
        if jmcode in self.bet_history:
            return
            
        name = self._get_stock_name(jmcode)
        print(f"🔥 <font color='#ff6b6b'><b>[Morning Bet 발동]</b> {name}({jmcode}) - 1주 시초가 돌파 매수!</font>")
        
        self.bet_history.add(jmcode)
        
        # TODO: 실제 매수 API (check_n_buy.add_buy 등) 호출 연동
        # from check_n_buy import add_buy
        # add_buy(self.api, jmcode, 1, 'market', 'MorningBet')

    def _get_stock_name(self, jmcode):
        """임시 종목명 반환 함수"""
        return jmcode

    def start(self):
        self.load_parameters()
        if not self.enabled:
            return
        self.is_running = True
        print("🌅 [Morning Bet Engine] 시초가 스캐닝/대기 루틴 시작...")
        asyncio.create_task(self.scan_expected_volume())

    def stop(self):
        self.is_running = False
        self.bet_history.clear()
