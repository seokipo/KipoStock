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
from get_setting import cached_setting, get_base_path
from login import fn_au10001 as get_token, safe_float, safe_int
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
        
        # [v2.4.6] 경로 로직 통합 (get_base_path 사용)
        base_path = get_base_path()
        
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

# [v3.3.8] 거래대금 상위 종목 캐시 (rt_search.py에서 주기적으로 업데이트함)
TOP_VOLUME_RANK_CACHE = [] # [V4.0.0] 순위 유지를 위해 list로 변경

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
# [v4.4.0] 전역 지수 상태 캐시 (AsyncWorker에서 주기적으로 업데이트)
GLOBAL_MARKET_STATUS = {
    'KOSPI': {'rate': 0.0, 'price': 0.0},
    'KOSDAQ': {'rate': 0.0, 'price': 0.0},
    'last_update': None
}

# [v5.1.33] 전역 VI 상태 캐시 (rt_search.py에서 실시간 업데이트)
# '1': 발동, '2': 해제, '3': 중지, '4': 재개
GLOBAL_VI_CACHE = {}

def update_vi_cache(stk_cd, vi_status):
    """실시간 수신된 VI 상태를 캐시에 업데이트합니다."""
    try:
        stk_cd = stk_cd.replace('A', '')
        GLOBAL_VI_CACHE[stk_cd] = str(vi_status)
    except: pass

def is_market_index_ok():
    """[v4.4.0] 지수 급락 자동 매매 정지 설정 및 현재 지수 상태를 비교하여 매매 가능 여부 반환"""
    try:
        # [v4.4.0] 지수 급락 정지 설정 로드
        enabled = get_setting('global_idx_stop_enabled', False)
        if not enabled: return True, ""
        
        kospi_thresh = safe_float(get_setting('kospi_stop_threshold', '-2.0'), -2.0)
        kosdaq_thresh = safe_float(get_setting('kosdaq_stop_threshold', '-3.0'), -3.0)
        
        # [v5.0.3] 구조적 안정성 확보: KOSPI/KOSDAQ 키 내부의 rate 참조
        kospi_obj = GLOBAL_MARKET_STATUS.get('KOSPI', {})
        kosdaq_obj = GLOBAL_MARKET_STATUS.get('KOSDAQ', {})
        
        cur_kospi_rate = safe_float(kospi_obj.get('rate', 0.0), 0.0)
        cur_kosdaq_rate = safe_float(kosdaq_obj.get('rate', 0.0), 0.0)
        
        # 만약 명시적 'KOSPI' 키가 비어있다면 평면(Flat) 구조('kospi_rate')까지 추가로 확인 (더블 체크)
        if cur_kospi_rate == 0.0:
            cur_kospi_rate = safe_float(GLOBAL_MARKET_STATUS.get('kospi_rate', 0.0), 0.0)
        if cur_kosdaq_rate == 0.0:
            cur_kosdaq_rate = safe_float(GLOBAL_MARKET_STATUS.get('kosdaq_rate', 0.0), 0.0)

        # [v1.1.7] 장 초반(09:00~09:01) 지수 데이터가 아직 0.0일 경우 매수 차단 방지 (Safe Pass)
        now_dt = datetime.now()
        if now_dt.hour == 9 and now_dt.minute <= 1:
            if cur_kospi_rate == 0.0 and cur_kosdaq_rate == 0.0:
                return True, ""

        # 임계값보다 지수가 더 낮으면 (더 많이 떨어졌으면) 정지
        if cur_kospi_rate <= kospi_thresh:
            return False, f"KOSPI {cur_kospi_rate}% (임계값: {kospi_thresh}%)"
        if cur_kosdaq_rate <= kosdaq_thresh:
            return False, f"KOSDAQ {cur_kosdaq_rate}% (임계값: {kosdaq_thresh}%)"
            
        return True, ""
    except Exception as e:
        if time.time() % 60 < 1.0: # 로그 폭발 방지
             print(f"⚠️ [지수체크] 오류 발생 (매매 허용): {e}")
        return True, ""

