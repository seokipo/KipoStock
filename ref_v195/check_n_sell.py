import time
import os
import json
from acc_val import fn_kt00004 as get_my_stocks
from sell_stock import fn_kt10001 as sell_stock
from tel_send import tel_send
from get_setting import cached_setting
from login import fn_au10001 as get_token
from market_hour import MarketHour
from check_n_buy import load_json_safe, save_json_safe, update_stock_condition # [신규] 안전 함수 가져오기

# 전역 캐시 (파일 수정 시간 기반의 I/O 최소화)
_STRATEGY_MAPPING_CACHE = {}
_LAST_MAPPING_MTIME = 0
_LAST_BULTAGI_DIAG_TIME = 0 # [v6.3.0] 불타기 진단 로그 출력 시간 기록
from check_n_buy import load_json_safe, save_json_safe, update_stock_condition, update_stock_peak_rt, update_stock_gate # [수정] update_stock_gate 추가

def chk_n_sell(token=None):
    global _STRATEGY_MAPPING_CACHE, _LAST_MAPPING_MTIME, _LAST_BULTAGI_DIAG_TIME
    
    current_time = time.time()
    # [v6.4.3] 하트비트 보정: 루프 시작 시점에 즉시 갱신하여 지연 누적 방지
    show_diag = False
    if current_time - _LAST_BULTAGI_DIAG_TIME >= 10:
        show_diag = True
        _LAST_BULTAGI_DIAG_TIME = current_time # 여기서 즉시 업데이트 (루프 지연 무관)
    
    mapping_updated = False # [신규] 상태 변경(최고수익률 등) 발생 시 저장하기 위한 플래그
    
    # 익절/손절 수익율(%)
    TP_RATE = cached_setting('take_profit_rate', 10.0)
    SL_RATE = cached_setting('stop_loss_rate', -10.0)

    # [최적화 & v6.4.4] 매핑 정보 파일 수정 시간 추적하여 즉각 갱신
    import sys
    if getattr(sys, 'frozen', False):
        base_path = os.path.dirname(sys.executable)
    else:
        base_path = os.path.dirname(os.path.abspath(__file__))
        
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
        my_stocks = []
        
        if isinstance(my_stocks_data, dict):
            my_stocks = my_stocks_data.get('stocks', [])
        elif isinstance(my_stocks_data, list):
            my_stocks = my_stocks_data

        if not my_stocks:
            if time.time() % 10 < 0.5:
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
                elif strat_mode == 'HTS':
                     st_data = cached_setting('strategy_tp_sl', {})
                     hts_set = st_data.get('HTS', {})
                     live_tp = float(hts_set.get('tp', 0))
                     live_sl = float(hts_set.get('sl', 0))
                     if live_tp != 0: specific_tp = live_tp
                     if live_sl != 0: specific_sl = live_sl
                else:
                    if info.get('tp') is not None: specific_tp = float(info['tp'])
                    if info.get('sl') is not None: specific_sl = float(info['sl'])

            if specific_tp == 0: specific_tp = TP_RATE if TP_RATE != 0 else 12.0
            if specific_sl == 0: specific_sl = SL_RATE if SL_RATE != 0 else -1.5

            if mapping and stk_cd in mapping:
                info = mapping[stk_cd]
                if info.get('bultagi_done'):
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

                    # [신규 v1.7.8/v1.7.9] 트레일링 스톱 (Trailing Stop) - 상호 배타적 모드
                    ts_en = cached_setting('bultagi_trailing_enabled', False)
                    ts_val = cached_setting('bultagi_trailing_val', 1.0)
                    
                    if ts_en:
                        # TS 모드일 때는 TP/Preservation 무시
                        should_sell = False
                        sell_reason = ""
                        
                        # 1. 고점에 따른 TS 판정
                        if peak_rt >= 0.5 and (peak_rt - pl_rt) >= ts_val:
                            should_sell = True
                            sell_reason = "트레일링스톱"
                        # 2. 안전망 (손실제한)은 별도로 작동
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
            
            if not b_enabled and show_diag:
                if current_time % 60 < 10:
                    print(f"⚠️ <font color='#888888'>[디버그] {stock.get('stk_nm', '알수없음')} 불타기 설정이 OFF 상태(b_enabled={b_enabled})되어 진단 건너뜀</font>")
            
            if b_enabled:
                safe_stk_nm = stock.get('stk_nm', stock.get('prdt_name', '알수없음'))
                mapping_info = mapping.get(stk_cd) if mapping else None
                
                time_backup = {}
                try:
                    import sys
                    base_path = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
                    time_backup = load_json_safe(os.path.join(base_path, 'daily_buy_times.json'))
                except: pass

                buy_time_str = None
                is_recovered = False
                
                if mapping_info:
                    buy_time_val = mapping_info.get('time')
                    buy_time_str = buy_time_val.get('time') if isinstance(buy_time_val, dict) else buy_time_val
                
                if not buy_time_str or buy_time_str == "99:99:99":
                    backup_entry = time_backup.get(stk_cd, {})
                    if isinstance(backup_entry, str): buy_time_str = backup_entry
                    else: buy_time_str = backup_entry.get('time')
                    
                    if buy_time_str:
                        is_recovered = True
                        if not mapping_info: 
                            mapping_info = {
                                'name': safe_stk_nm, 
                                'strat': 'HTS', 
                                'time': buy_time_str, 
                                'recovered': True,
                                'bultagi_done': backup_entry.get('done', False) if isinstance(backup_entry, dict) else False
                            }
                
                if not buy_time_str and show_diag and not mapping_info:
                    print(f"⚠️ <font color='#888888'>[디버그] {safe_stk_nm} 종목 매핑 데이터 누락으로 인해 진단 무시됨</font>")
                
                if buy_time_str and buy_time_str != "99:99:99":
                    info = mapping_info 
                    if safe_stk_nm == '알수없음' and info.get('name'): safe_stk_nm = info['name']
                    
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
                        is_profit_zone = True if current_price > 0 and buy_price > 0 and current_price >= buy_price else False
                        
                        # [v1.9.0] 불타기 5관문 시스템 (5-Gate System)
                        if not info.get('bultagi_done'):
                            # 현재 도달한 관문 상태 (없으면 1관문부터)
                            current_gate = info.get('current_gate', 1)
                            
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
                            except: pass

                            # --- Gate 1: 경과 시간 ---
                            wait_sec = int(cached_setting('bultagi_wait_sec', 10))
                            if elapsed >= wait_sec:
                                gate_status[0] = "✅"
                                gate_details[0] = f"{int(elapsed)}s"
                                if current_gate == 1: current_gate = 2
                            else:
                                gate_status[0] = "⏳"
                                gate_details[0] = f"{int(elapsed)}/{wait_sec}s"
                                current_gate = 1 

                            # --- Gate 2: 현재 수익 (수익권 확인) ---
                            current_price = float(stock.get('prpr', stock.get('now_prc', stock.get('cur_prc', 0))))
                            buy_price = float(stock.get('avg_prc', stock.get('pchs_avg_pric', 0)))
                            is_profit = current_price > 0 and buy_price > 0 and current_price >= buy_price
                            
                            if is_profit:
                                gate_status[1] = "✅"
                                gate_details[1] = f"{int(current_price):,}"
                                if current_gate == 2: current_gate = 3
                            else:
                                gate_status[1] = "🚫"
                                gate_details[1] = f"손실"
                                # [핵심] 리셋 로직: 3차 이상에서 2차 조건 미달 시 2차로 후퇴
                                if current_gate >= 3:
                                    current_gate = 2
                            
                            # --- Gate 3: 체결 강도 ---
                            if power_en:
                                p_limit = float(cached_setting('bultagi_power_val', 120))
                                cur_p = ex_data['power'] if ex_data else 0.0
                                if cur_p >= p_limit:
                                    gate_status[2] = "✅"
                                    gate_details[2] = f"{cur_p:.1f}"
                                    if current_gate == 3: current_gate = 4
                                else:
                                    gate_status[2] = "🚫"
                                    gate_details[2] = f"{cur_p:.1f}"
                                    if current_gate > 3: pass # 단계 유지 (사용자 요청에 따라 조절 가능)
                            else:
                                gate_status[2] = "⏩" # 비활성화 시 패스
                                if current_gate == 3: current_gate = 4

                            # --- Gate 4: 추세 변화 (상승) ---
                            if slope_en:
                                last_p = info.get('last_power', 0)
                                cur_p = ex_data['power'] if ex_data else 0.0
                                if cur_p > last_p:
                                    gate_status[3] = "✅"
                                    gate_details[3] = f"📈"
                                    if current_gate == 4: current_gate = 5
                                else:
                                    gate_status[3] = "📉"
                                    gate_details[3] = f"📉"
                                info['last_power'] = cur_p
                            else:
                                gate_status[3] = "⏩"
                                if current_gate == 4: current_gate = 5

                            # --- Gate 5: 호가 잔량비 ---
                            if orderbook_en:
                                ob_limit = float(cached_setting('bultagi_orderbook_val', 2.0))
                                ask_q = ex_data.get('total_ask_qty', 0) if ex_data else 0
                                bid_q = ex_data.get('total_bid_qty', 1) if ex_data else 1
                                ob_ratio = ask_q / bid_q if bid_q > 0 else 0
                                
                                if ex_data and ex_data.get('orderbook_valid'):
                                    if ob_ratio >= ob_limit:
                                        gate_status[4] = "✅"
                                        gate_details[4] = f"{ob_ratio:.1f}"
                                        if current_gate == 5: current_gate = 6 # All Pass!
                                    else:
                                        gate_status[4] = "⚖️"
                                        gate_details[4] = f"{ob_ratio:.1f}"
                                else:
                                    gate_status[4] = "⏳"
                                    gate_details[4] = "수집"
                            else:
                                gate_status[4] = "⏩"
                                if current_gate == 5: current_gate = 6

                            # 현재 단계 저장 (상태 유지)
                            if current_gate != info.get('current_gate'):
                                info['current_gate'] = current_gate
                                update_stock_gate(stk_cd, current_gate)
                            
                            # GUI 상태 보드 전송 (구조화 로그)
                            # 형식: [BULTAGI_STAT] 종목명|단계|1차|2차|3차|4차|5차
                            if current_gate <= 5:
                                phase_txt = f"{current_gate}관문"  # 현재 검증 중인 관문 번호
                            else:
                                phase_txt = "진입완료"  # 6이상 = 5관문 모두 통과 → 주문 집행됨
                            stat_payload = f"{safe_stk_nm}|{phase_txt}|{gate_status[0]}{gate_details[0]}|{gate_status[1]}{gate_details[1]}|{gate_status[2]}{gate_details[2]}|{gate_status[3]}{gate_details[3]}|{gate_status[4]}{gate_details[4]}"
                            print(f"[BULTAGI_STAT] {stat_payload}")

                            # 최종 트리거 (6단계 도달 시)
                            if current_gate >= 6:
                                print(f"🔥 <font color='#ff4444'><b>[발송]</b></font> {safe_stk_nm}: 5관문 모두 돌파! 주문 집행...")
                                try:
                                    from bultagi_engine import trigger_bultagi_buy
                                    success = trigger_bultagi_buy(stk_cd, token=token)
                                    if success:
                                        print(f"✅ [성공] {safe_stk_nm}: 매수 주문이 성공적으로 발송되었습니다.")
                                        update_stock_condition(
                                            stk_cd, name='불타기진입', strat='불타기',
                                            seq=info.get('seq'), bultagi_done=True
                                        )
                                    else:
                                        print(f"❌ [실패] {safe_stk_nm}: 엔진 호출은 성공했으나 주문 발송에 실패했습니다.")
                                except Exception as eng_err:
                                    print(f"❌ [오류] {safe_stk_nm}: 엔진 호출 중 예외 발생: {eng_err}")
                    except Exception as e_proc:
                         print(f"⚠️ [처리예외] {e_proc}")

            if pl_rt > specific_tp or pl_rt < specific_sl:
                if not MarketHour.is_market_open_time():
                    continue

                sell_result = sell_stock(stock['stk_cd'].replace('A', ''), str(qty), token=token)
                
                if isinstance(sell_result, (tuple, list)): ret_code = sell_result[0]
                elif isinstance(sell_result, dict): ret_code = sell_result.get('return_code')
                else: ret_code = sell_result

                if str(ret_code) != '0' and ret_code != 0:
                    print(f"⚠️ 매도 주문 실패: {stock['stk_nm']}")
                    continue

                try:
                    from trade_logger import session_logger
                    sell_prc = float(stock.get('prc', 0)) or float(stock.get('evlt_amt', 0)) / qty if qty > 0 else 0
                    pnl_amt = int(stock.get('pl_amt', 0))
                    
                    def get_tax(stock_obj):
                        for k in ['cmsn_alm_tax', 'cmsn_tax', 'tax']:
                            v = stock_obj.get(k)
                            if v is not None and str(v).strip() != "": return int(float(v))
                        return 0
                    tax_val = get_tax(stock)

                    actual_pl_rt = float(stock.get("pl_rt", pl_rt)) if pl_rt == 999 else pl_rt

                    strat_m = 'HTS'
                    try:
                        stk_info = mapping.get(stk_cd)
                        if stk_info: strat_m = stk_info.get('strat', 'HTS')
                    except: pass

                    session_logger.record_sell(
                        stock['stk_cd'].replace('A', ''), stock['stk_nm'], qty, 
                        sell_prc, actual_pl_rt, pnl_amt, tax=tax_val, seq=seq,
                        strat_mode=strat_m
                    )
                except Exception as ex:
                    print(f"⚠️ 세션 매도 기록 실패: {ex}")

                result_type = "익절" if pl_rt > specific_tp else "손절"
                if 'sell_reason' in locals() and sell_reason: result_type = sell_reason
                
                result_emoji = "😃" if "이익" in result_type or result_type == "익절" else "😰"
                message = f'{result_emoji} {stock["stk_nm"]} {qty}주 {result_type} 완료 (수익율: {pl_rt if pl_rt < 999 else float(stock["pl_rt"]):.2f}%)'
                tel_send(message, msg_type='log')
                
                log_color = '#ffdf00'
                try:
                    stk_info = mapping.get(stk_cd)
                    if stk_info:
                        mode = stk_info.get('strat', 'qty')
                        color_map = {'qty': '#dc3545', 'amount': '#28a745', 'percent': '#007bff'}
                        log_color = color_map.get(mode, '#ffdf00')
                except: pass

                print(f"<font color='{log_color}'>{message}</font>")
                # [v1.9.0] 매도 완료 즉시 불타기 보드에서 삭제 요청
                print(f"[BULTAGI_REMOVE] {stock['stk_nm']}")


        try:
             current_holding_codes = {s['stk_cd'].replace('A', '') for s in my_stocks if int(s.get('rmnd_qty', 0)) > 0}
             to_remove = [c for c in mapping.keys() if c not in current_holding_codes]
             if to_remove:
                 from check_n_buy import remove_stock_condition
                 for c in to_remove:
                     s_name = mapping.get(c, {}).get('name', c)
                     print(f"[BULTAGI_REMOVE] {s_name}") # 보드에서 삭제 요청
                     remove_stock_condition(c)
        except Exception as e:
             print(f"⚠️ 매핑 정리 오류: {e}")

        return True 

    except Exception as e:
        print(f"오류 발생(chk_n_sell): {e}")
        return False

if __name__ == "__main__":
    chk_n_sell(token=get_token())