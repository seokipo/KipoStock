# morning_bet_engine.py
# 자기야! 시초가의 폭발적인 에너지를 다채롭게 컨트롤할 수 있는 '라이브 하트' 엔진이야! 🚀🌅

import asyncio
from get_setting import get_setting
from market_hour import MarketHour
import time
from datetime import datetime

class MorningBetEngine:
    def __init__(self, api_core, news_sniper):
        self.api = api_core
        self.news_sniper = news_sniper
        self.is_running = False
        
        # 종목별 상태 관리 (종목코드: {info})
        self.stocks_data = {}
        
        # 오늘 매수한 종목 기록 (중복 방지)
        self.bet_history = set()
        
        # 후보 종목 리스트 (전략 A 전용)
        self.candidate_stocks = []
        
        # 실시간 데이터 수신 이벤트 및 최신 데이터
        self.last_rt_data = {}
        
        # 실행 중인 태스크 관리
        self.tasks = []

        # [v1.2.0] 속성 초기화 (AttributeError 방지)
        self.enabled = False
        self.use_a = False
        self.use_b = False
        self.use_c = False
        self.use_d = False
        self.morning_time_limit = "09:10"
        self.gap_min = 3.0
        self.gap_max = 10.0
        self.max_morning_stocks = 6

    def load_parameters(self):
        """UI에서 설정한 시초가 파라미터 로드 (실시간 갱신 가능)"""
        self.enabled = get_setting('morning_bet_enabled', False)
        
        # 전략별 활성화 여부 (A~D)
        self.use_a = get_setting('morning_bet_use_a', True)  # 예상체결 Scan
        self.use_b = get_setting('morning_bet_use_b', False) # 시가 재돌파
        self.use_c = get_setting('morning_bet_use_c', False) # 1분봉 고가 돌파
        self.use_d = get_setting('morning_bet_use_d', False) # 거래량 폭증
        
        self.gap_min = float(get_setting('morning_gap_min', 3.0))
        self.gap_max = float(get_setting('morning_gap_max', 10.0))
        self.morning_time_limit = get_setting('morning_time', '09:10')
        self.max_morning_stocks = 6 
        
        # [v1.1.6] 실시간 파라미터 반영 로그
        if self.is_running:
            print(f"🔄 [Morning Bet] 설정 실시간 반영 완료 (A:{'ON' if self.use_a else 'OFF'}, B:{'ON' if self.use_b else 'OFF'}, C:{'ON' if self.use_c else 'OFF'}, D:{'ON' if self.use_d else 'OFF'})")

    def reload_parameters(self):
        """외부에서 설정 변경 시 호출하여 실시간 반영"""
        was_enabled = self.enabled
        self.load_parameters()
        
        # 꺼져있다가 켜진 경우 엔진 가동
        if not was_enabled and self.enabled:
            print("🚀 [Morning Bet] 설정을 통해 엔진이 활성화되었습니다.")
            self.start()
        # 켜져있다가 꺼진 경우 엔진 정지
        elif was_enabled and not self.enabled:
            print("⏹ [Morning Bet] 설정을 통해 엔진이 비활성화되었습니다.")
            self.stop()

    def is_within_time_limit(self):
        """현재 시간이 설정된 morning_time_limit(예: 09:10) 이내인지 확인"""
        now = datetime.now()
        try:
            limit_h, limit_m = map(int, self.morning_time_limit.split(':'))
            # 8시 50분부터 9시 리밋 정각까지 (스캔 및 타격 타임)
            if (now.hour == 8 and now.minute >= 50) or (now.hour == 9 and now.minute <= limit_m):
                return True
        except:
            if now.hour == 9 and now.minute <= 10:
                return True
        return False

    async def strategy_a_routine(self):
        """[A전략] 예상 체결량 상위 스캔 및 9시 정각 선점"""
        print("🌅 [A전략] 예상 체결량 스캔 루틴 대기 중...")
        from stock_info import get_morning_scan_data
        from login import fn_au10001 as get_token
        
        scanned_today = False
        bet_fired = False
        
        while self.is_running:
            try:
                # 전략 비활성화 시 대기
                if not self.use_a:
                    await asyncio.sleep(1)
                    continue
                    
                now = datetime.now()
                token = get_token()
                
                # 1. 08:58:00 ~ 08:59:55 사이에 스캔 수행
                if now.hour == 8 and 58 <= now.minute <= 59 and not scanned_today:
                     print("🔍 [A전략] 장전 상위 종목 스캔 중...")
                     self.candidate_stocks = get_morning_scan_data(token=token)
                     if self.candidate_stocks:
                         print(f"✅ [A전략] 후보 {len(self.candidate_stocks)}종목 포착 완료!")
                         scanned_today = True
                
                # 2. 09:00:00 정각에 후보 종목들 시장가 타격
                if now.hour == 9 and now.minute == 0 and now.second <= 5 and not bet_fired:
                    if not self.candidate_stocks:
                        bet_fired = True
                        continue
                        
                    print(f"🚀 [A전략] 09:00 정각 타격 개시! (후보 {len(self.candidate_stocks)}종목)")
                    for stock in self.candidate_stocks:
                        code = stock['code']
                        expect_rt = stock['expect_rt']
                        
                        # Gap 조건 필터링
                        if self.gap_min <= expect_rt <= self.gap_max:
                            self.execute_bet(code, "A_Scan")
                            
                    bet_fired = True
                
                # 매일 리셋
                if now.hour == 9 and now.minute >= 10:
                    scanned_today = False
                    bet_fired = False
                    self.candidate_stocks = []
                    
            except Exception as e:
                print(f"⚠️ Strategy A Error: {e}")
            await asyncio.sleep(1)

    async def strategy_b_routine(self):
        """[B전략] 시가 재돌파 감시"""
        print("🎯 [B전략] 시가 재돌파 감시 루틴 대기 중...")
        processed_b = set()
        
        while self.is_running:
            try:
                if not self.use_b:
                    await asyncio.sleep(1); continue
                    
                now = datetime.now()
                if now.hour == 9 and now.minute < 30:
                    for code, data in list(self.last_rt_data.items()):
                        if code in self.bet_history or code in processed_b: continue
                        
                        price = data.get('price', 0)
                        oprc = data.get('open', 0)
                        
                        if oprc > 0 and price > 0:
                            if price < oprc * 0.995:
                                self.stocks_data.setdefault(code, {})['dipped'] = True
                            if self.stocks_data.get(code, {}).get('dipped') and price >= oprc * 1.003:
                                self.execute_bet(code, "MorningBet(B_OpenReBreak)")
                                processed_b.add(code)
                
                # 리셋
                if now.hour == 9 and now.minute >= 30: processed_b.clear()
                
                await asyncio.sleep(0.1)
            except Exception as e:
                print(f"⚠️ Strategy B Error: {e}"); await asyncio.sleep(1)

    async def strategy_c_routine(self):
        """[C전략] 1분봉 고가 돌파 감시"""
        print("⚡ [C전략] 1분봉 고가 돌파 감시 루틴 대기 중...")
        minute_highs = {}
        processed_c = set()
        
        while self.is_running:
            try:
                if not self.use_c:
                    await asyncio.sleep(1); continue
                    
                now = datetime.now()
                if now.hour == 9 and now.minute == 0:
                    for code, data in self.last_rt_data.items():
                         price = data.get('price', 0)
                         minute_highs[code] = max(minute_highs.get(code, 0), price)
                elif now.hour == 9 and 1 <= now.minute < 30:
                    for code, data in list(self.last_rt_data.items()):
                        if code in self.bet_history or code in processed_c: continue
                        target_high = minute_highs.get(code, 0)
                        price = data.get('price', 0)
                        if target_high > 0 and price >= target_high * 1.003:
                            self.execute_bet(code, "MorningBet(C_1MinHigh)")
                            processed_c.add(code)
                
                if now.hour == 9 and now.minute >= 30: processed_c.clear(); minute_highs.clear()
                
                await asyncio.sleep(0.1)
            except Exception as e:
                print(f"⚠️ Strategy C Error: {e}"); await asyncio.sleep(1)

    async def strategy_d_routine(self):
        """[D전략] 초광속 거래량 폭증 감시"""
        print("🔥 [D전략] 거래량 폭증 감시 루틴 대기 중...")
        processed_d = set()
        while self.is_running:
            try:
                if not self.use_d:
                    await asyncio.sleep(1); continue
                    
                now = datetime.now()
                if now.hour == 9 and now.minute < 10:
                    for code, data in list(self.last_rt_data.items()):
                        if code in self.bet_history or code in processed_d: continue
                        vol_rate = data.get('vol_rate', 0) 
                        if vol_rate >= 10.0:
                            self.execute_bet(code, "MorningBet(D_VolSurge)")
                            processed_d.add(code)
                
                if now.hour == 9 and now.minute >= 10: processed_d.clear()
                
                await asyncio.sleep(0.5)
            except Exception as e:
                print(f"⚠️ Strategy D Error: {e}"); await asyncio.sleep(1)

    def on_realtime_data(self, data):
        """rt_search에서 실시간 체결(REAL) 데이터를 넘겨줄 때 호출"""
        jmcode = data.get('stk_cd') or data.get('code')
        if not jmcode: return
        jmcode = jmcode.replace('A', '')
        
        # 데이터 정규화 및 저장
        norm_data = {
            'code': jmcode,
            'price': abs(int(data.get('now_prc', data.get('clpr', 0)))),
            'open': abs(int(data.get('oprc', data.get('stck_oprc', 0)))),
            'vol_rate': float(data.get('prdy_vol_rv_rate', data.get('vol_rate', 1.0)))
        }
        self.last_rt_data[jmcode] = norm_data

    def execute_bet(self, jmcode, strategy_name):
        """최종 매수 실행 (리스크 최소화: 1주 고정)"""
        now = datetime.now()
        
        if "A_Scan" in strategy_name:
            if not self.is_within_time_limit(): return
        else:
            if now.hour != 9 or now.minute >= 30: return
        
        if len(self.bet_history) >= self.max_morning_stocks: return
        if jmcode in self.bet_history: return
            
        from check_n_buy import get_stock_name_safe, add_buy
        from login import fn_au10001 as get_token
        
        token = get_token()
        name = get_stock_name_safe(jmcode, token)
        
        print(f"🔥 <font color='#ff6b6b'><b>[Morning Bet 발동]</b> {name}({jmcode}) - [{strategy_name}] 1주 매수!</font>")
        self.bet_history.add(jmcode)
        
        # 시장가 매수 실행
        add_buy(jmcode, token=token, seq_name=f'MorningBet({strategy_name})', qty=1, source='MORNING', price_type='market')

    def start(self):
        """엔진 기동 (중복 실행 방지 기능 탑재)"""
        self.load_parameters()
        if not self.enabled: 
            # print("ℹ️ [Morning Bet] 시초가 베팅이 비활성화 상태입니다.")
            return

        if self.is_running:
            # print("ℹ️ [Morning Bet] 엔진이 이미 가동 중입니다.")
            return
        
        self.is_running = True
        print(f"🌅 [Morning Bet Engine] 가동 시작 (A:{self.use_a}, B:{self.use_b}, C:{self.use_c}, D:{self.use_d})")
        
        # 태스크가 비어있을 때만 새로 생성
        if not self.tasks:
            self.tasks.append(asyncio.create_task(self.strategy_a_routine()))
            self.tasks.append(asyncio.create_task(self.strategy_b_routine()))
            self.tasks.append(asyncio.create_task(self.strategy_c_routine()))
            self.tasks.append(asyncio.create_task(self.strategy_d_routine()))

    def stop(self):
        """엔진 정지 및 태스크 정리"""
        self.is_running = False
        
        # 진행 중인 태스크 취소
        for task in self.tasks:
            task.cancel()
        self.tasks.clear()
        
        self.bet_history.clear()
        self.stocks_data.clear()
        self.last_rt_data.clear()
        self.candidate_stocks = []
        print("⏹ [Morning Bet Engine] 정지됨.")
