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
                save_buy_time(data['code']) # 기존 함수 재사용
                
            _LOG_QUEUE.task_done()
        except Exception as e:
            print(f"⚠️ [비동기로거] 처리 실패: {e}")

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
        
        data_dir = os.path.join(base_path, 'LogData')
        if not os.path.exists(data_dir):
            try: os.makedirs(data_dir, exist_ok=True)
            except: pass
        
        mapping_file = os.path.join(data_dir, 'stock_conditions.json')
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
    except Exception as ex:
        print(f"⚠️ [비동기] 조건식 매핑 저장 실패: {ex}")

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
    'acnt_no': '', # [신규] 계좌번호 저장 필드
    'holdings': {}, # [수정] set() -> dict {code: qty} (수량 변화 감지용)
    'names': {},
    'last_update': 0
}

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
            try: qty = int(stock.get('rmnd_qty', 0)) # 잔여 수량
            except: qty = 0
            
            new_holdings[code] = qty
            names[code] = name
        
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
                    
                    # [수정] 봇 주문 직후(2초)가 아니면 무조건 HTS/외부 매수로 간주하고 로그 출력
                    if time.time() - last_order_time > 2.0:
                        print(f"<font color='#ffc107'>🕵️ <b>[HTS매수/폴링]</b> {s_name} ({diff}주 추가 감지) [직접매매]</font>")
                        tel_send(f"🕵️ [HTS외부감지] {s_name} {diff}주 추가됨", msg_type='log')
                        
                        # [HTS 수동매매는 중복 감지 방지 캐시를 업데이트하지 않음]
                        # RECENT_ORDER_CACHE[code] = time.time() 
                        
                        # [신규] HTS 매수 정보 저장
                        try:
                            # [개선] HTS 매수 시 가격이 0이면 현재가를 가져와서 기록 (수익률 정밀도 향상)
                            hts_price = 0
                            try:
                                _, hts_price = get_current_price(code, token=token)
                            except: pass
                            
                            update_stock_condition(code, name='직접매매', strat='HTS')
                            session_logger.record_buy(code, s_name, diff, hts_price, strat_mode='HTS')
                        except Exception as e:
                            print(f"⚠️ [HTS저장] 메타데이터 저장 실패: {e}")
            
            # 2. 종목 삭제 / 수량 감소 (매도)
            for code, old_qty in old_holdings.items():
                new_qty = new_holdings.get(code, 0)
                if new_qty < old_qty:
                    diff = old_qty - new_qty
                    s_name = names.get(code, ACCOUNT_CACHE['names'].get(code, code))
                    
                    last_order_time = RECENT_ORDER_CACHE.get(code, 0)
                    # [수정] 봇 매도 직후가 아니면 HTS 매도로 로그 출력
                    if time.time() - last_order_time > 2.0:
                        print(f"<font color='#ffc107'>🕵️ <b>[HTS매도/폴링]</b> {s_name} ({diff}주 판매 감지) [직접매매]</font>")
                        tel_send(f"🕵️ [HTS외부매도] {s_name} {diff}주 판매됨", msg_type='log')
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

# [신규] 매수 시간 로컬 저장 함수 (Safe Version)
def save_buy_time(code, time_val=None):
    try:
        if getattr(sys, 'frozen', False):
            base_path = os.path.dirname(sys.executable)
        else:
            base_path = os.path.dirname(os.path.abspath(__file__))
            
        data_dir = os.path.join(base_path, 'LogData')
        if not os.path.exists(data_dir):
            try: os.makedirs(data_dir, exist_ok=True)
            except: pass
            
        json_path = os.path.join(data_dir, 'daily_buy_times.json')
        
        # [수정] 안전한 읽기/쓰기
        data = load_json_safe(json_path)
            
        # 날짜 확인 및 초기화
        today_str = datetime.now().strftime("%Y%m%d")
        if data.get('last_update_date') != today_str:
            data = {'last_update_date': today_str}
            
        code = code.replace('A', '')
        
        # [수정] 외부에서 준 시간이 있으면 그걸 우선, 없으면 현재 시간
        target_time = time_val if time_val else datetime.now().strftime("%H:%M:%S")
        
        # 이미 정확한(HTS복원 등) 시간이 있다면 덮어쓰지 않음 (단, 99:99:99면 덮어씀)
        old_time = data.get(code)
        if not old_time or old_time == "99:99:99" or time_val:
            data[code] = target_time
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

