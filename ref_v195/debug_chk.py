import sys
import os
import time

def emulate_chk_n_sell():
    my_stocks = [{
        'stk_cd': 'A053050',
        'stk_nm': '지에스이',
        'rmnd_qty': '1',
        'prpr': '4125',
        'avg_prc': '4155'
    }]
    
    mapping = {
        '053050': {
            'name': '지에스이',
            'strat': 'HTS',
            'time': '13:51:39'
        }
    }
    
    wait_sec = 10
    show_diag = True

    for stock in my_stocks:
        qty = int(stock.get('rmnd_qty', 0))
        if qty <= 0: continue
            
        stk_cd = stock['stk_cd'].replace('A', '')
        b_enabled = True
        
        if b_enabled:
            safe_stk_nm = stock.get('stk_nm', stock.get('prdt_name', '알수없음'))
            mapping_info = mapping.get(stk_cd) if mapping else None
            
            buy_time_str = mapping_info.get('time') if mapping_info else None
            
            if buy_time_str and buy_time_str != "99:99:99":
                from datetime import datetime
                now = datetime.now()
                try:
                    b_time = datetime.strptime(now.strftime("%Y%m%d") + " " + buy_time_str, "%Y%m%d %H:%M:%S")
                    elapsed = (now - b_time).total_seconds()
                    if elapsed < 0: elapsed = 999999
                    
                    def safe_float(val):
                        try: return float(str(val).replace(',', '')) if val else 0.0
                        except: return 0.0

                    current_price = safe_float(stock.get('prpr', 0))
                    buy_price = safe_float(stock.get('avg_prc', 0))
                    is_profit_zone = True if current_price > 0 and buy_price > 0 and current_price >= buy_price else False
                    
                    bultagi_trigger_ok = True
                    
                    if show_diag:
                        status_icon = "✅ 이익구간" if is_profit_zone else "❌ 손실구간"
                        time_icon = "⌛" if elapsed >= wait_sec else "⏳"
                        done_mark = ""
                        source_icon = "🛠️"
                        print(f"🔍 <font color='#f1c40f'><b>[불타기진단]</b></font> {source_icon} <font color='#ffffff'>{safe_stk_nm}{done_mark}</font> │ "
                              f"{status_icon}({int(current_price):,}/{int(buy_price):,}) │ "
                              f"{time_icon} {int(elapsed)}초/{int(wait_sec)}초 경과")
                except Exception as e:
                    print(f"Exception: {e}")

if __name__ == "__main__":
    emulate_chk_n_sell()
