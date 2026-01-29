import time
import os
import sys
import json
from datetime import datetime
from check_bal import fn_kt00001 as get_balance
from buy_stock import fn_kt10000 as buy_stock
from stock_info import fn_ka10001 as stock_info, get_current_price
from acc_val import fn_kt00004 as get_my_stocks
from tel_send import tel_send
from get_setting import cached_setting
from login import fn_au10001 as get_token
import subprocess

def say_text(text):
    """Windows SAPI.SpVoice를 사용하여 음성 출력 (PowerShell 경유, 창 숨김)"""
    try:
        ps_command = f'(New-Object -ComObject SAPI.SpVoice).Speak("{text}")'
        # [수정] CREATE_NO_WINDOW(0x08000000) 플래그를 사용하여 터미널 창 숨김
        subprocess.Popen(['powershell', '-Command', ps_command], 
                         stdout=subprocess.DEVNULL, 
                         stderr=subprocess.DEVNULL, 
                         creationflags=0x08000000)
    except Exception as e:
        print(f"⚠️ 음성 출력 오류: {e}")

# 전역 변수로 계좌 정보를 메모리에 들고 있음
ACCOUNT_CACHE = {
    'balance': 0,
    'holdings': set(),
    'names': {},
    'last_update': 0
}

RECENT_ORDER_CACHE = {}

def update_account_cache(token):
    try:
        balance_raw = get_balance(token=token, quiet=True)
        if balance_raw:
            ACCOUNT_CACHE['balance'] = int(str(balance_raw).replace(',', ''))
        
        holdings = set()
        names = {}
        my_stocks = get_my_stocks(token=token)
        
        if my_stocks:
            for stock in my_stocks:
                code = stock['stk_cd'].replace('A', '')
                name = stock['stk_nm']
                holdings.add(code)
                names[code] = name
        
        ACCOUNT_CACHE['holdings'] = holdings
        ACCOUNT_CACHE['names'].update(names)
        ACCOUNT_CACHE['last_update'] = time.time()
        
        print(f"\n💰 [계좌갱신] 잔고: {ACCOUNT_CACHE['balance']:,}원 | 보유: {len(holdings)}종목")
        print("-" * 60)
        
    except Exception as e:
        print(f"⚠️ 계좌 정보 갱신 실패: {e}")

def get_stock_name_safe(code, token):
    if code in ACCOUNT_CACHE['names']:
        return ACCOUNT_CACHE['names'][code]
    try:
        name = stock_info(code, token=token)
        if name:
            ACCOUNT_CACHE['names'][code] = name
            return name
    except:
        pass

    return code



# [신규] 매수 시간 로컬 저장 함수
def save_buy_time(code):
    try:
        # [수정] 경로 로직 통합 (ChatCommand와 동일하게)
        if getattr(sys, 'frozen', False):
            base_path = os.path.dirname(sys.executable)
        else:
            base_path = os.path.dirname(os.path.abspath(__file__))
            
        data_dir = os.path.join(base_path, 'LogData')
        if not os.path.exists(data_dir):
            try: os.makedirs(data_dir, exist_ok=True)
            except: pass
            
        json_path = os.path.join(data_dir, 'daily_buy_times.json')
        
        data = {}
        if os.path.exists(json_path):
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            except: data = {}
            
        # 날짜 확인 및 초기화
        today_str = datetime.now().strftime("%Y%m%d")
        if data.get('last_update_date') != today_str:
            data = {'last_update_date': today_str}
            
        code = code.replace('A', '')
        # [수정] 해당 종목 기록이 없을 때만 저장 (최초 매수 시간)
        if code not in data:
            current_time = datetime.now().strftime("%H:%M:%S")
            data[code] = current_time
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
    except Exception as e:
        print(f"⚠️ [DEBUG] 매수 시간 저장 실패: {e}")

# [신규] 로그를 예쁘게 출력하는 함수
# [Lite V1.0] 간결한 로그 시스템
def pretty_log(status_icon, status_msg, stock_name, code, is_error=False):
    display_name = stock_name[:7] + ".." if len(stock_name) > 8 else stock_name
    log_line = f"{status_icon} {status_msg:<6} │ {display_name}"
    if is_error: log_line += " ❌"
    print(log_line)

