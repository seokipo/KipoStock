import asyncio 
import websockets
import json
from config import socket_url
import time 
from get_setting import get_setting
from login import fn_au10001 as get_token
from market_hour import MarketHour
from tel_send import tel_send
from datetime import datetime, timedelta
import collections

class RealTimeSearch:
    def __init__(self, on_connection_closed=None):
        self.socket_url = socket_url + '/api/dostk/websocket'
        self.websocket = None
        self.connected = False
        self.keep_running = True
        self.receive_task = None
        self.on_connection_closed = on_connection_closed
        self.on_condition_loaded = None # [신규] 목록 로드 완료 콜백
        self.token = None
        
        # [추가] 조건식 이름을 저장할 딕셔너리와 이벤트
        self.condition_map = {} 
        self.list_loaded_event = asyncio.Event()
        
        # [신규] 종목별 출처(조건식 번호) 매핑
        self.stock_origin_map = {}
        
        # [신규] 현재 서버에 등록 성공하여 감시 중인 조건식 번호 집합
        self.active_conditions = set()

        # [신규 v5.1] 뉴스 분석 결과 전달 콜백
        self.on_news_result = None
        self.on_realtime_trade = None # [신규] 실시간 체결 데이터 전달 콜백
        
        # [v1.9.5] 종목별 VI 상태 캐시 (상태 변화 시에만 로깅/알람 트리거용)
        self.vi_release_cache = {}
        self.vi_state_cache = {} # [V4.2.8] 중복 수신 방지용 캐시
        
        # [V3.3.8] 거래대금 상위 종목 캐시 (필터링용)
        self.top_volume_set = set()
        self.ranking_task = None
        self.auth_error_detected = False # [v4.4.1] 인증 에러 감지 플래그 추가

    async def connect(self, token, acnt_no=None):
        try:
            self.token = token
            self.acnt_no = acnt_no
            self.websocket = await websockets.connect(self.socket_url)
            self.connected = True
            print("⚡ [접속] 서버 연결 성공. 로그인 시도...")
            await self.send_message({'trnm': 'LOGIN', 'token': token})
        except Exception as e:
            print(f'❌ 소켓 연결 실패: {e}')
            self.connected = False

    async def send_message(self, message, token=None):
        if not self.connected and token:
            await self.connect(token)
        if self.connected and self.websocket:
            if not isinstance(message, str):
                message = json.dumps(message)
            await self.websocket.send(message)

    async def receive_messages(self):
        """인터럽트형 고속 수신 처리"""
        loop = asyncio.get_event_loop()
        print("👀 [감시모드] 초고속 수신 대기 중...")
        
        # [v2.5.3] VI 로그 정밀 필터링 (통과한 종목만 표시)
        # [V4.2.8] 진단 로그 강화: 필터링 원인을 [VI-DEBUG]로 상세 로그창에 출력
        def _passes_vi_filter(name, v_price, v_type, code):
            if not get_setting('bultagi_turbo_vi', False): return False
            try:
                # [V3.3.8] 거래대금 상위 필터링 (최우선순위)
                if get_setting('bultagi_turbo_vi_volume_enabled', False):
                    # rank_limit = int(get_setting('bultagi_turbo_vi_volume_rank', 100))
                    if self.top_volume_set and code not in self.top_volume_set:
                        print(f"📡 <font color='#888888'>[VI-DEBUG] {name}({code}) 거래대금 순위 밖 스킵</font>")
                        return False

                p = int(float(v_price)) if v_price else 0
                if p > 0:
                    min_p = int(str(get_setting('bultagi_turbo_vi_min_price', '0')).replace(',', ''))
                    max_p = int(str(get_setting('bultagi_turbo_vi_max_price', '99999999')).replace(',', ''))
                    if p < min_p or p > max_p:
                        print(f"📡 <font color='#888888'>[VI-DEBUG] {name}({code}) 가격({p:,}원) 범위 밖 스킵</font>")
                        return False
                    
                if v_type == '1' and not get_setting('bultagi_turbo_vi_static', True):
                    print(f"📡 <font color='#888888'>[VI-DEBUG] {name}({code}) 정적 VI 필터 OFF 스킵</font>")
                    return False
                if v_type == '2' and not get_setting('bultagi_turbo_vi_dynamic', True):
                    print(f"📡 <font color='#888888'>[VI-DEBUG] {name}({code}) 동적 VI 필터 OFF 스킵</font>")
                    return False
                
                # 잡주 제외 필터
                if get_setting('bultagi_turbo_ex_etf', True):
                    if any(x in name for x in ['KODEX', 'TIGER', 'KBSTAR', 'HANARO', 'KOSEF', 'ARIRANG', 'SOL', 'ACE', 'TRUE', 'TIMEFOLIO', 'FOCUS', 'HK', '마이티', '파워', 'ETN']):
                        print(f"📡 <font color='#888888'>[VI-DEBUG] {name}({code}) ETF/ETN 스킵</font>")
                        return False
                if get_setting('bultagi_turbo_ex_spac', True):
                    if '스팩' in name or ('제' in name and '호' in name):
                        print(f"📡 <font color='#888888'>[VI-DEBUG] {name}({code}) 스팩 스킵</font>")
                        return False
                if get_setting('bultagi_turbo_ex_prefer', True):
                    if name.endswith('우') or name.endswith('우B') or name.endswith('우C'):
                        print(f"📡 <font color='#888888'>[VI-DEBUG] {name}({code}) 우선주 스킵</font>")
                        return False
                return True
            except Exception as e:
                print(f"📡 <font color='#888888'>[VI-DEBUG] {name} 필터링 오류: {e}</font>")
                return True

        while self.keep_running and self.websocket:
            try:
                raw_message = await self.websocket.recv()
                if not raw_message: continue
                
                response = json.loads(raw_message)
                trnm = response.get('trnm')

                # [🎰 마스터 스니퍼] 모든 메시지 수신 확인 (PING 제외)
                tr_lower = str(trnm).strip().lower() if trnm else ''
                
                if tr_lower != 'ping':
                    if tr_lower not in ['real', 'cnsr', 'rscn', 'system', '1h', 'login', 'cnsrlst', 'reg', 'cnsrreq']:
                        print(f"📥 <font color='#888888'>[수신-알수없음] {trnm} 수신됨 ({len(str(response))} bytes)</font>")

                if tr_lower == 'login':
                    if response.get('return_code') == 0:
                        print('✅ 로그인 성공 (조건식 이름 가져오는 중...)')
                        await self.send_message({'trnm': 'CNSRLST'})
                    else:
                        ret_msg = response.get('return_msg', '')
                        ret_code = str(response.get('return_code', ''))
                        print(f"❌ 로그인 실패 ({ret_code}): {ret_msg}")
                        # [v4.4.1] 토큰 이슈(8005)일 경우 강제 재결합을 위해 연결 종료 유도
                        if '8005' in ret_code or 'Token' in ret_msg or '유효하지' in ret_msg:
                            self.auth_error_detected = True # 플래그 활성화
                            self.connected = False
                            if self.websocket:
                                await self.websocket.close()
                            # 5초 뒤 재연결 시도를 위해 루프 탈출
                            break 

                elif trnm == 'CNSRLST':
                    raw_data = response.get('data', [])
                    if isinstance(raw_data, list):
                        self.condition_map = {}
                        for item in raw_data:
                            if len(item) >= 2:
                                self.condition_map[str(item[0])] = item[1]
                        self.list_loaded_event.set()
                        if self.on_condition_loaded:
                            self.on_condition_loaded()

                elif tr_lower == 'cnsr':
                    header = response.get('header', {})
                    data = response.get('data')
                    raw_seq = header.get('seq') or header.get('index') or header.get('condition_seq') or response.get('seq')
                    seq = str(raw_seq) if raw_seq is not None else ''

                    if data and isinstance(data, dict): data = [data]
                    
                    if not seq:
                        active_seqs = get_setting('search_seq', [])
                        if isinstance(active_seqs, str): active_seqs = [active_seqs]
                        if len(active_seqs) == 1: seq = str(active_seqs[0])

                    if data:
                        stock_list = []
                        for item in data:
                            jmcode = item.get('stk_cd') or item.get('code') or (item.get('values') or {}).get('9001')
                            if jmcode:
                                jmcode = jmcode.replace('A', '')
                                stock_list.append(jmcode)
                                if seq: self.stock_origin_map[jmcode] = seq
                        
                        if stock_list:
                            # print(f"📡 [검색검출] {seq}번({self.condition_map.get(seq, '이름모름')}): {len(stock_list)}종목") # [v1.2.3 제거]
                            try:
                                from check_n_buy import save_detected_stock
                                for jm in stock_list: save_detected_stock(jm)
                            except: pass

                        for item in data:
                            jmcode = item.get('stk_cd') or item.get('code') or (item.get('values') or {}).get('9001')
                            if jmcode:
                                jmcode = jmcode.replace('A', '')
                                trade_price = item.get('now_prc') or item.get('match_prc')
                                seq_name = self.condition_map.get(seq, "이름모름") if seq else "출처불명"

                                if not MarketHour.is_waiting_period():
                                    # print(f"🔍 [진단] {jmcode} 검출! (Seq: {seq}, Name: {seq_name}) - 매수 스레드 진입") # [v1.2.3 제거]
                                    from check_n_buy import chk_n_buy
                                    loop.run_in_executor(None, chk_n_buy, jmcode, self.token, seq, trade_price, seq_name, self.on_news_result)
                                else:
                                    print(f"⏳ [진단] {jmcode} 매수 스킵 (MarketHour.is_waiting_period() == True)")

                elif tr_lower == 'rscn': 
                    data = response.get('data')
                    if isinstance(data, list):
                        for item in data:
                            values = item.get('values') or {}
                            jmcode = values.get('1001', '').replace('A', '')
                            tp = values.get('8030') # 2: 매수, 1: 매도
                            tm = values.get('8031')
                            qty = values.get('1004', '0')
                            if jmcode:
                                from check_n_buy import RECENT_ORDER_CACHE, save_buy_time, update_stock_condition
                                f_time = f"{tm[:2]}:{tm[2:4]}:{tm[4:]}" if tm and len(tm) == 6 else datetime.now().strftime("%H:%M:%S")
                                s_name = self.condition_map.get(jmcode, jmcode)
                                icon = "⚡" if tp == '2' else "🔥"
                                status_txt = "[HTS매수]" if tp == '2' else "[HTS매도]"
                                log_color = "#ffc107" if tp == '2' else "#00b0f0"
                                
                                last_bot_order = RECENT_ORDER_CACHE.get(jmcode, 0)
                                if time.time() - last_bot_order > 5.0:
                                    print(f"<font color='{log_color}'>{icon} <b>{status_txt}</b> {s_name} ({qty}주) [HTS체결]</font>")
                                    RECENT_ORDER_CACHE[jmcode] = time.time()
                                    if tp == '2':
                                        save_buy_time(jmcode, f_time)
                                        update_stock_condition(jmcode, name='직접매매', strat='HTS', time_val=f_time)
                                        tel_send(f"🕵️ [HTS매수전파] {s_name} ({qty}주)")
                                    else:
                                        tel_send(f"🕵️ [HTS매도전파] {s_name} ({qty}주)")

                elif tr_lower == 'real':
                    data = response.get('data')
                    if isinstance(data, list):
                        for item in data:
                            target_name = item.get('name', '')
                            values = item.get('values') or {}
                            
                            # A. 계좌 관련 신호 (HTS 감지용)
                            if '주문체결' in target_name or '계좌' in target_name:
                                jmcode = values.get('9001', '').replace('A', '') or item.get('item', '').replace('A', '')
                                s_name = values.get('302', jmcode)
                                order_stat = values.get('913', '')
                                qty = values.get('900', '0')
                                order_type_raw = values.get('905', '')
                                is_buy = '매수' in order_type_raw or '+' in order_type_raw
                                
                                from check_n_buy import RECENT_ORDER_CACHE, save_buy_time, update_stock_condition
                                if '접수' in order_stat:
                                    print(f"<font color='#ffc107'>📝 [HTS접수] {s_name} ({order_stat}) {qty}주</font>")
                                elif any(x in order_stat for x in ['체', '완', '정', '량']):
                                    last_bot_order = RECENT_ORDER_CACHE.get(jmcode, 0)
                                    if time.time() - last_bot_order > 5.0:
                                        print(f"⚡ [HTS체결] {s_name} ({order_stat}) {qty}주")
                                        RECENT_ORDER_CACHE[jmcode] = time.time()
                                        if is_buy:
                                            save_buy_time(jmcode)
                                            update_stock_condition(jmcode, name='직접매매', strat='HTS')
                                            tel_send(f"🕵️ [HTS매수] {s_name} 체결!")
                                continue

                            # [v2.2.6] VI 감지 조건 극한 확장 (9068, 9051, 1224, 1225 등 가용한 모든 필드 체크)
                            vi_status_raw = values.get('9068') or values.get('1225') # VI상태/구분
                            vi_time_raw = values.get('9051') or values.get('1224') # 시간
                            
                            is_vi_event = ('VI' in target_name or item.get('type') == '1h' or vi_status_raw or vi_time_raw)
                            
                            if is_vi_event:
                                raw_jm = values.get('9001', '').replace('A', '') or item.get('item', '').replace('A', '')
                                jmcode = str(raw_jm)[:6]
                                s_name = values.get('302', jmcode)
                                
                                vi_status = str(values.get('9068', '')) # 1:발동, 2:해제, 3:중지, 4:재개
                                # [v2.2.8] 시간 감지 필드 보강: 9051, 1224가 000000일 경우 1223 시도
                                vi_time = values.get('9051') or values.get('1224')
                                if not vi_time or vi_time == '000000':
                                    vi_time = values.get('1223') or ""
                                
                                vi_type = values.get('9052') or values.get('1225', '') or str(values.get('9069', '')) # 1:정적, 2:동적, 3:변동성
                                vi_price = values.get('9054') or values.get('1236', '0')

                                # [v1.9.5] 강력한 상태 감지: 9068이 없더라도 해제 시간이 들어오면 '발동(1)' 또는 '해제(2)'로 추정
                                if not vi_status and vi_time:
                                    vi_status = '1' if (vi_price != '0' and vi_price != '') else '2'

                                # [v2.2.9] 시간 계산 유틸리티
                                def add_2min(t_str):
                                    if not t_str or len(t_str) != 6: return t_str
                                    try:
                                        h, m, s = int(t_str[:2]), int(t_str[2:4]), int(t_str[4:6])
                                        total = (h * 3600 + m * 60 + s + 120) % 86400
                                        return f"{total//3600:02d}{(total%3600)//60:02d}{total%60:02d}"
                                    except: return t_str

                                # [v1.9.5] 중복 로그 방지: 이전 상태와 동일하면 로깅 스킵
                                cache_key = f"{jmcode}_{vi_status}_{vi_time}"
                                last_val = self.vi_state_cache.get(jmcode, "") 
                                if last_val == cache_key:
                                    continue
                                
                                # [v2.2.9] 해제 오판단 방어: 발동(1) 상태에서 110초 이후의 신호는 해제로 간주
                                if vi_status == '1' and last_val:
                                    try:
                                        parts = last_val.split('_')
                                        if len(parts) >= 3:
                                            last_st, last_t = parts[1], parts[2]
                                            
                                            # Case A: 발동(1) 상태에서 110초 이상 경과 시 해제(2)로 보정
                                            if last_st == '1' and len(vi_time) == 6 and len(last_t) == 6:
                                                dt = (int(vi_time[:2])*3600 + int(vi_time[2:4])*60 + int(vi_time[4:6])) - \
                                                     (int(last_t[:2])*3600 + int(last_t[2:4])*60 + int(last_t[4:6]))
                                                if dt >= 110:
                                                    vi_status = '2' # 해제로 강제 보정
                                                    print(f"🕵️‍♂️ [v2.2.9] {s_name} 시간 경과({dt}초)에 의한 해제(2) 보정 적용")
                                            
                                            # [v2.3.0] Case B: 방금 해제(2) 되었는데 즉시 발동(1) 신호가 오면 무시 (노이즈 차단)
                                            if last_st == '2' and vi_status == '1':
                                                rel_data = self.vi_release_cache.get(jmcode)
                                                if rel_data:
                                                    last_rel_sys_t, last_rel_vi_t = rel_data
                                                    if (time.time() - last_rel_sys_t) < 5 and vi_time == last_rel_vi_t:
                                                        print(f"🕵️‍♂️ [v2.3.0] {s_name} 해제 직후 가짜 발동 신호 차단 (Time:{vi_time})")
                                                        continue
                                    except: pass

                                # [v2.3.0] 해제(2) 발생 시 캐시에 기록
                                if vi_status == '2':
                                    self.vi_release_cache[jmcode] = (time.time(), vi_time)

                                self.vi_state_cache[jmcode] = f"{jmcode}_{vi_status}_{vi_time}"

                                # [v2.5.3] 필터 조건 미달 시 로깅 및 진행 완전 차단 (사용자 요청)
                                if not _passes_vi_filter(s_name, vi_price, vi_type, jmcode):
                                    continue

                                # [v2.2.0 / v2.2.9] 로그에서 종목코드 제거
                                # [v1.9.1] VI 감지 시 즉시 로우 데이터 출력
                                print(f"📡 [VI-DEBUG] [{s_name}] 수신! [9068:{vi_status}] | Time:{vi_time} | Type:{vi_type}")
                                
                                # [v1.9.5] 패킷 전체 덤프 (자기 요청 스크린샷 대응)
                                print(f"📡 <font color='#888888'>[VI-DEBUG] trnm={trnm} | 패킷: {str(response)[:300]}</font>")

                                if vi_status:
                                    status_map = {'1': '발동', '2': '해제', '3': '중지', '4': '재개'}
                                    st_txt = status_map.get(vi_status, vi_status)
                                    
                                    # 상세 정보 조합
                                    # [v2.2.9] 해제 예정 시간 2분 추가 계산 적용
                                    release_time_raw = add_2min(vi_time) if vi_status == '1' else vi_time
                                    time_fmt = f"{release_time_raw[:2]}:{release_time_raw[2:4]}:{release_time_raw[4:6]}" if len(release_time_raw) == 6 else release_time_raw
                                    
                                    type_map = {'1': '정적', '2': '동적', '3': '변동성', '정적': '정적', '동적': '동적'}
                                    vi_type_txt = type_map.get(vi_type, "알수없음")
                                    detail_info = f" | {vi_type_txt}VI | 발동가: {int(float(vi_price or 0)):,} | 해제예정: {time_fmt}" if vi_status == '1' else ""
                                    
                                    # [v1.5.4] GUI 알람 트리거를 위해 [VI발동] 또는 [VI감지] 키워드 필수 포함
                                    tag = "[VI발동]" if vi_status == '1' else "[VI감지]"
                                    raw_sample = f" <font color='#888888'>(9068:{vi_status}{detail_info})</font>"
                                    # [v2.2.8 / v2.2.9] 사용자 요청: 로그에서 종목코드 제거
                                    print(f"📡 <font color='#f1c40f'><b>{tag}</b> {s_name} 상태: {st_txt}</font>{raw_sample}")

                                if get_setting('bultagi_turbo_vi', False):
                                    # [신규 v1.5.4] VI 발동(1) 시 보유 종목일 경우 1분 50초 알람 타이머 가동
                                    if vi_status == '1':
                                        from check_n_buy import ACCOUNT_CACHE
                                        if jmcode in ACCOUNT_CACHE['holdings']:
                                            s_name = values.get('302', jmcode)
                                            # [v2.2.9] 로그에서도 코드 제거
                                            # [v4.0.1] GUI의 append_log에서 [VI발동] 태그를 감지하여 110초 후 알람을 통합 관리하므로
                                            # 엔진 내부의 중복 타이머는 제거하고 로그만 출력합니다.
                                            print(f"📡 <font color='#f1c40f'><b>[VI발동]</b> {s_name} 보유 종목 VI 진입! (1분 50초 후 알람 예약됨)</font>")

                                    # [핵심] 해제(2) 또는 재개(4) 시 즉시 매수 트리거
                                    elif vi_status in ['2', '4']:
                                        s_name = values.get('302', jmcode)
                                        print(f"🚀 <font color='#00e5ff'><b>[Turbo VI 감지]</b> {s_name} ({jmcode}) {vi_type_txt} VI 해제 신호 발생!</font>")
                                        from check_n_buy import chk_n_buy
                                        # [v2.0.0 / v2.2.7 오타 수정] vi_type 전달 (vi_type_code -> vi_type)
                                        loop.run_in_executor(None, chk_n_buy, jmcode, self.token, 'SYSTEM_VI', None, 'VI해제', self.on_news_result, vi_type)
                                continue

                            # B. 일반 종목 신호 추출 강화 (API별 다양한 필드 대응)
                            jmcode = values.get('9001') or values.get('stk_cd') or values.get('code') or item.get('stk_cd') or item.get('code')
                            if jmcode:
                                jmcode = str(jmcode).replace('A', '')
                                origin_seq = self.stock_origin_map.get(jmcode) or values.get('841')
                                trade_price = values.get('10') or values.get('now_prc')
                                if trade_price:
                                    try: trade_price = abs(int(float(trade_price)))
                                    except: pass
                                
                                seq_name = self.condition_map.get(str(origin_seq), "실시간감시") if origin_seq else "실시간감시"
                                if not MarketHour.is_waiting_period():
                                    # print(f"🔍 [진단] {jmcode} 검출! (Seq: {origin_seq}, Name: {seq_name})") # [v1.2.3 제거]
                                    from check_n_buy import chk_n_buy
                                    loop.run_in_executor(None, chk_n_buy, jmcode, self.token, origin_seq, trade_price, seq_name, self.on_news_result)
                                
                                # [신규 v2.1.0] 실시간 체결 데이터를 시초가 엔진 등으로 전달
                                if self.on_realtime_trade:
                                    self.on_realtime_trade(values)

                elif tr_lower == 'cnsrreq':
                    rc = response.get('return_code', 0)
                    seq = str(response.get('seq'))
                    if str(rc) in ['0', '1']:
                        if seq not in self.active_conditions:
                            self.active_conditions.add(seq)
                            if self.on_condition_loaded: self.on_condition_loaded()
                    elif str(rc) == '900002':
                        self.active_conditions.discard(seq)
                        print(f"⛔ 한도초과: {seq}번({self.condition_map.get(seq, '')})")

                elif tr_lower == 'ping':
                    await self.send_message(response)

                elif tr_lower == 'system':
                    msg = response.get('message', '')
                    if '[장중 거래정지 지정/제개]' in msg and get_setting('bultagi_turbo_vi', False):
                        import re
                        match = re.search(r'(\d{6})', msg)
                        if match and any(x in msg for x in ['제개', '재개']):
                            jmcode = match.group(1)
                            if not MarketHour.is_waiting_period():
                                from check_n_buy import chk_n_buy
                                loop.run_in_executor(None, chk_n_buy, jmcode, self.token, 'SYSTEM_VI', None, 'VI해제', self.on_news_result)
                    else:
                        print(f"🔍 [SYSTEM] {msg}")

                elif tr_lower == '1h':
                    # [v2.2.6] 단독 1h (VI 발동/해제) TR 처리 - 수신 확인용 RAW 로그 최우선 출력
                    data = response.get('data')
                    if isinstance(data, list):
                        for item in data:
                            values = item.get('values') or {}
                            raw_item_id = item.get('item', '')
                            jmcode = (values.get('9001') or raw_item_id or '').replace('A', '')[:6]
                            s_name = values.get('302', jmcode)
                            
                            # [v2.2.6] 수신된 1h 패킷 무조건 덤프 (진단용)
                            print(f"📡 <font color='#888888'>[1h-DEBUG] {s_name}({jmcode}) 수신! Raw:{str(values)[:200]}</font>")

                            vi_status = str(values.get('9068', ''))
                            vi_time = values.get('9051') or values.get('1224') or ""
                            vi_type = values.get('9052') or values.get('1225', '') or str(values.get('9069', ''))
                            vi_price = values.get('9054') or values.get('1236', '0')
                            
                            # [V4.2.8] 강력한 상태 감지Fallback: 9068이 없더라도 해제 시간/가격이 들어오면 추정
                            if not vi_status and vi_time:
                                vi_status = '1' if (vi_price != '0' and vi_price != '') else '2'
                                print(f"📡 <font color='#888888'>[1h-DEBUG] vi_status 추정 적용: {vi_status} (Time:{vi_time})</font>")

                            # [v2.5.3] 필터 미달 시 잡주 로그 원천 차단
                            if not _passes_vi_filter(s_name, vi_price, vi_type, jmcode):
                                continue
                            
                            # 중복 체크
                            cache_key = f"{jmcode}_{vi_status}_{vi_time}"
                            if self.vi_state_cache.get(jmcode) == cache_key: continue
                            self.vi_state_cache[jmcode] = cache_key

                            if vi_status or vi_time:
                                status_map = {'1': '발동', '2': '해제', '3': '중지', '4': '재개'}
                                st_txt = status_map.get(vi_status, "감지")
                                # [V4.2.9] GUI의 보유 종목 매칭(regex)을 위해 종목코드 괄호를 제거하고 표준 포맷 유지
                                tag = "[VI발동]" if vi_status == '1' else "[VI감지]"
                                print(f"📡 <font color='#f1c40f'><b>{tag}</b> {s_name} 상태: {st_txt} | 시간:{vi_time}</font>")

                            # [V4.2.9] 1h TR에서도 보유 종목일 경우 알람 예약용 로그 출력 (GUI 전송용)
                            if get_setting('bultagi_turbo_vi', False) and vi_status == '1':
                                try:
                                    from check_n_buy import ACCOUNT_CACHE
                                    if jmcode in ACCOUNT_CACHE['holdings']:
                                        print(f"📡 <font color='#f1c40f'><b>[VI발동]</b> {s_name} 보유 종목 VI 진입! (1분 50초 후 알람 예약됨)</font>")
                                except: pass

                            if get_setting('bultagi_turbo_vi', False) and vi_status in ['2', '4']:
                                print(f"🚀 <font color='#00e5ff'><b>[Turbo VI 감지]</b> {s_name} ({jmcode}) VI 해제(1h) 발생!</font>")
                                from check_n_buy import chk_n_buy
                                # [V4.2.8 Fix] 누락된 vi_type 인자 추가
                                asyncio.create_task(asyncio.to_thread(chk_n_buy, jmcode, self.token, 'SYSTEM_VI', None, 'VI해제', self.on_news_result, vi_type))

                else:
                    if tr_lower not in ['ping', 'reg']:
                        print(f"🔍 [RAW] {trnm}: {response}")

            except Exception as e:
                if not self.keep_running: break
                await asyncio.sleep(1)

    async def refresh_conditions(self, token):
        """실시간 조건식 재등록 (동적 반영)"""
        if not self.websocket: return False
        try:
            seqs = get_setting('search_seq', ['0'])
            if isinstance(seqs, str): seqs = [seqs]
            print(f"🔄 [설정변경] 감시 조건식 갱신 요청: {seqs}")
            for seq in seqs:
                await self.send_message({'trnm': 'CNSRREQ', 'seq': str(seq), 'search_type': '1', 'stex_tp': 'K'})
                await asyncio.sleep(0.1)
            return True
        except: return False

    async def _account_polling_loop(self):
        """보조적으로 계좌 정보를 갱신 (토큰 갱신 감지 포함)"""
        while self.keep_running:
            try:
                from check_n_buy import update_account_cache
                loop = asyncio.get_event_loop()
                # [v3.0.4] 갱신된 최신 토큰을 받아 본인의 토큰 속성을 업데이트함
                updated_token = await loop.run_in_executor(None, update_account_cache, self.token)
                if updated_token and updated_token != self.token:
                    print(f"🔄 [rt_search] 토큰 자동 갱신 확인 ({self.token[:5]}... -> {updated_token[:5]}...)")
                    self.token = updated_token
            except Exception as e:
                print(f"⚠️ [Polling] 에러: {e}")
            await asyncio.sleep(60)
 
    async def _ranking_update_loop(self):
        """[V4.0.2] 주기적으로 거래대금 상위 종목 캐싱 (5분 간격)
        - [v3.0.4] 토큰 만료 시 자동 갱신 시도
        """
        while self.keep_running:
            try:
                from get_setting import get_setting
                from stock_info import get_top_trading_value
                from login import fn_au10001 as get_token
                
                loop = asyncio.get_event_loop()
                codes, res_json = await loop.run_in_executor(None, get_top_trading_value, self.token)
                
                # [v3.0.4] 토큰 오류 체크 (문자열 변환 후 정교하게 비교)
                ret_code = str(res_json.get('return_code', '0')).strip()
                if ret_code not in ['0', '0000', '00000']:
                    msg = str(res_json.get('return_msg', ''))
                    # [v3.0.5] 토큰 이슈일 때만 자동 갱신 시도 
                    if 'token' in msg or 'auth' in msg or '인증' in msg:
                        print("⚠️ [Ranking] 토큰 만료 감지 -> 즉시 자동 갱신 시도")
                        new_token = await loop.run_in_executor(None, get_token)
                        if new_token:
                            self.token = new_token
                            # 갱신 후 바로 1회 재시도
                            codes, res_json = await loop.run_in_executor(None, get_top_trading_value, self.token)
                    else:
                        # 그 외 일반 서버 에러는 로그만 출력
                         print(f"<font color='#e74c3c'>[Ranking-DEBUG] ⚠️ 조회 실패 ({ret_code}): {msg}</font>")
                
                if codes:
                    rank_limit = int(get_setting('bultagi_turbo_vi_volume_rank', 100))
                    limited_codes = codes[:rank_limit]
                    
                    # [V4.0.2] [Ranking-DEBUG] 로데이터 로그 출력 (상위 50개 미리보기)
                    # [V4.2.8] 종목명 매핑 및 50위까지 확대 노출
                    data_obj = res_json.get('data', res_json)
                    items = data_obj.get('trde_prica_upper', [])
                    import re
                    # [V4.2.9] name, stk_name 등 다양한 가능성 시도 (미상 방지)
                    name_map = {}
                    for it in items:
                        c = re.sub(r'[^0-9]', '', str(it.get('stk_cd', it.get('code', ''))))[:6]
                        if not c: continue
                        name = it.get('stk_nm') or it.get('name') or it.get('stk_name') or it.get('hts_kor_isnm', '')
                        name_map[c] = name

                    display_list = []
                    for i, c in enumerate(limited_codes[:50]):
                        name = name_map.get(c, "미상")
                        display_list.append(f"{i+1}:{name}({c})")
                    
                    top50_str = ", ".join(display_list)
                    print(f"<font color='#888888'>[Ranking-DEBUG] 거래대금 {len(limited_codes)}종목 갱신완료 | Top50: {top50_str}</font>")
                    # [v4.2.5] 상세 로그창 가독성 확보를 위해 원시 데이터(Raw JSON) 출력 주석 처리
                    # print(f"[Rank Raw] {res_json}")
                    
                    # [V3.3.8] VI 필터용 set 업데이트
                    self.top_volume_set = set(limited_codes)
                    
                    # [V4.0.0] 매수/진단 엔진과 캐시 동기화 (순위 유지를 위해 list로 전달)
                    try:
                        import check_n_buy
                        # [V4.0.2] Atomic 업데이트: 새 리스트 생성 후 통째로 교체 (스레드 안전)
                        check_n_buy.TOP_VOLUME_RANK_CACHE = list(limited_codes)
                    except Exception as sync_e:
                        print(f"⚠️ [Ranking-DEBUG] 캐시 동기화 실패: {sync_e}")
                else:
                    msg = res_json.get('return_msg', '빈 응답')
                    print(f"<font color='#e74c3c'>[Ranking-DEBUG] ⚠️ 거래대금 데이터 수신 실패 ({msg})</font>")
                    
            except Exception as e:
                print(f"⚠️ [RankingCache] 갱신 오류: {e}")
            await asyncio.sleep(300)

    async def start(self, token, acnt_no=None):
        try:
            self.active_conditions.clear()
            self.token = token
            self.acnt_no = acnt_no
            from check_n_buy import update_account_cache
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, update_account_cache, token)

            self.keep_running = True
            self.list_loaded_event.clear()
            
            await self.connect(token, acnt_no=acnt_no)
            if not self.connected: return False

            self.receive_task = asyncio.create_task(self.receive_messages())
            self.polling_task = asyncio.create_task(self._account_polling_loop())
            # [V3.3.8] 랭킹 캐싱 태스크 시작
            self.ranking_task = asyncio.create_task(self._ranking_update_loop())

            print(f"🔔 실시간 체결 감시 등록...")
            acnt = self.acnt_no if self.acnt_no else ''
            # [v2.2.6] 등록 항목 정교화: 1h를 별도 그룹으로 분리하여 수신 가능성 극대화
            reg_items = [
                {'item': [''], 'type': ['00']},
                {'item': [''], 'type': ['1h']} 
            ]
            await self.send_message({'trnm': 'REG', 'grp_no': '1', 'refresh': '1', 'data': reg_items})
            
            if acnt:
                # 계좌 관련은 별도 그룹으로 등록 (상호 간섭 배제)
                reg_acc = [
                    {'item': [acnt], 'type': ['01']},
                    {'item': [acnt], 'type': ['02']}
                ]
                await self.send_message({'trnm': 'REG', 'grp_no': '2', 'refresh': '1', 'data': reg_acc})

            print("⏳ 목록 수신 대기 중...")
            try: await asyncio.wait_for(self.list_loaded_event.wait(), timeout=5.0)
            except: pass

            seqs = get_setting('search_seq', ['0'])
            if isinstance(seqs, str): seqs = [seqs]
            for seq in seqs:
                await self.send_message({'trnm': 'CNSRREQ', 'seq': str(seq), 'search_type': '1', 'stex_tp': 'K'})
                await asyncio.sleep(0.2) 
            
            print("✅ 모든 감시 등록 완료!")
            return True
        except Exception as e:
            print(f'❌ 시작 오류: {e}')
            return False

    async def disconnect(self):
        self.keep_running = False
        self.connected = False
        self.active_conditions.clear()
        if self.on_condition_loaded: self.on_condition_loaded()
        if self.websocket: await self.websocket.close()

    async def stop(self):
        if self.receive_task: self.receive_task.cancel()
        await self.disconnect()
        return True
