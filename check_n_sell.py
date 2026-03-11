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
from check_n_buy import load_json_safe, save_json_safe, update_stock_condition, update_stock_peak_rt # [수정] update_stock_peak_rt 추가

def chk_n_sell(token=None):
    global _STRATEGY_MAPPING_CACHE, _LAST_MAPPING_MTIME, _LAST_BULTAGI_DIAG_TIME
    
    current_time = time.time()
    # [v6.4.3] 하트비트 보정: 루프 시작 시점에 즉시 갱신하여 지연 누적 방지
    show_diag = False
    if current_time - _LAST_BULTAGI_DIAG_TIME >= 10:
        show_diag = True
        _LAST_BULTAGI_DIAG_TIME = current_time # 여기서 즉시 업데이트 (루프 지연 무관)
    
    # [초정밀 진단 v6.1.3] 함수 호출 여부 확인
    # if show_diag: 
    #     print("💖 [chk_n_sell] 엔진 심장 박동 중...")
    
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
                
                if strat_mode == 'HTS':
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

                    should_sell = False
                    sell_reason = ""
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

            # [v6.2.8/v6.5.9] 불타기 엔진 안정성 강화: 기본값을 묻지도 따지지도 않고 True로!
            raw_b_enabled = cached_setting('bultagi_enabled', True)
            if raw_b_enabled is None:
                b_enabled = True
            elif isinstance(raw_b_enabled, str):
                b_enabled = raw_b_enabled.lower() in ['true', '1', 'yes']
            else:
                b_enabled = bool(raw_b_enabled)
            
            if not b_enabled and show_diag:
                # [v6.6.4] 1분(60초)마다 한 번씩만 출력하여 로그창 과부하 및 도배 방지
                if current_time % 60 < 10:
                    print(f"⚠️ <font color='#888888'>[디버그] {stock.get('stk_nm', '알수없음')} 불타기 설정이 OFF 상태(b_enabled={b_enabled})되어 진단 건너뜀</font>")
            
            if b_enabled:
                safe_stk_nm = stock.get('stk_nm', stock.get('prdt_name', '알수없음'))
                mapping_info = mapping.get(stk_cd) if mapping else None
                
                # [v6.2.8 Fallback] 매핑이 없으면 daily_buy_times.json에서 복구 시도
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
                    info = mapping_info # 하위 로직 호환성
                    if safe_stk_nm == '알수없음' and info.get('name'): safe_stk_nm = info['name']
                    
                    if buy_time_str:
                        try:
                            from datetime import datetime
                            now = datetime.now()
                            b_time = datetime.strptime(now.strftime("%Y%m%d") + " " + buy_time_str, "%Y%m%d %H:%M:%S")
                            wait_sec = int(cached_setting('bultagi_wait_sec', 10))
                            
                            elapsed = (now - b_time).total_seconds()
                            
                            # [Fix v6.4.6] 즉시 체결 버그 수정: 클럭 오차로 마이너스가 나면 999999가 아닌 0으로 간주
                            if -60 < elapsed < 0:
                                elapsed = 0 # 방금 매수함 (시스템 지터 대응)
                            elif elapsed <= -60:
                                elapsed = 999999 # 날짜가 바뀌었거나 실제 과거 기록임
                            
                            def safe_float(val):
                                try: return float(str(val).replace(',', '')) if val else 0.0
                                except: return 0.0

                            current_price = safe_float(stock.get('prpr', stock.get('now_prc', stock.get('cur_prc', 0))))
                            buy_price = safe_float(stock.get('avg_prc', stock.get('pchs_avg_pric', 0))) # [v6.1.12 정밀수정] avg_prc 우선
                            is_profit_zone = True if current_price > 0 and buy_price > 0 and current_price >= buy_price else False
                            
                            bultagi_trigger_ok = True
                            
                            # [v6.6.3] 완료된 종목은 로그 창 가독성을 위해 출력을 스킵함
                            if show_diag and not info.get('bultagi_done'):
                                status_icon = "✅ 이익구간" if is_profit_zone else "❌ 손실구간"
                                time_icon = "⌛" if elapsed >= wait_sec else "⏳"
                                done_mark = "" # [v6.6.3] 스킵하므로 빈 값
                                source_icon = "🛠️" if is_recovered else "🔗"
                                print(f"🔍 <font color='#f1c40f'><b>[불타기진단]</b></font> {source_icon} <font color='#ffffff'>{safe_stk_nm}{done_mark}</font> │ "
                                      f"{status_icon}({int(current_price):,}/{int(buy_price):,}) │ "
                                      f"{time_icon} {int(elapsed)}초/{int(wait_sec)}초 경과")

                            if elapsed < wait_sec:
                                bultagi_trigger_ok = False
                                # [v6.4.5] 10초 이내 절대 재매수 금지 (설정값보다 우선하는 최소 안전장치)
                                if elapsed < 10:
                                     print(f"📡 <font color='#95a5a6'>[시스템락] {safe_stk_nm}: 주문 후 10초 미경과로 로직 보호 중 ({int(elapsed)}/10초)</font>")
                                
                                # [v6.2.7] 대기 시간 카운트다운 1초마다 표시 (5초 간격)
                                remaining = int(wait_sec - elapsed)
                                if remaining % 5 == 0 and time.time() % 2 < 1:
                                    print(f"⏳ <font color='#95a5a6'>[불타기대기] {safe_stk_nm}: {int(elapsed)}/{int(wait_sec)}초 (발동까지 {remaining}초 남음)</font>")
                            elif not is_profit_zone:
                                bultagi_trigger_ok = False
                                if show_diag:
                                    print(f"🚫 <font color='#e74c3c'>[불타기차단] {safe_stk_nm}: 손실구간 ({int(current_price):,}원 &lt; 매입가 {int(buy_price):,}원) — 수익권 회복 후 발동</font>")
                            elif info.get('bultagi_done'):
                                bultagi_trigger_ok = False
                                # (완료 상태는 진단 로그에서 이미 표시됨)
                                
                            if bultagi_trigger_ok:
                                try:
                                    # [v6.4.3] API 호출 최소화: 필요한 필터가 켜져 있을 때만 확장 데이터 조회
                                    power_en = cached_setting('bultagi_power_enabled', False)
                                    slope_en = cached_setting('bultagi_slope_enabled', False)
                                    orderbook_en = cached_setting('bultagi_orderbook_enabled', False)
                                    
                                    ex_data = None
                                    if power_en or slope_en or orderbook_en:
                                        from stock_info import get_extended_stock_data
                                        ex_data = get_extended_stock_data(stk_cd, token=token)
                                    
                                    if power_en and ex_data:
                                        p_limit = float(cached_setting('bultagi_power_val', 120))
                                        if ex_data['power'] <= 0:
                                            # [v6.9.4] 정말 거래가 없어 0.0일 수도 있으므로 '수집 대기'를 '데이터 확인'으로 순화
                                            print(f"⚠️ <font color='#888888'>[불타기진단] {safe_stk_nm}: 체결강도 확인 중 (0.0)</font>")
                                            # [의논] 0.0일 때 무조건 차단할 것인가? 
                                            # 일단 수집 실패/대기 상태로 간주하여 안전하게 차단 유지 (사용자 설정값 120 등 미달)
                                            bultagi_trigger_ok = False
                                        elif ex_data['power'] < p_limit:
                                            print(f"🚫 <font color='#e74c3c'>[불타기차단] {safe_stk_nm}: 체결강도 미달 ({ex_data['power']} < {p_limit})</font>")
                                            bultagi_trigger_ok = False
                                        else:
                                            # [v6.8.6] 필터 통과 시 상세 로그 추가 (자기 요청!)
                                            print(f"⚡ <font color='#2ecc71'>[불타기필터] {safe_stk_nm}: 체결강도 통과 ({ex_data['power']} >= {p_limit})</font>")
                                            
                                    if slope_en and ex_data:
                                        last_p = info.get('last_power', 0)
                                        if ex_data['power'] > 0 and ex_data['power'] <= last_p:
                                            print(f"🚫 <font color='#e74c3c'>[불타기차단] {safe_stk_nm}: 체결강도 약화 추세 (현재 {ex_data['power']} &lt; 직전 {last_p})</font>")
                                            bultagi_trigger_ok = False
                                        info['last_power'] = ex_data['power']

                                    # [v6.4.3] 호가잔량비 필터 누락분 추가
                                    if orderbook_en and ex_data and bultagi_trigger_ok:
                                        # [v6.7.2] 데이터 수집 실패 시(orderbook_valid=False) 필터 무시 (안전장치)
                                        if not ex_data.get('orderbook_valid', True):
                                            if show_diag:
                                                print(f"⚠️ <font color='#888888'>[불타기진단] {safe_stk_nm}: 호가 데이터 수집 실패로 필터 일시 건너뜀</font>")
                                        else:
                                            ob_limit = float(cached_setting('bultagi_orderbook_val', 2.0))
                                            total_ask = ex_data.get('total_ask_qty', 0)
                                            total_bid = ex_data.get('total_bid_qty', 1) # 0 나누기 방지
                                            
                                            # [v6.7.2] 둘 다 0인 경우는 비정상 데이터로 간주 (상한가 제외 통상적 상황)
                                            if total_ask == 0 and total_bid == 0:
                                                if show_diag:
                                                    print(f"⚠️ <font color='#888888'>[불타기진단] {safe_stk_nm}: 호가 잔량이 모두 0입니다. (데이터 오류 의심)</font>")
                                            else:
                                                ob_ratio = total_ask / total_bid if total_bid > 0 else 0
                                                if ob_ratio < ob_limit:
                                                    # [v6.7.2] 차단 시 원본 수량 상세 표기
                                                    print(f"🚫 <font color='#e74c3c'>[불타기차단] {safe_stk_nm}: 호가잔량비 미달 ({ob_ratio:.2f} < {ob_limit}) [매도:{total_ask:,} / 매수:{total_bid:,}]</font>")
                                                    bultagi_trigger_ok = False
                                                else:
                                                    # [v6.8.6] 필터 통과 시 상세 로그 추가 (자기 요청!)
                                                    print(f"⚖️ <font color='#2ecc71'>[불타기필터] {safe_stk_nm}: 호가잔량비 통과 ({ob_ratio:.2f} >= {ob_limit}) [매도:{total_ask:,} / 매수:{total_bid:,}]</font>")

                                    if bultagi_trigger_ok:
                                        print(f"🔥 <font color='#ff4444'><b>[불타기발송]</b></font> {safe_stk_nm}: 모든 조건 충족! 주문 엔진 호출 중...")
                                        try:
                                            from bultagi_engine import trigger_bultagi_buy
                                            success = trigger_bultagi_buy(stk_cd, token=token)
                                            if success:
                                                print(f"✅ [불타기성공] {safe_stk_nm}: 매수 주문이 성공적으로 발송되었습니다.")
                                                update_stock_condition(
                                                    stk_cd, safe_stk_nm, strat='불타기',
                                                    seq=info.get('seq'), bultagi_done=True
                                                )
                                            else:
                                                print(f"❌ [불타기실패] {safe_stk_nm}: 엔진 호출은 성공했으나 주문 발송에 실패했습니다.")
                                        except Exception as eng_err:
                                            print(f"❌ [불타기오류] {safe_stk_nm}: 엔진 호출 중 예외 발생: {eng_err}")
                                except Exception as ex_err:
                                    print(f"⚠️ [불타기진단] 확장 데이터 수집 중 오류: {ex_err}")
                        except Exception as e_proc:
                             print(f"⚠️ [불타기처리예외] {e_proc}")

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

                    session_logger.record_sell(
                        stock['stk_cd'].replace('A', ''), stock['stk_nm'], qty, 
                        sell_prc, pl_rt, pnl_amt, tax=tax_val, seq=seq
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

        return True 

    except Exception as e:
        print(f"오류 발생(chk_n_sell): {e}")
        return False

if __name__ == "__main__":
    chk_n_sell(token=get_token())