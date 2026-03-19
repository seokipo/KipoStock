# ranking_bet_engine.py
# 자기야! 실시간 순위 급등을 낚아채는 매력적인 '정찰 스나이퍼' 엔진이야! 🚀🔎

import asyncio
from get_setting import get_setting
import time
from datetime import datetime
from stock_info import get_realtime_ranking_data
from login import fn_au10001 as get_token

class RankingBetEngine:
    def __init__(self, api_core):
        self.api = api_core
        self.is_running = False
        
        # 오늘 매수한 종목 기록 (중복 방지)
        self.bet_history = set()
        
        # 이전 순위 데이터 기록 (종목코드: 순위)
        self.previous_ranking = {}
        
        # 실행 중인 태스크 관리
        self.tasks = []

        # 설정값 초기화
        self.enabled = False
        self.new_entry_threshold = 10 # N위 내 신규 진입
        self.jump_threshold = 10      # N단계 이상 급상승
        self.interval = 30            # 감지 간격(초)

    def load_parameters(self):
        """설정 파일에서 파라미터를 로드합니다. (V2.2.0 모드별 설정 대응 ❤️)"""
        from get_setting import get_setting
        import json
        import os
        
        # 1. 기본값 로드 (get_setting 활용)
        self.enabled = get_setting('rank_scout_enabled', False)
        self.new_entry_threshold = int(get_setting('rank_scout_new_threshold', 10))
        self.jump_threshold = int(get_setting('rank_scout_jump_threshold', 10))
        self.interval = int(get_setting('rank_scout_interval', 60))
        self.qry_tp = str(get_setting('rank_scout_qry_tp', '1'))

        # 2. 현재 활성화된 프로필이 있다면 해당 프로필 설정을 덮어쓰기
        try:
            p = self.api
            profile_idx = str(getattr(p, 'current_profile_idx', 'M'))
            
            # settings.json 직접 읽기 (프로필 데이터 접근용)
            from get_setting import get_base_path
            base_dir = get_base_path()
            s_path = os.path.join(base_dir, 'settings.json')
            
            if os.path.exists(s_path):
                with open(s_path, 'r', encoding='utf-8') as f:
                    root = json.load(f)
                    if 'profiles' in root and profile_idx in root['profiles']:
                        target = root['profiles'][profile_idx]
                        self.enabled = target.get('rank_scout_enabled', self.enabled)
                        self.new_entry_threshold = int(target.get('rank_scout_new_threshold', self.new_entry_threshold))
                        self.jump_threshold = int(target.get('rank_scout_jump_threshold', self.jump_threshold))
                        self.interval = int(target.get('rank_scout_interval', self.interval))
                        self.qry_tp = str(target.get('rank_scout_qry_tp', self.qry_tp))
                        # print(f"✅ [Ranking Scout] 프로필({profile_idx}) 설정 로드 완료")
        except Exception as e:
            print(f"⚠️ [Ranking Scout] 프로필 로드 중 예외: {e}")

        if self.interval <= 0: self.interval = 60
        if self.is_running:
            print(f"🔄 [Ranking Scout] 설정 실시간 반영 완료 (진입:{self.new_entry_threshold}위, 급등:{self.jump_threshold}단계, 간격:{self.interval}초)")

    def reload_parameters(self):
        """외부에서 설정 변경 시 호출하여 실시간 반영"""
        was_enabled = self.enabled
        self.load_parameters()
        
        if not was_enabled and self.enabled:
            print("🚀 [Ranking Scout] 설정을 통해 엔진이 활성화되었습니다.")
            self.start()
        elif was_enabled and not self.enabled:
            print("⏹ [Ranking Scout] 설정을 통해 엔진이 비활성화되었습니다.")
            self.stop()

    async def monitoring_routine(self):
        """실시간 종목 조회 순위 감시 루프"""
        print(f"🔎 [Ranking Scout] 감시 루틴 가동 중... (간격: {self.interval}초)")
        
        while self.is_running:
            try:
                if not self.enabled:
                    await asyncio.sleep(1)
                    continue
                
                # 장중 시간 체크 (키움 조회 순위는 장중에만 의미 있음)
                now = datetime.now()
                if now.hour < 9 or (now.hour == 15 and now.minute > 35) or now.hour > 15:
                    await asyncio.sleep(60) # 장외에는 1분 단위로 체크
                    continue

                token = get_token()
                # [v2.4.6] 동기 API 호출을 별도 스레드에서 실행하여 이벤트 루프 블로킹 방지
                current_ranking_list = await asyncio.to_thread(get_realtime_ranking_data, token=token, qry_tp=self.qry_tp)
                
                if current_ranking_list:
                    # [v2.4.8] [Rank Raw] 상세 로그 출력 활성화 (자기 요청 ❤️)
                    raw_count = len(current_ranking_list)
                    raw_str = ", ".join([f"{x['name']}({x['rank']}위)" for x in current_ranking_list[:15]])
                    if hasattr(self.api, 'append_log'):
                        # 상세 로그창이 아니라 메인 로그에도 흐릿하게 뿌려주어 자기가 볼 수 있게 함
                        self.api.append_log(f"<font color='#666666'>[Rank Raw] {raw_count}종목 수신 | Top15: {raw_str}</font>")
                    
                    new_ranking_map = {item['code']: item['rank'] for item in current_ranking_list}
                    
                    # [v2.4.8] 엔진 기동 후 첫 데이터 수신 시 처리 개선 (자기야, 이제 첫판부터 신규 종목은 잡는다! ❤️)
                    is_first_sync = False
                    if not self.previous_ranking:
                        self.previous_ranking = new_ranking_map
                        is_first_sync = True
                        msg = "[RANK_SCOUT] ✅ 첫 순위 데이터 동기화 완료. (신규 진입 종목은 즉시 감시 시작!)"
                        print(msg)
                        if hasattr(self.api, 'append_log'):
                            self.api.append_log(f"<font color='#00e5ff'>{msg}</font>")

                    for stock in current_ranking_list:
                        code = stock['code']
                        name = stock['name']
                        rank = stock['rank']
                        rank_st = stock.get('rank_st', '') # N:신규, 1:상승...
                        rank_gap = stock.get('rank_gap', 0)
                        
                        # 1. 신규 진입 감지 (사용자 요청: 키움에서 'N'으로 찍히는 녀석들)
                        # 이전 리스트에는 없으면서, 키움 신호(rank_st)가 'N'이고, 설정된 순위 내일 때
                        # [v2.4.8] 첫 동기화 시점(is_first_sync)에도 'N' 신호는 즉시 매수하도록 허용
                        if (code not in self.previous_ranking or rank_st == 'N' or is_first_sync) and (rank_st == 'N'):
                            if rank <= self.new_entry_threshold:
                                # 중복 방지: N으로 찍혀도 이미 이전 루프에서 샀으면 패스
                                if code not in self.bet_history:
                                    print(f"✨ [Ranking Scout] 신규 진입(N) 포착! {name}({code}) {rank}위 등장!")
                                    self.execute_bet(code, name, f"NewEntry({rank}위)", tag='RANK_SCOUT')
                        
                        # 2. 순위 급상승 감지 (이전 순위 대비 설정된 단계 이상 상승)
                        elif code in self.previous_ranking:
                            prev_rank = self.previous_ranking[code]
                            jump = prev_rank - rank
                            if jump >= self.jump_threshold:
                                print(f"🚀 [Ranking Scout] 순위 급상승 포착! {name}({code}) {prev_rank}위 -> {rank}위 ({jump}단계 점프!)")
                                self.execute_bet(code, name, f"RankJump({jump}↑)", tag='RANK_SCOUT')
                    
                    # 현재 랭킹을 이전 데이터로 저장
                    self.previous_ranking = new_ranking_map
                else:
                    if hasattr(self.api, 'append_log'):
                        self.api.append_log(f"<font color='#e74c3c'>[RANK_SCOUT] ⚠️ 실시간 조회 순위 수신 실패 (데이터 비어있음)</font>")
                
                # 설정된 간격만큼 대기
                print(f"💓 [Ranking Scout] Heartbeat - 감시 루프 정상 작동 중... (설정 간격: {self.interval}초)")
                await asyncio.sleep(self.interval)
                
            except Exception as e:
                print(f"⚠️ [RANK_SCOUT] Monitoring Error: {e}")
                await asyncio.sleep(5)

    def execute_bet(self, code, name, reason, tag='RANK_SCOUT'):
        """1주 정찰병 매수를 주문합니다. (V2.2.0 정식 버전 ❤️)"""
        # 당일 중복 매수 체크
        if code in self.bet_history:
            return

        self.bet_history.add(code)
        
        qty = 1
        price = 0  # 시장가
        
        # 주기 정보 포함 (예: 30초 랭킹)
        itv_str = f"{self.interval}s"
        log_msg = f"[{tag}] {itv_str} {reason} {name}({code}) 정찰병 1주 투입! 🚩"
        
        # UI 및 로그 전송 (자기의 소중한 기포 로그창으로! ❤️)
        self.api.append_log(f"<font color='#00e5ff'><b>{log_msg}</b></font>")
        
        # 실제 주문 호출 (Parent의 check_n_buy.add_buy 유틸리티 사용)
        if hasattr(self.api, 'check_n_buy'):
            self.api.check_n_buy.add_buy(
                stk_cd=code,
                # stk_nm=name, # add_buy 시그니처 확인 결과 stk_nm은 없고 stk_cd, token, seq_name 등을 가짐
                token=self.api.token if hasattr(self.api, 'token') else None,
                seq_name=f"{itv_str} {reason}",
                qty=qty,
                source='RankScout',
                price_type='market'
            )

    def start(self):
        """엔진 기동"""
        self.load_parameters()
        if not self.enabled: 
            return

        if self.is_running:
            return
        
        self.is_running = True
        
        # [v2.4.6] 기존 테스크가 있다면 종료 여부 확인 후 정리
        valid_tasks = []
        for t in self.tasks:
            if not t.done():
                valid_tasks.append(t)
        self.tasks = valid_tasks

        if not self.tasks:
            msg = f"🔎 [Ranking Scout Engine] 가동 시작 (진입:{self.new_entry_threshold}위, 급등:{self.jump_threshold}단계, 간격:{self.interval}초)"
            print(msg)
            self.tasks.append(asyncio.create_task(self.monitoring_routine()))
        else:
            print("ℹ️ [Ranking Scout] 엔진이 이미 실행 중입니다.")

    def stop(self):
        """엔진 정지"""
        self.is_running = False
        
        for task in self.tasks:
            task.cancel()
        self.tasks.clear()
        
        self.bet_history.clear()
        self.previous_ranking.clear()
        print("⏹ [Ranking Scout Engine] 정지됨.")
