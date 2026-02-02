import asyncio 
import websockets
import json
from config import socket_url
from check_n_buy import chk_n_buy, update_account_cache, RECENT_ORDER_CACHE
from get_setting import get_setting
from login import fn_au10001 as get_token
from market_hour import MarketHour

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
        
        while self.keep_running and self.connected and self.websocket:
            try:
                raw_message = await self.websocket.recv()
                response = json.loads(raw_message)
                trnm = response.get('trnm')

                # --- 1. 로그인 성공 시 목록 요청 ---
                if trnm == 'LOGIN':
                    if response.get('return_code') == 0:
                        print('✅ 로그인 성공 (조건식 이름 가져오는 중...)')
                        await self.send_message({'trnm': 'CNSRLST'})
                    else:
                        print(f"❌ 로그인 실패: {response.get('return_msg')}")

                # --- 2. 조건식 목록 수신 (이름 매핑) ---
                elif trnm == 'CNSRLST':
                    raw_data = response.get('data', [])
                    # 데이터 예시: [['0', '25분 이격'], ['1', '급등주'], ...]
                    if isinstance(raw_data, list):
                        self.condition_map = {} # 초기화
                        for item in raw_data:
                            if len(item) >= 2:
                                self.condition_map[item[0]] = item[1]
                        
                        count = len(self.condition_map)
                        # print(f"📋 조건식명 {count}개 로드 완료")
                        self.list_loaded_event.set() # 목록 수신 완료 신호
                        if self.on_condition_loaded:
                            self.on_condition_loaded()

                # --- 3. [핵심] 조건검색 실시간 신호 (인터럽트 처리) ---
                elif trnm == 'CNSR':
                    data = response.get('data')
                    header = response.get('header', {})
                    
                    # [Debug] 구조 확인
                    # print(f"🔍 [CNSR_DEBUG] Header: {header}, BodyKeys: {list(response.keys())}")

                    # seq 추출 (Falsey '0' 문제 해결용 명시적 체크)
                    raw_seq = header.get('seq')
                    if raw_seq is None: raw_seq = header.get('index')
                    if raw_seq is None: raw_seq = header.get('condition_seq')
                    
                    if raw_seq is None:
                        raw_seq = response.get('seq')
                    if raw_seq is None: raw_seq = response.get('index')
                    if raw_seq is None: raw_seq = response.get('condition_seq')
                    
                    seq = str(raw_seq) if raw_seq is not None else ''

                    # [Normalization] data가 dict면 list로 변환 (먼저 수행하여 Fallback 1이 올바르게 동작하도록 함)
                    if data and isinstance(data, dict):
                        data = [data]
                    
                    # [Fallback 1] 데이터 내부에서 seq 찾기
                    if not seq and data:
                        if isinstance(data, list) and len(data) > 0:
                            # data[0]에 혹시 seq가 있는지?
                            possible = data[0].get('seq') or data[0].get('condition_seq')
                            if possible:
                                seq = str(possible)
                                # print(f"🔍 [CNSR_DEBUG] Found SEQ in data body: {seq}")

                    # [Fallback 2] 단일 조건식 감시 중이라면 그 번호로 가정
                    if not seq:
                        active_seqs = get_setting('search_seq', [])
                        if isinstance(active_seqs, str): active_seqs = [active_seqs]
                        if len(active_seqs) == 1:
                            seq = str(active_seqs[0])
                            # print(f"🔍 [CNSR_DEBUG] Fallback to single active SEQ: {seq}")
                        else:
                             # 다중 조건식인데 seq가 없으면 0번이라도 가정? (위험하지만 사용자 요청이 0번이 위주라면..)
                             # 일단은 경고만
                             print(f"⚠️ [CNSR_DEBUG] SEQ Missing in Multi-Search! Active: {active_seqs}")

                    # print(f"🔍 [CNSR_DEBUG] Extracted SEQ: '{seq}' (Name: {self.condition_map.get(seq, 'Unknown')})")
                    # [Raw Log] 구조 분석용
                    # print(f"📝 [CNSR_RAW] {raw_message}")

                    if data:
                        # [Lite V1.0] 한 번에 검출되는 종목 수를 절반으로 제한 (최소 1개)
                        orig_count = len(data)
                        data = data[:max(1, orig_count // 2)]
                        if orig_count > 1:
                            print(f"✂️ [Lite] 종목 제한: {orig_count}개 -> {len(data)}개")
                            
                        stock_list = []
                        for item in data:
                            jmcode = item.get('stk_cd') or item.get('code') or (item.get('values') or {}).get('9001')
                            if jmcode:
                                jmcode = jmcode.replace('A', '')
                                stock_list.append(jmcode)
                                if seq != '': # 00번 검색식('0')도 저장되도록 수정
                                    self.stock_origin_map[jmcode] = seq
                        
                        if stock_list:
                            print(f"📡 [검색검출] {seq}번({self.condition_map.get(seq, '이름모름')}): {', '.join(stock_list)}")

                        # 위에서 정규화된 data 사용
                        for item in data:
                            jmcode = item.get('stk_cd') or item.get('code') or (item.get('values') or {}).get('9001')
                            if jmcode:
                                # [수정] 코드 표준화 (A제거)
                                jmcode = jmcode.replace('A', '')
                                
                                # [매핑 저장] 종목의 출처(seq)를 기억
                                if seq:
                                    self.stock_origin_map[jmcode] = seq
                                    # print(f"💾 [Origin] Saved: {jmcode} -> Seq {seq}")
                                
                                # [신규] 가격 데이터 추출 시도 (CNSR는 보통 가격이 없을 수 있음, 있으면 추출)
                                trade_price = None
                                if isinstance(item, dict):
                                    # CNSR 메시지 구조에 따라 다르지만 보통 'now_prc'나 'stk_prc'
                                    trade_price = item.get('now_prc') or item.get('match_prc')

                                # 검색식 명칭 추출
                                seq_name = self.condition_map.get(seq, "이름모름") if seq else "출처불명"

                                # [신규] 매매 가능 시간인지 최종 확인 (3중 방어)
                                if not MarketHour.is_waiting_period():
                                    # 즉시 매수 스레드로 던짐 (seq, price 전달)
                                    loop.run_in_executor(None, chk_n_buy, jmcode, self.token, seq, trade_price, seq_name)
                                else:
                                    pass # print(f"⏳ [대외시간] {jmcode} 매수 건너뜀 (설정 시간 외)")
                
                # --- 6. 실시간 체결 처리 (HTS 매매 즉시 감지용) ---
                elif trnm == 'RSCN': 
                    data = response.get('data')
                    if isinstance(data, list):
                        for item in data:
                            values = item.get('values') or {}
                            jmcode = values.get('1001', '').replace('A', '') # 종목코드
                            tp = values.get('8030') # 2: 매수, 1: 매도
                            tm = values.get('8031') # 체결시각 (HHMMSS)
                            price = values.get('1002', '0') # 체결가
                            qty = values.get('1004', '0')  # 체결량
                            
                            if jmcode:
                                # 시간 포맷 (HH:MM:SS)
                                f_time = f"{tm[:2]}:{tm[2:4]}:{tm[4:]}" if tm and len(tm) == 6 else ""
                                s_name = self.condition_map.get(jmcode, jmcode)
                                
                                # 포맷팅 (가격/수량)
                                try: price_f = f"{int(price):,}"
                                except: price_f = price
                                
                                # [사용자 요청] 노란색 강조 및 직접매매 표시
                                icon = "⚡" if tp == '2' else "🔥"
                                status_txt = "[매수체결]" if tp == '2' else "[매도체결]"
                                log_color = "#ffc107" # 노란색 (Yellow)
                                
                                log_msg = f"<font color='{log_color}'>{icon} <b>{status_txt}</b> {s_name} ({price_f}원/{qty}주) [직접매매]</font>"
                                print(log_msg)
                                
                                # 폴링 로그 중복 방지를 위해 캐시 업데이트
                                RECENT_ORDER_CACHE[jmcode] = time.time()
                                
                                if tp == '2': # 매수 시에만 처리
                                    # 저장 로직 호출
                                    from check_n_buy import save_buy_time, update_stock_condition, RECENT_ORDER_CACHE
                                    if f_time:
                                        # [중복방지] HTS 매수 감지 시 즉시 캐시 업데이트하여 자동 매수 차단
                                        RECENT_ORDER_CACHE[jmcode] = time.time()
                                        save_buy_time(jmcode, f_time)
                                        update_stock_condition(jmcode, name='직접매매', strat='HTS', time_val=f_time)
                                    
                                    from tel_send import tel_send
                                    tel_send(f"🕵️ [HTS매수] {s_name} ({f_time}) {price_f}원/{qty}주")
                                else: # 매도 시
                                    from tel_send import tel_send
                                    tel_send(f"🕵️ [HTS매도] {s_name} ({f_time}) {price_f}원/{qty}주")

                # --- 4. 기타 메시지 ---
                elif trnm == 'REAL':
                    data = response.get('data')
                    if isinstance(data, list):
                        for item in data:
                            # [신규] 주문체결 REAL 메시지 감지 (dostk 서버 특성 반영)
                            if item.get('name') == '주문체결':
                                values = item.get('values') or {}
                                jmcode = values.get('9001', '').replace('A', '')
                                s_name = values.get('302', jmcode)
                                order_type = values.get('905', '') # 예: '+매수', '-매도'
                                order_stat = values.get('913', '') # 예: '접수', '체결'
                                qty = values.get('900', '0')
                                
                                # 매수/매도 구분
                                is_buy = '매수' in order_type
                                tag = "[HTS매수]" if is_buy else "[HTS매도]"
                                color = "#ffc107" if is_buy else "#00b0f0" # 노랑 vs 파랑
                                
                                # 로그 출력 (접수 등은 생략하고 체결만 출력)
                                if '체결' in order_stat:
                                    print(f"<font color='{color}'>⚡ <b>{tag}</b> {s_name} ({order_stat}) {qty}주 [실시간]</font>")
                                
                                # 캐시 업데이트 (Polling 중복 방지)
                                from check_n_buy import RECENT_ORDER_CACHE, save_buy_time, update_stock_condition
                                RECENT_ORDER_CACHE[jmcode] = time.time()
                                
                                if is_buy and '체결' in order_stat:
                                    save_buy_time(jmcode)
                                    update_stock_condition(jmcode, name='직접매매', strat='HTS')
                                continue

                            jmcode = (item.get('values') or {}).get('9001')
                            if jmcode:
                                # [수정] 코드 표준화 (A제거)
                                jmcode = jmcode.replace('A', '')
                                
                                origin_seq = self.stock_origin_map.get(jmcode)
                                
                                # [Log] REAL 신호 수신 로깅 (너무 잦을 수 있으므로 주석 처리하거나 필요 시 해제)
                                # print(f"🔄 [REAL] 수신: {jmcode} (Origin: {origin_seq})")
                                
                                # [신규] 실시간 체결가 추출 (REAL 메시지 values['10'] = 현재가)
                                trade_price = None
                                values = item.get('values')
                                if values and isinstance(values, dict):
                                    raw_price = values.get('10')
                                    if raw_price:
                                        trade_price = abs(int(float(raw_price)))
                                    
                                    # [핵심] 실시간 조건검색 신호(841)에서 seq 추출 시도
                                    real_seq = values.get('841')
                                    if real_seq:
                                        origin_seq = str(real_seq)
                                        # print(f"🎯 [REAL] Found Sequential ID 841: {origin_seq}")

                                # 이름 결정
                                if origin_seq and origin_seq != "N/A":
                                    seq_name = self.condition_map.get(origin_seq, "이름모름")
                                else:
                                    seq_name = "실시간감시" 
                                    origin_seq = "N/A"

                                # [신규] 매매 가능 시간인지 최종 확인 (3중 방어)
                                if not MarketHour.is_waiting_period():
                                    loop.run_in_executor(None, chk_n_buy, jmcode, self.token, origin_seq, trade_price, seq_name)
                                else:
                                    # REAL 신호는 너무 잦으므로 로그 생략
                                    pass

                elif trnm == 'CNSRREQ':
                    rc = response.get('return_code', 0)
                    seq = str(response.get('seq'))
                    # 이름 찾기
                    name = self.condition_map.get(seq, '')
                    
                    if str(rc) in ['0', '1']:
                         # [신규] 활성 목록에 추가하고 GUI 갱신 요청
                         if seq not in self.active_conditions:
                             self.active_conditions.add(seq)
                             if self.on_condition_loaded: self.on_condition_loaded()
                         # print(f"✅ 등록: {seq}번({name})")
                         pass
                    elif str(rc) == '900002':
                        # [신규] 실패 시 목록에서 제거
                        if seq in self.active_conditions:
                            self.active_conditions.discard(seq)
                            if self.on_condition_loaded: self.on_condition_loaded()
                        print(f"⛔ [등록실패] {seq}번({name}): 동시 감시 한도(10개) 초과! (증권사 정책)")
                    else:
                        print(f"⚠️ 실패: {seq}번 {response}")

                elif trnm == 'PING':
                    await self.send_message(response)

                else:
                    # [Lite V1.2] 신호 탐지 모드: PING, REG 외 모든 신호 로그 출력
                    if trnm not in ['PING', 'REG']:
                        print(f"🔍 [RAW] {trnm}: {response}")

                    # [Debug] 모르는 trnm 수신 시 로그
                    if trnm not in ['LOGIN', 'CNSRLST', 'CNSR', 'REAL', 'CNSRREQ', 'PING', 'REG']:
                        pass # 위에서 이미 출력함

            except websockets.ConnectionClosed:
                print("⚠️ [소켓] 서버와의 연결이 종료되었습니다.")
                self.connected = False
                if self.on_connection_closed:
                    await self.on_connection_closed()
                break
            except Exception as e:
                # [신규] 윈도우 소켓 강제종료 등 치명적 오류 감지 시 재연결 시도
                err_str = str(e)
                if "10054" in err_str or "closed" in err_str.lower():
                    print(f"❌ [소켓] 치명적 오류 감지: {e}")
                    self.connected = False
                    if self.on_connection_closed:
                        await self.on_connection_closed()
                    break

                if not self.connected: break
                continue

    async def refresh_conditions(self, token):
        """실시간 조건식 재등록 (동적 반영)"""
        if not self.connected or not self.websocket:
            return False
            
        try:
            # 1. 최신 설정 로드
            seqs = get_setting('search_seq', ['0'])
            if isinstance(seqs, str): seqs = [seqs]
            
            print(f"🔄 [설정변경] 감시 조건식 갱신 요청: {seqs}")
            
            # 2. 새로운 목록에 대해 등록 요청
            for seq in seqs:
                str_seq = str(seq)
                name = self.condition_map.get(str_seq, '이름모름')
                
                req_data = { 
                    'trnm': 'CNSRREQ', 
                    'seq': str_seq, 
                    'search_type': '1', # 1: 등록
                    'stex_tp': 'K'
                }
                await self.send_message(req_data)
                print(f'📡 [재요청] {str_seq}번: {name}')
                await asyncio.sleep(0.1)
                
            return True
        except Exception as e:
            print(f"❌ 조건식 갱신 실패: {e}")
            return False

    async def _account_polling_loop(self):
        """[신규] 보조적으로 계좌 정보를 갱신 (주기 연장)"""
        # chat_command가 5초마다 하므로 여기선 60초마다 보조적으로만 수행
        while self.keep_running and self.connected:
            try:
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, update_account_cache, self.token)
            except: pass
            await asyncio.sleep(60)

    async def start(self, token, acnt_no=None):
        try:
            self.active_conditions.clear() # [신규] 시작 시 초기화
            self.token = token
            self.acnt_no = acnt_no
            print("💰 계좌 정보 로딩...")
            
            # [수정] 블로킹 I/O를 스레드로 분리하여 GUI 프리징 방지
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, update_account_cache, token)

            self.keep_running = True
            self.list_loaded_event.clear() # 이벤트 초기화
            
            await self.connect(token, acnt_no=acnt_no)
            if not self.connected: return False

            self.receive_task = asyncio.create_task(self.receive_messages())
            
            # [신규] 계좌 폴링 태스크 시작
            self.polling_task = asyncio.create_task(self._account_polling_loop())

            # [신규] 실시간 체결(주문체결) 등록 - HTS 매매 즉시 감지용
            # 계좌번호(acnt_no)가 있으면 그걸로 등록
            reg_item = self.acnt_no if self.acnt_no else ''
            print(f"🔔 실시간 체결 감시 등록... (계좌: {reg_item if reg_item else '전체'})")
            # [수정] 계좌번호 미지정 시 item 필드 생략 (전체 감시 시도)
            reg_payload_data = {'type': ['00']}
            if reg_item:
                reg_payload_data['item'] = [reg_item]

            await self.send_message({ 
                'trnm': 'REG', 
                'grp_no': '1', 
                'refresh': '1', 
                'data': [reg_payload_data]
            })

            # 목록(이름)을 받아올 때까지 최대 5초 대기
            print("⏳ 목록 수신 대기 중 (최대 5초)...")
            try:
                await asyncio.wait_for(self.list_loaded_event.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                print("⚠️ 목록 수신 시간 초과 (이름 없이 진행합니다)")

            seqs = get_setting('search_seq', ['0'])
            if isinstance(seqs, str): seqs = [seqs]
            
            print(f"🚀 {len(seqs)}개 조건식 고속 등록 시작...")
            
            for seq in seqs:
                str_seq = str(seq)
                name = self.condition_map.get(str_seq, '이름모름')
                
                req_data = { 
                    'trnm': 'CNSRREQ', 
                    'seq': str_seq, 
                    'search_type': '1', 
                    'stex_tp': 'K'
                }
                await self.send_message(req_data)
                
                # 로그에 이름 표시
                print(f'📡 [요청] {str_seq}번: {name}')
                
                # [속도 향상] 1초 -> 0.2초 (안정화되었으므로 빠르게!)
                await asyncio.sleep(0.2) 
            
            print("✅ 모든 감시 등록 완료! (대기 중)")
            return True
        except Exception as e:
            print(f'❌ 시작 오류: {e}')
            return False

    async def disconnect(self):
        self.keep_running = False
        self.connected = False
        self.active_conditions.clear() # [신규] 종료 시 초기화
        if self.on_condition_loaded: self.on_condition_loaded()
        if self.websocket:
            await self.websocket.close()

    async def stop(self):
        if self.receive_task:
            self.receive_task.cancel()
        await self.disconnect()
        # print('🛑 중지됨.') # [제거] 불필요한 로그 노이즈 제거
        return True