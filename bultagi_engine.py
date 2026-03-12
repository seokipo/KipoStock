import time
from buy_stock import fn_kt10000 as buy_stock
from get_setting import cached_setting
from login import fn_au10001 as get_token
from tel_send import tel_send

def trigger_bultagi_buy(stk_cd, token=None):
    """
    자기야! 이 함수는 불타기(추가 매수) 주문을 실제로 실행하는 엔진이야! 🚀✨
    """
    try:
        if not token: token = get_token()
        
        # 1. 설정값 가져오기
        b_mode = cached_setting('bultagi_mode', 'multiplier') # 'multiplier' or 'amount'
        b_val = float(cached_setting('bultagi_val', 10)) # 수량(배수) 또는 금액
        
        ord_qty = 0
        ord_price = 0 # 시장가(3)는 0
        
        if b_mode == 'multiplier':
            # [Fix v6.2.3] 배수 모드: 현재 보유 수량 * b_val
            from acc_val import fn_kt00004 as get_my_stocks
            my_stocks_data = get_my_stocks(token=token)
            holding_qty = 0
            
            if isinstance(my_stocks_data, dict):
                my_stocks = my_stocks_data.get('stocks', [])
            elif isinstance(my_stocks_data, list):
                my_stocks = my_stocks_data
            else:
                my_stocks = []

            for stock in my_stocks:
                if stock['stk_cd'].replace('A', '') == stk_cd.replace('A', ''):
                    holding_qty = int(stock.get('rmnd_qty', 0))
                    break
            
            if holding_qty <= 0:
                print(f"⚠️ [bultagi_engine] 현재 보유 수량이 0주이므로 불타기를 취소합니다. ({stk_cd})")
                return False
                
            ord_qty = int(holding_qty * b_val)
            
        else:
            # 금액 기준일 경우 현재가로 수량 계산
            from stock_info import get_current_price
            _, cur_p = get_current_price(stk_cd, token=token)
            if cur_p > 0:
                ord_qty = int(float(b_val) / cur_p)
        
        if ord_qty <= 0:
            hint = ""
            if b_mode == 'amount' and cur_p > b_val:
                hint = f" (현재가 {cur_p:,}원보다 설정금액 {b_val:,}원이 작음)"
            print(f"⚠️ [bultagi_engine] 계산된 매수 수량이 0입니다.{hint} ({stk_cd}, 모드:{b_mode}, 입력값:{b_val})")
            return False

        # 2. 주문 실행
        ret_code, ret_msg = buy_stock(stk_cd, ord_qty, ord_price, token=token)
        
        if str(ret_code) == '0':
            # [신규 v6.4.5] 주문 캐시 즉시 업데이트 (HTS 오인 감지 방지 전용 락)
            try:
                from check_n_buy import RECENT_ORDER_CACHE, get_stock_name_safe
                RECENT_ORDER_CACHE[stk_cd.replace('A', '')] = time.time()
                s_name = get_stock_name_safe(stk_cd, token)
            except: 
                s_name = stk_cd

            msg = f"🔥 [불타기집행] {s_name} {ord_qty}주 시장가 추가 매수 완료!"
            print(f"<font color='#ff4444'><b>{msg}</b></font>")
            tel_send(msg, msg_type='log')
            
            # 3. 매수 시간 기록 (다음 불타기 대기시간 계산용)
            try:
                from check_n_buy import save_buy_time
                save_buy_time(stk_cd)
            except: pass
            
            return True
        else:
            print(f"❌ [bultagi_engine] 주문 실패: {ret_msg}")
            return False

    except Exception as e:
        print(f"⚠️ [bultagi_engine] 예외 발생: {e}")
        return False
