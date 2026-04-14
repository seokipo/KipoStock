# morning_bet_engine.py
# Kipo_Stock_Now Morning Bet Engine (V5.3.2)
# -------------------------------------------------------------
# - 2026-04-14: [V5.3.2] 터르 마 시서 명칭/시초가 비동기 복구 큐 시스텐 구축
# - 2026-04-13: [V5.1.30] 아침 정밀 타격 데이터 교정 및 UI 가속화 패치
#   1. [Fix] KIS API 가격부호 필드(843, 907) 매핑 오류 수정 (4.5M% 방지)
#   2. [Standard] MorningBet(X) 태그 표준화 (매도 엔진 연동 무결성)
#   3. [UI] 수익률 None% 표시 오류 방어 로직 연계
# [v1.2.0] 전면 진단 로그 패치 - 원인 추적용 상세 로그 심기 완료

import asyncio
from get_setting import get_setting
from market_hour import MarketHour
import time
from datetime import datetime
from login import safe_float, safe_int

# [v5.1.10] DEBUG_HTML_LOG 접두사 포함 → GUI 상세 로그창으로 직접 라우팅
def _dlog(msg):
    """상세 로그창(Detailed Log)으로 진단 메시지를 전송"""
    # DEBUG_HTML_LOG: 접두사로 출력하면 GUI StreamRedirector가 상세 로그창으로 라우팅함
    print(f"DEBUG_HTML_LOG: <font color='#aaaaaa'>[Morning-DIAG] {msg}</font>")

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
        
        # [진단] 실시간 데이터 수신 횟수 카운터
        self._rt_recv_count = 0
        self._rt_last_log_time = 0
        
        # [V5.2.4] 진단 리포트 발송 여부 플래그
        self._diag_830_reported = False
        self._readiness_850_reported = False
        self._ai_sniper_fired = False # [V5.3.0]
        
        # [V5.3.2] 명칭/시초가 누락 종목 비동기 복구 큐
        self._recovery_queue = set()

    def load_parameters(self):
        """UI에서 설정한 시초가 파라미터 로드 (실시간 갱신 가능)"""
        self.enabled = get_setting('morning_bet_enabled', False)
        
        # 전략별 활성화 여부 (A~D)
        self.use_a = get_setting('morning_bet_use_a', True)  # 예상체결 Scan
        self.use_b = get_setting('morning_bet_use_b', False) # 시가 재돌파
        self.use_c = get_setting('morning_bet_use_c', False) # 1분봉 고가 돌파
        self.use_d = get_setting('morning_bet_use_d', False) # 거래량 폭증
        
        self.gap_min = float(get_setting('morning_gap_min', 3.0) or 3.0)
        self.gap_max = float(get_setting('morning_gap_max', 10.0) or 10.0)
        self.morning_time_limit = get_setting('morning_time', '09:10')
        self.max_morning_stocks = 6
        
        # [V5.3.0] AI Morning Sniper 파라미터
        self.ai_selection_enabled = get_setting('morning_ai_selection_enabled', False)
        self.ai_count = int(get_setting('morning_ai_count', 3))
        self.ai_use_news = get_setting('morning_ai_use_news', True)

        # [진단] 파라미터 로드 시 상태를 상세 로그에 기록
        _dlog(f"[파라미터 로드] enabled={self.enabled} | A={self.use_a}, B={self.use_b}, C={self.use_c}, D={self.use_d} | GAP={self.gap_min}~{self.gap_max}% | 시간제한={self.morning_time_limit}")
        
        if self.is_running:
            print(f"🔄 [Morning Bet] 설정 실시간 반영 완료 (A:{'ON' if self.use_a else 'OFF'}, B:{'ON' if self.use_b else 'OFF'}, C:{'ON' if self.use_c else 'OFF'}, D:{'ON' if self.use_d else 'OFF'})")

    def reload_parameters(self):
        """외부에서 설정 변경 시 호출하여 실시간 반영"""
        was_enabled = self.enabled
        self.load_parameters()
        
        if not was_enabled and self.enabled:
            print("🚀 [Morning Bet] 설정을 통해 엔진이 활성화되었습니다.")
            self.start()
        elif was_enabled and not self.enabled:
            print("⏹ [Morning Bet] 설정을 통해 엔진이 비활성화되었습니다.")
            self.stop()

    def is_within_time_limit(self):
        """현재 시간이 설정된 morning_time_limit(예: 09:10 또는 12:00) 이내인지 확인"""
        now = datetime.now()
        cur_min = now.hour * 60 + now.minute
        start_min = 8 * 60 + 50 # 08:50 (장전 스캔 시작 대지)
        
        try:
            limit_h, limit_m = map(int, self.morning_time_limit.split(':'))
            end_min = limit_h * 60 + limit_m
        except:
            end_min = 9 * 60 + 10 # 기본값 09:10
            
        return start_min <= cur_min <= end_min

    async def diagnose_readiness(self, silent=False):
        """[V5.2.4] 시초가 매매 준비 상태를 정밀 진단하여 결과를 반환/로깅"""
        diag_results = []
        is_all_ok = True
        
        # 1. API 연결 및 토큰 상태 점검
        from login import fn_au10001 as get_token
        try:
            token = get_token()
            if not token:
                diag_results.append("<span style='color:#ff4757;'>❌ KIS API 토큰 발급 실패 (연결 확인 필요)</span>")
                is_all_ok = False
            else:
                diag_results.append("<span style='color:#2ed573;'>✅ KIS API 연결 상태 정상</span>")
        except:
            diag_results.append("<span style='color:#ff4757;'>❌ KIS API 통신 오류 발생</span>")
            is_all_ok = False

        # 2. 계좌 정보 수신 가능 여부 (잔고 체크)
        from check_n_buy import ACCOUNT_CACHE
        if ACCOUNT_CACHE['balance'] < 1000:
            diag_results.append("<span style='color:#ffa502;'>⚠️ 현재 예수금이 1,000원 미만입니다. (매매 불가 가능성)</span>")
            # 이건 경고일 뿐 치명적 에러는 아님
        else:
            diag_results.append(f"<span style='color:#2ed573;'>✅ 예수금 상태 확인 완료 ({ACCOUNT_CACHE['balance']:,}원)</span>")

        # 3. 설정값 논리 점검
        if self.gap_min >= self.gap_max:
            diag_results.append(f"<span style='color:#ff4757;'>❌ 설정 오류: Gap 최소값({self.gap_min}%)이 최대값({self.gap_max}%)보다 크거나 같습니다.</span>")
            is_all_ok = False
        
        # 4. 전략 활성화 상태 요약
        active_strats = []
        if self.use_a: active_strats.append("A(Scan)")
        if self.use_b: active_strats.append("B(시가재돌파)")
        if self.use_c: active_strats.append("C(1분봉고가)")
        if self.use_d: active_strats.append("D(거래량폭증)")
        
        if not active_strats:
            diag_results.append("<span style='color:#ffa502;'>⚠️ 활성화된 시초가 전략이 없습니다.</span>")
        else:
            diag_results.append(f"<span style='color:#00e5ff;'>ℹ️ 활성 전략: {', '.join(active_strats)}</span>")

        # 5. Ranking Scout 캐시 동기화 여부
        if self.use_a and hasattr(self.api, 'rt_search'):
            if not self.api.rt_search.ranking_cache:
                diag_results.append("<span style='color:#ffa502;'>⚠️ Ranking Scout 캐시가 비어있습니다. (08:59:50에 자동 동기화 예정)</span>")

        # 결과 출력
        if not silent:
            header = "📋 <b style='color:#ffffff;'>[Morning-DIAG] 시초가 정밀 진단 결과</b>"
            _dlog(header)
            for res in diag_results:
                _dlog(f"  > {res}")
            
            if is_all_ok and self.enabled:
                _dlog("<b style='color:#2ed573;'>✨ 종합 판정: 출격 준비 완료! 'Perfect'</b>")
            elif not self.enabled:
                _dlog("<b style='color:#ffa502;'>⚠️ 종합 판정: 엔진 비활성화 상태 (점검만 완료)</b>")
            else:
                _dlog("<b style='color:#ff4757;'>❌ 종합 판정: 설정 또는 연결 확인이 필요합니다!</b>")
        
        return is_all_ok

    async def strategy_a_routine(self):
        """[A전략] 예상 체결량 상위 스캔 및 9시 정각 선점"""
        print("🌅 [A전략] 예상 체결량 스캔 루틴 대기 중...")
        _dlog("[A전략] 루틴 시작됨 - 08:58분 스캔 대기 중")
        from stock_info import get_morning_scan_data
        from login import fn_au10001 as get_token
        
        scanned_today = False
        synced_last_min = False # [V5.1.29]
        bet_fired = False
        readiness_reported = False # [V5.1.32]
        
        while self.is_running:
            try:
                if not self.use_a:
                    await asyncio.sleep(1)
                    continue
                    
                now = datetime.now()
                
                # 0. [V5.1.29] 08:59:50 최종 정밀 동기화 및 재스캔 (타격 10초 전)
                if now.hour == 8 and now.minute == 59 and now.second == 50 and not synced_last_min:
                    _dlog("⚡ <b style='color:#f1c40f;'>[Morning-Precision]</b> 08:59:50 최종 정밀 동기화 가동!")
                    
                    # A. 실시간 거래대금 랭킹 캐시 강제 갱신
                    if hasattr(self.api, 'rt_search'):
                        _dlog("[A전략] 거래대금 랭킹 캐시 동기화 요청 중...")
                        await self.api.rt_search.sync_ranking_cache()
                    
                    # B. 최종 예상체결 데이터 재스캔 (최신 갭 데이터 확보)
                    def _fetch_final_scan():
                        token = get_token()
                        return get_morning_scan_data(token=token)
                    
                    self.candidate_stocks = await asyncio.to_thread(_fetch_final_scan)
                    if self.candidate_stocks:
                        _dlog(f"[A전략] 최종 재스캔 완료: {len(self.candidate_stocks)}종목 확보")
                    
                    synced_last_min = True

                # 0-1. [V5.2.4] 08:30:00 API 사전 점검 리포트
                if now.hour == 8 and now.minute == 30 and now.second <= 5 and not self._diag_830_reported:
                    _dlog("🔍 <b style='color:#f1c40f;'>[Morning-Early-Check]</b> 08:30 API 사전 점검을 시작합니다.")
                    await self.diagnose_readiness()
                    self._diag_830_reported = True

                # 0-2. [V5.1.32/V5.2.4] 08:50:00 출격 준비 완료 리포트 (Pre-flight Check)
                if now.hour == 8 and now.minute == 50 and now.second <= 5 and not self._readiness_850_reported:
                    # [V5.2.4] 자동 활성화 로직 추가 (사용자 편의성)
                    if not self.enabled:
                        _dlog("🤖 <b style='color:#00e5ff;'>[Morning-AutoSet]</b> 엔진이 비활성화 상태이므로 자동으로 활성화합니다.")
                        from get_setting import get_setting
                        profile_id = get_setting('current_profile_index', '1')
                        # [v5.2.4] 전역 설정 업데이트 호출 (구조상 chat_command 경유 대신 직접 로드)
                        self.enabled = True
                        # 실제 설정 파일에도 반영 (지속성)
                        from chat_command import ChatCommand
                        cc = ChatCommand()
                        cc.update_setting('morning_bet_enabled', True)
                        
                    _dlog("🚀 <b style='color:#00e5ff;'>[Morning-Readiness]</b> 08:50 최종 출격 준비 완료 점검!")
                    await self.diagnose_readiness()
                    
                    q_mode = get_setting('global_strategy_mode', 'qty')
                    q_val = get_setting('qty_val' if q_mode == 'qty' else 'amt_val', '1')
                    _dlog(f"📋 <b style='color:#aaaaaa;'>주문 요약:</b> GAP {self.gap_min}~{self.gap_max}% | {q_mode}({q_val}) | 최대 {self.max_morning_stocks}종목")
                    self._readiness_850_reported = True

                # 1. [v5.1.10] 스캔 타임슬롯 확장: 08:55 ~ 08:59 사이에 스캔 수행
                if now.hour == 8 and 55 <= now.minute <= 58 and not scanned_today:
                    print("🔍 [A전략] 장전 상위 종목 스캔 중...")
                    _dlog(f"[A전략] 스캔 시작 (현재시각: {now.strftime('%H:%M:%S')})")
                    
                    def _fetch_scan_data():
                        token = get_token()
                        _dlog(f"[A전략] 토큰 획득 완료. API 호출 중...")
                        result = get_morning_scan_data(token=token)
                        _dlog(f"[A전략] API 응답 수신 - 종목수: {len(result) if result else 0}개")
                        return result
                    
                    self.candidate_stocks = await asyncio.to_thread(_fetch_scan_data)
                    
                    if self.candidate_stocks:
                        scanned_today = True
                        print(f"✅ [A전략] 후보 {len(self.candidate_stocks)}종목 포착 완료!")
                        
                        # [V5.1.27] 장전 정밀 진단 요약 정보 출력
                        _dlog(f"🌅 <b style='color:#f1c40f;'>[장전 정밀 진단]</b> {now.strftime('%Y-%m-%d')} 매매 준비 완료!")
                        can_names = [s.get('name', s.get('code')) for s in self.candidate_stocks[:5]]
                        _dlog(f"📋 <b style='color:#00e5ff;'>감시 대상(Top5):</b> {', '.join(can_names)} 등 총 {len(self.candidate_stocks)}종목")
                        
                        # [진단] 후보 종목 전체 목록과 갭 수치 출력
                        _dlog(f"[A전략] ▼ 전체 후보 종목 목록 (GAP 필터: {self.gap_min}%~{self.gap_max}%)")
                        gap_pass = []
                        for s in self.candidate_stocks[:30]: # 최대 30개까지 확장 표시
                            code = s.get('code', '')
                            name = s.get('name', '')
                            rt = s.get('expect_rt', 0)
                            # [V5.1.17] 로데이터 샘플링 (사용자 요청 'Raw Data')
                            raw_sample = f" [Raw: {str(s)[:60]}...]" if rt > 0 else ""
                            passed = "✅통과" if self.gap_min <= rt <= self.gap_max else f"❌필터({rt:.1f}%)"
                            _dlog(f"  └ {name}({code}) 예상등락={rt:.1f}% → {passed}{raw_sample}")
                            if self.gap_min <= rt <= self.gap_max:
                                gap_pass.append(s)
                        _dlog(f"[A전략] GAP 필터 통과 종목: {len(gap_pass)}개")

                        
                        # [신규 v5.1.10] 후보 종목 rt_search 등록 후 등록 성공 여부 확인
                        if hasattr(self.api, 'rt_search'):
                            _dlog("[A전략] rt_search 감지 → 실시간 감시 등록 요청")
                            codes = [s['code'] for s in self.candidate_stocks]
                            task = asyncio.create_task(self.api.rt_search.add_realtime_codes(codes))
                            # 등록 완료 후 확인 로그 (v5.1.10 신규)
                            async def _log_reg_result(t, code_list):
                                try:
                                    await t
                                    _dlog(f"<font color='#00e5ff'>[A전략] ✅ 실시간 등록 요청 완료: {len(code_list)}종목 ({', '.join(code_list[:5])}...)</font>")
                                except Exception as re:
                                    _dlog(f"❌ [A전략] 실시간 등록 실패: {re}")
                            asyncio.create_task(_log_reg_result(task, codes))
                        else:
                            _dlog("⚠️ [A전략] self.api에 rt_search 속성이 없음! 실시간 등록 불가!")
                    else:
                        # [V5.1.17] 스캔 결과 0건 시 API 원시 응답 로깅 (Raw Data)
                        from stock_info import get_morning_scan_data_raw
                        _dlog("⚠️ [A전략] 스캔 결과 0건 - API 응답이 비어있음! 재시도 중...")
                        try:
                            token = get_token()
                            raw_res = get_morning_scan_data_raw(token=token)
                            _dlog(f"🔍 [A-Raw] API 원문 샘플: {str(raw_res)[:200]}...")
                        except: pass
                        await asyncio.sleep(2) # 재시도 주기 단축 (4s -> 2s)

                # 1-1. [V5.3.0] 08:56:00 AI Morning Sniper 가동 (AI 최종 선별 및 선제 타격)
                if now.hour == 8 and now.minute == 56 and now.second <= 5 and self.ai_selection_enabled and not self._ai_sniper_fired:
                    if self.candidate_stocks:
                        _dlog("🎯 <b style='color:#f1c40f;'>[AI-Morning-Sniper]</b> 08:56 AI 최종 선별을 시작합니다!")
                        from gemini_bot import evaluate_morning_champions
                        from stock_info import get_extended_stock_data
                        from news_sniper import fetch_latest_news
                        import json

                        # 상위 10개 후보에 대해 정밀 데이터 수집
                        eval_list = []
                        for s in self.candidate_stocks[:12]:
                            code = s['code']
                            name = s.get('name', '')
                            _dlog(f"🔎 {name}({code}) 정밀 분석 데이터 수집 중...")
                            
                            # A. 호가 잔량 및 체결강도
                            token = get_token()
                            ext = await asyncio.to_thread(get_extended_stock_data, code, token)
                            ask_qty = ext.get('total_ask_qty', 0)
                            bid_qty = ext.get('total_bid_qty', 0)
                            ob_ratio = ask_qty / bid_qty if bid_qty > 0 else 0
                            
                            # B. 뉴스 분석 (옵션)
                            news_summary = ""
                            if self.ai_use_news:
                                news_list = await asyncio.to_thread(fetch_latest_news, name, 2)
                                if news_list:
                                    news_summary = " | ".join([n['title'] for n in news_list])

                            eval_list.append({
                                "code": code,
                                "name": name,
                                "gap": s['expect_rt'],
                                "volume": s['expect_vol'],
                                "ask_bid_ratio": round(ob_ratio, 2),
                                "news": news_summary
                            })

                        # Gemini에게 평가 요청
                        _dlog("🧠 AI에게 챔피언 선별 요청 중 (Gemini Thinking...)")
                        ai_res_raw = await asyncio.to_thread(evaluate_morning_champions, json.dumps(eval_list, ensure_ascii=False))
                        
                        try:
                            champions = json.loads(ai_res_raw)
                            if champions:
                                _dlog(f"✨ <b style='color:#2ed573;'>[AI Selection]</b> 오늘의 최정예 챔피언 {len(champions)}종목이 선정되었습니다!")
                                buy_limit = self.ai_count
                                for idx, cp in enumerate(champions[:buy_limit]):
                                    cp_code = cp['code']
                                    cp_name = cp.get('name', cp_code)
                                    reason = cp.get('reason', 'AI가 선정한 강력 후보!')
                                    
                                    _dlog(f"  <b style='color:#ffffff;'>[{idx+1}] {cp_name}</b> ({cp_code})")
                                    _dlog(f"  └ <i style='color:#aaaaaa;'>{reason}</i>")
                                    
                                    # 동시호가 시장가 타격 (배팅 금액은 1주/씨앗매매 고정)
                                    # tag를 별도로 부여하여 A전략과 구분
                                    self.execute_bet(cp_code, "AI_Sniper", tag=f"MorningBet(AI)")
                                
                                _dlog(f"🚀 AI 추천 {min(len(champions), buy_limit)}종목 동시호가 주문 발송 완료!")
                            else:
                                _dlog("🤔 AI가 마땅한 후보를 찾지 못했습니다. (관망)")
                        except Exception as je:
                            _dlog(f"❌ AI 응답 파싱 실패: {je}")
                    else:
                        _dlog("⚠️ AI Sniper: 후보 종목이 없어 분석을 취소합니다.")
                    
                    self._ai_sniper_fired = True
                
                # 2. 09:00:00 정각에 후보 종목들 시장가 타격 (30초 윈도우로 확대 [V5.1.32])
                if now.hour == 9 and now.minute == 0 and now.second <= 30 and not bet_fired:
                    _dlog(f"[A전략] ⏰ 09:00 타격 트리거! 후보={len(self.candidate_stocks)}종목 / bet_history={len(self.bet_history)}건 / max={self.max_morning_stocks}")
                    
                    if not self.candidate_stocks:
                        _dlog("⚠️ [A전략] 후보 종목 없음! 타격 취소 (스캔이 안됐거나 0건 반환)")
                        bet_fired = True
                        continue
                        
                    print(f"🚀 [A전략] 09:00 정각 타격 개시! (후보 {len(self.candidate_stocks)}종목)")
                    fired_count = 0
                    for stock in self.candidate_stocks:
                        code = stock['code']
                        expect_rt = stock['expect_rt']
                        name = stock.get('name', code)
                        if self.gap_min <= expect_rt <= self.gap_max:
                            # [V5.1.30] chk_n_sell 인식을 위해 전용 이름표(MorningBet)로 매수
                            self.execute_bet(code, "A_Scan", tag=f"MorningBet(A)")
                            fired_count += 1
                        else:
                            _dlog(f"❌ [A-Reason] {name}({code}) GAP 범위 밖 ({expect_rt:.1f}%, 기준:{self.gap_min}~{self.gap_max}%) - 차단")
                            
                    _dlog(f"[A전략] 타격 완료: 총 {fired_count}개 주문 발송")
                    bet_fired = True
                
                # 09:00:30 초과 시 bet_fired 미발동 방지 [V5.1.32]
                if now.hour == 9 and now.minute == 0 and now.second > 30 and not bet_fired:
                    _dlog(f"⚠️ [A전략] 09:00:30 타임슬롯 놓침! (second={now.second})")  
                    bet_fired = True
                
                # 매일 리셋
                if now.hour == 9 and now.minute >= 10:
                    if scanned_today or bet_fired:
                        _dlog(f"[A전략] 09:10 이후 → 일일 리셋 (오늘 매수이력: {len(self.bet_history)}건)")
                    scanned_today = False
                    synced_last_min = False
                    bet_fired = False
                    self._ai_sniper_fired = False # [V5.3.0]
                    self.candidate_stocks = []
                    
            except Exception as e:
                _dlog(f"❌ [A전략 예외] {e}")
                print(f"⚠️ Strategy A Error: {e}")
            await asyncio.sleep(1)

    async def strategy_b_routine(self):
        """[B전략] 시가 재돌파 감시"""
        print("🎯 [B전략] 시가 재돌파 감시 루틴 대기 중...")
        _dlog("[B전략] 루틴 시작됨")
        processed_b = set()
        _last_log_time = 0
        
        while self.is_running:
            try:
                if not self.use_b:
                    await asyncio.sleep(1); continue
                    
                now = datetime.now()
                if self.is_within_time_limit():
                    
                    # [진단] 30초마다 B전략 감시 현황 상세 로그
                    if time.time() - _last_log_time > 30:
                        _last_log_time = time.time()
                        tracked = [(c, d) for c, d in self.last_rt_data.items() if c not in self.bet_history and c not in processed_b]
                        _dlog(f"[B전략] 감시 현황 ({now.strftime('%H:%M:%S')}): 대상={len(tracked)}종목 / 완료={len(processed_b)}건 / rt수신={len(self.last_rt_data)}")
                        if not tracked:
                            _dlog("  └ ⚠️ 감시 대상 종목 없음 (last_rt_data가 비어있거나 모두 처리 완료)")
                        else:
                            for code, d in tracked[:10]:
                                price = d.get('price', 0)
                                oprc = d.get('open', 0)
                                dipped = self.stocks_data.get(code, {}).get('dipped', False)
                                rate = (price/oprc - 1)*100 if oprc > 0 else 0
                                need_dip = "눌림O" if dipped else f"눌림X({rate:.2f}% / 기준:-0.5%)"
                                need_break = f"돌파기준:{oprc*1.003:,.0f}" if oprc > 0 else "-"
                                _dlog(f"  └ {code}: 현재={price:,} / 시가={oprc:,} ({rate:+.2f}%) | {need_dip} | {need_break}")
                    
                    for code, data in list(self.last_rt_data.items()):
                        if code in self.bet_history or code in processed_b: continue
                        
                        price = data.get('price', 0)
                        oprc = data.get('open', 0)
                        s_name = data.get('name', code)
                        
                        if oprc > 0 and price > 0:
                            # [V5.1.11] 개별 종목 정밀 추적 로그 (5초 간격)
                            s_data = self.stocks_data.setdefault(code, {})
                            last_log = s_data.get('last_b_log', 0)
                            if time.time() - last_log > 5:
                                rate = (price/oprc - 1)*100
                                if not s_data.get('dipped'):
                                    _dlog(f"[B-Trace] {s_name}: 현재 {rate:+.2f}% (눌림목 기준:-0.5%) - 대기 중")
                                else:
                                    _dlog(f"[B-Trace] {s_name}: 현재 {rate:+.2f}% (재돌파 기준:+0.3%) - 추적 중")
                                s_data['last_b_log'] = time.time()

                            if price <= oprc * 0.995:
                                if not s_data.get('dipped'):
                                    _dlog(f"<font color='#f1c40f'><b>[B-Step1] {s_name} 눌림 확인! (-0.5% 돌파)</b></font>")
                                    print(f"🎯 [B전략-눌림] {s_name} 재돌파 감시 모드 진입")
                                s_data['dipped'] = True
                            
                            if s_data.get('dipped') and price >= oprc * 1.003:
                                _dlog(f"<font color='#00e5ff'><b>[B-Step2] {s_name} 시가 재돌파 타격! (Price:{price:,})</b></font>")
                                self.execute_bet(code, "B_OpenReBreak", tag=f"MorningBet(B)")
                                processed_b.add(code)
                
                if now.hour == 9 and now.minute >= 30:
                    if processed_b: _dlog(f"[B전략] 09:30 리셋 (처리된 종목={len(processed_b)}건)")
                    processed_b.clear()
                
                await asyncio.sleep(0.1)
            except Exception as e:
                _dlog(f"❌ [B전략 예외] {e}")
                print(f"⚠️ Strategy B Error: {e}"); await asyncio.sleep(1)

    async def strategy_c_routine(self):
        """[C전략] 1분봉 고가 돌파 감시"""
        print("⚡ [C전략] 1분봉 고가 돌파 감시 루틴 대기 중...")
        _dlog("[C전략] 루틴 시작됨")
        minute_highs = {}
        processed_c = set()
        _last_log_time = 0
        
        while self.is_running:
            try:
                if not self.use_c:
                    await asyncio.sleep(1); continue
                    
                now = datetime.now()
                if now.hour == 9 and now.minute == 0:
                    for code, data in self.last_rt_data.items():
                         price = data.get('price', 0)
                         minute_highs[code] = max(minute_highs.get(code, 0), price)
                         
                elif self.is_within_time_limit():
                    
                    # [진단] 30초마다 C전략 감시 현황 상세 로그
                    if time.time() - _last_log_time > 30:
                        _last_log_time = time.time()
                        tracked = [(c, d) for c, d in self.last_rt_data.items() if c not in self.bet_history and c not in processed_c]
                        _dlog(f"[C전략] 감시 현황 ({now.strftime('%H:%M:%S')}): 대상={len(tracked)}종목 / 1분고가기록={len(minute_highs)}건 / 완료={len(processed_c)}건")
                        if not tracked:
                            _dlog("  └ ⚠️ 감시 대상 없음")
                        else:
                            for code, d in tracked[:10]:
                                price = d.get('price', 0)
                                high_1m = minute_highs.get(code, 0)
                                target = high_1m * 1.003 if high_1m > 0 else 0
                                gap = (price / target - 1) * 100 if target > 0 else 0
                                status = "✅돌파!" if (high_1m > 0 and price >= target) else f"⏳대기중 ({gap:+.2f}%)"
                                _dlog(f"  └ {code}: 현재={price:,} / 1분고가={high_1m:,} / 돌파기준={target:,.0f} | {status}")
                    
                    for code, data in list(self.last_rt_data.items()):
                        if code in self.bet_history or code in processed_c: continue
                        target_high = minute_highs.get(code, 0)
                        price = data.get('price', 0)
                        s_name = data.get('name', code)
                        
                        if target_high > 0:
                            # [V5.1.11] 정밀 추적 로그
                            s_data = self.stocks_data.setdefault(code, {})
                            last_log = s_data.get('last_c_log', 0)
                            if time.time() - last_log > 5:
                                reach = (price / (target_high * 1.003)) * 100
                                _dlog(f"[C-Trace] {s_name}: 현재가 {price:,} / 1분고가 {target_high:,} (도달률:{reach:.1f}%)")
                                s_data['last_c_log'] = time.time()

                            if price >= target_high * 1.003:
                                _dlog(f"<font color='#00e5ff'><b>[C-Strike] {s_name} 1분봉 고가 돌파 타격! (Price:{price:,})</b></font>")
                                self.execute_bet(code, "C_1MinHigh", tag=f"MorningBet(C)")
                                processed_c.add(code)
                
                if now.hour == 9 and now.minute >= 30:
                    if processed_c: _dlog(f"[C전략] 09:30 리셋 (처리={len(processed_c)}건)")
                    processed_c.clear(); minute_highs.clear()
                
                await asyncio.sleep(0.1)
            except Exception as e:
                _dlog(f"❌ [C전략 예외] {e}")
                print(f"⚠️ Strategy C Error: {e}"); await asyncio.sleep(1)

    async def strategy_d_routine(self):
        """[D전략] 초광속 거래량 폭증 감시"""
        print("🔥 [D전략] 거래량 폭증 감시 루틴 대기 중...")
        _dlog("[D전략] 루틴 시작됨")
        processed_d = set()
        while self.is_running:
            try:
                if not self.use_d:
                    await asyncio.sleep(1); continue
                    
                now = datetime.now()
                if self.is_within_time_limit():
                    for code, data in list(self.last_rt_data.items()):
                        if code in self.bet_history or code in processed_d: continue
                        
                        vol_rate = data.get('vol_rate', 0)
                        s_name = data.get('name', code)
                        
                        if vol_rate >= 1.5:
                            _dlog(f"<font color='#ff6b6b'><b>[D-Strike] {s_name} 거래량 폭증! ({vol_rate:.2f}배) → 타격!</b></font>")
                            print(f"🔥 [D전략-타격] {s_name}({code}) 거래량 1.5배 폭증! 타격 개시")
                            self.execute_bet(code, "D_VolSurge", tag=f"MorningBet(D)")
                            processed_d.add(code)
                        elif vol_rate >= 0.8:
                            # [V5.1.11] 수급 유입 실시간 추적
                            s_data = self.stocks_data.setdefault(code, {})
                            last_log = s_data.get('last_d_log', 0)
                            if time.time() - last_log > 10: # D전략은 10초 간격
                                _dlog(f"[D-Trace] {s_name}: 거래량 비율 {vol_rate:.2f}배 (목표:1.5배) - 수집 중")
                                s_data['last_d_log'] = time.time()
                                if vol_rate >= 1.1:
                                    print(f"🔍 [D전략-관찰] {s_name} 수급 유입 중.. ({vol_rate:.2f}배)")
                
                if now.hour == 9 and now.minute >= 10: processed_d.clear()
                
                await asyncio.sleep(0.5)
            except Exception as e:
                _dlog(f"❌ [D전략 예외] {e}")
                print(f"⚠️ Strategy D Error: {e}"); await asyncio.sleep(1)

    async def _rt_monitor_routine(self):
        """[진단 전용] 실시간 데이터 수신 현황을 30초마다 상세 로그에 출력"""
        while self.is_running:
            try:
                now = datetime.now()
                is_premarket = (7 <= now.hour < 9)
                is_market    = (now.hour == 9 and now.minute < 30)

                # [v5.1.10] 장전 하트비트: 07:00~08:59 매 1분 엄닸가 살아있는지 확인
                if is_premarket:
                    _dlog(
                        f"<font color='#00e5ff'><b>[HB] ♥ 엔진 대기 중 (시간: {now.strftime('%H:%M:%S')}) | "
                        f"후보종목={len(self.candidate_stocks)}개 | 매수이력={len(self.bet_history)}건</b></font>"
                    )
                    await asyncio.sleep(60)  # 장전에는 1분 하트비트
                    continue

                if is_market:
                    _dlog(f"[RT-Monitor] 실시간 데이터 수신 현황: "
                          f"last_rt_data={len(self.last_rt_data)}종목 / "
                          f"총수신={self._rt_recv_count}회 / "
                          f"후보종목={len(self.candidate_stocks)}개 / "
                          f"매수이력={len(self.bet_history)}건")
                    
                    if self.last_rt_data:
                        sample = list(self.last_rt_data.items())[:3]
                        for code, d in sample:
                            _dlog(f"  └ 샘플: {code} name={d.get('name','알수없음')} price={d.get('price',0):,} open={d.get('open',0):,}")
                        if self._recovery_queue:
                            _dlog(f"  └ 🔧 [복구큐] 대기 종목: {len(self._recovery_queue)}개 ({', '.join(list(self._recovery_queue)[:5])})")
                    else:
                        _dlog("  └ ⚠️ last_rt_data가 비어있음! on_realtime_data가 호출되지 않고 있음 (연결 or 콜백 문제)")
                        
            except Exception as e:
                _dlog(f"❌ [RT-Monitor 예외] {e}")
            await asyncio.sleep(30)

    async def _resolve_data_routine(self):
        """[V5.3.2] 명칭/시초가 누락 종목을 비동기 백그라운드에서 자동 복구하는 전담반"""
        _dlog("[V5.3.2] 데이터 복구 전담반 시작됨 (명칭/시초가 비동기 보충)")
        while self.is_running:
            try:
                await asyncio.sleep(4)  # 4초마다 복구 배치 실행
                if not self._recovery_queue:
                    continue

                # 큐에서 최대 5개씩 처리 (API 쿼터 과부하 방지)
                batch = list(self._recovery_queue)[:5]
                
                from login import fn_au10001 as get_token
                from stock_info import get_morning_data
                token = await asyncio.to_thread(get_token)

                for code in batch:
                    try:
                        cached = self.last_rt_data.get(code, {})
                        needs_name = (cached.get('name', '알수없음') in ('알수없음', '', code))
                        needs_open = not cached.get('open', 0)

                        if not (needs_name or needs_open):
                            # 이미 다 채워졌으면 큐에서 제거
                            self._recovery_queue.discard(code)
                            continue

                        # API 조회 (동기 호출을 스레드에서 실행 → 이벤트 루프 블로킹 방지)
                        s_name, open_p, _ = await asyncio.to_thread(get_morning_data, code, token)
                        
                        # 결과 반영
                        updated = False
                        if code in self.last_rt_data:
                            if needs_name and s_name:
                                self.last_rt_data[code]['name'] = s_name
                                # ACCOUNT_CACHE에도 캐싱
                                try:
                                    from check_n_buy import ACCOUNT_CACHE
                                    ACCOUNT_CACHE['names'][code] = s_name
                                except: pass
                                updated = True

                            if needs_open and open_p:
                                self.last_rt_data[code]['open'] = open_p
                                updated = True

                            if updated:
                                _dlog(f"✅ [V5.3.2] {s_name or code} 데이터 복구 완료! (명칭={s_name}, 시초가={open_p:,}원)")

                            # 완전히 복구된 경우 큐에서 제거
                            still_needs_name = self.last_rt_data[code].get('name', '') in ('알수없음', '', code)
                            still_needs_open = not self.last_rt_data[code].get('open', 0)
                            if not still_needs_name and not still_needs_open:
                                self._recovery_queue.discard(code)
                        else:
                            # last_rt_data에서 사라진 종목은 큐에서도 제거
                            self._recovery_queue.discard(code)

                    except Exception as e_inner:
                        _dlog(f"⚠️ [V5.3.2] {code} 복구 실패: {e_inner}")

            except asyncio.CancelledError:
                break
            except Exception as e:
                _dlog(f"❌ [V5.3.2 복구 전담반 예외] {e}")

    def on_realtime_data(self, data):
        """rt_search에서 실시간 체결(REAL) 데이터를 넘겨줄 때 호출"""

        if not self.is_running:
            return
            
        try:
            # [Fix] 종목코드 추출 로직 보강 (9001 필드 및 다양한 키 대응)
            jmcode = data.get('stk_cd') or data.get('code') or str(data.get('9001', '')).replace('A', '')
            if not jmcode or len(str(jmcode).strip()) < 6:
                if self._rt_recv_count < 10:
                    _dlog(f"[RT 코드추출실패] 키목록: {list(data.keys())[:10]} | stk_cd={data.get('stk_cd')}, code={data.get('code')}, 9001={data.get('9001')}")
                return
            jmcode = str(jmcode).strip()
            
            # 현재가(10), 시가(13) 추출 (Kiwom, KIS 실시간검색 등 다양한 필드 대응)
            # [V5.1.30] KIS 실시간검색 전용 필드 매핑 정규화 (부호 필드 843, 907 제거하여 4.5M% 튐 현상 원천 차단)
            curr_p = data.get('10') or data.get('20') or data.get('now_prc') or data.get('clpr') or data.get('cur_prc') or data.get('price')
            open_p = data.get('13') or data.get('oprc') or data.get('stck_oprc') or data.get('base_pric') or data.get('open')
            
            curr_p = safe_int(curr_p)
            open_p = safe_int(open_p)
            
            # [V5.1.21] 매핑 결과 상세 진단 (최초 20회는 매핑 성공 여부 로깅)
            if self._rt_recv_count < 20 and (curr_p or open_p):
                used_keys = [k for k in ['10','20','843','13','907'] if data.get(k)]
                _dlog(f"[RT-Map] 매핑 시도 ({jmcode}): curr={curr_p}, open={open_p} | Raw Keys={used_keys}")

            # [V5.1.18] 파싱 후에도 0인 경우 원본 데이터 기록 (추적용)
            if (not curr_p or not open_p) and self._rt_recv_count % 10 == 0:
                 _dlog(f"⚠️ [RT-Zero] 가격 누락 감지 ({jmcode}): curr={curr_p}, open={open_p} | Raw Keys: {list(data.keys())[:10]}")

            # [V5.1.12 / 5.1.21 패치] 누락된 데이터는 이전 데이터로 보존 (패킷 간헐성 대응)
            # [V5.1.21] 새로 들어온 데이터가 0일 때만 캐시를 활용하고, 캐시에 유효 데이터가 있으면 0으로 덮어쓰지 않음
            if jmcode in self.last_rt_data:
                cached = self.last_rt_data[jmcode]
                if not curr_p: curr_p = cached.get('price', 0)
                if not open_p: open_p = cached.get('open', 0)
            
            # [V5.1.21/V5.1.26] 시가가 0이거나 비정상적으로 낮은 경우(예: 2원) 후보 데이터에서 복구
            if not open_p or (open_p < 50 and curr_p > 1000):
                for s in self.candidate_stocks:
                    if s.get('code') == jmcode:
                        open_p = safe_int(s.get('open') or s.get('expect_prc'))
                        if open_p: _dlog(f"[RT-Recovery] {jmcode} 시가 누락 → 후보 데이터에서 복구 ({open_p:,})")
                        break

            # [BUG FIX v1.2.0] v_rate 미정의 버그 수정 - 거래량 비율 올바르게 추출
            # [V5.1.21] 거래량 필드(841) 추가 대응
            raw_vol = data.get('15') or data.get('841') or data.get('vol') or data.get('trde_qty') or data.get('volume')  # 현재 거래량
            raw_yvol = data.get('16') or data.get('yvol') or data.get('prev_volume')  # 전일 거래량
            try:
                v_now = safe_int(raw_vol)
                v_prev = safe_int(raw_yvol)
                v_rate = (v_now / v_prev) if v_prev > 0 else 1.0
            except:
                v_rate = 1.0
            
            s_name = data.get('302') or data.get('name')
            if not s_name:
                if jmcode in self.last_rt_data:
                    s_name = self.last_rt_data[jmcode].get('name')
                
                if not s_name:
                    # [V5.1.26] 실시간 데이터에 명칭 없을 시 후보 리스트에서 수혈
                    for s in self.candidate_stocks:
                        if s.get('code') == jmcode:
                            s_name = s.get('name')
                            if s_name: _dlog(f"[RT-Recovery] {jmcode} 종목명 누락 → 후보 데이터에서 복구 ({s_name})")
                            break

            if not s_name: s_name = "알수없음"
            
            norm_data = {
                'code': jmcode,
                'name': s_name or '알수없음',
                'price': curr_p,
                'open': open_p,
                'vol_rate': v_rate
            }
            self.last_rt_data[jmcode] = norm_data
            self._rt_recv_count += 1
            
            # [V5.3.2] 명칭 또는 시초가 누락 시 백그라운드 복구 큐에 등록 (비차단 방식)
            if s_name == '알수없음' or not open_p:
                self._recovery_queue.add(jmcode)
            
            # [v5.1.10] 후보 종목 여부 확인 (A전략 스캔 리스트 대조)
            is_candidate = jmcode in {s.get('code','') for s in self.candidate_stocks}
            
            # [진단] 첫 데이터 수신 알림 / 후보 종목은 항상 로그
            if self._rt_recv_count == 1:
                _dlog(f"[RT] 첫 실시간 데이터 수신! 종목={jmcode}, 키목록={list(data.keys())[:10]}")
            elif self._rt_recv_count <= 5 or is_candidate:
                cmark = "[후보]" if is_candidate else ""
                _dlog(f"[RT] #{self._rt_recv_count} 수신{cmark}: {jmcode} price={norm_data['price']:,} open={norm_data['open']:,} vol_rate={v_rate:.2f}")
        except Exception as e:
            # 최초 5회는 에러도 보여줌 (조용히 묻지 않음)
            if self._rt_recv_count < 5:
                _dlog(f"❌ [RT 파싱 오류] {e} | 받은 키: {list(data.keys()) if hasattr(data, 'keys') else type(data)}")

    def execute_bet(self, jmcode, strategy_name, tag='MORNING'):
        """최종 매수 실행 (리스크 최소화: 1주 고정)"""
        now = datetime.now()
        _dlog(f"[execute_bet] 호출됨: {jmcode} / {strategy_name} / {now.strftime('%H:%M:%S')}")
        
        # [v4.4.0] 지수 급락 자동 매매 정지 체크 (Global Stop)
        try:
            from check_n_buy import is_market_index_ok, get_stock_name_safe, add_buy
            is_ok, reason = is_market_index_ok()
            if not is_ok:
                _dlog(f"⚠️ [execute_bet] 지수 급락 정지로 차단됨: {reason}")
                print(f"🛡️ <font color='#ff6b6b'><b>[지수급락 정지]</b> MorningBet({strategy_name}) 차단 ({reason})</font>")
                return
        except Exception as e:
            _dlog(f"⚠️ [execute_bet] 지수체크 예외: {e}")

        # [V5.3.1] 전략별 시간 제한 체크 (AI Sniper는 08:30~09:10 사이면 무조건 허용)
        if "AI_Sniper" in strategy_name:
            # 동시호가 시장가 발주를 위해 08:30 이후면 시간 체크 통과
            if now.hour == 8 and now.minute >= 30:
                in_limit = True
            else:
                in_limit = self.is_within_time_limit()
        else:
            in_limit = self.is_within_time_limit()
            
        if not in_limit:
            _dlog(f"⚠️ [execute_bet] {strategy_name} 시간 범위 밖으로 차단: {now.strftime('%H:%M:%S')} (제한:{self.morning_time_limit})")
            return
        
        if len(self.bet_history) >= self.max_morning_stocks:
            _dlog(f"⚠️ [execute_bet] 최대 종목 수 도달 ({len(self.bet_history)}/{self.max_morning_stocks}) - 차단!")
            return
        if jmcode in self.bet_history:
            _dlog(f"⚠️ [execute_bet] {jmcode} 이미 매수 이력 있음 - 중복 차단!")
            return

        # [V5.1.17] 거래대금 순위 필터링 및 구체적 사유 로깅
        try:
            from check_n_buy import TOP_VOLUME_RANK_CACHE
            rank_limit_enabled = get_setting('morning_bet_rank_filter_enabled', True)
            
            # [V5.3.1] AI 스나이퍼와 전략 A(장초반 1분)은 순환 필터 예외 처리 (공격적 진입 보장)
            is_aggressive = ("AI_Sniper" in strategy_name) or ("A_Scan" in strategy_name and now.minute == 0)
            
            if rank_limit_enabled and not is_aggressive and TOP_VOLUME_RANK_CACHE:
                if jmcode not in TOP_VOLUME_RANK_CACHE:
                    _dlog(f"❌ <b style='color:#ff6b6b;'>[Skip-Reason]</b> {jmcode} 거래대금 순위 밖 필터링 (현재 순위 데이터 {len(TOP_VOLUME_RANK_CACHE)}개 내 없음)")
                    return
                else:
                    rank_idx = TOP_VOLUME_RANK_CACHE.index(jmcode) + 1
                    _dlog(f"✅ [Rank-Check] {jmcode} 거래대금 순위 확인: {rank_idx}위 (통과)")
            elif is_aggressive:
                 _dlog(f"⚡ [Aggressive] {strategy_name} 전략: 순위 필터 우회 진격!")
        except Exception as re:
            _dlog(f"⚠️ [execute_bet] 순위 체크 예외: {re}")
            
        from check_n_buy import get_stock_name_safe, add_buy
        from login import fn_au10001 as get_token
        
        token = get_token()
        name = get_stock_name_safe(jmcode, token)
        
        print(f"🔥 <font color='#ff6b6b'><b>[Morning Bet 발동]</b> {name}({jmcode}) - [{strategy_name}] 매수 시도!</font>")
        _dlog(f"✅ [execute_bet] {name}({jmcode}) 매수 주문 프로세스 시작 (전략:{strategy_name})")
        
        # [V5.1.32] 하드코딩된 1주 제거 -> 사용자 설정 연동 (chk_n_buy 방식 계승)
        q_mode = get_setting('global_strategy_mode', 'qty')
        q_val = get_setting('qty_val' if q_mode == 'qty' else ('amt_val' if q_mode == 'amount' else 'pct_val'), '1')
        
        self.bet_history.add(jmcode)
        
        # [V5.3.1] 실시간 데이터에 보관된 시초가 정보 추출
        open_p = 0
        if jmcode in self.last_rt_data:
            open_p = self.last_rt_data[jmcode].get('open', 0)
        
        result = add_buy(jmcode, token=token, seq_name=f'MorningBet({strategy_name})', qty=q_val, source=tag, price_type='market', open_price=open_p)
        _dlog(f"[execute_bet] add_buy 호출 결과: {result} (시초가:{open_p:,}원)")

    def start(self):
        """엔진 기동 (중복 실행 방지 기능 탑재)"""
        self.load_parameters()
        if not self.enabled:
            _dlog("⚠️ [start] morning_bet_enabled=False → 엔진 미기동! (설정 확인 필요)")
            return

        if self.is_running:
            return
        
        self.is_running = True
        self._rt_recv_count = 0  # 수신 카운터 리셋
        print(f"🌅 [Morning Bet Engine] 가동 시작 (A:{self.use_a}, B:{self.use_b}, C:{self.use_c}, D:{self.use_d})")
        _dlog(f"[start] 엔진 기동! GAP={self.gap_min}~{self.gap_max}% / 시간제한={self.morning_time_limit} / 최대={self.max_morning_stocks}종목")
        
        if not self.tasks:
            self.tasks.append(asyncio.create_task(self.strategy_a_routine()))
            self.tasks.append(asyncio.create_task(self.strategy_b_routine()))
            self.tasks.append(asyncio.create_task(self.strategy_c_routine()))
            # self.tasks.append(asyncio.create_task(self.strategy_d_routine())) # [V5.3.1] 전략 D(거래량 폭증) 영구 제거
            self.tasks.append(asyncio.create_task(self._rt_monitor_routine()))  # [진단 전용 태스크]
            self.tasks.append(asyncio.create_task(self._resolve_data_routine()))  # [V5.3.2] 명칭/시초가 비동기 복구 전담반
            _dlog(f"[start] 총 {len(self.tasks)}개 태스크 생성 완료")

    def stop(self):
        """엔진 정지 및 태스크 정리"""
        _dlog(f"[stop] 엔진 정지! 오늘 매수이력: {len(self.bet_history)}건, 총 RT 수신: {self._rt_recv_count}회")
        self.is_running = False
        
        for task in self.tasks:
            task.cancel()
        self.tasks.clear()
        
        self.bet_history.clear()
        self.stocks_data.clear()
        self.last_rt_data.clear()
        self.candidate_stocks = []
        self._recovery_queue.clear()  # [V5.3.2] 복구 큐 정리
        print("⏹ [Morning Bet Engine] 정지됨.")
