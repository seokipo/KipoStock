import time
import os
import json
from acc_val import fn_kt00004 as get_my_stocks
from sell_stock import fn_kt10001 as sell_stock
from tel_send import tel_send
from get_setting import cached_setting
from login import fn_au10001 as get_token
from market_hour import MarketHour

# 전역 캐시 (파일 I/O 최소화를 통한 성능 최적화)
_STRATEGY_MAPPING_CACHE = {}
_LAST_MAPPING_LOAD_TIME = 0

def chk_n_sell(token=None):
    global _STRATEGY_MAPPING_CACHE, _LAST_MAPPING_LOAD_TIME
    mapping_updated = False # [신규] 상태 변경(최고수익률 등) 발생 시 저장하기 위한 플래그
    
    # 익절/손절 수익율(%)
    TP_RATE = cached_setting('take_profit_rate', 10.0)
    SL_RATE = cached_setting('stop_loss_rate', -10.0)

    # [최적화] 매핑 정보 캐싱 (5초마다 한 번만 디스크 읽기)
    current_time = time.time()
    if not _STRATEGY_MAPPING_CACHE or (current_time - _LAST_MAPPING_LOAD_TIME > 5):
        try:
            import sys
            base_path = os.path.dirname(os.path.abspath(__file__))
            if getattr(sys, 'frozen', False):
                base_path = os.path.dirname(sys.executable)
            mapping_file = os.path.join(base_path, 'LogData', 'stock_conditions.json')
            if os.path.exists(mapping_file):
                with open(mapping_file, 'r', encoding='utf-8') as f:
                    _STRATEGY_MAPPING_CACHE = json.load(f)
                _LAST_MAPPING_LOAD_TIME = current_time
        except: pass
    
    mapping = _STRATEGY_MAPPING_CACHE

    try:
        my_stocks_data = get_my_stocks(token=token)
        my_stocks = []
        
        if isinstance(my_stocks_data, dict):
            my_stocks = my_stocks_data.get('stocks', [])
        elif isinstance(my_stocks_data, list):
            my_stocks = my_stocks_data

        if not my_stocks:
            return True
            
        for stock in my_stocks:
            # -----------------------------------------------------------
            # [수정] 수량 체크 추가 (0주면 매도 시도 금지)
            # -----------------------------------------------------------
            qty = int(stock.get('rmnd_qty', 0)) # 보유수량 가져오기
            if qty <= 0:
                continue # 수량이 없으면 다음 종목으로 넘어감
            # -----------------------------------------------------------

            # pl_rt는 문자열이므로 float으로 변환
            try:
                pl_rt = float(stock['pl_rt'])
            except:
                pl_rt = 0.0

            # [신규] 종목별 개별 익절/손절 설정 적용
            stk_cd = stock['stk_cd'].replace('A', '')
            specific_tp = TP_RATE
            specific_sl = SL_RATE
            
            if mapping and stk_cd in mapping:
                info = mapping[stk_cd]
                strat_mode = info.get('strat', 'qty')
                seq = info.get('seq') # [신규] 저장된 시퀀스 정보 추출
                
                # [Fix] HTS(직접) 전략인 경우, 저장된 값 대신 "실시간" 전역 설정값 우선 적용
                # 이를 통해 사용자가 GUI에서 설정을 바꾸면 즉시 반영됨 (Live Control)
                if strat_mode == 'HTS':
                     st_data = cached_setting('strategy_tp_sl', {})
                     hts_set = st_data.get('HTS', {})
                     
                     # HTS 실시간 설정 가져오기
                     live_tp = float(hts_set.get('tp', 0))
                     live_sl = float(hts_set.get('sl', 0))
                     
                     # 값이 유효하면 덮어쓰기 (0이면 아래 안전장치에서 기본값 처리됨)
                     if live_tp != 0: specific_tp = live_tp
                     if live_sl != 0: specific_sl = live_sl
                     
                else:
                    if info.get('tp') is not None: specific_tp = float(info['tp'])
                    if info.get('sl') is not None: specific_sl = float(info['sl'])

            # [Fix] 값이 0이면 전역 설정 또는 기본값 사용 (HTS 매수 시 초기화 오류 방지)
            if specific_tp == 0: specific_tp = TP_RATE if TP_RATE != 0 else 12.0
            if specific_sl == 0: specific_sl = SL_RATE if SL_RATE != 0 else -1.5

            # [신규 v4.6] 불타기 완료 종목 전용 익절/손절 덮어쓰기 로직
            if mapping and stk_cd in mapping:
                info = mapping[stk_cd]
                if info.get('bultagi_done'):
                    # [V4.6.8] 키움 스타일 3단 스탑로스 적용
                    b_tp_en = cached_setting('bultagi_tp_enabled', True)
                    b_tp = cached_setting('bultagi_tp', 5.0)
                    b_p_en = cached_setting('bultagi_preservation_enabled', False)
                    b_p_trigger = cached_setting('bultagi_preservation_trigger', 3.0)
                    b_p_limit = cached_setting('bultagi_preservation_limit', 2.0)
                    b_sl_en = cached_setting('bultagi_sl_enabled', True)
                    b_sl = cached_setting('bultagi_sl', -2.0)

                    # 1. 최고 수익률 갱신 (이익보존용)
                    peak_rt = info.get('peak_pl_rt', 0.0)
                    if pl_rt > peak_rt:
                        info['peak_pl_rt'] = pl_rt
                        peak_rt = pl_rt
                        mapping_updated = True # 갱신 발생 알림
                        # 최고점 갱신 시 즉시 저장 (파일 I/O 오버헤드 주의)
                        # 여기서는 루프 끝난 후 일괄 저장하거나 중요 지점에서만 저장하는 것이 좋으나
                        # 정확성을 위해 매번 갱신 (부하 적을 때만 사용 권장)

                    # 2. 매도 조건 판별
                    should_sell = False
                    sell_reason = ""
                    
                    # (1) 이익실현
                    if b_tp_en and pl_rt >= b_tp:
                        should_sell = True
                        sell_reason = "이익실현"
                    # (2) 이익보존 (트레일링)
                    elif b_p_en and peak_rt >= b_p_trigger and pl_rt <= b_p_limit:
                        should_sell = True
                        sell_reason = "이익보존"
                    # (3) 손실제한
                    elif b_sl_en and pl_rt <= b_sl:
                        should_sell = True
                        sell_reason = "손실제한"
                    
                    if should_sell:
                        specific_tp = -999 # 강제 익절 트리거 방지
                        specific_sl = 999  # 강제 손절 트리거 방지
                        # 아래 공통 매도 로직에서 처리되도록 pl_rt 조작 또는 플래그 설정
                        pl_rt = 999 if should_sell else pl_rt 
                    else:
                        # 아직 매도 타점 아니면 기본 체크 패스하도록 극단값 설정
                        specific_tp = 999
                        specific_sl = -999

            # [신규 v4.5] 불타기(Fire-up) 추가 매수 로직 체크 (v4.5 DIAMOND)
            b_enabled = cached_setting('bultagi_enabled', True)
            if b_enabled and mapping and stk_cd in mapping:
                info = mapping[stk_cd]
                # [V4.6.9 수절] 전략 필터 확장 (기존 qty에서 amount, percent, HTS까지 모두 포함)
                if info.get('strat') in ['qty', 'amount', 'percent', 'HTS'] and not info.get('bultagi_done'):
                    buy_time_str = info.get('time')
                    if buy_time_str:
                        try:
                            from datetime import datetime
                            now = datetime.now()
                            # 오늘 날짜와 결합하여 datetime 객체 생성
                            b_time = datetime.strptime(now.strftime("%Y%m%d") + " " + buy_time_str, "%Y%m%d %H:%M:%S")
                            wait_sec = cached_setting('bultagi_wait_sec', 30)
                            
                            elapsed = (now - b_time).total_seconds()
                            
                            # [Fix] 오버나잇 종목 처리: elapsed가 음수면 전날 산 것이므로 충분히 시간이 흐른 것으로 간주
                            if elapsed < 0:
                                elapsed = 999999
                            
                            # 설정 시간 경과 + 수익권(+) 이면 불타기 실행!
                            if elapsed >= wait_sec and pl_rt > 0:
                                # [신규 v4.6.6] 고급 필터링 (체결강도, 호가잔량비)
                                try:
                                    from stock_info import get_extended_stock_data
                                    ex_data = get_extended_stock_data(stk_cd, token=token)
                                    
                                    # 1. 체결강도 체크
                                    if cached_setting('bultagi_power_enabled', False):
                                        p_limit = cached_setting('bultagi_power_val', 120)
                                        if ex_data['power'] < float(p_limit):
                                            # print(f"⏳ [불타기보류] 체결강도 부족: {ex_data['power']}% < {p_limit}%")
                                            continue 
                                            
                                    # 2. 체결강도 기울기(상승추세) 체크
                                    if cached_setting('bultagi_slope_enabled', False):
                                        last_p = info.get('last_power', 0)
                                        if ex_data['power'] <= last_p:
                                            # print(f"⏳ [불타기보류] 체결강도 약화/유지: {last_p}% -> {ex_data['power']}%")
                                            info['last_power'] = ex_data['power'] # 현재값 업데이트 후 다음 기회 노림
                                            continue
                                        info['last_power'] = ex_data['power'] # 기록 갱신

                                    # 3. 호가잔량비 역전 체크 (매도 > 매수*N)
                                    if cached_setting('bultagi_orderbook_enabled', False):
                                        ob_limit = float(cached_setting('bultagi_orderbook_val', 2.0))
                                        ask_q = ex_data['total_ask_qty']
                                        bid_q = ex_data['total_bid_qty']
                                        if bid_q > 0:
                                            ratio = ask_q / bid_q
                                            if ratio < ob_limit:
                                                # print(f"⏳ [불타기보류] 호가잔량비 미달: {ratio:.2f}배 < {ob_limit}배")
                                                continue
                                        else: continue # 데이터 오류 방어

                                    b_mode = cached_setting('bultagi_mode', 'multiplier')
                                    b_val = cached_setting('bultagi_val', '10')
                                    
                                    val_int = int(str(b_val).replace(',', ''))
                                    if b_mode == 'multiplier':
                                        # 현재 보유 수량의 X배 추가 (예: 1주 보유 시 10주 추가 매수)
                                        add_qty = qty * val_int
                                    else:
                                        # [수정] 고정 금액만큼 추가 매수 시 현재가 객체 필드명 확인 (prc / prvs_rcv_prc 등)
                                        curr_prc = float(ex_data['price'] or stock.get('prc') or stock.get('now_prc') or 0)
                                        add_qty = (val_int // int(curr_prc)) if curr_prc > 0 else 0
                                    if add_qty > 0:
                                        from check_n_buy import add_buy, save_json_safe
                                        # [신규 v4.5] 불타기 전용 주문 방식(시/현) 연동
                                        b_price_type = cached_setting('bultagi_price_type', 'market')
                                        # 추가 매수 실행
                                        add_buy(stk_cd, token=token, seq_name=info.get('name'), qty=add_qty, source='BULTAGI', price_type=b_price_type)
                                        
                                        # 상태 업데이트 및 즉시 저장 (중복 방지)
                                        info['bultagi_done'] = True
                                        mapping[stk_cd] = info
                                        
                                        # 파일 경로 재계산 (저장용)
                                        import sys
                                        bp = os.path.dirname(os.path.abspath(__file__))
                                        if getattr(sys, 'frozen', False): bp = os.path.dirname(sys.executable)
                                        m_path = os.path.join(bp, 'LogData', 'stock_conditions.json')
                                        save_json_safe(m_path, mapping)
                                        
                                except Exception as e_inner:
                                    print(f"⚠️ [불타기실행에러] {e_inner}")
                        except Exception as e_outer:
                            pass

            if pl_rt > specific_tp or pl_rt < specific_sl:
                # [신규] 장 시작 전(09:00 이전)에는 매도 주문 제한
                if not MarketHour.is_market_open_time():
                    # 로그 스팸 방지를 위해 장 시작 전에는 별도 로그 없이 넘어가거나
                    # 필요시 디버그 로그만 출력 (현재는 조용히 넘김)
                    # print(f"⏳ [Standby] 장 시작 전 대기: {stock['stk_nm']}")
                    continue

                # 매도 실행
                sell_result = sell_stock(stock['stk_cd'].replace('A', ''), str(qty), token=token)
                
                # 결과 확인 (리스트나 튜플로 올 수도 있고, 숫자/문자열일 수도 있음 방어코드)
                if isinstance(sell_result, (tuple, list)):
                    ret_code = sell_result[0]
                elif isinstance(sell_result, dict):
                    ret_code = sell_result.get('return_code')
                else:
                    ret_code = sell_result

                if str(ret_code) != '0' and ret_code != 0:
                    print(f"⚠️ 매도 주문 실패: {stock['stk_nm']}")  # (코드: {ret_code})")
                    continue

                # [추가] 세션 로그에 매도 기록
                try:
                    from trade_logger import session_logger
                    # 매도 가격 추정 (현재가 또는 평가 단가)
                    sell_prc = float(stock.get('prc', 0)) or float(stock.get('evlt_amt', 0)) / qty if qty > 0 else 0
                    pnl_amt = int(stock.get('pl_amt', 0)) # [표준화] pl_amt -> pnl_amt
                    
                    # [신규] 세금 정보 추출
                    def val(keys):
                        for k in keys:
                            v = stock.get(k)
                            if v is not None and str(v).strip() != "": return v
                        return 0
                    tax_val = int(float(val(['cmsn_alm_tax', 'cmsn_tax', 'tax'])))

                    session_logger.record_sell(
                        stock['stk_cd'].replace('A', ''), 
                        stock['stk_nm'], 
                        qty, 
                        sell_prc, 
                        pl_rt, 
                        pnl_amt,
                        tax=tax_val,
                        seq=seq # [신규] 보존된 시퀀스 정보 전달
                    )
                except Exception as ex:
                    print(f"⚠️ 세션 매도 기록 실패: {ex}")

                result_type = "익절" if pl_rt > specific_tp else "손절"
                # [V4.6.8] 상세 사유 연동
                if 'sell_reason' in locals() and sell_reason:
                    result_type = sell_reason
                
                result_emoji = "😃" if "이익" in result_type or result_type == "익절" else "😰"
                
                # 수익률 소수점 2자리까지만 예쁘게 출력
                message = f'{result_emoji} {stock["stk_nm"]} {qty}주 {result_type} 완료 (수익율: {pl_rt if pl_rt < 999 else float(stock["pl_rt"]):.2f}%)'
                tel_send(message, msg_type='log')
                
                # [신규] 매수 전략 색상 연동 (빨강:1주, 초록:금액, 파랑:비율)
                log_color = '#ffdf00' # 기본값 (금색)
                # [수정] 이미 위에서 로드한 mapping 사용
                try:
                    stk_info = mapping.get(stk_cd)
                    if stk_info:
                        mode = stk_info.get('strat', 'qty')
                        color_map = {'qty': '#dc3545', 'amount': '#28a745', 'percent': '#007bff'}
                        log_color = color_map.get(mode, '#ffdf00')
                except: pass

                # [신규] GUI 로그 컬러링 (전략별 색상 적용)
                colored_msg = f"<font color='{log_color}'>{message}</font>"
                print(colored_msg)

        # [신규 v4.6.8] 루프 종료 후 상태(최고수익률 등)가 변했다면 일괄 저장
        if mapping_updated:
            from check_n_buy import save_json_safe
            import sys
            bp = os.path.dirname(os.path.abspath(__file__))
            if getattr(sys, 'frozen', False): bp = os.path.dirname(sys.executable)
            m_path = os.path.join(bp, 'LogData', 'stock_conditions.json')
            save_json_safe(m_path, mapping)

        return True 

    except Exception as e:
        print(f"오류 발생(chk_n_sell): {e}")
        return False

if __name__ == "__main__":
    chk_n_sell(token=get_token())