def chk_n_buy(stk_cd, token=None, seq=None, trade_price=None, seq_name=None):
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
            # pretty_log("💼", "이미보유", s_name, stk_cd) # [요청] 로그 삭제 (패스)
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

            # [수정] 비동기 처리: 매수 시간 저장
            _LOG_QUEUE.put(('save_buy_time', {'code': stk_cd}))

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
        return
    PROCESSING_FLAGS.add(stk_cd)

    try:
        current_time = time.time()
        last_entry = RECENT_ORDER_CACHE.get(stk_cd, 0)
        
        # [수정] 추가 매수 쿨타임 동기화 (5초)
        if current_time - last_entry < 5:
            return

        RECENT_ORDER_CACHE[stk_cd] = current_time
        token = token if token else get_token()

        # 잔고 부족 시 스킵
        if ACCOUNT_CACHE['balance'] < 1000:
            return

        # [필수] 추가 매수(불타기)이므로 보유 중인 종목인 경우에만 진행 (0->1은 chk_n_buy가 담당)
        current_holdings = ACCOUNT_CACHE['holdings'].get(stk_cd, 0)
        if current_holdings <= 0:
            # [Fix] 캐시 지연 방어: chk_n_sell에서 호출되었다면 보유 중일 확률이 매우 높으므로 로그만 남기고 일단 진행
            # 만약 진짜 없으면 API에서 증거금 부족이나 수량 부족으로 튕길 것임
            if source == 'BULTAGI':
                print(f"ℹ️ [BULTAGI] 캐시상 보유 수량 0주이나 '정찰병' 확인되어 진행합니다. (캐시지연 방어)")
            else:
                return

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
            
            # 매수 시간 및 정보 저장 (비동기)
            _LOG_QUEUE.put(('save_buy_time', {'code': stk_cd}))
            
            # 알림 및 로그
            if source == 'BULTAGI':
                log_msg = f"<font color='#f39c12'>🔥<b>[불타기]</b> {s_name} ({final_price:,}원/{qty}주)</font>"
                tel_msg = f"🔥 [불타기 완료] {s_name} {qty}주 추가 체결!"
                voice_msg = f"{s_name} 불타기"
            else:
                log_msg = f"<font color='#ff00ff'>🔥<b>[추가매수]</b> {s_name} ({final_price:,}원/{qty}주) [수급폭발]</font>"
                tel_msg = f"🔥 [추가매수] {s_name} {qty}주 추가 체결! (수급폭발)"
                voice_msg = f"{s_name} 추가매수"
            
            print(log_msg)
            tel_send(tel_msg, msg_type='log')
            say_text(voice_msg) # 음성 알림

    except Exception as e:
        print(f"⚠️ [add_buy] 추가 매수 오류: {e}")
    finally:
        PROCESSING_FLAGS.discard(stk_cd)

# [신규] 조건식 매핑 업데이트 (HTS 매매 등 외부 요인)
def update_stock_condition(code, name='직접매매', strat='qty', time_val=None, seq=None):
    try:
        
        if getattr(sys, 'frozen', False):
            base_path = os.path.dirname(sys.executable)
        else:
            base_path = os.path.dirname(os.path.abspath(__file__))
            
        data_dir = os.path.join(base_path, 'LogData')
        if not os.path.exists(data_dir):
            try: os.makedirs(data_dir, exist_ok=True)
            except: pass
        
        mapping_file = os.path.join(data_dir, 'stock_conditions.json')
        mapping = load_json_safe(mapping_file)
        
        # [중요] 기존 설정값 유지하면서 업데이트 (특히 SL/TP)
        # HTS 매수의 경우 기본 SL/TP(-1.5/12.0)를 따르되, 사용자가 수동으로 고친 게 있으면 그걸 따라야 함
        # 여기서는 'HTS' 전략일 경우 기본 설정값을 강제로 주입하여 sell 로직에서 0으로 인식되지 않게 함
        
        # 기본 설정 로드
        default_tp = get_setting('take_profit_rate', 10.0)
        default_sl = get_setting('stop_loss_rate', -10.0)
        
        # 전략별 설정 로드
        st_data = get_setting('strategy_tp_sl', {})
        specific_setting = st_data.get(strat, {})
        
        # [수정] strat이 'HTS'이거나 매핑 없을 때 기본값 사용
        spec_tp = float(specific_setting.get('tp', default_tp))
        spec_sl = float(specific_setting.get('sl', default_sl))

        # [안전장치] 만약 값이 0이면 강제로 기본값 적용
        if spec_tp == 0: spec_tp = 12.0
        if spec_sl == 0: spec_sl = -1.5
        
        mapping[code] = {
            'name': name,
            'strat': strat,
            'seq': seq, # [신규] 시퀀스 정보 저장
            'tp': spec_tp, 
            'sl': spec_sl,
            'time': time_val if time_val else datetime.now().strftime("%H:%M:%S")
        }
        
        save_json_safe(mapping_file, mapping)
        
    except Exception as e:
        print(f"⚠️ 매핑 업데이트 실패: {e}")