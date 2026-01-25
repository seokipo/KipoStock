import json
import os
import sys
import asyncio
import time
from datetime import datetime
from rt_search import RealTimeSearch
from tel_send import tel_send
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
            
        self.settings_path = os.path.join(self.script_dir, 'settings.json')
        
        self.check_n_sell_task = None
        self.account_sync_task = None
        self.token = None
        self.is_starting = False # [신규] 중복 시작(R10001) 방지용 플래그
        self.on_clear_logs = None # [신규] GUI 로그 초기화 콜백
        self.on_request_log_file = None # [신규] 로그 파일 저장 요청 콜백
        self.on_auto_sequence = None # [신규] 시퀀스 자동 시작 콜백

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
                if not self.token: 
                    await asyncio.sleep(1)
                    continue
                    
                success = await asyncio.get_event_loop().run_in_executor(None, chk_n_sell, self.token)
                failure_count = 0 if success else failure_count + 1
                
                if failure_count >= 20:
                    print("⚠️ 매도 루프 연속 실패로 재시작 시도")
                    break 
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"⚠️ 매도 루프 에러: {e}")
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
                tel_send("❌ 토큰 발급 실패")
                return False
            
            self.update_setting('auto_start', True)
            if not MarketHour.is_market_open_time():
                now_str = datetime.now().strftime('%H:%M:%S')
                print(f"⚠️ [거부] 장외 시간입니다. 시간을 다시 설정하세요. (현재: {now_str})")
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
                tel_send("🚀 초고속 엔진 가동! 감시 시작.")
                if profile_info:
                    tel_send(f"🚀 {profile_info}로 감시를 시작합니다.")
                return True
            return False
        except Exception as e:
            tel_send(f"❌ start 오류: {e}")
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
            if not quiet: tel_send("✅ 시스템 중지됨")
            return True
        except Exception as e:
            if not quiet: tel_send(f"❌ stop 오류: {e}")
            return False

    async def _cancel_tasks(self):
        """실행 중인 태스크 취소"""
        tasks = [self.check_n_sell_task, self.account_sync_task]
        for task in tasks:
            if task and not task.done():
                task.cancel()
                try: await task
                except asyncio.CancelledError: pass
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

    async def today(self, sort_mode=None, is_reverse=False, summary_only=False):
        """당일 매매 일지 조회 (Hybrid: ka10170 전체목록 + ka10077 상세세금)"""
        print(f"▶ Today 명령어 수신 (요약모드: {summary_only}): 처리 시작")
        try:
            if not self.token: 
                print("▶ 토큰 없음, 발급 시도")
                self.get_token()
                
            loop = asyncio.get_event_loop()
            
            # 1. 전체 매매 목록 조회 (ka10170)
            res_list = await loop.run_in_executor(None, get_trade_diary, self.token)
            diary_list = res_list.get('list', [])
            
            if not diary_list:
                tel_send("📭 오늘 매매 내역이 없습니다.")
                return

            # [수정] 요약 모드라도 합계 계산을 위해 데이터 처리는 진행
            cond_mapping = {}
            mapping_file = os.path.join(self.script_dir, 'stock_conditions.json')
            if os.path.exists(mapping_file):
                try:
                    with open(mapping_file, 'r', encoding='utf-8') as f:
                        cond_mapping = json.load(f)
                except: pass

            bt_data = {}
            try:
                bt_path = os.path.join(self.script_dir, 'daily_buy_times.json')
                if os.path.exists(bt_path):
                    with open(bt_path, 'r', encoding='utf-8') as f:
                        bt_data = json.load(f)
            except: pass

            total_b_amt = 0
            total_s_amt = 0
            total_tax = 0
            total_pnl = 0
            pnl_rt_sum = 0
            count = 0

            display_rows = []
            if not summary_only:
                header = "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                header += " [매수시간] [매수전략] [조건식] 종목명     |  매수(평균/수량/금액)  |  매도(평균/수량/금액)  |  세금  | 손익(수익률) \n"
                header += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                display_rows.append(header)

            table_rows = []
            for item in diary_list:
                try:
                    code = item['stk_cd'].replace('A', '')
                    name = item['stk_nm']
                    
                    def val(keys):
                        for k in keys:
                            v = item.get(k)
                            if v is not None and str(v).strip() != "": return v
                        return 0

                    b_avg = int(float(val(['buy_avg_pric', 'buy_avg_prc', 'buy_avg_price'])))
                    b_qty = int(float(val(['buy_qty', 'tot_buy_qty', 'buy_q'])))
                    b_amt = int(float(val(['buy_amt', 'tot_buy_amt', 'buy_a'])))
                    s_avg = int(float(val(['sel_avg_pric', 'sel_avg_prc', 'sell_avg_pric', 'sell_avg_price'])))
                    s_qty = int(float(val(['sell_qty', 'sel_qty', 'tot_sel_qty', 'sell_q'])))
                    s_amt = int(float(val(['sell_amt', 'sel_amt', 'tot_sel_amt', 'sell_a'])))
                    tax = int(float(val(['cmsn_alm_tax', 'cmsn_tax', 'tax', 'tot_tax'])))
                    pnl = int(float(val(['pl_amt', 'pnl_amt', 'rznd_pnl', 'tdy_sel_pl'])))
                    pnl_rt = float(val(['prft_rt', 'pl_rt', 'profit_rate']))
                    
                    total_b_amt += b_amt
                    total_s_amt += s_amt
                    total_tax += tax
                    total_pnl += pnl
                    pnl_rt_sum += pnl_rt
                    count += 1
                    
                    if not summary_only:
                        # [복구] 조건식 및 전략 색상 추출
                        mapping_val = cond_mapping.get(code, "직접매매")
                        strat_display = "[--]"
                        if isinstance(mapping_val, dict):
                            cond_name = mapping_val.get('name', "직접매매")
                            strat = mapping_val.get('strat', 'none')
                            strat_map = {'qty': '1주', 'amount': '금액', 'percent': '비율'}
                            strat_nm = strat_map.get(strat, '--')
                            colors = {'qty': '#ff4444', 'amount': '#00c851', 'percent': '#33b5e5'}
                            row_color = colors.get(strat, '#00ff00')
                            strat_display = f"[{strat_nm}]"
                            cond_display = f"{cond_name}"
                        else:
                            cond_name = mapping_val
                            cond_display = cond_name
                            strat_nm = "--"
                            strat_display = "[--]"
                            row_color = "#00ff00"
                        
                        buy_time_str = f"[{bt_data.get(code, '--:--:--')}]"
                        row_content = f"{buy_time_str:<10} {strat_display} {cond_display} {name:<10} | {b_avg:>7,}/{b_qty:>3}/{b_amt:>8,} | {s_avg:>7,}/{s_qty:>3}/{s_amt:>8,} | {tax:>5,} | {pnl:>+8,} ({pnl_rt:>+6.2f}%)\n"
                        display_rows.append(f"<font color='{row_color}'>{row_content}</font>")
                        
                        table_rows.append({
                            '매수시간': bt_data.get(code, '--:--:--'), '매수전략': strat_nm,
                            '조건식': cond_name, '종목명': name, '종목코드': code,
                            '매수평균가': b_avg, '매수수량': b_qty, '매수금액': b_amt,
                            '매도평균가': s_avg, '매도수량': s_qty, '매도금액': s_amt,
                            '세금': tax, '손익금액': pnl, '수익률(%)': pnl_rt
                        })

                except Exception as row_err:
                    print(f"▶ [DEBUG] 행 처리 중 오류: {row_err}")

            if summary_only:
                avg_pnl_rt = (pnl_rt_sum / count) if count > 0 else 0
                summary_msg = "📝 [ 당일 매매 요약 리포트 ]\n"
                summary_msg += "━━━━━━━━━━━━━━━\n"
                summary_msg += f"🔹 거래종목: {count}건\n"
                summary_msg += f"🔹 총 매수: {total_b_amt:,}원\n"
                summary_msg += f"🔹 총 매도: {total_s_amt:,}원\n"
                summary_msg += "────────────────\n"
                summary_msg += f"💸 제세공과: {total_tax:,}원\n"
                summary_msg += f"✨ 실현손익: {total_pnl:+,}원\n"
                summary_msg += f"📈 최종수익률: {avg_pnl_rt:+.2f}%\n"
                summary_msg += "━━━━━━━━━━━━━━━"
                tel_send(summary_msg)
                return True

            # [복구] 상세 리포트 마무리
            if count > 0:
                avg_pnl_rt = pnl_rt_sum / count
                display_rows.append("--------------------------------------------------------------------------------------------------------------------\n")
                summary_str = f"{'TOTAL':<21} {'  ':<6} {'합계':<10} | {'-':>7}/{'-':>3}/{total_b_amt:>8,} | {'-':>7}/{'-':>3}/{total_s_amt:>8,} | {total_tax:>5,} | {total_pnl:>+8,} ({avg_pnl_rt:>+6.2f}%)\n"
                display_rows.append(summary_str)

            footer = "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
            display_rows.append(footer)
            tel_send("".join(display_rows))

            try:
                df = pd.DataFrame(table_rows)
                # [수정] 엑셀에도 합정 행 추가
                if count > 0:
                    summary_row = pd.Series({\
                        '조건식': '합계', '종목명': f'{count}종목', '종목코드': '-',\
                        '매수평균가': 0, '매수수량': 0, '매수금액': total_b_amt,\
                        '매도평균가': 0, '매도수량': 0, '매도금액': total_s_amt,\
                        '세금': total_tax, '손익금액': total_pnl, '수익률(%)': pnl_rt_sum / count\
                    })
                    df = pd.concat([df, summary_row.to_frame().T], ignore_index=True)
                
                date_str = datetime.now().strftime("%Y%m%d")
                csv_name = f"trade_log_{date_str}.csv"
                csv_path = os.path.join(self.script_dir, csv_name)
                df.to_csv(csv_path, index=False, encoding='utf-8-sig')
                tel_send(f"💾 엑셀 파일 저장 완료: {csv_name}")
            except Exception as e:
                tel_send(f"⚠️ 엑셀 저장 실패: {e}")
        except Exception as e:
            import traceback
            traceback.print_exc()
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
                    tel_send(msg)
            return True
        except: 
            if not quiet: tel_send("❌ 목록 조회 실패")

    def update_setting(self, key, value):
        return self.update_settings_batch({key: value})

    def update_settings_batch(self, updates_dict):
        """여러 설정을 한 번에 안전하게 업데이트 (레이스 컨디션 방지)"""
        try:
            settings = {}
            if os.path.exists(self.settings_path):
                with open(self.settings_path, 'r', encoding='utf-8') as f:
                    settings = json.load(f)
            
            settings.update(updates_dict)
            
            with open(self.settings_path, 'w', encoding='utf-8') as f:
                json.dump(settings, f, ensure_ascii=False, indent=2)
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
• today : 당일 매매 일지 조회 (기본: 매수시간순)
• tel today : 텔레그램용 당일 매매 요약 리포트
• (팁: auto 1~3은 시작, auto 0은 시퀀스 자동 중지입니다)
• clr : 로그 화면 초기화 (GUI 전용)
• log : 현재 로그를 .txt 파일로 저장 (GUI 전용)
• print {메세지} (또는 msg) : 텔레그램 메세지 전송"""
        tel_send(help_msg)

    async def process_command(self, text):
        cmd_full = text.strip()
        cmd = cmd_full.lower()
        
        if cmd == 'start': await self.start()
        elif cmd == 'stop': await self.stop(True)
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
        elif cmd == 'log':
            if self.on_request_log_file: self.on_request_log_file()
            else: tel_send("ℹ️ log 명령어는 GUI 환경에서만 작동합니다.")
        elif cmd == 'print' or cmd == 'msg':
            tel_send(f"❓ {cmd} 뒤에 메세지를 입력해주세요. (예: {cmd} 안녕하세요)")
        elif cmd.startswith('print '):
            await asyncio.get_event_loop().run_in_executor(None, tel_send, cmd_full[6:].strip())
        elif cmd.startswith('msg '):
            await asyncio.get_event_loop().run_in_executor(None, tel_send, cmd_full[4:].strip())
        elif cmd.startswith('tel_send '):
            await asyncio.get_event_loop().run_in_executor(None, tel_send, cmd_full[9:].strip())
        elif cmd == 'refresh_conditions': 
            await self.rt_search.refresh_conditions(self.token)
        elif cmd == 'help': await self.help()
        elif cmd == 'tel today': await self.today(summary_only=True)
        elif cmd.startswith('today'):
            is_rev = cmd.endswith('-')
            # 하이픈 제거 후 옵션 파악
            clean_cmd = cmd[:-1] if is_rev else cmd
            
            if clean_cmd == 'today': await self.today(is_reverse=is_rev)
            elif clean_cmd == 'today/sic': await self.today(sort_mode='sic', is_reverse=is_rev)
            elif clean_cmd == 'today/jun': await self.today(sort_mode='jun', is_reverse=is_rev)
            elif clean_cmd == 'today/son': await self.today(sort_mode='son', is_reverse=is_rev)
            else: tel_send(f"❓ 알 수 없는 today 옵션: {text}")
        else: tel_send(f"❓ 알 수 없는 명령어: {text}")