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
from check_n_buy import update_vi_cache # [v5.1.33] 전역 VI 캐시 업데이트용

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
        
        # [V5.3.3] VI 알람 예약 캐시 (중복 방지)
        self._vi_alarm_keys = set()

    async def connect(self, token, acnt_no=None):
        try:
            self.token = token
            self.acnt_no = acnt_no
            self.websocket = await websockets.connect(self.socket_url, ping_interval=20, ping_timeout=20)
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

    async def _schedule_vi_alarm(self, jmcode, name, trigger_time):
        """[V5.3.3] VI 해제 10초 전 알람 예약 및 실행 (110초 대기)"""
        alarm_key = f"{jmcode}_{trigger_time}"
        if alarm_key in self._vi_alarm_keys:
            return
        
        self._vi_alarm_keys.add(alarm_key)
        
        # [진단] 알람 예약 로그
        print(f"⏰ <font color='#f1c40f'><b>[알람예약]</b> {name}({jmcode}) VI 해제 10초 전 알람 예약됨 ({trigger_time} 발동)</font>")
        
        # 110초 대기 (표준 120초 VI - 10초 버퍼)
        await asyncio.sleep(110)
        
        try:
            from check_n_buy import ACCOUNT_CACHE, say_text
            # 알람 시점에 아직 보유 중인지 최종 확인
            if jmcode in ACCOUNT_CACHE['holdings']:
                alert_msg = f"{name} VI 해제 10초 전입니다."
                say_text(alert_msg)
                print(f"📢 <font color='#f1c40f'><b>[VI알람]</b> {alert_msg}</font>")
                tel_send(f"🔔 [VI알람] {alert_msg}")
            else:
                print(f"ℹ️ <font color='#888888'>[알람취소] {name}({jmcode}) 매도 완료되어 VI 알람을 취소합니다.</font>")
        except Exception as e:
            print(f"⚠️ VI 알람 실행 실패: {e}")
        finally:
            # 5분 후 캐시에서 제거 (다음 VI를 위해)
            await asyncio.sleep(300)
            self._vi_alarm_keys.discard(alarm_key)

    async def receive_messages(self):
        """인터럽트형 고속 수신 처리"""
        loop = asyncio.get_event_loop()
        print("👀 [감시모드] 초고속 수신 대기 중...")
        
        def _passes_vi_filter(name, v_price, v_type, code):
            if not get_setting('bultagi_turbo_vi', False): return False
            try:
                if get_setting('bultagi_turbo_vi_volume_enabled', False):
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
                        if '8005' in ret_code or 'Token' in ret_msg or '유효하지' in ret_msg:
                            self.auth_error_detected = True 
                            self.connected = False
                            if self.websocket: await self.websocket.close()
                            break 

                elif trnm == 'CNSRLST':
                    raw_data = response.get('data', [])
                    if isinstance(raw_data, list):
                        self.condition_map = {}
                        for item in raw_data:
                            if len(item) >= 2:
                                self.condition_map[str(item[0])] = item[1]
                        self.list_loaded_event.set()
                        if self.on_condition_loaded: self.on_condition_loaded()

                elif tr_lower == 'cnsr':
                    header = response.get('header', {})
                    data = response.get('data')
                    raw_seq = header.get('seq') or header.get('index') or header.get('condition_seq') or response.get('seq')
                    seq = str(raw_seq) if raw_seq is not None else ''

                    if seq and seq not in self.active_conditions:
                        continue

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
                                    from check_n_buy import chk_n_buy
                                    loop.run_in_executor(None, chk_n_buy, jmcode, self.token, seq, trade_price, seq_name, self.on_news_result)

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

                            vi_status_raw = values.get('9068') or values.get('1225') 
                            vi_time_raw = values.get('9051') or values.get('1224') 
                            
                            is_vi_event = ('VI' in target_name or item.get('type') == '1h' or vi_status_raw or vi_time_raw)
                            
                            if is_vi_event:
                                raw_jm = values.get('9001', '').replace('A', '') or item.get('item', '').replace('A', '')
                                jmcode = str(raw_jm)[:6]
                                s_name = values.get('302', jmcode)
                                
                                vi_status = str(values.get('9068', '')) 
                                vi_time = values.get('9051') or values.get('1224')
                                if not vi_time or vi_time == '000000':
                                    vi_time = values.get('1223') or ""
                                
                                vi_type = values.get('9052') or values.get('1225', '') or str(values.get('9069', '')) 
                                vi_price = values.get('9054') or values.get('1236', '0')

                                if not vi_status and vi_time:
                                    vi_status = '1' if (vi_price != '0' and vi_price != '') else '2'

                                def add_2min(t_str):
                                    if not t_str or len(t_str) != 6: return t_str
                                    try:
                                        h, m, s = int(t_str[:2]), int(t_str[2:4]), int(t_str[4:6])
                                        total = (h * 3600 + m * 60 + s + 120) % 86400
                                        return f"{total//3600:02d}{(total%3600)//60:02d}{total%60:02d}"
                                    except: return t_str

                                cache_key = f"{jmcode}_{vi_status}_{vi_time}"
                                last_val = self.vi_state_cache.get(jmcode, "") 
                                if last_val == cache_key:
                                    continue
                                
                                if vi_status == '1' and last_val:
                                    try:
                                        parts = last_val.split('_')
                                        if len(parts) >= 3:
                                            last_st, last_t = parts[1], parts[2]
                                            if last_st == '1' and len(vi_time) == 6 and len(last_t) == 6:
                                                dt = (int(vi_time[:2])*3600 + int(vi_time[2:4])*60 + int(vi_time[4:6])) - \
                                                     (int(last_t[:2])*3600 + int(last_t[2:4])*60 + int(last_t[4:6]))
                                                if dt >= 110: vi_status = '2' 
                                            
                                            if last_st == '2' and vi_status == '1':
                                                rel_data = self.vi_release_cache.get(jmcode)
                                                if rel_data:
                                                    last_rel_sys_t, last_rel_vi_t = rel_data
                                                    if (time.time() - last_rel_sys_t) < 5 and vi_time == last_rel_vi_t:
                                                        continue
                                    except: pass

                                if vi_status == '2': self.vi_release_cache[jmcode] = (time.time(), vi_time)
                                self.vi_state_cache[jmcode] = f"{jmcode}_{vi_status}_{vi_time}"
                                
                                # [v5.1.33] 전역 VI 캐시 업데이트 (매수 차단 필터용)
                                update_vi_cache(jmcode, vi_status)

                                if vi_status:
                                    status_map = {'1': '발동', '2': '해제', '3': '중지', '4': '재개'}
                                    st_txt = status_map.get(vi_status, vi_status)
                                    release_time_raw = add_2min(vi_time) if vi_status == '1' else vi_time
                                    time_fmt = f"{release_time_raw[:2]}:{release_time_raw[2:4]}:{release_time_raw[4:6]}" if len(release_time_raw) == 6 else release_time_raw
                                    
                                    type_map = {'1': '정적', '2': '동적', '3': '변동성', '정적': '정적', '동적': '동적'}
                                    vi_type_txt = type_map.get(vi_type, "알수없음")
                                    detail_info = f" | {vi_type_txt}VI | 발동가: {int(float(vi_price or 0)):,} | 해제예정: {time_fmt}" if vi_status == '1' else ""
                                    
                                    tag = "[VI발동]" if vi_status == '1' else "[VI감지]"
                                    raw_sample = f" <font color='#888888'>(9068:{vi_status}{detail_info})</font>"
                                    print(f"📡 <font color='#f1c40f'><b>{tag}</b> {s_name} 상태: {st_txt}</font>{raw_sample}")

                                    # [V5.3.4] 보유 종목 알람은 전략 필터링과 무관하게 최우선 실행 🚀
                                    if vi_status == '1':
                                        from check_n_buy import ACCOUNT_CACHE
                                        target_code = str(jmcode).strip()
                                        if target_code in ACCOUNT_CACHE['holdings']:
                                            asyncio.create_task(self._schedule_vi_alarm(target_code, s_name, vi_time))

                                if not _passes_vi_filter(s_name, vi_price, vi_type, jmcode): continue

                                # [Turbo VI] 자동 추매 로직 (설정 및 필터 통과 시에만)
                                if get_setting('bultagi_turbo_vi', False):
                                    if vi_status in ['2', '4']:
                                        s_name = values.get('302', jmcode)
                                        print(f"🚀 <font color='#00e5ff'><b>[Turbo VI 감지]</b> {s_name} ({jmcode}) {vi_type_txt} VI 해제 신호 발생!</font>")
                                        from check_n_buy import chk_n_buy
                                        loop.run_in_executor(None, chk_n_buy, jmcode, self.token, 'SYSTEM_VI', None, 'VI해제', self.on_news_result, vi_type)
                                continue

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
                                    from check_n_buy import chk_n_buy
                                    loop.run_in_executor(None, chk_n_buy, jmcode, self.token, origin_seq, trade_price, seq_name, self.on_news_result)
                                
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

                elif tr_lower == '1h':
                    data = response.get('data')
                    if isinstance(data, list):
                        for item in data:
                            values = item.get('values') or {}
                            raw_item_id = item.get('item', '')
                            jmcode = (values.get('9001') or raw_item_id or '').replace('A', '')[:6]
                            s_name = values.get('302', jmcode)
                            vi_status = str(values.get('9068', ''))
                            vi_time = values.get('9051') or values.get('1224') or ""
                            vi_type = values.get('9052') or values.get('1225', '') or str(values.get('9069', ''))
                            vi_price = values.get('9054') or values.get('1236', '0')
                            
                            if not vi_status and vi_time:
                                vi_status = '1' if (vi_price != '0' and vi_price != '') else '2'

                            if not _passes_vi_filter(s_name, vi_price, vi_type, jmcode): continue
                            
                            cache_key = f"{jmcode}_{vi_status}_{vi_time}"
                            if self.vi_state_cache.get(jmcode) == cache_key: continue
                            self.vi_state_cache[jmcode] = cache_key
                            
                            # [v5.1.33] 전역 VI 캐시 업데이트 (매수 차단 필터용 - 1h 데이터 대응)
                            update_vi_cache(jmcode, vi_status)

                            if vi_status or vi_time:
                                tag = "[VI발동]" if vi_status == '1' else "[VI감지]"
                                print(f"📡 <font color='#f1c40f'><b>{tag}</b> {s_name} ({vi_time})</font>")

                            if get_setting('bultagi_turbo_vi', False) and vi_status == '1':
                                from check_n_buy import ACCOUNT_CACHE
                                if str(jmcode).strip() in ACCOUNT_CACHE['holdings']:
                                    print(f"📡 <font color='#f1c40f'><b>[VI인식]</b> {s_name} 보유 확인!</font>")

                            if get_setting('bultagi_turbo_vi', False) and vi_status in ['2', '4']:
                                from check_n_buy import chk_n_buy
                                asyncio.create_task(asyncio.to_thread(chk_n_buy, jmcode, self.token, 'SYSTEM_VI', None, 'VI해제', self.on_news_result, vi_type))

            except Exception as e:
                if not self.keep_running: break
                await asyncio.sleep(1)

    async def add_realtime_codes(self, codes):
        if not self.websocket or not self.connected: return False
        try:
            if not codes: return False
            unique_codes = list(set([str(c).replace('A', '') for c in codes if c]))[:100]
            print(f"📡 [실시간감시] {len(unique_codes)}종목 동적 등록 요청...")
            reg_items = [{'item': [code], 'type': ['00']} for code in unique_codes]
            await self.send_message({'trnm': 'REG', 'grp_no': '3', 'refresh': '1', 'data': reg_items})
            return True
        except: return False

    async def refresh_conditions(self, token):
        if not self.websocket: return False
        try:
            seqs = get_setting('search_seq', ['0'])
            if isinstance(seqs, str): seqs = [seqs]
            for seq in seqs:
                await self.send_message({'trnm': 'CNSRREQ', 'seq': str(seq), 'search_type': '1', 'stex_tp': 'K'})
                await asyncio.sleep(0.1)
            return True
        except: return False

    async def _account_polling_loop(self):
        while self.keep_running:
            try:
                from check_n_buy import update_account_cache
                loop = asyncio.get_event_loop()
                updated_token = await loop.run_in_executor(None, update_account_cache, self.token)
                if updated_token and updated_token != self.token: self.token = updated_token
            except: pass
            await asyncio.sleep(60)

    async def sync_ranking_cache(self):
        """[V5.1.29] 거래대금 상위 종목 캐시 즉시 갱신"""
        try:
            from get_setting import get_setting
            from stock_info import get_top_trading_value
            from login import fn_au10001 as get_token
            loop = asyncio.get_event_loop()
            codes, res_json = await loop.run_in_executor(None, get_top_trading_value, self.token)
            ret_code = str(res_json.get('return_code', '0')).strip()
            if ret_code not in ['0', '0000', '00000']:
                msg = str(res_json.get('return_msg', ''))
                if 'token' in msg or 'auth' in msg or '인증' in msg:
                    new_token = await loop.run_in_executor(None, get_token)
                    if new_token:
                        self.token = new_token
                        codes, res_json = await loop.run_in_executor(None, get_top_trading_value, self.token)
            if codes:
                rank_limit = int(get_setting('bultagi_turbo_vi_volume_rank', 100))
                self.top_volume_set = set(codes[:rank_limit])
                import check_n_buy
                check_n_buy.TOP_VOLUME_RANK_CACHE = list(codes[:rank_limit])
                print(f"✅ [Ranking-Sync] 거래대금 {len(self.top_volume_set)}종목 캐시 갱신 완료")
                return True
        except Exception as e:
            print(f"⚠️ [Ranking-Sync] 갱신 오류: {e}")
        return False

    async def _ranking_update_loop(self):
        while self.keep_running:
            await self.sync_ranking_cache()
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
            self.ranking_task = asyncio.create_task(self._ranking_update_loop())
            acnt = self.acnt_no if self.acnt_no else ''
            reg_items = [{'item': [''], 'type': ['00']}, {'item': [''], 'type': ['1h']}]
            await self.send_message({'trnm': 'REG', 'grp_no': '1', 'refresh': '1', 'data': reg_items})
            if acnt:
                reg_acc = [{'item': [acnt], 'type': ['01']}, {'item': [acnt], 'type': ['02']}]
                await self.send_message({'trnm': 'REG', 'grp_no': '2', 'refresh': '1', 'data': reg_acc})
            try: await asyncio.wait_for(self.list_loaded_event.wait(), timeout=5.0)
            except: pass
            seqs = get_setting('search_seq', ['0'])
            if isinstance(seqs, str): seqs = [seqs]
            for seq in seqs:
                await self.send_message({'trnm': 'CNSRREQ', 'seq': str(seq), 'search_type': '1', 'stex_tp': 'K'})
                await asyncio.sleep(0.2) 
            print("✅ 모든 감시 등록 완료!")
            return True
        except: return False

    async def stop_all_monitoring(self):
        if not self.websocket or not self.connected: return
        try:
            active_list = list(self.active_conditions)
            if not active_list: return
            for seq in active_list:
                await self.send_message({'trnm': 'CNSRREQ', 'seq': str(seq), 'search_type': '2', 'stex_tp': 'K'})
                await asyncio.sleep(0.05)
            self.active_conditions.clear()
        except: pass

    async def disconnect(self):
        self.keep_running = False
        self.connected = False
        await self.stop_all_monitoring()
        self.active_conditions.clear()
        if self.on_condition_loaded: self.on_condition_loaded()
        if self.websocket: await self.websocket.close()

    async def stop(self):
        if self.receive_task: self.receive_task.cancel()
        await self.disconnect()
        return True
