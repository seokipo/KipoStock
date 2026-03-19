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
        self.vi_state_cache = {} 

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
        
        # [v1.9.1] 딥 디버깅용 변수
        last_heartbeat = time.time()
        
        while self.keep_running and self.websocket:
            try:
                # [v1.9.1] 10초마다 하트비트 출력 (프로세스 생존 확인)
                if time.time() - last_heartbeat > 10:
                    print("💓 [RT-SEARCH] 감시 루프 정상 작동 중...")
                    last_heartbeat = time.time()

                raw_message = await self.websocket.recv()
                if not raw_message: continue
                
                response = json.loads(raw_message)
                trnm = response.get('trnm')

                # [v1.9.3] 로깅 다이어트: 모든 패킷 덤프 제거 (I/O 부하 방지)
                # 꼭 필요할 때만 아래 주석을 풀어서 사용
                # try:
                #     with open("rt_packet_dump.log", "a", encoding="utf-8") as f:
                #         f.write(f"[{datetime.now().strftime('%H:%M:%S.%f')}] {raw_message}\n")
                # except: pass

                # [🎰 마스터 스니퍼] 모든 메시지 수신 확인 (PING 제외)
                tr_lower = str(trnm).strip().lower() if trnm else ''
                
                if tr_lower == 'reg':
                    r_code = response.get('return_code')
                    r_msg = response.get('return_msg', '')
                    print(f"📡 [REG응답] 결과:{r_code} | 메시지:{r_msg}")

                if tr_lower == 'login':
                    if response.get('return_code') == 0:
                        print('✅ 로그인 성공 (조건식 이름 가져오는 중...)')
                        await self.send_message({'trnm': 'CNSRLST'})
                    else:
                        print(f"❌ 로그인 실패: {response.get('return_msg')}")

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

                            # [v1.9.1] VI 감지 조건 강화 및 디버깅 로그
                            is_vi_event = ('VI' in target_name or item.get('type') == '1h' or '9068' in values or '9051' in values)
                            
                            if is_vi_event:
                                # [v1.9.3] 종목 코드 정규화: _AL 등이 붙어있더라도 숫자 6자리만 추출
                                raw_jm = values.get('9001', '').replace('A', '') or item.get('item', '').replace('A', '')
                                jmcode = str(raw_jm)[:6]
                                s_name = values.get('302', jmcode)
                                
                                # [v1.9.5] 9068뿐만 아니라 1225(VI구분), 9051(해제시간) 등 다양한 필드 조합 대응
                                vi_status = str(values.get('9068', '')) # 1:발동, 2:해제, 3:중지, 4:재개
                                vi_time = values.get('9051') or values.get('1224') or "" # HHMMSS
                                vi_type = values.get('9052') or values.get('1225', '') # 1:정적, 2:동적, 3:변동성
                                vi_price = values.get('9054') or values.get('1236', '0')

                                # [v1.9.5] 강력한 상태 감지: 9068이 없더라도 해제 시간이 들어오면 '발동(1)' 또는 '해제(2)'로 추정
                                if not vi_status and vi_time:
                                    # 발동가(1236)가 있고 해제시간이 있으면 발동(1) 상태로 간주
                                    vi_status = '1' if vi_price != '0' else '2'

                                # [v1.9.5] 중복 로그 방지: 이전 상태와 동일하면 로깅 스킵
                                cache_key = f"{jmcode}_{vi_status}_{vi_time}"
                                if self.vi_state_cache.get(jmcode) == cache_key:
                                    continue
                                self.vi_state_cache[jmcode] = cache_key

                                # [v1.9.3] VI 상세 덤프 로그 (파일) - VI 이벤트만 기록하여 부하 최소화
                                # [v1.9.4] I/O 블로킹 방지를 위해 run_in_executor 사용
                                def log_vi_event(msg_line):
                                    try:
                                        with open("vi_event_debug.log", "a", encoding="utf-8") as f:
                                            f.write(msg_line)
                                    except: pass
                                
                                log_line = f"[{datetime.now().strftime('%H:%M:%S')}] {s_name}({jmcode}) | 9068:{vi_status} | {raw_message}\n"
                                loop.run_in_executor(None, log_vi_event, log_line)

                                # [v1.9.1] VI 감지 시 즉시 로우 데이터 출력 (상세 로그창으로)
                                print(f"📡 [VI-DEBUG] {s_name}({jmcode}) 수신! [9068:{vi_status}] | Time:{vi_time} | Type:{vi_type}")
                                
                                # 시간 포맷팅 (140530 -> 14:05:30)
                                time_fmt = f"{vi_time[:2]}:{vi_time[2:4]}:{vi_time[4:6]}" if len(vi_time) == 6 else vi_time
                                type_map = {'1': '정적', '2': '동적', '3': '변동성', '정적': '정적', '동적': '동적'}
                                type_txt = type_map.get(vi_type, '알수없음')

                                status_map = {'1': '발동', '2': '해제', '3': '중지', '4': '재개'}
                                st_txt = status_map.get(vi_status, vi_status)
                                
                                # 상세 정보 조합 (해제 시간, 종류, 발동가)
                                detail_info = f" | {type_txt}VI | 발동가: {int(float(vi_price)):,} | 해제예정: {time_fmt}" if vi_status == '1' else ""
                                
                                # [v1.6.1] 로우 데이터 무조건 출력 (상세 로그창 전용)
                                raw_sample = f" <font color='#888888'>(9068:{vi_status}{detail_info})</font>"
                                print(f"📡 <font color='#f1c40f'>[VI감지] {s_name}({jmcode}) 상태: {st_txt}</font>{raw_sample}")

                                if get_setting('bultagi_turbo_vi', False):
                                    # [핵심] 해제(2) 또는 재개(4) 시 즉시 매수 트리거
                                    if vi_status in ['2', '4']:
                                        # [v1.9.1] 0.5초 초단기 지연 후 주문 (안정적 체결 유도)
                                        async def delayed_vi_buy(code, name):
                                            await asyncio.sleep(0.5)
                                            print(f"🚀 <font color='#00e5ff'><b>[Turbo VI 감지]</b> {name} ({code}) VI 해제 신호 발생!</font>")
                                            from check_n_buy import chk_n_buy
                                            loop.run_in_executor(None, chk_n_buy, code, self.token, 'SYSTEM_VI', None, 'VI해제', self.on_news_result)
                                        
                                        asyncio.create_task(delayed_vi_buy(jmcode, s_name))
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
                    # [v1.9.0] 단독 1h (VI 발동/해제) TR 처리
                    # [v1.9.0 수정] TR 0w (VI 발동/해제) 데이터 처리
                    data = response.get('data')
                    if isinstance(data, list):
                        for item in data:
                            values = item.get('values') or {}
                            vi_status = str(values.get('9068', ''))
                            jmcode = (values.get('9001') or item.get('item', '')).replace('A', '')
                            s_name = values.get('302', jmcode)
                            
                            # [v1.5.8] 단독 1h 수신 시에도 로그 출력 (디버깅용)
                            if vi_status:
                                status_map = {'1': '발동', '2': '해제', '3': '중지', '4': '재개'}
                                st_txt = status_map.get(vi_status, vi_status)
                                # [v1.6.1] 1h 데이터도 로우 데이터 무조건 출력 (상세 로그창)
                                raw_sample = f" (1h_9068:{vi_status}, 9001:{jmcode})"
                                # [v1.9.0] 상세 로그창 출력을 위해 [VI감지] 태그 사용
                                print(f"📡 <font color='#f1c40f'>[VI감지] {s_name}({jmcode}) 상태: {st_txt}</font>{raw_sample}")

                            if get_setting('bultagi_turbo_vi', False) and (vi_status in ['2', '4'] or values.get('1224') == '000000'): 
                                # [v1.9.4] 1224가 000000이 아니게 변할 때를 감지하는 로직 보강 필요하지만 일단 상태값 우선
                                if vi_status in ['2', '4']:
                                    print(f"🚀 <font color='#00e5ff'><b>[Turbo VI 감지]</b> {s_name} ({jmcode}) VI 해제(1h) 발생!</font>")
                                    from check_n_buy import chk_n_buy
                                    loop.run_in_executor(None, chk_n_buy, jmcode, self.token, 'SYSTEM_VI', None, 'VI해제', self.on_news_result)

                else:
                    if tr_lower not in ['ping', 'reg']:
                        print(f"🔍 [RAW] {trnm}: {str(response)[:300]}")

                # [v1.9.0 디버그] 1h/REAL 패킷 실제 구조 덤프 (VI 진단용)
                # 모든 수신 메시지 중 9068 키가 있거나 1h인 경우 전체 출력
                # [v1.9.0 디버그] 실시간 패킷 구조 덤프
                if tr_lower in ['1h', 'real']:
                    raw_str = str(response)
                    if '9068' in raw_str or tr_lower == '1h':
                        print(f"📡 [VI-DEBUG] trnm={trnm} | 패킷: {raw_str[:500]}")

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
        """보조적으로 계좌 정보를 갱신"""
        while self.keep_running:
            try:
                from check_n_buy import update_account_cache
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, update_account_cache, self.token)
            except: pass
            await asyncio.sleep(60)

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

            print(f"🔔 실시간 체결 감시 등록...")
            acnt = self.acnt_no if self.acnt_no else ''
            reg_items = [
                {'item': [''], 'type': ['00']},
                {'item': [''], 'type': ['1h']} # [v1.9.0] VI 발동/해제 실시간 수신 (공식가이드 확인됨: 1h)
            ]
            await self.send_message({'trnm': 'REG', 'grp_no': '1', 'refresh': '1', 'data': reg_items})

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
