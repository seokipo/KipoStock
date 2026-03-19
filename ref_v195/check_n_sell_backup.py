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

# 전역 캐시 (파일 I/O 최소화를 통한 성능 최적화)
_STRATEGY_MAPPING_CACHE = {}
_LAST_MAPPING_LOAD_TIME = 0
from check_n_buy import load_json_safe, save_json_safe, update_stock_condition, update_stock_peak_rt # [수정] update_stock_peak_rt 추가

def chk_n_sell(token=None):
    global _STRATEGY_MAPPING_CACHE, _LAST_MAPPING_LOAD_TIME
    # [초정밀 진단 v6.1.3] 함수 호출 여부 확인
    if time.time() % 10 < 0.5: # 10초에 한 번만 출력하여 로그 폭주 방지
        print("💓 [chk_n_sell] 엔진 심장 박동 중...")
    
    mapping_updated = False # [신규] 상태 변경(최고수익률 등) 발생 시 저장하기 위한 플래그
    
    # 익절/손절 수익율(%)
    TP_RATE = cached_setting('take_profit_rate', 10.0)
    SL_RATE = cached_setting('stop_loss_rate', -10.0)

    # [최적화] 매핑 정보 캐싱 (5초마다 한 번만 디스크 읽기)
    current_time = time.time()
    if not _STRATEGY_MAPPING_CACHE or (current_time - _LAST_MAPPING_LOAD_TIME > 5):
        import sys
        
        # [Fix v6.1.6] 무조건 실행 중인 메인 스크립트(또는 EXE)가 있는 상위 폴더를 기준으로 함.
        # 기존 getattr(sys, 'frozen'... 의 혼선 방지 (KipoStockNow 폴더 기준)
        if getattr(sys, 'frozen', False):
            base_path = os.path.dirname(sys.executable)
        else:
            base_path = os.path.dirname(os.path.abspath(__file__))
            
        mapping_file = os.path.join(base_path, 'stock_conditions.json')
        
        # [수정] 파일이 존재하는지, 비어있지는 않은지 정밀 확인
        mapped_data = {}
        if os.path.exists(mapping_file):
             mapped_data = load_json_safe(mapping_file)
        
        _STRATEGY_MAPPING_CACHE = mapped_data
        _LAST_MAPPING_LOAD_TIME = current_time
    
    mapping = _STRATEGY_MAPPING_CACHE

    try:
        my_stocks_data = get_my_stocks(token=token)
        my_stocks = []
        
        if isinstance(my_stocks_data, dict):
            my_stocks = my_stocks_data.get('stocks', [])
        elif isinstance(my_stocks_data, list):
            my_stocks = my_stocks_data

        if not my_stocks:
            # [진단 v6.1.7] my_stocks가 아예 비어있는지 확인
            if time.time() % 10 < 0.5:
                print("⚠️ [chk_n_sell] 보유 종목(my_stocks) 목록이 비어있어 루프를 종료합니다.")
            return True
            
        # [진단 v6.1.7] 루프 진입 전 보유 종목 수 출력
        if time.time() % 10 < 0.5:
             print(f"📦 [chk_n_sell] 보유 종목 {len(my_stocks)}개 루프 진입 시도...")
             
        for stock in my_stocks:
            # -----------------------------------------------------------
            # [수정] 수량 체크 추가 (0주면 매도 시도 금지)
            # -----------------------------------------------------------
            qty = int(stock.get('rmnd_qty', 0)) # 보유수량 가져오기
            stk_nm_test = stock.get('stk_nm', stock.get('prdt_name', '알수없음'))
            
            # [진단 v6.1.7] 각 종목별 수량 파싱 결과 확인 (10초 1회)
            if time.time() % 10 < 0.5:
                print(f"   ↳ 🔍 [수량체크] {stk_nm_test} : {qty}주")
                
            if qty <= 0:
                continue # 수량이 없으면 다음 종목으로 넘어감
            # -----------------------------------------------------------

            # [Fix] 수익률(pl_rt) 파싱 오류 수정: 다양한 API 응답 키워드 호환 및 예외 방어
            pl_rt = 0.0
            keys_to_try = ['pl_rt', 'evlu_pfls_rt', 'return_rate', 'profit_rate']
            for k in keys_to_try:
                if k in stock and str(stock[k]).strip():
                    try:
                        pl_rt = float(stock[k])
                        break # 성공적으로 찾으면 탈출
                    except:
                        pass

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
                        # [V4.6.8] 고점 갱신 시 원자적으로 파일에 즉시 저장 (데이터 유실 방지)
                        update_stock_peak_rt(stk_cd, pl_rt)

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
            # [Fix v6.1.11] 설정 캐시에서 예상치 못한 타입이 올 수 있으므로 한 번 더 보정
            raw_b_enabled = cached_setting('bultagi_enabled', True)
            b_enabled = True if str(raw_b_enabled).lower() in ['true', '1', 'yes'] else False
            
            if b_enabled:
                safe_stk_nm = stock.get('stk_nm', stock.get('prdt_name', '알수없음'))
                # [진단 v6.1.11] 로그 노이즈 최소화 모드
                bultagi_log_allowed = True 
                
                if bultagi_log_allowed and time.time() % 30 < 1: # 심장박동 30초에 한번으로 축소
                    print(f"💓 [chk_n_sell] {safe_stk_nm} 엔진 심장 박동 중...")

                if mapping and stk_cd in mapping:
                    info = mapping[stk_cd]
                    if safe_stk_nm == '알수없음' and info.get('name'):
                        safe_stk_nm = info['name']

                    buy_time_str = info.get('time')
                    if buy_time_str:
                            try:
                                from datetime import datetime
                                now = datetime.now()
                                # 오늘 날짜와 결합하여 datetime 객체 생성
                                b_time = datetime.strptime(now.strftime("%Y%m%d") + " " + buy_time_str, "%Y%m%d %H:%M:%S")
                                wait_sec = cached_setting('bultagi_wait_sec', 10)
                                
                                elapsed = (now - b_time).total_seconds()
                                
                                # [Fix] 오버나잇 종목 처리: elapsed가 음수이면, 
                                # 문자열 파싱 당시 오늘 날짜(YYYYMMDD)를 강제로 붙여서 미래의 시간으로 계산되었기 때문.
                                # 즉, 전날 이전에 산 종목이므로 대기 시간은 안 봐도 100% 충족한 것으로 처리.
                                if elapsed < 0:
                                    elapsed = 999999
                                
                                # [신규 v6.1.2] 진단 모드에서는 로그 항시 허용
                                bultagi_log_allowed = True 
                                
                                # [Fix v6.0.7] 가격 데이터 콤마(,) 제거 추가 (치명적 파싱 오류 방지)
                                def safe_float(val):
                                    return float(str(val).replace(',', '')) if val else 0.0

                                current_price = safe_float(stock.get('prpr', stock.get('now_prc', stock.get('cur_prc', 0)))) # 현재가
                                buy_price = safe_float(stock.get('pchs_avg_pric', stock.get('avg_prc', 0))) # 매입단가(평단가)
                                
                                # [원상 복구 v6.1.9] 실제 가격이 높으면 무조건 수익권으로 간주
                                is_profit_zone = True if current_price > 0 and buy_price > 0 and current_price >= buy_price else False
                                
                                # 불타기 트리거 가능 여부 플래그
                                bultagi_trigger_ok = True
                                
                                # [v6.1.12] 통합 진단 로그: 가독성 극대화 및 10초 주기 출력
                                status_icon = "✅ 이익구간" if is_profit_zone else "❌ 손실구간"
                                time_icon = "⌛" if elapsed >= wait_sec else "⏳"
                                done_mark = " (완료됨)" if info.get('bultagi_done') else ""
                                
                                # 10초에 한 번만 출력하여 노이즈 억제
                                if time.time() % 10 < 1:
                                    print(f"🔍 <font color='#f1c40f'><b>[불타기진단]</b></font> <font color='#ffffff'>{safe_stk_nm}{done_mark}</font> │ "
                                          f"{status_icon}({int(current_price):,}/{int(buy_price):,}) │ "
                                          f"{time_icon} {int(elapsed)}초/{int(wait_sec)}초 경과")

                                # 조건 검사 1: 대기 시간
                                if elapsed < wait_sec:
                                    bultagi_trigger_ok = False
                                
                                # 조건 검사 2: 수익률권(가격기준) 진입 여부
                                elif not is_profit_zone:
                                    bultagi_trigger_ok = False
                                        
                                # 조건 검사 3: 이미 불타기 완료된 종목인지 체크
                                elif info.get('bultagi_done'):
                                    bultagi_trigger_ok = False
                                    
                                # 설정 시간 경과 + 수익권(+) 이면 불타기 기본 조건 통과! (2단계 필터로)
                                if bultagi_trigger_ok:
                                    
                                    # [신규 v4.6.6] 고급 필터링 (체결강도, 호가잔량비)
                                    try:

                                        from stock_info import get_extended_stock_data
                                        ex_data = get_extended_stock_data(stk_cd, token=token)
                                        
                                        # 1. 체결강도 체크
                                        if cached_setting('bultagi_power_enabled', False):
                                            p_limit = cached_setting('bultagi_power_val', 120)
                                            # API 응답이 유효할 때만 체크 (0.0은 오류일 가능성 높음)
                                            if ex_data['power'] > 0 and ex_data['power'] < float(p_limit):
                                                if bultagi_log_allowed:
                                                    print(f"⏳ [불타기진단] {safe_stk_nm} | 보류사유: 체결강도 부족 (현재 {ex_data['power']}% < 목표 {p_limit}%)")
                                                bultagi_trigger_ok = False
                                                
                                        # 2. 체결강도 기울기(상승추세) 체크
                                        if cached_setting('bultagi_slope_enabled', False):
                                            last_p = info.get('last_power', 0)
                                            if ex_data['power'] > 0 and ex_data['power'] <= last_p:
                                                info['last_power'] = ex_data['power']
                                                bultagi_trigger_ok = False
                                            else:
                                                info['last_power'] = ex_data['power']
    
                                        # 3. 호가잔량비 역전 체크 (매도 > 매수*N)
                                        if cached_setting('bultagi_orderbook_enabled', False):
                                            ob_limit = float(cached_setting('bultagi_orderbook_val', 2.0))
                                            ask_q = ex_data.get('total_ask_qty', 0)
                                            bid_q = ex_data.get('total_bid_qty', 0)
                                            if bid_q > 0:
                                                ratio = ask_q / bid_q
                                                if ratio < ob_limit:
                                                    if bultagi_log_allowed:
                                                        print(f"⏳ [불타기진단] {safe_stk_nm} | 보류사유: 호가잔량비 미달 (현재 {ratio:.2f}배 < 목표 {ob_limit}배)")
                                                    bultagi_trigger_ok = False
                                            else: bultagi_trigger_ok = False # 데이터 오류 방어
                                        
                                        # 모든 필터 통과했을 때만 실행
                                        if not bultagi_trigger_ok:
                                            pass # 아래 매도 로직으로 자연스럽게 흐름
                                        else:
                                            b_mode = cached_setting('bultagi_mode', 'multiplier')
                                        b_val = cached_setting('bultagi_val', '10')
                                        
                                        val_int = int(str(b_val).replace(',', ''))
                                        if b_mode == 'multiplier':
                                            # 현재 보유 수량의 X배 추가 (예: 1주 보유 시 10주 추가 매수)
                                            add_qty = qty * val_int
                                        else:
                                            # [Fix] 정확한 현재가 무조건 확보하여 0주 매수 계산 차단
                                            curr_prc = 0.0
                                            # 여러 곳에서 현재가 후보를 싹쓸이 시도
                                            for p_key in [ex_data.get('price'), stock.get('prc'), stock.get('now_prc'), stock.get('prpr'), stock.get('stck_prpr')]:
                                                if p_key and float(p_key) > 0:
                                                    curr_prc = float(p_key)
                                                    break
                                            
                                            add_qty = (val_int // int(curr_prc)) if curr_prc > 0 else 0
                                            
                                        if add_qty > 0:
                                            from check_n_buy import add_buy, save_json_safe
                                            # [신규 v4.5] 불타기 전용 주문 방식(시/현) 연동
                                            b_price_type = cached_setting('bultagi_price_type', 'market')
                                            # 추가 매수 실행
                                            # [Fix] add_buy 의 리턴결과를 추적하도록 변경하여 실패 시 도달 처리 금지!
                                            is_success = add_buy(stk_cd, token=token, seq_name=info.get('name'), qty=add_qty, source='BULTAGI', price_type=b_price_type)
                                            
                                            if is_success:
                                                # [V5.3.1] 원자적 업데이트로 변경 (HTS 데이터 유실 방지 핵심)
                                                from check_n_buy import update_stock_condition
                                                update_stock_condition(
                                                    stk_cd, 
                                                    name=info.get('name', '알수없음'), 
                                                    strat=info.get('strat', 'qty'),
                                                    time_val=datetime.now().strftime("%H:%M:%S"), # 시간 갱신
                                                    seq=info.get('seq'),
                                                    bultagi_done=True # 불타기 완료 도장 찍기!
                                                )
                                            else:
                                                print(f"⚠️ [{safe_stk_nm}] 증거금 부족 또는 거래 조건 오류로 불타기 매수 실패, 다음 기회 대기")
                                        else:
                                            if time.time() % 60 < 2:
                                                print(f"⚠️ [{safe_stk_nm}] 현재가를 가져오지 못했거나 계산된 매수 수량이 0주입니다.")
                                            
                                    except Exception as e_inner:
                                        print(f"⚠️ [불타기실행에러] {e_inner}")
                            except Exception as e_outer:
                                if bultagi_log_allowed:
                                    print(f"⚠️ [불타기진단계산에러] {e_outer}")
                else:
                    # [신규 v5.3] 파일 위치 매핑 누락 진단 (장부 없음)
                    # [v6.1.11] 노이즈 제거: 1분당 2회만 출력
                    if bultagi_log_allowed and time.time() % 30 < 1:
                        print(f"⏳ [불타기진단] {safe_stk_nm} | 보류사유: 매핑 장부에 데이터가 없습니다. (수동/과거 1주 매수 또는 exe 폴더 이동 확인)")
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

        return True 

    except Exception as e:
        print(f"오류 발생(chk_n_sell): {e}")
        return False

if __name__ == "__main__":
    chk_n_sell(token=get_token())