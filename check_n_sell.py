import time
import os
import json
from acc_val import fn_kt00004 as get_my_stocks
from sell_stock import fn_kt10001 as sell_stock
from tel_send import tel_send
from get_setting import cached_setting, get_base_path
from login import fn_au10001 as get_token
from market_hour import MarketHour
from check_n_buy import load_json_safe, save_json_safe, update_stock_condition # [신규] 안전 함수 가져오기
from trade_logger import session_logger # [신규] 수익 기록용 세션 로거


# 전역 캐시 (파일 수정 시간 기반의 I/O 최소화)
_STRATEGY_MAPPING_CACHE = {}
_LAST_MAPPING_MTIME = 0
_LAST_BULTAGI_DIAG_TIME = 0 # [v6.3.0] 불타기 진단 로그 출력 시간 기록
from check_n_buy import load_json_safe, save_json_safe, update_stock_condition, update_stock_peak_rt # [수정] update_stock_peak_rt 추가

def chk_n_sell(token=None, disabled_stocks=None):
    global _STRATEGY_MAPPING_CACHE, _LAST_MAPPING_MTIME, _LAST_BULTAGI_DIAG_TIME
    if disabled_stocks is None:
        disabled_stocks = set()
    
    try:
        current_time = time.time()
        # [v6.4.3] 하트비트 보정: 루프 시작 시점에 즉시 갱신하여 지연 누적 방지
        show_diag = False
        if current_time - _LAST_BULTAGI_DIAG_TIME >= 5:
            show_diag = True
            _LAST_BULTAGI_DIAG_TIME = current_time # 여기서 즉시 업데이트 (루프 지연 무관)
        
        mapping_updated = False # [신규] 상태 변경(최고수익률 등) 발생 시 저장하기 위한 플래그
        
        # 익절/손절 수익율(%)
        TP_RATE = cached_setting('take_profit_rate', 10.0)
        SL_RATE = cached_setting('stop_loss_rate', -10.0)

        # [최적화 & v6.4.4] 매핑 정보 파일 수정 시간 추적하여 즉각 갱신
        base_path = get_base_path()
            
        mapping_file = os.path.join(base_path, 'stock_conditions.json')
        
        current_mtime = 0
        if os.path.exists(mapping_file):
            current_mtime = os.path.getmtime(mapping_file)
            
        if not _STRATEGY_MAPPING_CACHE or current_mtime > _LAST_MAPPING_MTIME:
            mapped_data = {}
            if current_mtime > 0:
                 mapped_data = load_json_safe(mapping_file)
            
            _STRATEGY_MAPPING_CACHE = mapped_data
            _LAST_MAPPING_MTIME = current_mtime
        
        mapping = _STRATEGY_MAPPING_CACHE

        try:
            my_stocks_data = get_my_stocks(token=token)
            # [v5.0.2] 8005 에러 감지 시 강제 재로그인 후 재시도 (Auto-Auth Recovery)
            if isinstance(my_stocks_data, dict) and my_stocks_data.get('error_code') == '8005':
                print("🔄 [chk_n_sell] 8005 감지 → 토큰 강제 갱신 후 재시도 중...")
                token = get_token(force=True)
                my_stocks_data = get_my_stocks(token=token)
            my_stocks = []
            
            if isinstance(my_stocks_data, dict):
                my_stocks = my_stocks_data.get('stocks', [])
            elif isinstance(my_stocks_data, list):
                my_stocks = my_stocks_data

            if not my_stocks:
                if time.time() % 30 < 1.0:
                    print("⚠️ [chk_n_sell] 보유 종목 데이터가 비어있습니다.")
                return True
            
            for stock in my_stocks:
                qty = int(stock.get('rmnd_qty', 0))
                if qty <= 0:
                    continue

                # [Fix v6.5.8] 변수 미초기화로 인한 UnboundLocalError 방지
                seq = None
                sell_reason = ""

                pl_rt = 0.0
                keys_to_try = ['pl_rt', 'evlu_pfls_rt', 'return_rate', 'profit_rate']
                for k in keys_to_try:
                    if k in stock and str(stock[k]).strip():
                        try:
                            pl_rt = float(stock[k])
                            break
                        except: pass

                stk_cd = stock['stk_cd'].replace('A', '')
                specific_tp = TP_RATE
                specific_sl = SL_RATE
                
                if mapping and stk_cd in mapping:
                    info = mapping[stk_cd]
                    strat_mode = info.get('strat', 'qty')
                    seq = info.get('seq')
                    s_name = info.get('name', '')
                    
                    # [신규 v6.9.7] 시초가 배팅 (Morning Bet) 전용 타이트 컷 (개별 룰 완전 우대)
                    if s_name.startswith('MorningBet'):
                        specific_tp = float(cached_setting('morning_tp', 2.0))
                        specific_sl = float(cached_setting('morning_sl', -1.5))
                    elif s_name.startswith('MorningBet'):
                        # (위 조건과 동일하게 유지 - 가독성용)
                        pass
                    else:
                        if info.get('tp') is not None: specific_tp = float(info['tp'])
                        if info.get('sl') is not None: specific_sl = float(info['sl'])

                if specific_tp == 0: specific_tp = TP_RATE if TP_RATE != 0 else 12.0
                if specific_sl == 0: specific_sl = SL_RATE if SL_RATE != 0 else -1.5

                if mapping and stk_cd in mapping:
                    info = mapping[stk_cd]
                    # [v2.5.4] HTS 로 일원화: 불타기 완료된 종목이거나 직접 매수(HTS) 매수한 종목일 경우 불타기 매도 룰 적용
                    if info.get('bultagi_done') or info.get('strat', '') == 'HTS':
                        b_tp_en = cached_setting('bultagi_tp_enabled', True)
                        b_tp = cached_setting('bultagi_tp', 5.0)
                        b_p_en = cached_setting('bultagi_preservation_enabled', False)
                        b_p_trigger = cached_setting('bultagi_preservation_trigger', 3.0)
                        b_p_limit = cached_setting('bultagi_preservation_limit', 2.0)
                        b_sl_en = cached_setting('bultagi_sl_enabled', True)
                        b_sl = cached_setting('bultagi_sl', -2.0)

                        peak_rt = info.get('peak_pl_rt', 0.0)
                        if pl_rt > peak_rt:
                            info['peak_pl_rt'] = pl_rt
                            peak_rt = pl_rt
                            update_stock_peak_rt(stk_cd, pl_rt)

                        ts_en = cached_setting('bultagi_trailing_enabled', False)
                        ts_val = abs(float(cached_setting('bultagi_trailing_val', 1.0)))
                        
                        should_sell = False
                        sell_reason = ""
                        
                        if ts_en:
                            # TS 모드: 고점 대비 하락 시 매도 (익절/보존 무시)
                            if peak_rt >= 0.5 and (peak_rt - pl_rt) >= ts_val:
                                should_sell = True
                                sell_reason = f"트레일링스톱 (고점:{peak_rt:.1f}%, 현재:{pl_rt:.1f}%, 하락:{peak_rt-pl_rt:.1f}% >= {ts_val:.1f}%)"
                            elif b_sl_en and pl_rt <= b_sl:
                                should_sell = True
                                sell_reason = "손실제한"
                        else:
                            # 일반 모드: 기존 익절/보존/손절 로직 작동
                            if b_tp_en and pl_rt >= b_tp:
                                should_sell = True
                                sell_reason = "이익실현"
                            elif b_p_en and peak_rt >= b_p_trigger and pl_rt <= b_p_limit:
                                should_sell = True
                                sell_reason = "이익보존"
                            elif b_sl_en and pl_rt <= b_sl:
                                should_sell = True
                                sell_reason = "손실제한"
                        
                        if should_sell:
                            # [v3.1.9] 매도 실행을 위해 pl_rt를 강제로 임계값 너머로 밀어내기 전, 
                            # 원본 pl_rt를 백업하여 진단 보드 및 로그에 정확한 수치 표시
                            actual_pl_rt_for_diag = pl_rt
                            # 트리거 변수 설정
                            specific_tp = -999
                            specific_sl = 999
                            pl_rt = 999
                        else:
                            specific_tp = 999
                            specific_sl = -999

                # [v6.2.8/v6.5.9] 불타기 엔진 안정성 강화
                raw_b_enabled = cached_setting('bultagi_enabled', True)
                if raw_b_enabled is None:
                    b_enabled = True
                elif isinstance(raw_b_enabled, str):
                    b_enabled = raw_b_enabled.lower() in ['true', '1', 'yes']
                else:
                    b_enabled = bool(raw_b_enabled)
                
                if b_enabled:
                    safe_stk_nm = stock.get('stk_nm', stock.get('prdt_name', '알수없음'))
                    mapping_info = mapping.get(stk_cd) if mapping else None
                    
                    time_backup = {}
                    try:
                        base_path = get_base_path()
                        time_backup = load_json_safe(os.path.join(base_path, 'daily_buy_times.json'))
                    except: pass

                    buy_time_str = None
                    
                    if mapping_info:
                        buy_time_val = mapping_info.get('time')
                        buy_time_str = buy_time_val.get('time') if isinstance(buy_time_val, dict) else buy_time_val
                    
                    if not buy_time_str or buy_time_str == "99:99:99":
                        backup_entry = time_backup.get(stk_cd, {})
                        if isinstance(backup_entry, str): buy_time_str = backup_entry
                        else: buy_time_str = backup_entry.get('time')
                        
                        if buy_time_str:
                            if not mapping_info: 
                                mapping_info = {
                                    'name': safe_stk_nm, 
                                    'strat': 'HTS', 
                                    'time': buy_time_str, 
                                    'recovered': True,
                                    'bultagi_done': backup_entry.get('done', False) if isinstance(backup_entry, dict) else False
                                }
                                mapping[stk_cd] = mapping_info
                    
                    if buy_time_str and buy_time_str != "99:99:99":
                        info = mapping_info 
                        if safe_stk_nm == '알수없음' and info.get('name'): safe_stk_nm = info['name']
                        
                        # [v3.1.9 Hotfix-2] 매도 설정 로드 (모든 종목 진단에 공통 사용 - 조건문 외부 배치)
                        b_ts_en = cached_setting('bultagi_trailing_enabled', False)
                        b_ts_val = abs(float(cached_setting('bultagi_trailing_val', 1.2)))
                        b_pres_en = cached_setting('bultagi_preservation_enabled', False)
                        b_pres_trig = float(cached_setting('bultagi_preservation_trigger', 5.3))
                        b_pres_lim = float(cached_setting('bultagi_preservation_limit', 4.8))
                        b_tp_en = cached_setting('bultagi_tp_enabled', True)
                        b_tp = float(cached_setting('bultagi_tp', 5.0))
                        
                        try:
                            from datetime import datetime
                            now = datetime.now()
                            b_time = datetime.strptime(now.strftime("%Y%m%d") + " " + buy_time_str, "%Y%m%d %H:%M:%S")
                            wait_sec = int(cached_setting('bultagi_wait_sec', 10))
                            elapsed = (now - b_time).total_seconds()
                            
                            if -60 < elapsed < 0:
                                elapsed = 0
                            elif elapsed <= -60:
                                elapsed = 999999
                            
                            def safe_float(val):
                                try: return float(str(val).replace(',', '')) if val else 0.0
                                except: return 0.0

                            current_price = safe_float(stock.get('prpr', stock.get('now_prc', stock.get('cur_prc', 0))))
                            buy_price = safe_float(stock.get('avg_prc', stock.get('pchs_avg_pric', 0)))

                            # [v1.9.0] 불타기 5관문 시스템 (5-Gate System) 복구
                            # 현재 도달한 관문 상태 (없으면 1관문부터)
                            current_gate = info.get('current_gate', 1)
                            bultagi_done = info.get('bultagi_done', False)
                            
                            gate_status = ["⏳", "⏳", "⏳", "⏳", "⏳"] # 상태 아이콘
                            gate_details = ["-", "-", "-", "-", "-"] # 상세 수치
                            
                            # 데이터 수집 (확장 데이터)
                            power_en = cached_setting('bultagi_power_enabled', False)
                            slope_en = cached_setting('bultagi_slope_enabled', False)
                            orderbook_en = cached_setting('bultagi_orderbook_enabled', False)
                            
                            ex_data = None
                            try:
                                if power_en or slope_en or orderbook_en:
                                    from stock_info import get_extended_stock_data
                                    ex_data = get_extended_stock_data(stk_cd, token=token)
                                    # [v4.1.0] 체결강도 미갱신 현상 진단을 위한 로데이터 상세 로그창 출력
                                        # [v4.2.3] 불타기 상세 진단 로그 일시 숨김 (주석 처리로 보존)
                                        # if ex_data and ex_data.get('raw_log'):
                                        #     print(f"[BULTAGI-DEBUG] {safe_stk_nm}({stk_cd}) 수급데이터: {ex_data['raw_log']}")
                                    time.sleep(0.2)
                            except: pass

                            # --- Gate 1: 경과 시간 ---
                            if elapsed >= wait_sec:
                                gate_status[0] = "✅"
                                gate_details[0] = f"{int(elapsed)}/{wait_sec}s"
                                if not bultagi_done and current_gate == 1: current_gate = 2
                            else:
                                gate_status[0] = "⏳"
                                gate_details[0] = f"{int(elapsed)}/{wait_sec}s"
                                if not bultagi_done: current_gate = 1 

                            # --- Gate 2: 현재 수익 (수익권 확인) ---
                            is_profit = current_price > 0 and buy_price > 0 and current_price >= buy_price
                            
                            if is_profit:
                                gate_status[1] = "✅"
                                gate_details[1] = f"{int(current_price):,}/{int(buy_price):,}"
                                if not bultagi_done and current_gate == 2: current_gate = 3
                            else:
                                gate_status[1] = "🚫"
                                gate_details[1] = f"{int(current_price):,}/{int(buy_price):,}"
                                if not bultagi_done and current_gate >= 3: current_gate = 2
                            
                            # --- Gate 3: 체결 강도 ---
                            if power_en:
                                p_limit = float(cached_setting('bultagi_power_val', 120))
                                cur_p = ex_data['power'] if ex_data else 0.0
                                if cur_p >= p_limit:
                                    gate_status[2] = "✅"
                                    gate_details[2] = f"{cur_p:.0f}/{p_limit:.0f}"
                                    if not bultagi_done and current_gate == 3: current_gate = 4
                                else:
                                    # [v4.2.0] 현장 진단용 로그 (3관문 상태 실시간 출력, 소수점 1자리로 갱신 확인 가능)
                                    if cur_p > 0:
                                        gate_details[2] = f"{cur_p:.1f}/{p_limit:.0f}"
                                    else: # cur_p <= 0 인 경우에도 기본 포맷으로 표시
                                        gate_details[2] = f"{cur_p:.0f}/{p_limit:.0f}"
                                    gate_status[2] = "🚫"
                            else:
                                gate_status[2] = "⏩"
                                if not bultagi_done and current_gate == 3: current_gate = 4

                            # --- Gate 4: 추세 변화 (상승) ---
                            if slope_en:
                                last_p = info.get('last_power', 0)
                                cur_p = ex_data['power'] if ex_data else 0.0
                                if cur_p > last_p:
                                    gate_status[3] = "✅"
                                    gate_details[3] = "📈"
                                    if not bultagi_done and current_gate == 4: current_gate = 5
                                else:
                                    gate_status[3] = "📉"
                                    gate_details[3] = "📉"
                                info['last_power'] = cur_p
                            else:
                                gate_status[3] = "⏩"
                                if not bultagi_done and current_gate == 4: current_gate = 5

                            # --- Gate 5: 호가 잔량비 ---
                            if orderbook_en:
                                ob_limit = float(cached_setting('bultagi_orderbook_val', 2.0))
                                ask_q = ex_data.get('total_ask_qty', 0) if ex_data else 0
                                bid_q = ex_data.get('total_bid_qty', 1) if ex_data else 1
                                ob_ratio = ask_q / bid_q if bid_q > 0 else 0
                                
                                if ex_data and ex_data.get('orderbook_valid'):
                                    if ob_ratio >= ob_limit:
                                        gate_status[4] = "✅"
                                        gate_details[4] = f"{ob_ratio:.1f}/{ob_limit:.1f}"
                                        if not bultagi_done and current_gate == 5: current_gate = 6 
                                    else:
                                        gate_status[4] = "⚖️"
                                        gate_details[4] = f"{ob_ratio:.1f}/{ob_limit:.1f}"
                                else:
                                    gate_status[4] = "⏳"
                                    gate_details[4] = f"0.0/{ob_limit:.1f}"
                            else:
                                gate_status[4] = "⏩"
                                if not bultagi_done and current_gate == 5: current_gate = 6

                            # [v3.3.0] 진입 완료 상태일 경우 관문 상태를 강제로 완료 표시하되 상세 수치는 유지
                            if bultagi_done:
                                phase_txt = "진입완료"
                                # 모든 관문을 완료로 표시하되, 상세 수치는 위에서 계산된 것을 사용
                                for gi in range(5): gate_status[gi] = "✅"
                            else:
                                # 현재 단계 저장 (상태 유지)
                                if current_gate != info.get('current_gate'):
                                    info['current_gate'] = current_gate
                                    try:
                                        from check_n_buy import update_stock_gate
                                        update_stock_gate(stk_cd, current_gate)
                                    except: pass
                                
                                if current_gate <= 5: phase_txt = f"{current_gate}관문"
                                else: phase_txt = "진입완료"
                            
                            # [신규] 종가 베팅 종목일 경우 머리말 추가 (UI 강조용)
                            if info.get('strat') == 'CLOSING_BET':
                                phase_txt = f"종가:{phase_txt}"

                            # [v3.3.0] 매도 조건 시각적 마킹 (✅) - 전 종목 적용
                            diag_pl_rt = pl_rt if pl_rt < 999 else actual_pl_rt_for_diag
                            conds = []
                            
                            # [v3.3.0] 매도 조건 시각적 마킹 (✅) - 전 종목 적용
                            diag_pl_rt = pl_rt if pl_rt < 999 else actual_pl_rt_for_diag
                            
                            # 불타기 매도 설정 로드
                            b_ts_en = cached_setting('bultagi_trailing_enabled', False)
                            b_ts_val = abs(float(cached_setting('bultagi_trailing_val', 1.2)))
                            b_pres_en = cached_setting('bultagi_preservation_enabled', False)
                            b_pres_trig = float(cached_setting('bultagi_preservation_trigger', 5.3))
                            b_pres_lim = float(cached_setting('bultagi_preservation_limit', 4.8))
                            b_tp_en = cached_setting('bultagi_tp_enabled', True)
                            b_tp = float(cached_setting('bultagi_tp', 5.0))
                            
                            conds = []
                            if b_ts_en:
                                drop = info.get('peak_pl_rt', 0.0) - diag_pl_rt
                                # [V3.3.0] 진단용 ✅ 마킹은 peak_rt 가드 없이 수치 조건만 맞으면 표시하되, 진입완료 종목에만 적용
                                is_met = "✅" if bultagi_done and drop >= b_ts_val else ""
                                conds.append(f"{is_met}TS:{b_ts_val}(▼{drop:.1f})")
                            if b_pres_en:
                                is_met = "✅" if bultagi_done and peak_rt >= b_pres_trig and diag_pl_rt <= b_pres_lim else ""
                                conds.append(f"{is_met}P:{b_pres_trig}>{b_pres_lim}(C:{diag_pl_rt:.1f})")
                            if not b_ts_en and not b_pres_en and b_tp_en:
                                is_met = "✅" if bultagi_done and diag_pl_rt >= b_tp else ""
                                conds.append(f"{is_met}TP:{b_tp}(C:{diag_pl_rt:.1f})")

                            if not conds: conds.append("-")
                            sell_cond_str = " / ".join(conds)
                            
                            # [v3.3.0] ✅ 마크와 상세 수치를 결합하여 전송
                            def format_gate(status, detail):
                                if status == "✅": return f"✅ {detail}"
                                return f"{status} {detail}"

                            # [V4.0.2] 거래대금 순위 정보 추출 (안정성 강화)
                            rank_val = "-"
                            try:
                                from check_n_buy import TOP_VOLUME_RANK_CACHE
                                if TOP_VOLUME_RANK_CACHE:
                                    if stk_cd in TOP_VOLUME_RANK_CACHE:
                                        rank_val = f"{TOP_VOLUME_RANK_CACHE.index(stk_cd) + 1}위"
                                    else:
                                        rank_val = f"순위밖(/{len(TOP_VOLUME_RANK_CACHE)}위)"
                                else:
                                    rank_val = "미수신"
                            except Exception as rank_e:
                                rank_val = "오류"
                                print(f"⚠️ [Rank-DEBUG] 순위 계산 오류: {rank_e}")

                            stat_payload = f"{safe_stk_nm}|{phase_txt}|{rank_val}|{format_gate(gate_status[0], gate_details[0])}|{format_gate(gate_status[1], gate_details[1])}|{format_gate(gate_status[2], gate_details[2])}|{format_gate(gate_status[3], gate_details[3])}|{format_gate(gate_status[4], gate_details[4])}|{sell_cond_str}"
                            print(f"[BULTAGI_STAT] {stat_payload}")

                            # 최종 트리거 (진입 전일 때만 실행)
                            if not bultagi_done and current_gate >= 6:
                                # [V4.3.4] 일시 정지된 종목은 불타기 발동 스킵
                                if safe_stk_nm in disabled_stocks:
                                    print(f"⏸ <font color='#f39c12'>[정지중]</font> {safe_stk_nm}: 5관문 돌파! 그러나 일시 정지 중이라 주문을 건너뜁니다.")
                                else:
                                    print(f"🔥 <font color='#ff4444'><b>[발송]</b></font> {safe_stk_nm}: 5관문 모두 돌파! 주문 집행...")
                                    try:
                                        from bultagi_engine import trigger_bultagi_buy
                                        success = trigger_bultagi_buy(stk_cd, token=token)
                                        if success:
                                            print(f"✅ [성공] {safe_stk_nm}: 매수 주문이 성공적으로 발송되었습니다.")
                                            update_stock_condition(stk_cd, name='불타기진입', strat='불타기', seq=info.get('seq'), bultagi_done=True)
                                        else:
                                            print(f"❌ [실패] {safe_stk_nm}: 엔진 호출은 성공했으나 주문 발송에 실패했습니다.")
                                    except Exception as eng_err:
                                        print(f"❌ [오류] {safe_stk_nm}: 엔진 호출 중 예외 발생: {eng_err}")

                        except Exception as e_proc_inner:
                            if show_diag: print(f"⚠️ [불타기진단내부오류] {safe_stk_nm}: {e_proc_inner}")

                    # --- [Gate 6] 실제 매도 실행 로직 복구 (V3.1.9) ---
                    # [V4.3.4] 일시 정지 중인 종목은 매도도 스킵
                    if safe_stk_nm in disabled_stocks:
                        if pl_rt > specific_tp or pl_rt < specific_sl:
                            print(f"⏸ <font color='#f39c12'>[정지중]</font> {safe_stk_nm}: 매도 조건 도달! 그러나 일시 정지 중이라 매도를 건너뜁니다.")
                    elif pl_rt > specific_tp or pl_rt < specific_sl:
                        if MarketHour.is_market_open_time():
                            sell_result = sell_stock(stk_cd, str(qty), token=token)
                            
                            # 주문 성공 여부 확인
                            ret_code = sell_result.get('return_code') if isinstance(sell_result, dict) else sell_result
                            if str(ret_code) == '0' or ret_code == 0:
                                result_type = sell_reason if sell_reason else ("익절" if pl_rt > specific_tp else "손절")
                                real_pl_rt = float(stock.get('pl_rt', 0)) if pl_rt == 999 else pl_rt
                                
                                message = f'🚀 {safe_stk_nm} {qty}주 {result_type} 완료 (수익율: {real_pl_rt:.2f}%)'
                                print(f"<font color='#ffdf00'>{message}</font>")
                                tel_send(message, msg_type='log')
                                print(f"[BULTAGI_REMOVE] {safe_stk_nm}") # UI 보드에서 삭제
                                
                                # [신규 v3.3.4] 수익 기록 및 차트 실시간 갱신 트리거
                                try:
                                    pnl_amt = float(stock.get('evlu_pfls_amt', 0))
                                    tax_amt = float(stock.get('evlu_pftls_tax', 0))
                                    session_logger.record_sell(
                                        stk_cd, safe_stk_nm, qty, current_price, 
                                        real_pl_rt, pnl_amt, tax=tax_amt, 
                                        seq=seq, strat_mode=info.get('strat')
                                    )
                                except Exception as log_err:
                                    print(f"⚠️ [수익기록오류] {log_err}")

                                # 매수 매핑 정보에서도 삭제
                                try:
                                    from check_n_buy import remove_stock_condition
                                    remove_stock_condition(stk_cd)
                                except: pass

                            else:
                                print(f"❌ [매도실패] {safe_stk_nm}: {sell_result}")
            
            return True # 한 루프 성공 완료
            
        except Exception as e_main:
            print(f"⚠️ [불타기엔진오류] {e_main}")
            return False

    except Exception as e_outer:
        print(f"⚠️ [chk_n_sell 최상위오류] {e_outer}")
        return False

# [v1.1.0] 외부 호출용 래퍼 (동기 환경 대응)
def run_chk_n_sell():
    # 이제 chk_n_sell은 다시 동기 함수이므로 별도 이벤트 루프 필요 없음
    return chk_n_sell()

if __name__ == "__main__":
    run_chk_n_sell()
