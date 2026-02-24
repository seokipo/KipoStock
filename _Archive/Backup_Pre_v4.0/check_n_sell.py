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

            # [Debug] 매도 판단 로깅 (사용자 요청: 왜 파는지 확인)
            # [Debug] 매도 판단 로깅 (사용자 요청: 왜 파는지 확인) -> [요청] 로그 너무 많음 (지움)
            # print(f"🧐 [Sell Check] {stock['stk_nm']}: 수익률 {pl_rt}% (익절: {specific_tp}% / 손절: {specific_sl}%)")

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
                result_emoji = "😃" if pl_rt > specific_tp else "😰"
                
                # 수익률 소수점 2자리까지만 예쁘게 출력
                message = f'{result_emoji} {stock["stk_nm"]} {qty}주 {result_type} 완료 (수익율: {pl_rt:.2f}%)'
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