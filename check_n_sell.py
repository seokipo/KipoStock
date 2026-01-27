import time
import os
import json
from acc_val import fn_kt00004 as get_my_stocks
from sell_stock import fn_kt10001 as sell_stock
from tel_send import tel_send
from get_setting import cached_setting
from login import fn_au10001 as get_token

def chk_n_sell(token=None):
    # 익절 수익율(%)
    TP_RATE = cached_setting('take_profit_rate', 10.0)
    # 손절 수익율(%)
    SL_RATE = cached_setting('stop_loss_rate', -10.0)

    # [신규] 매핑 정보 사전 로드
    mapping = {}
    try:
        base_path = os.path.dirname(os.path.abspath(__file__))
        if getattr(sys, 'frozen', False):
            base_path = os.path.dirname(sys.executable)
        mapping_file = os.path.join(base_path, 'LogData', 'stock_conditions.json')
        if os.path.exists(mapping_file):
            with open(mapping_file, 'r', encoding='utf-8') as f:
                mapping = json.load(f)
    except: pass

    try:
        my_stocks = get_my_stocks(token=token)
        if not my_stocks:
            # print("보유 종목이 없습니다.") # 로그 너무 많으면 생략
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
            
            # 매칭 정보 읽기
            if mapping and stk_cd in mapping:
                info = mapping[stk_cd]
                if info.get('tp') is not None: specific_tp = float(info['tp'])
                if info.get('sl') is not None: specific_sl = float(info['sl'])

            if pl_rt > specific_tp or pl_rt < specific_sl:
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
                    session_logger.record_sell(
                        stock['stk_cd'].replace('A', ''), 
                        stock['stk_nm'], 
                        qty, 
                        sell_prc, 
                        pl_rt, 
                        pnl_amt
                    )
                except Exception as ex:
                    print(f"⚠️ 세션 매도 기록 실패: {ex}")

                result_type = "익절" if pl_rt > specific_tp else "손절"
                result_emoji = "😃" if pl_rt > specific_tp else "😰"
                
                # 수익률 소수점 2자리까지만 예쁘게 출력
                message = f'{result_emoji} {stock["stk_nm"]} {qty}주 {result_type} 완료 (수익율: {pl_rt:.2f}%)'
                tel_send(message)
                
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