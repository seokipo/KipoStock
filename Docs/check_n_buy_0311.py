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
import asyncio
import subprocess
import queue
import threading

# [v4.8] 고급 비동기 패턴 (Skills: async-python-patterns)
_FILE_LOCK = threading.Lock() 
_ORDER_SEMAPHORE = None # 비동기 루프 내에서 초기화 예정
from get_setting import get_setting
from trade_logger import session_logger

_LOG_QUEUE = queue.Queue()

def _log_worker():
    """백그라운드에서 파일 I/O를 처리하는 워커 (메인 스레드 지연 방지)"""
    while True:
        try:
            task = _LOG_QUEUE.get()
            if task is None: break # 종료 신호
            
            task_type, data = task
            
            if task_type == 'save_mapping':
                _process_save_mapping(data)
            elif task_type == 'save_buy_time':
                save_buy_time(data['code'], overwrite=data.get('overwrite', False)) # [v6.2.8] overwrite 전달
                
            _LOG_QUEUE.task_done()
        except Exception as e:
            # print(f"⚠️ [비동기로거] 처리 실패: {e}")
            pass

# 데몬 스레드로 시작 (메인 프로그램 종료 시 자동 종료)
_WORKER_THREAD = threading.Thread(target=_log_worker, daemon=True)
_WORKER_THREAD.start()

def _process_save_mapping(data):
    """실제 파일 저장을 수행하는 내부 함수"""
    try:
        stk_cd = data['code']
        seq_name = data['name']
        mode = data['mode']
        seq = data.get('seq') # [신규] 시퀀스 정보
        
        # 경로 로직 통합
        if getattr(sys, 'frozen', False):
            base_path = os.path.dirname(sys.executable)
        else:
            base_path = os.path.dirname(os.path.abspath(__file__))
        
        mapping_file = os.path.join(base_path, 'stock_conditions.json')
        mapping = load_json_safe(mapping_file)
        
        st_data = get_setting('strategy_tp_sl', {})
        specific_setting = st_data.get(mode, {})
        
        mapping[stk_cd] = {
            'name': seq_name,
            'strat': mode,
            'seq': seq, # [신규] 시퀀스 번호 저장
            'tp': specific_setting.get('tp'),
            'sl': specific_setting.get('sl'),
            'time': datetime.now().strftime("%H:%M:%S")
        }
        save_json_safe(mapping_file, mapping)
    except Exception:
        # print(f"⚠️ [비동기] 조건식 매핑 저장 실패: {ex}")
        pass

def say_text(text):
    """Windows SAPI.SpVoice를 사용하여 음성 출력 (PowerShell 경유, 창 숨김)"""
    try:
        ps_command = f'(New-Object -ComObject SAPI.SpVoice).Speak("{text}")'
        # [수정] CREATE_NO_WINDOW(0x08000000) 플래그를 사용하여 터미널 창 숨김
        subprocess.Popen(['powershell', '-Command', ps_command], 
                         stdout=subprocess.DEVNULL, 
                         stderr=subprocess.DEVNULL, 
                         creationflags=0x08000000)
    except Exception:
        # print(f"⚠️ 음성 출력 오류: {e}")
        pass

# 전역 변수로 계좌 정보를 메모리에 들고 있음
ACCOUNT_CACHE = {
    'balance': 0,
    'acnt_no': '', # [신규] 계좌번호 저장 필드
    'holdings': {}, # [수정] set() -> dict {code: qty} (하위 호환 및 수량 감지용)
    'realtime_holdings': {}, # [신규] GUI 렌더링을 위한 상세 데이터 {code: dict}
    'names': {},
    'last_update': 0
}

# [v6.7.3] 실시간 탐색 종목 이력 (AI 종가 추천용)
DAILY_DETECTED_STOCKS = set()