def chk_n_buy(stk_cd, token=None, seq=None, trade_price=None, seq_name=None):
    stk_cd = stk_cd.replace('A', '') 
    
    # [Debug] 매수 진입로깅
    # print(f"🔍 [BUY_DEBUG] chk_n_buy 진입: {stk_cd}, seq={seq} (type={type(seq)})")

    current_time = time.time()
    last_entry = RECENT_ORDER_CACHE.get(stk_cd, 0)

   
    
    
    RECENT_ORDER_CACHE[stk_cd] = current_time 

    try:
        max_stocks = cached_setting('max_stocks', 20) 
        if current_time - last_entry < 10:
        # 10초 컷은 너무 자주 뜨므로 로그를 생략하거나 아주 심플하게 출력
            s_name = get_stock_name_safe(stk_cd, token)
            pretty_log("⏰", "시간제한", s_name, stk_cd) # 2024/0115
            return 

        # A. 보유 종목 확인
        if stk_cd in ACCOUNT_CACHE['holdings']:
            s_name = get_stock_name_safe(stk_cd, token)
            pretty_log("💼", "이미보유", s_name, stk_cd)
            return

        # B. 최대 종목 수 확인
        current_count = len(ACCOUNT_CACHE['holdings'])
        if current_count >= max_stocks:
            s_name = get_stock_name_safe(stk_cd, token)
            pretty_log("⛔", f"풀방({current_count})", s_name, stk_cd)
            return

        # C. 잔고 체크
        if ACCOUNT_CACHE['balance'] < 1000: 
            s_name = get_stock_name_safe(stk_cd, token)
            pretty_log("💸", "잔고부족", s_name, stk_cd)
            RECENT_ORDER_CACHE.pop(stk_cd, None)
            return

        # =========================================================
        # 3. 매수 주문 전송
        # =========================================================
        
        # [신규] 조건식별 개별 매수 전략 적용 (V3.8.1)
        try:
            strat_map = cached_setting('condition_strategies', {})
            # seq가 없거나 맵에 없으면 기본 qty 모드
            mode = strat_map.get(str(seq), 'qty')
            
            if mode == 'qty':
                val_str = cached_setting('qty_val', '1')
            elif mode == 'amount':
                val_str = cached_setting('amt_val', '100,000')
            elif mode == 'percent':
                val_str = cached_setting('pct_val', '10')
            else:
                mode = 'qty'
                val_str = '1'
        except:
            mode = 'qty'
            val_str = '1'
            
        # 기본 수량
        qty = 1
        
        try:
            if mode == 'qty':
                # 고정 수량
                qty = int(val_str.replace(',', ''))
            
            elif mode in ['amount', 'percent']:
                # 가격 확인 (실시간 -> API)
                current_price = 0
                if trade_price:
                    current_price = int(trade_price)
                
                if current_price == 0:
                    _, current_price = get_current_price(stk_cd, token=token)
                    
                if current_price > 0:
                    if mode == 'amount':
                        target_amt = int(val_str.replace(',', ''))
                        qty = target_amt // current_price
                        pretty_log("💰", f"금액({target_amt:,})", f"{qty}주", stk_cd)
                    elif mode == 'percent':
                        pct = float(val_str)
                        current_balance = ACCOUNT_CACHE['balance']
                        target_amt = current_balance * (pct / 100)
                        qty = int(target_amt // current_price)
                        pretty_log("💰", f"비율({pct}%)", f"{qty}주", stk_cd)
                else:
                    print(f"⚠️ [매수전략] 가격 조회 실패로 1주 매수 진행")
                    qty = 1
                    
            if qty < 1: qty = 1
            
        except Exception as e:
            print(f"⚠️ [매수전략] 계산 오류 (기본 1주): {e}")
            qty = 1

        result = buy_stock(stk_cd, qty, '0', token=token)
        
        # [추가] 매수 성공 시 세션 로그에 기록하기 위해 가격 정보 준비
        try:
            _, final_price = get_current_price(stk_cd, token=token)
        except:
            final_price = current_price if 'current_price' in locals() else 0
        
        if isinstance(result, tuple) or isinstance(result, list):
            ret_code = result[0]
            ret_msg = result[1] if len(result) > 1 else ""
        else:
            ret_code = result
            ret_msg = ""

        is_success = str(ret_code) == '0' or ret_code == 0
        
        if is_success:
            from trade_logger import session_logger
            ACCOUNT_CACHE['holdings'].add(stk_cd)
            s_name = get_stock_name_safe(stk_cd, token)
            
            # 세션 매수 기록
            session_logger.record_buy(stk_cd, s_name, qty, final_price)
            
            # [신규] 종목별 검색 조건명 및 전략 저장 (당일매매일지용 색상 구분)
            if seq_name:
                try:
                    # [수정] 경로 로직 통합 (ChatCommand와 동일하게)
                    if getattr(sys, 'frozen', False):
                        base_path = os.path.dirname(sys.executable)
                    else:
                        base_path = os.path.dirname(os.path.abspath(__file__))
                    
                    data_dir = os.path.join(base_path, 'LogData')
                    if not os.path.exists(data_dir):
                        try: os.makedirs(data_dir, exist_ok=True)
                        except: pass
                    
                    mapping_file = os.path.join(data_dir, 'stock_conditions.json')
                    mapping = {}
                    if os.path.exists(mapping_file):
                        try:
                            with open(mapping_file, 'r', encoding='utf-8') as f:
                                mapping = json.load(f)
                        except: mapping = {}
                    
                    # [수정] 이름, 전략, 그리고 개별 익절/손절 값을 함께 저장
                    from get_setting import get_setting
                    st_data = get_setting('strategy_tp_sl', {})
                    specific_setting = st_data.get(mode, {})
                    
                    mapping[stk_cd] = {
                        'name': seq_name,
                        'strat': mode,
                        'tp': specific_setting.get('tp'),
                        'sl': specific_setting.get('sl'),
                        'time': datetime.now().strftime("%H:%M:%S") # 백업용 시간
                    }
                    with open(mapping_file, 'w', encoding='utf-8') as f:
                        json.dump(mapping, f, ensure_ascii=False, indent=2)
                except Exception as ex:
                    print(f"⚠️ 조건식 매핑 저장 실패: {ex}")

            # [신규] 매수 시간 저장
            save_buy_time(stk_cd)

            # [신규] 전략별 색상 결정
            color_map = {'qty': '#dc3545', 'amount': '#28a745', 'percent': '#007bff'}
            log_color = color_map.get(mode, '#00ff00')
            
            # [Lite V1.0] 다이어트 로그 (한 줄 요약 적용)
            log_msg = f"<font color='{log_color}'>⚡<b>[매수체결]</b> {s_name} ({final_price:,}원/{qty}주)"
            if seq_name: log_msg += f" <b>[{seq}. {seq_name}]</b>"
            log_msg += "</font>"
            print(log_msg)
            
            # [신규] 텔레그램 전송 추가
            tel_send(f"⚡[{qty}주 매수가동]⚡ {s_name} ({final_price:,}원)")

            # [신규] 전략별 음성 안내 추가 (조건식 이름 포함)
            # [수정] voice_guidance 설정값 확인 (기본값 True)
            from get_setting import get_setting
            if get_setting('voice_guidance', True):
                voice_map = {'qty': '한주', 'amount': '금액', 'percent': '비율'}
                strategy_voice = voice_map.get(mode, '매수')
                voice_msg = f"{seq_name} {strategy_voice}" if seq_name else strategy_voice
                say_text(voice_msg)
            else:
                # [신규] 음성 끔(Voice Off)일 때 짧은 비프음 재생 (beep_sound 설정 확인)
                if get_setting('beep_sound', True):
                    try:
                        import winsound
                        winsound.Beep(800, 200) # 800Hz, 200ms
                    except: pass
            
        else:
            s_name = get_stock_name_safe(stk_cd, token)
            pretty_log("❌", "주문실패", s_name, stk_cd, is_error=True)
            print(f"   ㄴ 사유: {ret_msg}") # [수정] 코드 제거
            
    except Exception as e:
        s_name = get_stock_name_safe(stk_cd, token)
        pretty_log("⚠️", "로직에러", s_name, stk_cd, is_error=True)
        print(f"   ㄴ 내용: {e}")
        RECENT_ORDER_CACHE.pop(stk_cd, None)