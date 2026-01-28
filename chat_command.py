import json
import os
import sys
import asyncio
import time
from datetime import datetime
from rt_search import RealTimeSearch
from tel_send import tel_send as real_tel_send
# 기본 tel_send는 GUI에서 패치될 수 있으므로 별도 정의 (GUI 로그용)
def tel_send(msg):
    real_tel_send(msg)

def log_and_tel(msg, parse_mode=None):
    """GUI 로그와 텔레그램 모두에 전송 (중요 이벤트용)"""
    tel_send(msg) # GUI 로그 (패치됨)
    real_tel_send(msg, parse_mode=parse_mode) # 진짜 텔레그램
from check_n_sell import chk_n_sell
from acc_val import fn_kt00004
from market_hour import MarketHour
from get_seq import get_condition_list
from check_n_buy import ACCOUNT_CACHE
from check_bal import fn_kt00001 as get_balance
from acc_val import fn_kt00004 as get_my_stocks
from acc_realized import fn_kt00006 as get_realized_pnl
from acc_diary import fn_ka10170 as get_trade_diary, fn_ka10077 as get_realized_detail
from login import fn_au10001
import pandas as pd

class ChatCommand:
    def __init__(self):
        self.rt_search = RealTimeSearch(on_connection_closed=self._on_connection_closed)
        
        # [수정] 경로 설정 로직 변경
        if getattr(sys, 'frozen', False):
            # EXE 실행 시
            self.script_dir = os.path.dirname(sys.executable)
        else:
            # 파이썬 실행 시
            self.script_dir = os.path.dirname(os.path.abspath(__file__))
            
        self.settings_file = os.path.join(self.script_dir, 'settings.json')
        self.stock_conditions_file = os.path.join(self.script_dir, 'stock_conditions.json')
        self.config_file = os.path.join(self.script_dir, 'config.py')
        self.data_dir = os.path.join(self.script_dir, 'LogData')
        if not os.path.exists(self.data_dir):
            try: os.makedirs(self.data_dir)
            except: pass
        
        self.check_n_sell_task = None
        self.account_sync_task = None
        self.token = None
        self.is_starting = False # [신규] 중복 시작(R10001) 방지용 플래그
        
        # [신규] 원격/명령어 인터페이스를 위한 콜백
        self.on_clear_logs = None # [신규] GUI 로그 초기화 콜백
        self.on_request_log_file = None # [신규] 로그 파일 저장 요청 콜백
        self.on_auto_sequence = None # [신규] 시퀀스 자동 시작 콜백
        self.on_condition_loaded = None # [신규] 목록 로드 완료 콜백
        self.on_start = None # [신규] 엔진 시작 성공 콜백
        self.on_stop = None # [신규] 엔진 정지 콜백
        
        # [신규] 시작/중지 요청 콜백 (GUI를 거쳐 실행되도록)
        self.on_start_request = None
        self.on_stop_request = None
        
        # [신규] rt_search의 콜백을 wrapper로 연결
        self.rt_search.on_condition_loaded = self._on_condition_loaded_wrapper

    def _on_condition_loaded_wrapper(self):
        if self.on_condition_loaded:
            self.on_condition_loaded()

    def get_token(self):
        """새로운 토큰을 발급받고 모든 모듈에 강제 동기화합니다."""
        try:
            token = fn_au10001()
            if token:
                self.token = token
                if self.rt_search:
                    self.rt_search.token = token
                print(f"✅ 새로운 토큰 발급 및 동기화 완료: {token[:10]}...")
                return token
            return None
        except Exception as e:
            print(f"❌ 토큰 발급 중 오류: {e}")
            return None

    async def _account_sync_loop(self):
        """계좌 정보를 메모리에 동기화하며 인증 에러 시 즉시 재시도합니다."""
        print("🔄 계좌 동기화 루프 가동 시작 (로그 최소화 모드)")
        while self.rt_search.keep_running:
            try:
                if not self.token:
                    self.get_token()
                    await asyncio.sleep(2)

                loop = asyncio.get_event_loop()
                try:
                    # [수정됨] quiet=True 옵션 추가하여 로그 숨김
                    balance_raw = await loop.run_in_executor(None, get_balance, 'N', '', self.token, True)
                    stocks_data = await loop.run_in_executor(None, get_my_stocks, False, 'N', '', self.token)
                    
                    if balance_raw is not None and isinstance(stocks_data, list):
                        ACCOUNT_CACHE['balance'] = int(balance_raw)
                        ACCOUNT_CACHE['holdings'] = {s['stk_cd'].replace('A', '') for s in stocks_data}
                        ACCOUNT_CACHE['last_update'] = time.time()
                except Exception as api_err:
                    err_msg = str(api_err)
                    if any(x in err_msg for x in ['8005', 'Token', 'entr', 'Invalid']):
                        print(f"⚠️ 인증 실패 감지: 토큰을 재발급합니다.")
                        self.get_token()
                        await asyncio.sleep(2)
                        continue 
            except Exception as e:
                print(f"⚠️ 계좌 동기화 루프 예외: {e}")
            await asyncio.sleep(5.0)

    async def _check_n_sell_loop(self):
        """매도 체크 루프"""
        failure_count = 0
        while self.rt_search.keep_running:
            try:
                if MarketHour.is_waiting_period():
                    await asyncio.sleep(0.5)
                    continue

                if not self.token: 
                    await asyncio.sleep(1)
                    continue
                    
                success = await asyncio.get_event_loop().run_in_executor(None, chk_n_sell, self.token)
                failure_count = 0 if success else failure_count + 1
                
                if failure_count >= 20:
                    print("⚠️ 매도 루프 연속 실패로 재시작 시도")
                    break 
                
                # [최적화] CPU 점유율 과다 방지를 위해 0.5초 대기 (초고속 성능 유지와 부하 균형)
                await asyncio.sleep(0.5) 
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"⚠️ 매도 루프 에러: {e}")
                await asyncio.sleep(1) # 에러 시 잠시 대기
                failure_count += 1
            await asyncio.sleep(0.1)

    async def start(self, profile_info=None):
        """시스템 시작"""
        if self.is_starting:
            print("⏳ [알람] 이미 엔진을 시작하는 중입니다. 중복 요청을 무시합니다.")
            return False
            
        try:
            self.is_starting = True
            await self._cancel_tasks()
            
            # [Fix] 중복 로그인(R10001) 방지: 기존 소켓이 열려있다면 닫고 시작
            if self.rt_search.connected or self.rt_search.websocket:
                print("🔄 [재접속] 기존 연결을 정리하고 새로 시작합니다...")
                await self.rt_search.stop()
                await asyncio.sleep(2.0) # 세션 정리 대기 시간 추가 증가 (1.5 -> 2.0)

            token = self.get_token()
            if not token:
                log_and_tel("❌ 토큰 발급 실패")
                self.is_starting = False # Ensure flag is reset on failure
                return False
            
            self.update_setting('auto_start', True)
            if MarketHour.is_waiting_period():
                now_str = datetime.now().strftime('%H:%M:%S')
                print(f"⚠️ [거부] 설정된 매매 시간이 아닙니다. (현재: {now_str})")
                self.is_starting = False # Ensure flag is reset on failure
                return False
            
            loop = asyncio.get_event_loop()
            try:
                balance_raw = await loop.run_in_executor(None, get_balance, 'N', '', token, True)
                stocks_data = await loop.run_in_executor(None, get_my_stocks, False, 'N', '', token)
                
                if balance_raw is not None and isinstance(stocks_data, list):
                    ACCOUNT_CACHE['balance'] = int(balance_raw)
                    ACCOUNT_CACHE['holdings'] = {s['stk_cd'].replace('A', '') for s in stocks_data}
                    ACCOUNT_CACHE['last_update'] = time.time()
                    print(f"✅ 계좌 정보 초기화 완료: 잔고 {ACCOUNT_CACHE['balance']:,}원, 보유 종목 {len(ACCOUNT_CACHE['holdings'])}개")
            except Exception as e:
                print(f"⚠️ 계좌 정보 초기화 중 오류: {e} - 계속 진행합니다.")
            
            success = await self.rt_search.start(token)
            if success:
                self.check_n_sell_task = asyncio.create_task(self._check_n_sell_loop())
                self.account_sync_task = asyncio.create_task(self._account_sync_loop())
                log_and_tel(f"🚀 실시간 감시 엔진 {profile_info if profile_info else '기본'} 모드 시작 완료")
                if self.on_start: self.on_start() # [신규] GUI 상태 동기화
                return True
            else:
                self.is_starting = False # Ensure flag is reset on failure
                return False
        except Exception as e:
            log_and_tel(f"❌ start 오류: {e}")
            return False
        finally:
            self.is_starting = False

    async def stop(self, set_auto_start_false=True, quiet=False):
        """시스템 중지"""
        try:
            if set_auto_start_false:
                self.update_setting('auto_start', False)
            await self._cancel_tasks()
            await self.rt_search.stop()
            if not quiet:
                log_and_tel("⏹ 실시간 감시 엔진이 정지되었습니다.")
                if self.on_stop: self.on_stop() # [신규] GUI 상태 동기화
            return True
        except Exception as e:
            if not quiet: log_and_tel(f"❌ stop 오류: {e}")
            return False

    async def _cancel_tasks(self):
        """실행 중인 태스크 취소 및 대기"""
        tasks = [('매도', self.check_n_sell_task), ('계좌', self.account_sync_task)]
        for name, task in tasks:
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    print(f"⚠️ {name} 태스크 종료 중 에러: {e}")
        
        self.check_n_sell_task = None
        self.account_sync_task = None

    async def _on_connection_closed(self):
        """재연결 콜백"""
        # [신규] 이미 시작 중인 경우(예: 시퀀스 전환, 사용자 클릭) 중복 재연결 방지
        if self.is_starting:
            print("🔄 [안내] 엔진 재시작 중으로 자동 재연결을 건너뜁니다.")
            return

        await self.stop(set_auto_start_false=False)
        await asyncio.sleep(2)
        await self.start()

    async def report(self):
        """계좌 보고"""
        try:
            if not self.token: self.get_token()
            loop = asyncio.get_event_loop()
            balance_raw = await loop.run_in_executor(None, get_balance, 'N', '', self.token, True)
            balance_str = f"{int(balance_raw):,}원" if balance_raw else "조회 실패"
            
            from trade_logger import session_logger
            session_report = session_logger.get_session_report()
            account_data = await loop.run_in_executor(None, fn_kt00004, False, 'N', '', self.token)
            
            msg = "📊 [ 실시간 session 매매 및 계좌 보고서 ]\n"
            msg += "━━━━━━━━━━━━━━━━━━━━━\n"
            msg += "📂 [오늘 세션 매매 수익]\n"
            if session_report:
                stock_sum = session_report['stock_summary']
                for code, s in stock_sum.items():
                    b_amt = s['buy_amt']
                    s_amt = s['sell_amt']
                    p_amt = s['pnl_amt']
                    if s_amt > 0:
                        rt = (p_amt / b_amt * 100) if b_amt > 0 else 0.0
                        emoji = "🔺" if p_amt > 0 else "🔻" if p_amt < 0 else "⚪"
                        msg += f"{emoji} {s['name']}\n"
                        msg += f"   └ 매입: {b_amt:,}원 | 매도: {s_amt:,}원\n"
                        msg += f"   └ 수익: {rt:+.2f}%\n"
                    else:
                        msg += f"⚪ {s['name']} (보유 중)\n"
                        msg += f"   └ 매입: {b_amt:,}원\n"
                msg += "─────────────────────\n"
                msg += f"💰 [세션 총 합계]\n"
                msg += f"   🔹 총 매입: {session_report['total_buy']:,}원\n"
                msg += f"   🔹 총 매도: {session_report['total_sell']:,}원\n"
                msg += f"   ✨ 실현손익: {session_report['total_pnl']:+,}원 ({session_report['total_rt']:+.2f}%)\n"
            else:
                msg += "   (현재 세션 매매 내역이 없습니다)\n"
            
            msg += "━━━━━━━━━━━━━━━━━━━━━\n"
            msg += "🏦 [현재 계좌 보유 현황]\n"
            if account_data:
                for s in account_data:
                    pl_rt = float(s['pl_rt'])
                    emoji = "📈" if pl_rt > 0 else "📉"
                    msg += f"{emoji} {s['stk_nm']}: {pl_rt:+.2f}% ({int(s['pl_amt']):,}원)\n"
            else:
                msg += "   보유 종목이 없습니다.\n"
                
            msg += "─────────────────────\n"
            msg += f"💳 예수금(잔고): {balance_str}\n"
            msg += "━━━━━━━━━━━━━━━━━━━━━"
            tel_send(msg)
            return True
        except Exception as e:
            tel_send(f"❌ report 오류: {e}")

    async def today(self, sort_mode=None, is_reverse=False, summary_only=False, send_telegram=False):
        """당일 매매 일지 조회 (Hybrid: ka10170 전체목록 + ka10077 상세세금)"""
        print(f"▶ Today 명령어 수신 (모드: {sort_mode}, 역순: {is_reverse}, 요약: {summary_only}, 텔레그램전송: {send_telegram})")
        try:
            if not self.token: 
                self.get_token()
                
            loop = asyncio.get_event_loop()
            res_list = await loop.run_in_executor(None, get_trade_diary, self.token)
            diary_list = res_list.get('list', [])
            
            if not diary_list:
                tel_send("📭 오늘 매매 내역이 없습니다.")
                return

            # 데이터 매핑 로드
            cond_mapping = {}
            mapping_file = os.path.join(self.data_dir, 'stock_conditions.json')
            if os.path.exists(mapping_file):
                try:
                    with open(mapping_file, 'r', encoding='utf-8') as f:
                        cond_mapping = json.load(f)
                except: pass

            bt_data = {}
            try:
                bt_path = os.path.join(self.data_dir, 'daily_buy_times.json')
                if os.path.exists(bt_path):
                    with open(bt_path, 'r', encoding='utf-8') as f:
                        bt_data = json.load(f)
            except: pass

            processed_data = []
            for item in diary_list:
                try:
                    code = item['stk_cd'].replace('A', '')
                    def val(keys):
                        for k in keys:
                            v = item.get(k)
                            if v is not None and str(v).strip() != "": return v
                        return 0

                    # [수정] 매칭 데이터 최우선 참조 (구조화된 데이터 지원)
                    mapping_val = cond_mapping.get(code, "직접매매")
                    cond_name = "직접매매"
                    strat_key = "none"
                    strat_nm = "--"
                    found_buy_time = bt_data.get(code)
                    
                    if isinstance(mapping_val, dict):
                        cond_name = mapping_val.get('name', "직접매매")
                        strat_key = mapping_val.get('strat', 'none')
                        strat_map = {'qty': '1주', 'amount': '금액', 'percent': '비율'}
                        strat_nm = strat_map.get(strat_key, '--')
                        # [신규] 매핑 데이터 내의 백업 시간 활용
                        if not found_buy_time:
                            found_buy_time = mapping_val.get('time')
                    else:
                        cond_name = str(mapping_val)
                    
                    # [수정] 오버나이트 종목 판별 및 시간 표시 개선
                    current_time_str = datetime.now().strftime("%H:%M:%S")
                    is_overnight = False
                    
                    # 매수 기록(금품)이 0이거나, 찾은 시간이 현재 시각보다 미래라면 오버나이트로 간주
                    buy_amt_val = int(float(val(['buy_amt', 'tot_buy_amt'])))
                    if buy_amt_val <= 0 or (found_buy_time and found_buy_time > current_time_str):
                        is_overnight = True
                    
                    final_buy_time = found_buy_time if found_buy_time else "99:99:99"
                    if is_overnight:
                        # 오버나이트면 [전일] 표시를 붙여서 시각적 오해 방지
                        if found_buy_time: final_buy_time = f"전일 {found_buy_time[:5]}"
                        else: final_buy_time = "[전일]"

                    row = {
                        'code': code,
                        'name': item.get('stk_nm', '--'),
                        'buy_time': final_buy_time,
                        'buy_avg': int(float(val(['buy_avg_pric', 'buy_avg_prc']))),
                        'buy_qty': int(float(val(['buy_qty', 'tot_buy_qty']))),
                        'buy_amt': buy_amt_val,
                        'sel_avg': int(float(val(['sel_avg_pric', 'sel_avg_prc', 'sell_avg_pric']))),
                        'sel_qty': int(float(val(['sell_qty', 'tot_sel_qty', 'sel_qty']))),
                        'sel_amt': int(float(val(['sell_amt', 'tot_sel_amt', 'sel_amt']))),
                        'tax': int(float(val(['cmsn_alm_tax', 'cmsn_tax', 'tax']))),
                        'pnl': int(float(val(['pl_amt', 'pnl_amt', 'rznd_pnl', 'tdy_sel_pl']))),
                        'pnl_rt': float(val(['prft_rt', 'pl_rt', 'profit_rate'])),
                        'cond_name': cond_name,
                        'strat_key': strat_key,
                        'strat_nm': strat_nm,
                        'is_overnight': is_overnight
                    }
                    processed_data.append(row)
                except: continue

            # 정렬 적용
            if sort_mode == 'jun':
                processed_data.sort(key=lambda x: x['strat_nm'], reverse=is_reverse)
            elif sort_mode == 'sic':
                processed_data.sort(key=lambda x: x['cond_name'], reverse=is_reverse)
            elif sort_mode == 'son':
                # [신규] 손익금 기준 정렬 (기본: 내림차순 - 수익 큰 순)
                processed_data.sort(key=lambda x: x['pnl'], reverse=not is_reverse) 
            else:
                processed_data.sort(key=lambda x: x['buy_time'], reverse=is_reverse)

            total_b_amt = sum(r['buy_amt'] for r in processed_data)
            total_s_amt = sum(r['sel_amt'] for r in processed_data)
            total_tax = sum(r['tax'] for r in processed_data)
            total_pnl = sum(r['pnl'] for r in processed_data)
            count = len(processed_data)
            # [수정] 음수 매수금액이 합산될 경우를 대비해 abs() 사용 및 0 체크 강화
            avg_pnl_rt = (total_pnl / abs(total_b_amt) * 100) if abs(total_b_amt) > 100 else 0

            if summary_only:
                summary_msg = "<b>📝 [ 당일 매매 요약 리포트 ]</b>\n"
                summary_msg += "━━━━━━━━━━━━━━━\n"
                summary_msg += f"🔹 거래종목: {count}건\n"
                summary_msg += f"🔹 총 매수: {total_b_amt:,}원\n"
                summary_msg += f"🔹 총 매도: {total_s_amt:,}원\n"
                summary_msg += "────────────────\n"
                summary_msg += f"💸 제세공과: {total_tax:,}원\n"
                summary_msg += f"✨ 실현손익: <b>{total_pnl:+,}원</b>\n"
                summary_msg += f"📈 최종수익률: <b>{avg_pnl_rt:+.2f}%</b>\n"
                summary_msg += "━━━━━━━━━━━━━━━"
                
                # 진짜 텔레그램으로 전송 (HTML 모드 활용, send_telegram이 True일 때만)
                if send_telegram:
                    real_tel_send(summary_msg, parse_mode='HTML')
                    print("📢 텔레그램으로 요약 보고서를 전송했습니다.")
                
                # GUI 로그창에는 요약 표시
                tel_send(summary_msg.replace('<b>', '').replace('</b>', ''))
                return True

            # 상세 리포트 생성
            display_rows = [] # GUI용 (HTML)
            tel_rows = []     # 텔레그램용 (Plain Text)
            
            h_line = "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            header = " [매수시간] [매수전략] [조건식] 종목명     |  매수(평균/수량/금액)  |  매도(평균/수량/금액)  |  세금  | 손익(수익률) \n"
            
            display_rows.append(h_line + header + h_line)
            tel_rows.append(h_line + header + h_line)

            colors = {'qty': '#ff4444', 'amount': '#00c851', 'percent': '#33b5e5', 'none': '#00ff00'}
            for r in processed_data:
                row_color = colors.get(r['strat_key'], '#00ff00')
                bt_str = f"[{r['buy_time']}]"
                if r.get('is_overnight'):
                    bt_str = f"<font color='#ffeb3b'><b>{bt_str}</b></font>" # 오버나이트 강조
                
                st_str = f"[{r['strat_nm']}]"
                
                # [수정] 오버나이트 종목은 매수 데이터가 0인 경우가 많으므로 '-' 로 표시해서 가독성 높임
                buy_avg_str = f"{r['buy_avg']:>7,}" if r['buy_avg'] > 0 else f"{'-':>7}"
                buy_qty_str = f"{r['buy_qty']:>3}" if r['buy_qty'] > 0 else f"{'-':>3}"
                buy_amt_str = f"{r['buy_amt']:>8,}" if r['buy_amt'] > 0 else f"{'-':>8}"
                
                row_content = f"{bt_str:<10} {st_str:<6} {r['cond_name']:.8} {r['name']:<10} | {buy_avg_str}/{buy_qty_str}/{buy_amt_str} | {r['sel_avg']:>7,}/{r['sel_qty']:>3}/{r['sel_amt']:>8,} | {r['tax']:>5,} | {r['pnl']:>+8,} ({r['pnl_rt']:>+6.2f}%)\n"
                
                # [수정] 텔레그램용은 HTML 태그 제거
                row_tel = f"[{r['buy_time']:<8}] {st_str:<6} {r['cond_name']:.8} {r['name']:<10} | {buy_avg_str}/{buy_qty_str}/{buy_amt_str} | {r['sel_avg']:>7,}/{r['sel_qty']:>3}/{r['sel_amt']:>8,} | {r['tax']:>5,} | {r['pnl']:>+8,} ({r['pnl_rt']:>+6.2f}%)\n"
                
                display_rows.append(f"<font color='{row_color}'>{row_content}</font>")
                tel_rows.append(row_tel)

            d_ft = "--------------------------------------------------------------------------------------------------------------------\n"
            display_rows.append(d_ft)
            tel_rows.append(d_ft)
            
            summary_str = f"{'TOTAL':<21} {'  ':<6} {'합계':<10} | {'-':>7}/{'-':>3}/{total_b_amt:>8,} | {'-':>7}/{'-':>3}/{total_s_amt:>8,} | {total_tax:>5,} | {total_pnl:>+8,} ({avg_pnl_rt:>+6.2f}%)\n"
            display_rows.append(summary_str)
            tel_rows.append(summary_str)
            
            display_rows.append(h_line)
            tel_rows.append(h_line)
            
            # GUI에는 HTML 버전 전송 (패치된 tel_send 사용 가능)
            tel_send("".join(display_rows))
            
            # 텔레그램에는 진짜 전송 (HTML 태그 없는 버전, send_telegram이 True일 때만)
            if send_telegram:
                real_tel_send("".join(tel_rows))
                print("📢 텔레그램으로 상세 보고서를 전송했습니다.")
            
            try:
                df_data = [{
                    '매수시간': r['buy_time'], '매수전략': r['strat_nm'], '조건식': r['cond_name'], 
                    '종목명': r['name'], '종목코드': r['code'], '매수평균가': r['buy_avg'], 
                    '매수수량': r['buy_qty'], '매수금액': r['buy_amt'], '매도평균가': r['sel_avg'], 
                    '매도수량': r['sel_qty'], '매도금액': r['sel_amt'], '세금': r['tax'], 
                    '손익금액': r['pnl'], '수익률(%)': r['pnl_rt']
                } for r in processed_data]
                
                # [신규] 합계 행 추가
                df_data.append({
                    '매수시간': '합계', '매수전략': '-', '조건식': '-', 
                    '종목명': '-', '종목코드': '-', '매수평균가': 0, 
                    '매수수량': 0, '매수금액': total_b_amt, '매도평균가': 0, 
                    '매도수량': 0, '매도금액': total_s_amt, '세금': total_tax, 
                    '손익금액': total_pnl, '수익률(%)': avg_pnl_rt
                })
                
                df = pd.DataFrame(df_data)
                date_str = datetime.now().strftime("%Y%m%d")
                
                # [신규] 중복 파일명 체크 (a, b, c...)
                import string
                suffix_list = list(string.ascii_lowercase) # a-z
                
                final_filename = f"trade_log_{date_str}.csv"
                csv_path = os.path.join(self.data_dir, final_filename)
                
                # 기본 파일이 존재하면 알파벳 접미사 붙여서 비어있는 이름 찾기
                if os.path.exists(csv_path):
                    for char in suffix_list:
                        temp_name = f"trade_log_{date_str}_{char}.csv"
                        if not os.path.exists(os.path.join(self.data_dir, temp_name)):
                            final_filename = temp_name
                            csv_path = os.path.join(self.data_dir, final_filename)
                            break
                
                df.to_csv(csv_path, index=False, encoding='utf-8-sig')
                tel_send(f"<font color='#28a745'>📂 매매 일지가 저장되었습니다: {final_filename}</font>")
                
            except Exception as save_err: 
                print(f"❌ csv 저장 오류: {save_err}")

        except Exception as e:
            print(f"❌ today 오류: {e}")
            tel_send(f"❌ today 오류: {e}")

    async def tpr(self, number):
        if self.update_setting('take_profit_rate', float(number)):
            tel_send(f"✅ 익절 기준: {number}%")

    async def slr(self, number):
        rate = -abs(float(number))
        if self.update_setting('stop_loss_rate', rate):
            tel_send(f"✅ 손절 기준: {rate}%")

    async def brt(self, number):
        if self.update_setting('buy_ratio', float(number)):
            tel_send(f"✅ 매수 비중: {number}%")

    async def condition(self, number=None, quiet=False):
        try:
            await self.stop(set_auto_start_false=False, quiet=quiet)
            if number is not None:
                if self.update_setting('search_seq', str(number)):
                    tel_send(f"✅ 조건식 {number}번으로 변경")
                    if MarketHour.is_market_open_time(): await self.start()
                    return True
            token = self.token if self.token else self.get_token()
            cond_list = await asyncio.wait_for(get_condition_list(token), timeout=5.0)
            if cond_list:
                cond_list.sort(key=lambda x: int(x[0]))
                # [추가] GUI 표시를 위해 rt_search의 condition_map 업데이트
                for c in cond_list:
                    self.rt_search.condition_map[str(c[0])] = c[1]

                if not quiet:
                    msg = "📋 [조건식 목록]\n"
                    for c in cond_list: msg += f"• {c[0]}: {c[1]}\n"
                    log_and_tel(msg)
            return True
        except: 
            if not quiet: log_and_tel("❌ 목록 조회 실패")

    def update_setting(self, key, value):
        return self.update_settings_batch({key: value})

    def update_settings_batch(self, updates_dict):
        """여러 설정을 한 번에 안전하게 업데이트 (레이스 컨디션 방지)"""
        try:
            # 1. 파일에서 현재 설정 읽기
            settings = {}
            if os.path.exists(self.settings_file):
                with open(self.settings_file, 'r', encoding='utf-8') as f:
                    settings = json.load(f)
            
            # 2. 모든 요청된 필드 업데이트
            settings.update(updates_dict)
                
            # 3. 파일에 다시 쓰기
            with open(self.settings_file, 'w', encoding='utf-8') as f:
                json.dump(settings, f, indent=4, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"❌ 설정 저장 실패: {e}")
            return False

    async def help(self):
        help_msg = """🤖 [명령어 가이드]
• start / stop : 시작 및 중지
• r (또는 report) : 잔고 확인
• auto {번호} : {번호}번 부터 시퀀스 가동 (0은 중지)
• condition {번호} : 조건식 변경
• tpr / slr / brt : 익절/손절/비중 설정
• today 옵션 : 당일 매매 일지 조회
  - today : 시간순
  - today jun : 전략순 (매수전략)
  - today sic : 조건식순 (검색식명)
  - today son : 손익순 (손익금액)
  - (팁: 뒤에 -를 붙이면 역순 출력, 예: today jun-)
• tel today : 텔레그램으로 매매 요약 리포트 전송
• clr : 로그 화면 초기화 (GUI 전용)
• log : 현재 로그를 .txt 파일로 저장 (GUI 전용)
• msg {메세지} : 텔레그램 메세지 직접 전송"""
        tel_send(help_msg)

    async def process_command(self, text):
        cmd_full = text.strip()
        cmd = cmd_full.lower()
        
        if cmd == 'start':
            if self.on_start_request: self.on_start_request()
            else: await self.start()
        elif cmd == 'stop':
            if self.on_stop_request: self.on_stop_request()
            else: await self.stop(True)
        elif cmd in ['report', 'r']: await self.report()
        elif cmd.startswith('auto'):
            parts = cmd_full.split()
            idx = 1
            if len(parts) > 1:
                try: idx = int(parts[1])
                except: idx = 1
            
            if self.on_auto_sequence:
                # 텔레그램이나 명령창에서 수신 시 GUI로 신호 전달
                self.on_auto_sequence(idx)
            else:
                tel_send("ℹ️ auto 명령어는 GUI 환경에서만 작동합니다.")
        elif cmd == 'condition': await self.condition()
        elif cmd.startswith('condition '): await self.condition(cmd_full.split()[1])
        elif cmd.startswith('tpr '): await self.tpr(cmd_full.split()[1])
        elif cmd.startswith('slr '): await self.slr(cmd_full.split()[1])
        elif cmd.startswith('brt '): await self.brt(cmd_full.split()[1])
        elif cmd == 'clr':
            if self.on_clear_logs: self.on_clear_logs()
            else: tel_send("ℹ️ clr 명령어는 GUI 환경에서만 작동합니다.")
        elif cmd == 'voice on':
            self.update_setting('voice_guidance', True)
            log_and_tel("🔊 음성 안내가 활성화되었습니다.")
        elif cmd == 'voice off':
            self.update_setting('voice_guidance', False)
            log_and_tel("🔇 음성 안내가 비활성화되었습니다.")
        elif cmd == 'log':
            if self.on_request_log_file: self.on_request_log_file()
            else: tel_send("ℹ️ log 명령어는 GUI 환경에서만 작동합니다.")
        elif cmd == 'print' or cmd == 'msg':
            tel_send(f"❓ {cmd} 뒤에 메세지를 입력해주세요. (예: {cmd} 안녕하세요)")
        elif cmd.startswith('print '):
            await asyncio.get_event_loop().run_in_executor(None, log_and_tel, cmd_full[6:].strip())
        elif cmd.startswith('msg '):
            await asyncio.get_event_loop().run_in_executor(None, log_and_tel, cmd_full[4:].strip())
        elif cmd.startswith('tel_send '):
            await asyncio.get_event_loop().run_in_executor(None, log_and_tel, cmd_full[9:].strip())
        elif cmd == 'refresh_conditions': 
            await self.rt_search.refresh_conditions(self.token)
        elif cmd == 'help': await self.help()
        elif cmd.startswith('tel today'):
            # tel today jun- 등 처리
            sub_raw = cmd_full[4:].strip() # "today jun-"
            is_rev = sub_raw.endswith('-')
            
            parts = sub_raw.lower().split()
            sub_cmd = 'default'
            if len(parts) > 1:
                sub_part = parts[1].replace('-', '')
                if sub_part: sub_cmd = sub_part
            
            # 요약 보고서 여부 확인 (tel today 만 쳤을 때)
            is_summary = (sub_raw.lower() == 'today')
            
            if sub_cmd == 'sic': await self.today(sort_mode='sic', is_reverse=is_rev, send_telegram=True)
            elif sub_cmd == 'jun': await self.today(sort_mode='jun', is_reverse=is_rev, send_telegram=True)
            elif sub_cmd == 'son': await self.today(sort_mode='son', is_reverse=is_rev, send_telegram=True)
            else: await self.today(summary_only=is_summary, is_reverse=is_rev, send_telegram=True)

        elif cmd.startswith('today'):
            # 명령어 파싱: today jun- 등 공백 및 하이픈 처리
            parts = cmd.split()
            sub_cmd = 'default'
            is_rev = False
            
            # today jun- 처럼 공백이 없는 경우와 있는 경우 모두 대응
            full_text = cmd
            is_rev = full_text.endswith('-')
            
            if len(parts) > 1:
                sub_part = parts[1].replace('-', '')
                if sub_part: sub_cmd = sub_part
            elif ' ' not in full_text and len(full_text) > 5:
                # todayjun- 같은 형태 대비
                sub_part = full_text[5:].replace('-', '')
                if sub_part: sub_cmd = sub_part
                
            if sub_cmd in ['default', 'today']: await self.today(is_reverse=is_rev, send_telegram=False)
            elif sub_cmd == 'sic': await self.today(sort_mode='sic', is_reverse=is_rev, send_telegram=False)
            elif sub_cmd == 'jun': await self.today(sort_mode='jun', is_reverse=is_rev, send_telegram=False)
            elif sub_cmd == 'son': await self.today(sort_mode='son', is_reverse=is_rev, send_telegram=False)
            else: await self.today(is_reverse=is_rev, send_telegram=False) # 기본값
        else: tel_send(f"❓ 알 수 없는 명령어: {text}")