def save_detected_stock(code):
    """오늘 실시간으로 검출된 종목 코드를 메모리와 파일에 저장"""
    try:
        code = code.replace('A', '')
        if code in DAILY_DETECTED_STOCKS: return
        
        DAILY_DETECTED_STOCKS.add(code)
        
        # 파일 저장
        if getattr(sys, 'frozen', False):
            base = os.path.dirname(sys.executable)
        else:
            base = os.path.dirname(os.path.abspath(__file__))
            
        fpath = os.path.join(base, 'daily_detected_stocks.json')
        
        data = []
        if os.path.exists(fpath):
            with open(fpath, 'r', encoding='utf-8') as f:
                try: data = json.load(f)
                except: data = []
        
        if code not in data:
            data.append(code)
            with open(fpath, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
    except: pass

RECENT_ORDER_CACHE = {}
PROCESSING_FLAGS = set() # [신규] 중복 처리 동시 진입 방지 락

def update_account_cache(token):
    global _ORDER_SEMAPHORE
    try:
        # [v4.8] 비동기 세마포어 초기화 (최초 1회)
        if _ORDER_SEMAPHORE is None:
            try:
                loop = asyncio.get_event_loop()
                _ORDER_SEMAPHORE = asyncio.Semaphore(5) # 동시 주문 5개 제한 (안정성)
            except: pass

        balance_data = get_balance(token=token, quiet=True)
        if balance_data and isinstance(balance_data, dict):
            ACCOUNT_CACHE['balance'] = int(str(balance_data.get('balance', '0')).replace(',', ''))
            ACCOUNT_CACHE['acnt_no'] = balance_data.get('acnt_no', '')
        
        # [수정] 수량까지 포함하여 비교 (DICT 형태)
        old_holdings = ACCOUNT_CACHE['holdings'].copy()
        new_holdings = {}
        realtime_holdings = {} # [신규]
        names = {}
        
        my_stocks_data = get_my_stocks(token=token)
        my_stocks = []
        
        if isinstance(my_stocks_data, dict):
            my_stocks = my_stocks_data.get('stocks', [])
            # [신규] 계좌번호 확보 (예수금 조회 실패 대비)
            if not ACCOUNT_CACHE['acnt_no']:
                ACCOUNT_CACHE['acnt_no'] = my_stocks_data.get('acnt_no', '')
        elif isinstance(my_stocks_data, list):
            my_stocks = my_stocks_data
            
        for stock in my_stocks:
            code = stock['stk_cd'].replace('A', '')
            name = stock['stk_nm']
            try: qty = int(stock.get('hldg_qty', stock.get('rmnd_qty', 0))) # [v6.1.12 수정] 필드명 유연성 확보
            except: qty = 0
            
            new_holdings[code] = qty
            names[code] = name

            # [v6.1.12 수정] 실제 API 필드명에 맞춰 정밀 매핑 (0패딩 문자열 대응)
            try:
                def _parse(k, default=0.0):
                    val = stock.get(k, default)
                    return float(str(val).replace(',', '')) if val else default

                realtime_holdings[code] = {
                    'name': name,
                    'buy_price': _parse('avg_prc'),
                    'cur_price': _parse('cur_prc'),
                    'pl_rt': _parse('pl_rt'),
                    'qty': int(_parse('rmnd_qty')),
                    'pnl': int(_parse('pl_amt'))
                }
            except Exception as e:
                print(f"⚠️ [realtime_holdings] 가공 중 예외: {e}")
        
        ACCOUNT_CACHE['realtime_holdings'] = realtime_holdings # 전역 캐시 업데이트
        
        # [신규] HTS/외부 매매 감지 로직 (최초 실행 시엔 skip)
        if ACCOUNT_CACHE['last_update'] > 0:
            # 1. 신규 종목 / 수량 증가 (매수)
            for code, new_qty in new_holdings.items():
                old_qty = old_holdings.get(code, 0)
                
                if new_qty > old_qty:
                    diff = new_qty - old_qty
                    s_name = names.get(code, code)
                    
                    # [HTS 감지 핵심] 봇 주문 후 잠시 동안은 중복 방지를 위해 스킵하지만,
                    # HTS 주문은 last_order_time이 없거나 오래되었으므로 통과됨.
                    last_order_time = RECENT_ORDER_CACHE.get(code, 0)
                    
                    # [수정] 봇 주문 직후(10초)가 아니면 무조건 HTS/외부 매수로 간주
                    if time.time() - last_order_time > 10.0:
                        print(f"<font color='#ffc107'>🕵️ <b>[HTS매수/폴링]</b> {s_name} ({diff}주 추가 감지) [직접매매]</font>")
                        tel_send(f"🕵️ [HTS외부감지] {s_name} {diff}주 추가됨", msg_type='log')
                        
                        # [HTS 수동매매는 중복 감지 방지 캐시를 업데이트하지 않음]
                        # RECENT_ORDER_CACHE[code] = time.time() 
                        
                        try:
                            # [개선] HTS 매수 시 가격이 0이면 현재가를 가져와서 기록 (수익률 정밀도 향상)
                            hts_price = 0
                            try:
                                _, hts_price = get_current_price(code, token=token)
                            except: pass
                            
                            from trade_logger import session_logger # [v5.5.1 fix]
                            update_stock_condition(code, name='직접매매', strat='HTS')
                            session_logger.record_buy(code, s_name, diff, hts_price, strat_mode='HTS')
                        except Exception as e:
                            print(f"⚠️ [HTS저장] 메타데이터 저장 실패: {e}")

                # [v6.2.8] 매핑 누락 자동 복구 로직
                # stock_conditions.json(mapping)에 없지만 보유 중인 종목을 daily_buy_times.json 기반으로 구제
                try:
                    import sys
                    base_path = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
                    mapping_file = os.path.join(base_path, 'stock_conditions.json')
                    buy_times_file = os.path.join(base_path, 'daily_buy_times.json')
                    
                    # 매 루프마다 파일을 읽는 것은 비효율적이므로 ACCOUNT_CACHE에 매핑 상태 체크
                    if code not in load_json_safe(mapping_file):
                        bt_data = load_json_safe(buy_times_file)
                        if code in bt_data:
                            b_entry = bt_data[code]
                            b_time = b_entry.get('time') if isinstance(b_entry, dict) else b_entry
                            if b_time and b_time != "99:99:99":
                                print(f"🛠️ [매핑복구] {names.get(code, code)} ({code}): 매핑 누수 감지 -> {b_time} 기반 자동 복구")
                                update_stock_condition(code, name=names.get(code, '복구종목'), strat='HTS', time_val=b_time)
                except: pass
            
            # 2. 종목 삭제 / 수량 감소 (매도)
            for code, old_qty in old_holdings.items():
                new_qty = new_holdings.get(code, 0)
                if new_qty < old_qty:
                    diff = old_qty - new_qty
                    s_name = names.get(code, ACCOUNT_CACHE['names'].get(code, code))
                    
                    last_order_time = RECENT_ORDER_CACHE.get(code, 0)
                    # [수정] 봇 매도 직후(10초)가 아니면 HTS 매도로 로그 출력
                    if time.time() - last_order_time > 10.0:
                        print(f"<font color='#ffc107'>🕵️ <b>[HTS매도/폴링]</b> {s_name} ({diff}주 판매 감지) [직접매매]</font>")
                        tel_send(f"🕵️ [HTS외부매도] {s_name} {diff}주 판매됨", msg_type='log')
                        # [v5.5] 수동 매도시에도 차트 P&L 강제 동기화 트리거
                        try:
                            from trade_logger import session_logger
                            session_logger.sync_required = True
                        except Exception as e:
                            print(f"⚠️ HTS 매도 동기화 요청 실패: {e}")
                            
                        # [HTS 수동매도는 시간 제한 없이 모두 로깅되도록 캐시 업데이트 제거]
                        # RECENT_ORDER_CACHE[code] = time.time()
        
        # [신규] 계좌 갱신 성공 로그 (최초 1회만)
        if ACCOUNT_CACHE['last_update'] == 0:
             print(f"✅ 계좌 정보 초기화 완료: 잔고 {ACCOUNT_CACHE['balance']:,}원, 보유 {len(new_holdings)}종목")
        
        ACCOUNT_CACHE['holdings'] = new_holdings
        ACCOUNT_CACHE['names'].update(names)
        ACCOUNT_CACHE['last_update'] = time.time()
        
        # print(f"\n💰 [계좌갱신] 잔고: {ACCOUNT_CACHE['balance']:,}원 | 보유: {len(new_holdings)}종목")
        
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



# [신규] 안전한 JSON 파일 입출력 헬퍼 (Atomic Write & Retry Read)
def load_json_safe(path, retries=5):
    """파일을 안전하게 읽어옵니다. (Race Condition 및 WinError 5 방지)"""
    for i in range(retries):
        try:
            with _FILE_LOCK: # 스레드 간 충돌 방지
                if not os.path.exists(path): return {}
                if os.path.getsize(path) == 0:
                    time.sleep(0.05 * (i + 1))
                    continue
                    
                with open(path, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except (json.JSONDecodeError, PermissionError, IOError) as e:
            if i < retries - 1:
                time.sleep(0.05 * (i + 1)) # 지수 백오프와 유사한 대기
                continue
    return {}

def save_json_safe(path, data, retries=5):
    """파일을 안전하게 저장합니다. (Temp 파일 + Atomic Rename + Retry)"""
    temp_path = None
    for i in range(retries):
        try:
            with _FILE_LOCK:
                dir_name = os.path.dirname(path)
                base_name = os.path.basename(path)
                timestamp = int(time.time()*1000)
                temp_path = os.path.join(dir_name, f".tmp_{base_name}_{timestamp}_{i}")
                
                # 1. 임시 파일 쓰기
                with open(temp_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                    f.flush()
                    os.fsync(f.fileno())
                
                # 2. 원자적 교체
                if os.path.exists(path):
                    # 윈도우에서 os.replace가 WinError 5를 낼 때를 대비한 내부 재시도
                    os.replace(temp_path, path)
                else:
                    os.rename(temp_path, path)
                return True # 성공 시 즉시 리턴
                
        except (PermissionError, IOError) as e:
            if i < retries - 1:
                time.sleep(0.1 * (i + 1))
                continue
            else:
                print(f"⚠️ [FileIO] 저장 최종 실패 ({path}): {e}")
        finally:
            # 임시 파일이 남아있다면 삭제 시도
            if temp_path and os.path.exists(temp_path):
                try: os.remove(temp_path)
                except: pass
    return False

# [v6.2.8 수정] 매수 시간 로컬 저장 함수 (overwrite 옵션 추가)
def save_buy_time(code, time_val=None, overwrite=False):
    try:
        if getattr(sys, 'frozen', False):
            base_path = os.path.dirname(sys.executable)
        else:
            base_path = os.path.dirname(os.path.abspath(__file__))
            
        json_path = os.path.join(base_path, 'daily_buy_times.json')
        data = load_json_safe(json_path)
            
        today_str = datetime.now().strftime("%Y%m%d")
        if data.get('last_update_date') != today_str:
            data = {'last_update_date': today_str}
            
        code = code.replace('A', '')
        old_data = data.get(code, {})
        if isinstance(old_data, str): old_data = {"time": old_data} # 하위 호환
        
        target_time = time_val if time_val else datetime.now().strftime("%H:%M:%S")
        
        # [v6.2.8 / v6.4.6] overwrite가 True거나, 기존 시간이 없으면 덮어씀
        if overwrite or not old_data.get('time') or old_data.get('time') == "99:99:99" or time_val:
            new_entry = {
                "time": target_time,
                "done": data.get(code, {}).get('done', False) if isinstance(data.get(code), dict) else False
            }
            # bultagi_done이 명시적으로 인자로 오지 않으므로, overwrite 시 상태 유지가 중요
            data[code] = new_entry
            save_json_safe(json_path, data)
            
    except Exception as e:
        print(f"⚠️ [DEBUG] 매수 시간 저장 실패: {e}")


# [신규] 로그를 예쁘게 출력하는 함수
# [Lite V1.0] 간결한 로그 시스템
def pretty_log(status_icon, status_msg, stock_name, code, is_error=False):
    display_name = stock_name[:7] + ".." if len(stock_name) > 8 else stock_name
    log_line = f"{status_icon} {status_msg:<6} │ {display_name}"
    if is_error: log_line += " ❌"
    print(log_line)

def chk_n_buy(stk_cd, token=None, seq=None, trade_price=None, seq_name=None, on_news_cb=None):
    stk_cd = stk_cd.replace('A', '') 
    
    # [Debug] 매수 진입로깅
    # print(f"🔍 [BUY_DEBUG] chk_n_buy 진입: {stk_cd}, seq={seq} (type={type(seq)})")

    # 0. 메모리 락 (동시 처리 방지)
    if stk_cd in PROCESSING_FLAGS:
        return
    PROCESSING_FLAGS.add(stk_cd)

    try:
        current_time = time.time()
        last_entry = RECENT_ORDER_CACHE.get(stk_cd, 0)

        RECENT_ORDER_CACHE[stk_cd] = current_time 
        token = token if token else get_token()

        max_stocks = cached_setting('max_stocks', 20) 
        # [수정] 재구매 쿨타임 단축 (10초 -> 5초) - 가속도 엔진과의 시너지 고려
        if current_time - last_entry < 5:
            s_name = get_stock_name_safe(stk_cd, token)
            # pretty_log("⏰", "시간제한", s_name, stk_cd) # [요청] 로그 삭제 (패스)
            return 

        # A. 보유 종목 확인 (캐시 기반)
        if stk_cd in ACCOUNT_CACHE['holdings']:
            s_name = get_stock_name_safe(stk_cd, token)
            # [신규 v6.9.5] 보유 중인데 VI 해제 신호가 왔다면 "VI 탈출 불타기"로 전환
            if seq == 'SYSTEM_VI':
                print(f"🔥 <font color='#f1c40f'><b>[Turbo VI]</b> {s_name} 보유 중 확인! 즉시 추가 매수(불타기) 시도...</font>")
                turbo_type = cached_setting('bultagi_turbo_vi_type', 'current')
                add_buy(stk_cd, token=token, seq_name='VI해제탈출', qty=1, source='VI_TURBO', price_type=turbo_type)
                return

            # [v6.4.5] 사용자 요청: 이미 보유 중인 종목은 매수 안 함 (투명성을 위한 디버그 로그)
            print(f"ℹ️ <font color='#888888'>[디버그] {s_name} 종목은 이미 보유 중이므로 매수 시퀀스를 건너뜁니다.</font>")
            return

        # [수정] A-2. 보유 종목 확인 (캐시 기반으로 충분, API 중복 호출 제거하여 속도 극대화)
        # 0.1초가 아쉬운 초단타를 위해 매수 직전 계좌 전체 조회 API는 생략함

        # B. 최대 종목 수 확인
        current_count = len(ACCOUNT_CACHE['holdings'])
        if current_count >= max_stocks:
            s_name = get_stock_name_safe(stk_cd, token)
            pretty_log("⛔", f"풀방({current_count})", s_name, stk_cd)
            return

        # C. 잔고 체크 (Safe Retry)
        if ACCOUNT_CACHE['balance'] < 1000:
            # [Fix] 잔고가 0원이거나 정보가 없을 수 있으므로 API로 한 번 더 확실하게 확인
            # print(f"⚠️ [잔고재확인] 캐시 잔고({ACCOUNT_CACHE['balance']}) 부족 -> API 재조회 시도")
            try:
                bal_data = get_balance(token=token, quiet=True)
                if bal_data and isinstance(bal_data, dict):
                    real_bal = int(str(bal_data.get('balance', '0')).replace(',', ''))
                    ACCOUNT_CACHE['balance'] = real_bal
                    ACCOUNT_CACHE['acnt_no'] = bal_data.get('acnt_no', '')
            except: pass

        if ACCOUNT_CACHE['balance'] < 1000: 
            s_name = get_stock_name_safe(stk_cd, token)
            pretty_log("💸", "잔고부족", s_name, stk_cd)
            # [Fix] 무한 재시도(로그 폭탄) 방지를 위해 10초 쿨타임 적용 (pop 제거)
            # RECENT_ORDER_CACHE.pop(stk_cd, None) 
            return

        # =========================================================
        # 3. 매수 주문 전송
        # =========================================================
        
        # [신규] 조건식별 개별 매수 전략 적용 (V3.8.1)
        try:
            # [신규 v6.9.5] Turbo VI 특별 예우
            if seq == 'SYSTEM_VI':
                mode = 'qty'
                val_str = '1' # 무조건 1주
                print(f"🚀 <font color='#00e5ff'><b>[Turbo Pass]</b> {stk_cd}: VI 해제 즉시 진입 모드 (1주)</font>")
            else:
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
            
        # [V2.0] 매수 방식 결정 (시장가 vs 현재가)
        if seq == 'SYSTEM_VI':
             p_type = cached_setting('bultagi_turbo_vi_type', 'current')
        else:
             price_types = cached_setting('strategy_price_types', {})
             p_type = price_types.get(mode, 'market')
        
        trde_tp = '3' # 기본: 시장가
        ord_uv = '0'  # 시장가는 가격 0
        
        # 가격 확인 (실시간 -> API)
        current_price = 0
        if trade_price:
            current_price = int(trade_price)
        
        if current_price == 0:
            try:
                _, current_price = get_current_price(stk_cd, token=token)
            except: pass
            
        if p_type == 'current' and current_price > 0:
            trde_tp = '0' # 지정가
            ord_uv = str(current_price)
            # pretty_log("📍", "현재가", f"{current_price:,}원", stk_cd)

        try:
            if mode == 'qty':
                # 고정 수량
                qty = int(val_str.replace(',', ''))
            
            elif mode in ['amount', 'percent']:
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

        # [v4.8] 비동기 세마포어 적용 (주문 폭주 방지)
        # 만약 비동기 루프 밖이면 일반 실행
        result = buy_stock(stk_cd, qty, ord_uv, trde_tp=trde_tp, token=token)
        
        # [추가] 매수 성공 시 세션 로그에 기록하기 위해 가격 정보 준비
        final_price = current_price
        
        if isinstance(result, tuple) or isinstance(result, list):
            ret_code = result[0]
            ret_msg = result[1] if len(result) > 1 else ""
        else:
            ret_code = result
            ret_msg = ""

        is_success = str(ret_code) == '0' or ret_code == 0
        
        if is_success:
            # [수정] set.add -> dict 갱신
            current_qty = ACCOUNT_CACHE['holdings'].get(stk_cd, 0)
            ACCOUNT_CACHE['holdings'][stk_cd] = current_qty + qty
            
            # [신규] 중복 로그 방지를 위해 주문 캐시 즉시 업데이트 (rt_search 필터링용)
            RECENT_ORDER_CACHE[stk_cd] = time.time()
            
            s_name = get_stock_name_safe(stk_cd, token)
            
            # 세션 매수 기록
            session_logger.record_buy(stk_cd, s_name, qty, final_price, strat_mode=mode, seq=seq)
            
            # [수정] 비동기 처리: 종목별 검색 조건명 및 전략 저장
            if seq_name:
                task_data = {
                    'code': stk_cd,
                    'name': seq_name,
                    'mode': mode,
                    'seq': seq # [신규] 시퀀스 정보 전달
                }
                _LOG_QUEUE.put(('save_mapping', task_data))
            
            # [신규 v6.0.5] 마킹된 조건식인 경우 매수 성공 시 뉴스 스나이퍼 즉시 출동
            marked_conditions = get_setting('marked_conditions', [])
            # [수정] seq(검출된 번호)가 마킹된 리스트에 있는지 정확히 체크 (문자열/숫자 호환성 고려)
            if str(seq) in map(str, marked_conditions):
                from news_sniper import run_news_sniper
                
                def news_trigger_task(nm, cb):
                    try:
                        # [주의] news_sniper 내부에서 중복 팝업 방지 로직이 동작함
                        result = run_news_sniper(nm)
                        if result and cb:
                            cb(result)
                    except Exception as e:
                        print(f"⚠️ [뉴스트리거] 실패: {e}")

                # 비동기로 뉴스 검색 및 분석 수행 (워커 스레드 활용)
                threading.Thread(target=news_trigger_task, args=(s_name, on_news_cb), daemon=True).start()
            else:
                # [디버그] 마킹되지 않은 경우 조용히 넘어감
                # print(f"ℹ️ [뉴스패스] {s_name} (조건 {seq}번 마킹 안됨)")
                pass

            # [v6.2.8] 비동기 처리: 매수 시간 저장 (재매수 대응 overwrite=True)
            _LOG_QUEUE.put(('save_buy_time', {'code': stk_cd, 'overwrite': True}))

            # [신규] 전략별 색상 결정
            color_map = {'qty': '#dc3545', 'amount': '#28a745', 'percent': '#007bff'}
            log_color = color_map.get(mode, '#00ff00')
            
            # [Lite V1.0] 다이어트 로그 (한 줄 요약 적용) - 음수 가격 방지(abs)
            log_msg = f"<font color='{log_color}'>⚡<b>[매수체결]</b> {s_name} ({abs(final_price):,}원/{qty}주)"
            if seq_name: log_msg += f" <b>[{seq}. {seq_name}]</b>"
            log_msg += "</font>"
            print(log_msg)
            
            # [신규] 텔레그램 전송 추가
            tel_send(f"✅ [매수체결] {s_name} {qty}주 ({final_price:,}원)", msg_type='log')

            # [신규] 전략별 음성 안내 추가 (조건식 이름 포함)
            # [수정] voice_guidance 설정값 확인 (기본값 True)
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
            # [사용자 요청] 매수증거금 부족 시 종목명 포함 커스텀 로그
            if "매수증거금이 부족합니다" in ret_msg:
                print(f"<font color='#e91e63'>❌ <b>[{s_name}]</b> 매수증거금이 부족합니다.</font>")
            else:
                # 그 외 에러는 상세 내용 표시
                print(f"❌ 매수 실패 [{s_name}]: [{ret_code}] {ret_msg}")
                
            # [Fix] 수동 매수 등의 재시도를 위해 실패 시 주문 캐시에서 제거
            RECENT_ORDER_CACHE.pop(stk_cd, None)
            
    except Exception as e:
        s_name = get_stock_name_safe(stk_cd, token)
        pretty_log("⚠️", "로직에러", s_name, stk_cd, is_error=True)
        print(f"   ㄴ 내용: {e}")
        RECENT_ORDER_CACHE.pop(stk_cd, None)
    finally:
        # [신규] 락 해제 (필수)
        if stk_cd in PROCESSING_FLAGS:
            PROCESSING_FLAGS.remove(stk_cd)

def add_buy(stk_cd, token=None, seq_name=None, qty=1, source='ACCEL', price_type='market'):
    """[수정 v4.5.1] 가속도 또는 불타기 조건 만족 시 시장가/현재가 추가 매수"""
    stk_cd = stk_cd.replace('A', '')

    # 0. 메모리 락
    if stk_cd in PROCESSING_FLAGS:
        return False
    PROCESSING_FLAGS.add(stk_cd)

    try:
        current_time = time.time()
        last_entry = RECENT_ORDER_CACHE.get(stk_cd, 0)
        
        # [Fix] 불타기(BULTAGI) 진입 시에는 check_n_sell 에서 이미 대기 시간을 체크했으므로 
        # add_buy 자체의 5초 쿨타임을 무조건 무시(프리패스) 해야 함.
        # [신규 v6.9.5] VI_TURBO 진입 시에도 쿨타임 무시
        # 중복 주문 방지 캐시 업데이트도 BULTAGI인 경우에만 제한 시간 우회
        if source not in ['BULTAGI', 'VI_TURBO'] and (current_time - last_entry < 5):
            return False

        RECENT_ORDER_CACHE[stk_cd] = current_time
        token = token if token else get_token()

        # 잔고 부족 시 스킵
        if ACCOUNT_CACHE['balance'] < 1000:
            return False

        # [필수] 추가 매수(불타기)이므로 보유 중인 종목인 경우에만 진행 (0->1은 chk_n_buy가 담당)
        current_holdings = ACCOUNT_CACHE['holdings'].get(stk_cd, 0)
        if current_holdings <= 0:
            # [Fix] 캐시 지연 방어: chk_n_sell에서 호출되었다면 보유 중일 확률이 매우 높으므로 로그만 남기고 일단 진행
            if source == 'BULTAGI':
                print(f"ℹ️ [BULTAGI] 캐시상 보유 수량 0주이나 '정찰병' 확인되어 불타기 매수 시도. (캐시지연 방어)")
            else:
                return False

        # [수정] 주문 방식 처리 (시장가/현재가)
        trde_tp = '3' # 기본: 시장가
        ord_uv = '0'
        
        # 가격 정보 획득 (로깅 및 현재가 주문용)
        _, final_price = get_current_price(stk_cd, token=token)

        if price_type == 'current' and final_price > 0:
            trde_tp = '0' # 지정가
            ord_uv = str(final_price)

        result = buy_stock(stk_cd, qty, ord_uv, trde_tp=trde_tp, token=token)
        
        is_success = False
        if isinstance(result, (tuple, list)):
            is_success = str(result[0]) == '0'
        else:
            is_success = str(result) == '0'

        if is_success:
            # 계좌 캐시 업데이트
            current_qty = ACCOUNT_CACHE['holdings'].get(stk_cd, 0)
            ACCOUNT_CACHE['holdings'][stk_cd] = current_qty + qty
            
            s_name = get_stock_name_safe(stk_cd, token)
            
            # 세션 매수 기록 (strat_mode='ACCEL'로 구분)
            session_logger.record_buy(stk_cd, s_name, qty, final_price, strat_mode='ACCEL')
            
            # [v6.2.8] 매수 시간 및 정보 저장 (재매수 대응 overwrite=True)
            _LOG_QUEUE.put(('save_buy_time', {'code': stk_cd, 'overwrite': True}))
            
            # 알림 및 로그
            if source == 'BULTAGI':
                log_msg = f"<font color='#f39c12'>🔥<b>[불타기 성공]</b> {s_name} ({final_price:,}원/{qty}주)</font>"
                tel_msg = f"🔥 [불타기 완료] {s_name} {qty}주 추가 체결!"
                voice_msg = f"{s_name} 불타기"
            else:
                log_msg = f"<font color='#ff00ff'>🔥<b>[추가매수 성공]</b> {s_name} ({final_price:,}원/{qty}주) [수급폭발]</font>"
                tel_msg = f"🔥 [추가매수 완료] {s_name} {qty}주 추가 체결! (수급폭발)"
                voice_msg = f"{s_name} 추가매수"
            
            print(log_msg)
            tel_send(tel_msg, msg_type='log')
            say_text(voice_msg) # 음성 알림
            
        return is_success

    except Exception as e:
        print(f"⚠️ [add_buy] 추가 매수 오류: {e}")
        return False
    finally:
        PROCESSING_FLAGS.discard(stk_cd)

# [신규] 조건식 매핑 업데이트 (HTS 매매 등 외부 요인)
def update_stock_condition(code, name='직접매매', strat='qty', time_val=None, seq=None, bultagi_done=None):
    try:
        if getattr(sys, 'frozen', False):
            base_path = os.path.dirname(sys.executable)
        else:
            base_path = os.path.dirname(os.path.abspath(__file__))
            
        mapping_file = os.path.join(base_path, 'stock_conditions.json')
        mapping = load_json_safe(mapping_file)
        
        # [V6.0.6] 기존 데이터 완전 보존형 업데이트 (peak_pl_rt 등 유실 방지)
        existing_info = mapping.get(code, {})
        
        # 기본 설정 로드
        default_tp = get_setting('take_profit_rate', 10.0)
        default_sl = get_setting('stop_loss_rate', -10.0)
        
        # 전략별 설정 로드
        st_data = get_setting('strategy_tp_sl', {})
        specific_setting = st_data.get(strat, {})
        
        spec_tp = float(specific_setting.get('tp', default_tp))
        spec_sl = float(specific_setting.get('sl', default_sl))

        if spec_tp == 0: spec_tp = 12.0
        if spec_sl == 0: spec_sl = -1.5
        
        # 새 데이터 구성 (기존 데이터 위에 덮어쓰기)
        new_info = existing_info.copy()
        
        # [Fix v6.1.12 / v6.4.5] HTS(직접매매) 또는 신규 진입 시 과거 기록 초기화
        # 단, 이미 불타기가 완료된 경우(bultagi_done)는 HTS 감지 시에도 상태 유지 (중복 불타기 방지)
        if strat == 'HTS' or not existing_info:
            if not existing_info.get('bultagi_done'):
                new_info['bultagi_done'] = False
            new_info['peak_pl_rt'] = 0.0
            # [신규] 매수 시간도 현재 시간으로 갱신 (경과 시간 계산용)
            if not time_val:
                time_val = datetime.now().strftime("%H:%M:%S")

        new_info.update({
            'name': name,
            'strat': strat,
            'seq': seq if seq is not None else existing_info.get('seq'),
            'tp': spec_tp, 
            'sl': spec_sl,
            'time': time_val if time_val else (existing_info.get('time') or datetime.now().strftime("%H:%M:%S"))
        })
        
        # 불타기 완료 명시적 설정
        if bultagi_done is not None:
            new_info['bultagi_done'] = bultagi_done
            # [신규 v6.4.6] 백업 파일에도 완료 상태 동기화 (재매수 절대 차단)
            try:
                buy_times_file = os.path.join(base_path, 'daily_buy_times.json')
                bt_data = load_json_safe(buy_times_file)
                if code in bt_data:
                    if isinstance(bt_data[code], str): bt_data[code] = {"time": bt_data[code]}
                    bt_data[code]['done'] = bultagi_done
                    save_json_safe(buy_times_file, bt_data)
            except: pass
            
        mapping[code] = new_info
        save_json_safe(mapping_file, mapping)
        
    except Exception as e:
        print(f"⚠️ 매핑 업데이트 실패: {e}")

# [신규] 특정 종목의 최고 수익률(Peak)만 원자적으로 업데이트 (데이터 유실 방지)
def update_stock_peak_rt(code, peak_rt):
    try:
        if getattr(sys, 'frozen', False):
            base_path = os.path.dirname(sys.executable)
        else:
            base_path = os.path.dirname(os.path.abspath(__file__))
            
        mapping_file = os.path.join(base_path, 'stock_conditions.json')
        
        # 1. 파일에서 최신 데이터 읽기
        mapping = load_json_safe(mapping_file)
        
        # 2. 값 수정 (종목이 있을 때만)
        if code in mapping:
            mapping[code]['peak_pl_rt'] = peak_rt
            # 3. 다시 저장
            save_json_safe(mapping_file, mapping)
            
    except Exception as e:
        print(f"⚠️ Peak RT 업데이트 실패: {e}")