# 계좌 캐시 테이블 (불타기/매도 시 활용)
account_cache = {} 

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
        # [v5.0.2] 8005 에러 감지 시 강제 재로그인 후 재시도 (Auto-Auth Recovery)
        if isinstance(balance_data, dict) and balance_data.get('error_code') == '8005':
            print("🔄 [check_n_buy] 잔고조회 8005 감지 → 토큰 강제 갱신 후 재시도 중...")
            token = get_token(force=True)
            balance_data = get_balance(token=token, quiet=True)
        if balance_data and isinstance(balance_data, dict) and 'error_code' not in balance_data:
            ACCOUNT_CACHE['balance'] = int(str(balance_data.get('balance', '0')).replace(',', ''))
            ACCOUNT_CACHE['acnt_no'] = balance_data.get('acnt_no', '')
        
        # [수정] 수량까지 포함하여 비교 (DICT 형태)
        old_holdings = ACCOUNT_CACHE['holdings'].copy()
        new_holdings = {}
        realtime_holdings = {} # [신규]
        names = {}
        
        my_stocks_data = get_my_stocks(token=token)
        # [v5.0.2] 8005 에러 감지 시 강제 재로그인 후 재시도 (Auto-Auth Recovery)
        if isinstance(my_stocks_data, dict) and my_stocks_data.get('error_code') == '8005':
            print("🔄 [check_n_buy] 계좌조회 8005 감지 → 토큰 강제 갱신 후 재시도 중...")
            token = get_token(force=True)
            my_stocks_data = get_my_stocks(token=token)
        if my_stocks_data is None:
            # [Fix v3.0.3] API 통신 실패 및 토큰 만료 시 기존 데이터를 날리지 않고 유지하여 UI 증발 방지
            # [v3.0.4] 혹시 모를 토큰 만료 대응: 즉시 1회 자동 토큰 갱신 시도
            print("⚠️ [계좌갱신] API 응답 에러 (데이터 유지 및 토큰 갱신 시도...)")
            new_token = get_token(force=True) # 강제 재발급
            if new_token:
                # 갱신 성공 시 바로 1회 재시도
                my_stocks_data = get_my_stocks(token=new_token)
                if my_stocks_data:
                    token = new_token
                else: 
                    time.sleep(0.5)
                    return token
            else: 
                time.sleep(0.5)
                return token

        my_stocks = []
        if isinstance(my_stocks_data, dict):
            # [v3.0.3] 만약 에러 응답(stocks가 없는 경우)이면 업데이트 스킵
            if 'stocks' not in my_stocks_data:
                return
            my_stocks = my_stocks_data.get('stocks', [])
            # [신규] 계좌번호 확보 (예수금 조회 실패 대비)
            if not ACCOUNT_CACHE['acnt_no']:
                ACCOUNT_CACHE['acnt_no'] = my_stocks_data.get('acnt_no', '')
        elif isinstance(my_stocks_data, list):
            my_stocks = my_stocks_data
            
        for stock in my_stocks:
            code = stock['stk_cd'].replace('A', '')
            name = stock['stk_nm']
            qty = safe_int(stock.get('hldg_qty', stock.get('rmnd_qty', 0))) # [v6.1.12 수정] 필드명 유연성 확보
            
            new_holdings[code] = qty
            names[code] = name

            # [v6.1.12 수정] 실제 API 필드명에 맞춰 정밀 매핑 (0패딩 문자열 대응)
            try:
                realtime_holdings[code] = {
                    'name': name,
                    'buy_price': safe_float(stock.get('avg_prc')),
                    'cur_price': safe_float(stock.get('cur_prc')),
                    'pl_rt': safe_float(stock.get('pl_rt')),
                    'qty': safe_int(stock.get('rmnd_qty')),
                    'pnl': safe_int(stock.get('pl_amt'))
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
                            # [v5.0.7] HTS 매수 시 불타기 보드 즉시 노출을 위해 bultagi_done=True 추가
                            update_stock_condition(code, name='직접매매', strat='HTS', bultagi_done=True)
                            session_logger.record_buy(code, s_name, diff, hts_price, strat_mode='HTS')
                        except Exception as e:
                            print(f"⚠️ [HTS저장] 메타데이터 저장 실패: {e}")

                # [v6.2.8 / v5.0.6] 매핑 누락 자동 복구 로직
                # stock_conditions.json(mapping)에 없지만 보유 중인 종목을 daily_buy_times.json 기반으로 구제
                try:
                    base_path = get_base_path()
                    mapping_file = os.path.join(base_path, 'stock_conditions.json')
                    buy_times_file = os.path.join(base_path, 'daily_buy_times.json')
                    
                    current_mapping = load_json_safe(mapping_file)
                    if code not in current_mapping:
                        # 1단계: 오늘 매수한 이력이 있는지 체크
                        bt_data = load_json_safe(buy_times_file)
                        if code in bt_data:
                            b_entry = bt_data[code]
                            b_time = b_entry.get('time') if isinstance(b_entry, dict) else b_entry
                            if b_time and b_time != "99:99:99":
                                print(f"🛠️ [매핑복구] {names.get(code, code)} ({code}): 매핑 누수 감지 -> {b_time} 기반 자동 복구")
                                # [v5.0.7] 복구 시에도 불타기 보드 노출을 위해 bultagi_done=True 추가
                                update_stock_condition(code, name=names.get(code, 'HTS매매'), strat='HTS', time_val=b_time, bultagi_done=True)
                        
                        # [신규 v5.0.6] 2단계: 어제 종가 베팅 종목인지 DB에서 확인 (전략 보존)
                        else:
                            from kipodb import kipo_db
                            last_trade = kipo_db.get_last_trade_by_code(code)
                            if last_trade and last_trade.get('strat_mode') == 'CLOSING_BET':
                                print(f"🌙 [전략복구] {names.get(code, code)} ({code}): 종가 베팅 전략 복원 완료")
                                # [v5.0.7] 종가베팅 복원 시 불타기 보드 노출을 위해 bultagi_done=True 추가
                                update_stock_condition(code, name=names.get(code, '종가베팅'), strat='CLOSING_BET', time_val='[전일]', bultagi_done=True)
                            
                            # [신규 v5.0.7] 3단계: 최종적으로 아무 정보도 없으면 무조건 HTS로 등록하여 '매수 전략' -- 방지 및 불타기 보드 강제 이동
                            else:
                                print(f"🕵️ [최종구제] {names.get(code, code)} ({code}): 정보 없음 -> HTS 전략 강제 할당 (불타기 보드 이동)")
                                update_stock_condition(code, name=names.get(code, 'HTS매매'), strat='HTS', time_val='[미상]', bultagi_done=True)
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
        
        return token # [v3.0.4] 최신 토큰 반환
        
    except Exception as e:
        print(f"⚠️ 계좌 정보 갱신 실패: {e}")
        return token

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

def chk_n_buy(stk_cd, token=None, seq=None, trade_price=None, seq_name=None, on_news_cb=None, vi_type=None):
    # [V5.1.6 2중 철벽 방어] 현재 비활성화된 조건식(유령) 신호는 즉시 차단 🚫
    if seq and str(seq).isdigit():
        active_seqs = cached_setting('search_seq', [])
        if isinstance(active_seqs, str): active_seqs = [active_seqs]
        if str(seq) not in map(str, active_seqs):
            # print(f"👻 [유령차단-2] 비활성 조건식({seq}: {seq_name}) 매수 요청 거부됨")
            return
            
    stk_cd = stk_cd.replace('A', '') 
    
    # [v4.4.0] 지수 급락 자동 매매 정지 체크 (Global Stop)
    is_ok, reason = is_market_index_ok()
    if not is_ok:
        s_name = get_stock_name_safe(stk_cd, token if token else get_token())
        # [V5.1.17] 지수 수치 포함 상세 진단 로그 (Detailed Log)
        print(f"DEBUG_HTML_LOG: <font color='#ff6b6b'>[Market-STOP] {s_name}({stk_cd}) 차단 사유: {reason}</font>")
        print(f"🛡️ <font color='#ff6b6b'><b>[지수급락 정지]</b> {s_name}({stk_cd}) 매수 차단 ({reason})</font>")
        return

    # [v5.1.33] VI 발동 중 매수 금지 체크 (Global Filter)
    # Turbo VI(SYSTEM_VI)는 해제 시점에 들어가는 로직이므로 제외
    if seq != 'SYSTEM_VI' and get_setting('block_buy_during_vi', False):
        vi_status = GLOBAL_VI_CACHE.get(stk_cd)
        if vi_status == '1': # '1'은 VI 발동(Active) 상태
            s_name = get_stock_name_safe(stk_cd, token if token else get_token())
            print(f"🛡️ <font color='#ff6b6b'><b>[VI차단]</b> {s_name}({stk_cd}) 현재 VI 발동 중으로 매수 차단됨</font>")
            return

    # 0. 메모리 락 (동시 처리 방지)
    if stk_cd in PROCESSING_FLAGS:
        # [v1.5.7] VI 해제는 긴급 상황이므로 이미 처리 중이더라도 비동기 예약 로직을 통해 재시도 가능하도록 고려
        if seq == 'SYSTEM_VI':
            print(f"📡 <font color='#f1c40f'><b>[Turbo VI 긴급]</b> {stk_cd} 이미 처리 중이나 VI 해제 신호로 재진입 시도...</font>")
        else:
            if not cached_setting('simple_log', False):
                print(f"⚠️ [차단] 이미 처리 중인 종목: {stk_cd}")
            return
    PROCESSING_FLAGS.add(stk_cd)

    try:
        current_time = time.time()
        last_entry = RECENT_ORDER_CACHE.get(stk_cd, 0)

        token = token if token else get_token()

        max_stocks = cached_setting('max_stocks', 20) 
        # [신규 v2.0.0] Turbo VI (SYSTEM_VI) 정밀 필터링 로직
        if seq == 'SYSTEM_VI':
            s_name = get_stock_name_safe(stk_cd, token)
            
            # [V3.3.8 / V5.1.17 고도화] 0단계: 거래대금 상위 필터링
            if cached_setting('bultagi_turbo_vi_volume_enabled', False):
                if TOP_VOLUME_RANK_CACHE and stk_cd not in TOP_VOLUME_RANK_CACHE:
                    msg = f"📡 <font color='#888888'>[Turbo 스킵] {s_name}({stk_cd}) 거래대금 순위 밖 스킵</font>"
                    print(msg)
                    # [V5.1.17] 상세 로그 라우팅
                    print(f"DEBUG_HTML_LOG: <font color='#aaaaaa'>[VI-DEBUG] {s_name}({stk_cd}) 매수 스킵: 거래대금 순위({len(TOP_VOLUME_RANK_CACHE)}위) 밖</font>")
                    return

            # 1단계: 가격대 필터링
            min_p = safe_int(str(cached_setting('bultagi_turbo_vi_min_price', '0')).replace(',', ''))
            max_p = safe_int(str(cached_setting('bultagi_turbo_vi_max_price', '99999999')).replace(',', ''))
            
            # 현재가 확인 (trade_price가 없으면 API 호출)
            if not trade_price or safe_int(trade_price) == 0:
                _, trade_price = get_current_price(stk_cd, token=token)
            
            cur_p = safe_int(trade_price)
            
            if cur_p < min_p:
                msg = f"📡 <font color='#888888'>[Turbo 스킵] {s_name}({stk_cd}) 현재가({cur_p:,}원) < 최소설정({min_p:,}원)</font>"
                print(msg)
                return
            if cur_p > max_p:
                msg = f"📡 <font color='#888888'>[Turbo 스킵] {s_name}({stk_cd}) 현재가({cur_p:,}원) > 최대설정({max_p:,}원)</font>"
                print(msg)
                return

            # 2단계: VI 타입 필터링 (1:정적, 2:동적)
            use_static = cached_setting('bultagi_turbo_vi_static', True)
            use_dynamic = cached_setting('bultagi_turbo_vi_dynamic', True)
            
            vi_t_txt = "정적" if vi_type == '1' else ("동적" if vi_type == '2' else "알수없음")
            
            if vi_type == '1' and not use_static:
                msg = f"📡 <font color='#888888'>[Turbo 스킵] {s_name}({stk_cd}) 정적 VI 필터 비활성 스킵</font>"
                print(msg)
                return
            if vi_type == '2' and not use_dynamic:
                msg = f"📡 <font color='#888888'>[Turbo 스킵] {s_name}({stk_cd}) 동적 VI 필터 비활성 스킵</font>"
                print(msg)
                return
                
            # 3단계: 제외 잡주 정밀 필터
            if cached_setting('bultagi_turbo_ex_etf', True):
                if any(x in s_name for x in ['KODEX', 'TIGER', 'KBSTAR', 'HANARO', 'KOSEF', 'ARIRANG', 'SOL', 'ACE', 'TRUE', 'TIMEFOLIO', 'FOCUS', 'HK', '마이티', '파워', 'ETN']):
                    print(f"📡 <font color='#888888'>[Turbo 스킵] {s_name} (ETF/ETN 제외)</font>")
                    return 
            if cached_setting('bultagi_turbo_ex_spac', True):
                if '스팩' in s_name or ('제' in s_name and '호' in s_name):
                    print(f"📡 <font color='#888888'>[Turbo 스킵] {s_name} (스팩 제외)</font>")
                    return
            if cached_setting('bultagi_turbo_ex_prefer', True):
                if s_name.endswith('우') or s_name.endswith('우B') or s_name.endswith('우C'):
                    print(f"📡 <font color='#888888'>[Turbo 스킵] {s_name} (우선주 제외)</font>")
                    return
            
            # [통과] 쿨타임 패스
            print(f"🚀 <font color='#00e5ff'><b>[Turbo Pass]</b> {s_name}({stk_cd}) 필터 통과! ({cur_p:,}원/{vi_t_txt}) 즉시 진입!</font>")
        
        elif (current_time - last_entry < 5):
            s_name = get_stock_name_safe(stk_cd, token)
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

            # [v6.4.5] 사용자 요청: 이미 보유 중인 종목은 매수 안 함
            if not cached_setting('simple_log', False):
                print(f"ℹ️ [스킵] {s_name} ({stk_cd}) 이미 보유 중입니다.")
            return

        # [핵심] 주문 시도 시간 기록 (보유하지 않았을 때만 스로틀 작동) - v1.1.7
        RECENT_ORDER_CACHE[stk_cd] = current_time 

        # [수정] A-2. 보유 종목 확인 (캐시 기반으로 충분, API 중복 호출 제거하여 속도 극대화)
        # 0.1초가 아쉬운 초단타를 위해 매수 직전 계좌 전체 조회 API는 생략함

        # B. 최대 종목 수 확인
        current_count = len(ACCOUNT_CACHE['holdings'])
        if current_count >= max_stocks:
            if not cached_setting('simple_log', False):
                s_name = get_stock_name_safe(stk_cd, token)
                print(f"⛔ [차단] 최대 종목 수 도달 ({current_count}/{max_stocks}): {stk_cd}")
                pretty_log("⛔", f"풀방({current_count})", s_name, stk_cd)
            return

        # C. 잔고 체크 (Safe Retry)
        if ACCOUNT_CACHE['balance'] < 1000:
            print(f"💸 [진단] 잔고 부족 예상 ({ACCOUNT_CACHE['balance']}), 재조회 시도...")
            try:
                bal_data = get_balance(token=token, quiet=True)
                if bal_data and isinstance(bal_data, dict):
                    real_bal = int(str(bal_data.get('balance', '0')).replace(',', ''))
                    ACCOUNT_CACHE['balance'] = real_bal
                    ACCOUNT_CACHE['acnt_no'] = bal_data.get('acnt_no', '')
                    print(f"💰 [진단] 잔고 갱신 결과: {real_bal:,}원")
            except: pass

        if ACCOUNT_CACHE['balance'] < 1000: 
            s_name = get_stock_name_safe(stk_cd, token)
            print(f"💸 [차단] 최종 잔고 부족: {ACCOUNT_CACHE['balance']}원")
            pretty_log("💸", "잔고부족", s_name, stk_cd)
            return

        # =========================================================
        # 3. 매수 주문 전송
        # =========================================================
        try:
            if seq == 'SYSTEM_VI':
                mode = 'VI해제'
                val_str = '1'
                # [v1.5.9] 진입 근거 로그 보강
                print(f"🚀 <font color='#00e5ff'><b>[Turbo Pass]</b> {stk_cd}: VI 해제 즉시 진입 결정 (1주/현재가형)</font>")
            else:
                strat_map = cached_setting('condition_strategies', {})
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

        # [삭제 v6.9.8] 시초가 베팅 A방식(조건식 연동) 제거 - 전용 엔진에서 B방식으로 일원화됨
        
        if p_type == 'current' and current_price > 0:
            trde_tp = '0' # 지정가
            ord_uv = str(current_price)
            # pretty_log("📍", "현재가", f"{current_price:,}원", stk_cd)

        try:
            qty = 1 # [Fix] 기본값 미리 할당
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
                        pct = safe_float(val_str, 0.0)
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
            
            # [v5.0.8] 전략명 정규화 (랭크, 불타기, VI 등)
            s_mode_db = '랭크'
            if seq == 'SYSTEM_VI':
                s_mode_db = 'VI'
            elif seq_name and "MorningBet" in seq_name:
                s_mode_db = '시초가'
            elif mode == 'BULTAGI': 
                s_mode_db = '랭크' # chk_n_buy는 1차 진입이므로 '랭크'
            else:
                s_mode_db = '랭크'
            
            # 세션 매수 기록
            session_logger.record_buy(stk_cd, s_name, qty, final_price, strat_mode=s_mode_db, seq=seq)
            
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
            if get_setting('voice_guidance', True):
                voice_map = {'qty': '한주', 'amount': '금액', 'percent': '비율', 'VI해제': '브이아이 해제 매매'}
                strategy_voice = voice_map.get(mode, '매수')
                
                # [v1.5.4 고도화] 시초가 전략인 경우 구분하여 안내
                if seq_name and "MorningBet" in seq_name:
                    if "(A_Scan)" in seq_name: strategy_voice = "시초가 에이"
                    elif "(B_OpenReBreak)" in seq_name: strategy_voice = "시초가 비"
                    elif "(C_1MinHigh)" in seq_name: strategy_voice = "시초가 씨"
                    elif "(D_VolSurge)" in seq_name: strategy_voice = "시초가 디"
                    voice_msg = f"{s_name} {strategy_voice}"
                else:
                    voice_msg = f"{seq_name} {strategy_voice}" if seq_name else f"{s_name} {strategy_voice}"
                
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

def add_buy(stk_cd, token=None, seq_name=None, qty=1, source='ACCEL', price_type='market', open_price=None):
    """[수정 v4.5.1] 가속도 또는 불타기 조건 만족 시 시장가/현재가 추가 매수"""
    stk_cd = stk_cd.replace('A', '')

    # [v4.4.0] 지수 급락 자동 매매 정지 체크 (Global Stop) - 불타기도 포함
    is_ok, reason = is_market_index_ok()
    if not is_ok:
        s_name = get_stock_name_safe(stk_cd, token if token else get_token())
        print(f"🛡️ <font color='#ff6b6b'><b>[지수급락 정지]</b> {s_name}({stk_cd}) 추가 매수(불타기) 차단 ({reason})</font>")
        return False

    # [v5.1.34] VI 발동 중 매수 금지 체크 (Global Filter)
    # Turbo VI(VI_TURBO)는 해제 시점에 들어가는 로직이므로 제외
    if source != 'VI_TURBO' and get_setting('block_buy_during_vi', False):
        vi_status = GLOBAL_VI_CACHE.get(stk_cd)
        if vi_status == '1': # '1'은 VI 발동(Active) 상태
            s_name = get_stock_name_safe(stk_cd, token if token else get_token())
            # [사용자 요청] 이유를 로그창에 명시적으로 표시 ❤️
            print(f"🛡️ <font color='#ff6b6b'><b>[VI차단]</b> {s_name}({stk_cd}) 현재 VI 발동 중으로 추가 매수(정찰병 포함) 건너뜀</font>")
            return False

    # 0. 메모리 락
    if stk_cd in PROCESSING_FLAGS:
        return False
    PROCESSING_FLAGS.add(stk_cd)

    try:
        current_time = time.time()
        last_entry = RECENT_ORDER_CACHE.get(stk_cd, 0)
        
        # [Fix] 불타기(BULTAGI) 또는 시초가(MORNING), VI터보 진입 시에는 쿨타임 무시
        RECENT_ORDER_CACHE[stk_cd] = current_time
        token = token if token else get_token()

        # [신규 v5.3.7] 불타기 가격 상한선 체크 (고점 추격 방지 가드)
        if source == 'BULTAGI' and get_setting('bultagi_limit_enabled', True):
            from stock_info import get_price_high_data
            cur_p, _, base_p = get_price_high_data(stk_cd, token)
            if base_p > 0:
                cur_rt = (cur_p - base_p) / base_p * 100
                limit_rt = get_setting('bultagi_limit_rt', 22.0)
                if cur_rt >= limit_rt:
                    s_name = get_stock_name_safe(stk_cd, token)
                    print(f"🛡️ <font color='#ff6b6b'><b>[가격상한 차단]</b> {s_name}({stk_cd}) 현재 대비율({cur_rt:.1f}%)이 상한선({limit_rt:.1f}%)을 초과하여 불타기 생략</font>")
                    return False

        # 잔고 부족 시 스킵
        if ACCOUNT_CACHE['balance'] < 1000:
            return False

        # [필수] 추가 매수(불타기)이므로 보유 중인 종목인 경우에만 진행 (0->1은 chk_n_buy가 담당)
        current_holdings = ACCOUNT_CACHE['holdings'].get(stk_cd, 0)
        # [v2.2.7] Ranking Scout는 추가 매수 형식이지만 첫 진입이 주 목적이므로 0주여도 허용
        if current_holdings <= 0:
            # [Fix] 캐시 지연 방어: chk_n_sell에서 호출되었다면 보유 중일 확률이 매우 높으므로 로그만 남기고 일단 진행
            # [v1.5.7 / v2.2.7] 시초가 추매나 VI터보, 정찰병 진입 시에는 0주여도 허용 (첫 진입 대응)
            if source in ['BULTAGI', 'VI_TURBO', 'RankScout'] or source.startswith('MORNING'):
                print(f"ℹ️ [{source}] 캐시상 보유 수량 0주이나 진입 신호 확인되어 매수 시도. (첫 진입 보류 해제)")
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
        ret_code, ret_msg = ("", "")
        if isinstance(result, (tuple, list)):
            is_success = str(result[0]) == '0'
            if len(result) >= 2: ret_code, ret_msg = result[0], result[1]
        else:
            is_success = str(result) == '0'
            ret_code = str(result)

        if is_success:
            # 계좌 캐시 업데이트
            current_qty = ACCOUNT_CACHE['holdings'].get(stk_cd, 0)
            ACCOUNT_CACHE['holdings'][stk_cd] = current_qty + qty
            
            s_name = get_stock_name_safe(stk_cd, token)
            
            # 세션 매수 기록 (v5.0.8 전략 정규 명칭 반영: 시초가, VI, 랭크, 불타기 등)
            if source.startswith('MORNING'):
                s_mode = '시초가'
            elif source == 'VI_TURBO':
                s_mode = 'VI'
            elif source == 'RankScout':
                s_mode = '랭크'
            elif source == 'BULTAGI':
                s_mode = '불타기'
            else:
                s_mode = '가속'
            session_logger.record_buy(stk_cd, s_name, qty, final_price, strat_mode=s_mode)
            
            # [v6.2.8] 매수 시간 및 정보 저장 (재매수 대응 overwrite=True)
            _LOG_QUEUE.put(('save_buy_time', {'code': stk_cd, 'overwrite': True}))
            
            # [신규] 시초가/불타기 등 전략 매핑 정보 업데이트 (chk_n_sell에서 TP/SL 인식용)
            if seq_name:
                strat_tag = source if source.startswith('MORNING') else 'BULTAGI'
                update_stock_condition(stk_cd, name=seq_name, strat=strat_tag, seq='MORNING' if source.startswith('MORNING') else None, open_price=open_price)
            
            # 알림 및 로그
            if source == 'BULTAGI':
                log_msg = f"<font color='#f39c12'>🔥<b>[불타기 성공]</b> {s_name} ({final_price:,}원/{qty}주)</font>"
                tel_msg = f"🔥 [불타기 완료] {s_name} {qty}주 추가 체결!"
                voice_msg = f"{s_name} 실시간 불타기"
            elif source == 'VI_TURBO':
                log_msg = f"<font color='#00e5ff'>🚀<b>[VI터보 성공]</b> {s_name} ({final_price:,}원/{qty}주)</font>"
                tel_msg = f"🚀 [VI터보 완료] {s_name} {qty}주 돌파 체결!"
                voice_msg = f"{s_name} 브이아이 돌파"
            elif source.startswith('MORNING'):
                log_msg = f"<font color='#ff6b6b'>🌅<b>[시초가추매 성공]</b> {s_name} ({final_price:,}원/{qty}주)</font>"
                tel_msg = f"🌅 [시초가추매 완료] {s_name} {qty}주 추가 체결!"
                m_type = source.split('_')[-1] # A, B, C, D
                voice_msg = f"{s_name} 시초가 {m_type} 추가매수"
            elif source == 'RankScout':
                log_msg = f"<font color='#ffbb33'>🚩<b>[정찰병 투입]</b> {s_name} ({final_price:,}원/{qty}주)</font>"
                tel_msg = f"🚩 [정찰병 완료] {s_name} {qty}주 즉시 매수!"
                
                # [v5.2.1] 정찰병 세부 유형별 보이스 알림 강화 (자기야, 이제 눈 감고도 들을 수 있어! ❤️)
                v_type = "순위 정찰병"
                if seq_name:
                    if "NewEntry" in seq_name: v_type = "순위 신규 정찰병"
                    elif "RankJump" in seq_name: v_type = "순위 급등 정찰병"
                    elif "RankConsec" in seq_name: v_type = "연속 상승 정찰병"
                
                voice_msg = f"{v_type}, {s_name}"
            else:
                log_msg = f"<font color='#ff00ff'>🔥<b>[추가매수 성공]</b> {s_name} ({final_price:,}원/{qty}주) [수급폭발]</font>"
                tel_msg = f"🔥 [추가매수 완료] {s_name} {qty}주 추가 체결! (수급폭발)"
                voice_msg = f"{s_name} 가속도 매수"
            
            print(log_msg)
            tel_send(tel_msg, msg_type='log')
            say_text(voice_msg) # 음성 알림
            
        else:
            # [V5.1.17] 주문 실패 시 상세 로그 전송
            s_name = get_stock_name_safe(stk_cd, token)
            _err_log = f"❌ [Order-FAIL] {s_name}({stk_cd}) 주문 실패: [{ret_code}] {ret_msg}"
            print(f"DEBUG_HTML_LOG: <font color='#ff6b6b'>{_err_log}</font>")
            print(_err_log)
            # 수동 매수 등의 재시도를 위해 실패 시 주문 캐시에서 제거
            RECENT_ORDER_CACHE.pop(stk_cd, None)
            
        return is_success

    except Exception as e:
        # [V5.1.17] 에러 발생 시 상세 로그 전송
        print(f"DEBUG_HTML_LOG: <font color='#ff6b6b'>[Order-ERROR] {stk_cd} 주문 실행 중 예외: {e}</font>")
        print(f"⚠️ [add_buy] 추가 매수 오류: {e}")
        return False
    finally:
        PROCESSING_FLAGS.discard(stk_cd)

# [신규] 조건식 매핑 업데이트 (HTS 매매 등 외부 요인)
def update_stock_condition(code, name='직접매매', strat='qty', time_val=None, seq=None, bultagi_done=None, open_price=None):
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
        
        spec_tp = safe_float(specific_setting.get('tp', default_tp), default_tp)
        spec_sl = safe_float(specific_setting.get('sl', default_sl), default_sl)

        if spec_tp == 0: spec_tp = 12.0
        if spec_sl == 0: spec_sl = -1.5
        
        # [신규] RankScout 전용 기본값 (정찰병은 보수적 대응)
        if strat == 'RankScout':
            spec_tp = 20.0 # 정찰병은 크게 본다
            spec_sl = -3.0
            
        # [신규 v5.0.6] CLOSING_BET 전용 기본값 (종가 베팅은 익절을 넉넉히)
        if strat == 'CLOSING_BET':
            spec_tp = max(spec_tp, 15.0) 
            spec_sl = min(spec_sl, -2.0)
        
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
            'time': time_val if time_val else (existing_info.get('time') or datetime.now().strftime("%H:%M:%S")),
            'open_price': open_price if open_price is not None else existing_info.get('open_price', 0)
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
        base_path = get_base_path()
            
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

def remove_stock_condition(code):
    """[신규 v1.3.4] 매도 완료 시 해당 종목의 매핑 정보를 삭제 (자기 요청 ❤️)"""
    try:
        code = code.replace('A', '')
        base_path = get_base_path()
            
        mapping_file = os.path.join(base_path, 'stock_conditions.json')
        mapping = load_json_safe(mapping_file)
        
        if code in mapping:
            del mapping[code]
            save_json_safe(mapping_file, mapping)
            # print(f"🧹 [매핑정리] {code} 삭제 완료")
            
    except Exception as e:
        print(f"⚠️ 매핑 삭제 실패: {e}")

