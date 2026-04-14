import time
import os
import json
from acc_val import fn_kt00004 as get_my_stocks
from sell_stock import fn_kt10001 as sell_stock
from tel_send import tel_send
from get_setting import cached_setting, get_base_path
from login import fn_au10001 as get_token, safe_float, safe_int
from market_hour import MarketHour
from check_n_buy import load_json_safe, save_json_safe, update_stock_condition # [신규] 안전 함수 가져오기
from trade_logger import session_logger # [신규] 수익 기록용 세션 로거


# 전역 캐시 (파일 수정 시간 기반의 I/O 최소화)
_STRATEGY_MAPPING_CACHE = {}
_LAST_MAPPING_MTIME = 0
_LAST_BULTAGI_DIAG_TIME = 0 # [v6.3.0] 불타기 진단 로그 출력 시간 기록
from check_n_buy import load_json_safe, save_json_safe, update_stock_condition, update_stock_peak_rt # [수정] update_stock_peak_rt 추가

def chk_n_sell(token=None, disabled_stocks=None):
    global _STRATEGY_MAPPING_CACHE, _LAST_MAPPING_MTIME, _LAST_BULTAGI_DIAG_TIME
    if disabled_stocks is None:
        disabled_stocks = set()
    
    try:
        current_time = time.time()
        # [v6.4.3] 하트비트 보정: 루프 시작 시점에 즉시 갱신하여 지연 누적 방지
        show_diag = False
        if current_time - _LAST_BULTAGI_DIAG_TIME >= 5:
            show_diag = True
            _LAST_BULTAGI_DIAG_TIME = current_time # 여기서 즉시 업데이트 (루프 지연 무관)
        
        mapping_updated = False # [신규] 상태 변경(최고수익률 등) 발생 시 저장하기 위한 플래그
        
        # 익절/손절 수익율(%)
        TP_RATE = cached_setting('take_profit_rate', 10.0)
        SL_RATE = cached_setting('stop_loss_rate', -10.0)

        # [최적화 & v6.4.4] 매핑 정보 파일 수정 시간 추적하여 즉각 갱신
        base_path = get_base_path()
            
        mapping_file = os.path.join(base_path, 'stock_conditions.json')
        
        current_mtime = 0
        if os.path.exists(mapping_file):
            current_mtime = os.path.getmtime(mapping_file)
            
        if not _STRATEGY_MAPPING_CACHE or current_mtime > _LAST_MAPPING_MTIME:
            mapped_data = {}
            if current_mtime > 0:
                 mapped_data = load_json_safe(mapping_file)
            
            _STRATEGY_MAPPING_CACHE = mapped_data
            _LAST_MAPPING_MTIME = current_mtime
        
        mapping = _STRATEGY_MAPPING_CACHE

        try:
            my_stocks_data = get_my_stocks(token=token)
            # [v5.0.2] 8005 에러 감지 시 강제 재로그인 후 재시도 (Auto-Auth Recovery)
            if isinstance(my_stocks_data, dict) and my_stocks_data.get('error_code') == '8005':
                print("🔄 [chk_n_sell] 8005 감지 → 토큰 강제 갱신 후 재시도 중...")
                token = get_token(force=True)
                my_stocks_data = get_my_stocks(token=token)
            my_stocks = []
            
            if isinstance(my_stocks_data, dict):
                my_stocks = my_stocks_data.get('stocks', [])
            elif isinstance(my_stocks_data, list):
                my_stocks = my_stocks_data

            if not my_stocks:
                if time.time() % 30 < 1.0:
                    print("⚠️ [chk_n_sell] 보유 종목 데이터가 비어있습니다.")
                return True
            
            for stock in my_stocks:
                qty = int(stock.get('rmnd_qty', 0))
                if qty <= 0:
                    continue

                # [Fix v6.5.8] 변수 미초기화로 인한 UnboundLocalError 방지
                seq = None
                sell_reason = ""

                pl_rt = 0.0
                keys_to_try = ['pl_rt', 'evlu_pfls_rt', 'return_rate', 'profit_rate']
                for k in keys_to_try:
                    if k in stock and str(stock[k]).strip():
                        try:
                            pl_rt = float(stock[k])
                            break
                        except: pass

                stk_cd = stock['stk_cd'].replace('A', '')
                specific_tp = TP_RATE
                specific_sl = SL_RATE
                
                if mapping and stk_cd in mapping:
                    info = mapping[stk_cd]
                    strat_mode = info.get('strat', 'qty')
                    seq = info.get('seq')
                    s_name = info.get('name', '')
                    
                    # [신규 v6.9.7 / v5.1.30] 시초가 배팅 (Morning Bet) 전용 타이트 컷
                    strat_tag = str(info.get('strat', '') or '')
                    if s_name.startswith('MorningBet') or strat_tag.startswith('MorningBet'):
                        specific_tp = float(cached_setting('morning_tp', 2.0) or 2.0)
                        specific_sl = float(cached_setting('morning_sl', -1.5) or -1.5)
                    else:
                        tp_val = info.get('tp')
                        sl_val = info.get('sl')
                        specific_tp = float(tp_val) if tp_val is not None else TP_RATE
                        specific_sl = float(sl_val) if sl_val is not None else SL_RATE

                # [V5.1.30] 최종 보정: 여전히 0이라면 기본 설정값으로 강제 복구 (None% 방어 하한선)
                if specific_tp == 0: specific_tp = TP_RATE if TP_RATE != 0 else 12.0
                if specific_sl == 0: specific_sl = SL_RATE if SL_RATE != 0 else -1.5

                if mapping and stk_cd in mapping:
                    info = mapping[stk_cd]
                    # [v2.5.4] HTS 로 일원화: 불타기 완료된 종목이거나 직접 매수(HTS) 매수한 종목일 경우 불타기 매도 룰 적용
                    if info.get('bultagi_done') or info.get('strat', '') == 'HTS':
                        # [V5.1.34] 불타기 매도 설정 통합 로드 (중복 제거 및 하드코딩 방지)
                        b_tp_en = cached_setting('bultagi_tp_enabled', True)
                        b_tp = safe_float(cached_setting('bultagi_tp', 5.0), 5.0)
                        b_sl_en = cached_setting('bultagi_sl_enabled', True)
                        b_sl = safe_float(cached_setting('bultagi_sl', -2.0), -2.0)
                        b_pres_en = cached_setting('bultagi_preservation_enabled', False)
                        b_pres_trig = safe_float(cached_setting('bultagi_preservation_trigger', 3.0), 3.0)
                        b_pres_lim = safe_float(cached_setting('bultagi_preservation_limit', 2.0), 2.0)
                        b_ts_en = cached_setting('bultagi_trailing_enabled', False)
                        b_ts_val = abs(safe_float(cached_setting('bultagi_trailing_val', 1.0), 1.0))
                        b_ts_start = safe_float(cached_setting('bultagi_trailing_start_rate', 0.5), 0.5)

                        peak_rt = info.get('peak_pl_rt', 0.0)
                        if pl_rt > peak_rt:
                            info['peak_pl_rt'] = pl_rt
                            peak_rt = pl_rt
                            update_stock_peak_rt(stk_cd, pl_rt)
                        
                        should_sell = False
                        sell_reason = ""
                        
                        if b_ts_en:
                            # TS 모드: 고점 대비 하락 시 매도 (익절/보존 무시)
                            if peak_rt >= b_ts_start and (peak_rt - pl_rt) >= b_ts_val:
                                should_sell = True
                                sell_reason = f"트레일링스톱 (고점:{peak_rt:.1f}%, 현재:{pl_rt:.1f}%, 하락:{peak_rt-pl_rt:.1f}% >= {b_ts_val:.1f}%)"
                            elif b_sl_en and pl_rt <= b_sl:
                                should_sell = True
                                sell_reason = "손실제한"
                        else:
                            # 일반 모드: 기존 익절/보존/손절 로직 작동
                            if b_tp_en and pl_rt >= b_tp:
                                should_sell = True
                                sell_reason = "이익실현"
                            elif b_pres_en and peak_rt >= b_pres_trig and pl_rt <= b_pres_lim:
                                should_sell = True
                                sell_reason = "이익보존"
                            elif b_sl_en and pl_rt <= b_sl:
                                should_sell = True
                                sell_reason = "손실제한"
                        
                        if should_sell:
                            # [v3.1.9] 매도 실행을 위해 pl_rt를 강제로 임계값 너머로 밀어내기 전, 
                            # 원본 pl_rt를 백업하여 진단 보드 및 로그에 정확한 수치 표시
                            actual_pl_rt_for_diag = pl_rt
                            # 트리거 변수 설정
                            specific_tp = -999
                            specific_sl = 999
                            pl_rt = 999
                        else:
                            specific_tp = 999
                            specific_sl = -999

                # [v6.2.8/v6.5.9] 불타기 엔진 안정성 강화
                raw_b_enabled = cached_setting('bultagi_enabled', True)
                if raw_b_enabled is None:
                    b_enabled = True
                elif isinstance(raw_b_enabled, str):
                    b_enabled = raw_b_enabled.lower() in ['true', '1', 'yes']
                else:
                    b_enabled = bool(raw_b_enabled)
                
                if b_enabled:
                    safe_stk_nm = stock.get('stk_nm', stock.get('prdt_name', '알수없음'))
                    mapping_info = mapping.get(stk_cd) if mapping else None
                    
                    time_backup = {}
                    try:
                        base_path = get_base_path()
                        time_backup = load_json_safe(os.path.join(base_path, 'daily_buy_times.json'))
                    except: pass

                    buy_time_str = None
                    
                    if mapping_info:
                        buy_time_val = mapping_info.get('time')
                        buy_time_str = buy_time_val.get('time') if isinstance(buy_time_val, dict) else buy_time_val
                    
                    if not buy_time_str or buy_time_str == "99:99:99":
                        backup_entry = time_backup.get(stk_cd, {})
                        if isinstance(backup_entry, str): buy_time_str = backup_entry
                        else: buy_time_str = backup_entry.get('time')
                        
                        if buy_time_str:
                            if not mapping_info: 
                                mapping_info = {
                                    'name': safe_stk_nm, 
                                    'strat': 'HTS', 
                                    'time': buy_time_str, 
                                    'recovered': True,
                                    'bultagi_done': backup_entry.get('done', False) if isinstance(backup_entry, dict) else False
                                }
                                mapping[stk_cd] = mapping_info
                    
                    if buy_time_str and buy_time_str != "99:99:99":
                        info = mapping_info 
                        if safe_stk_nm == '알수없음' and info.get('name'): safe_stk_nm = info['name']
                        
                        # [V5.1.34] 불타기 매도 설정 재사용 (위에서 로드한 변수 활용)
                        # 여기서는 변수만 정의 (루프 내에서 이미 로드됨)
                        pass 
                        
                        try:
                            from datetime import datetime, timedelta
                            now = datetime.now()
                            wait_sec = int(cached_setting('bultagi_wait_sec', 10))
                            
                            # [V5.1.28] 시간 포맷 유효성 검사 및 정제 ([미상] 대응)
                            clean_time = str(buy_time_str).strip()
                            b_time = None
                            
                            if "[미상]" in clean_time or not clean_time:
                                # [자율] 대기 시간이 충분히 지난 것으로 간주 (유저 요청: 30초+ 지난 상태로 설정)
                                b_time = now - timedelta(seconds=max(wait_sec, 30) + 5)
                            else:
                                try:
                                    # 시간만 있는 경우와 날짜가 포함된 경우(HTS 리턴값) 대응
                                    if len(clean_time) > 8: # 예: "20260410 09:30:00"
                                        b_time = datetime.strptime(clean_time, "%Y%m%d %H:%M:%S")
                                    else:
                                        b_time = datetime.strptime(now.strftime("%Y%m%d") + " " + clean_time, "%Y%m%d %H:%M:%S")
                                except:
                                    # 파싱 실패 시에도 대기시간 통과 처리를 위해 과거 시간 할당
                                    b_time = now - timedelta(seconds=max(wait_sec, 30) + 5)
                            
                            elapsed = (now - b_time).total_seconds() if b_time else 999999
                            
                            if -60 < elapsed < 0:
                                elapsed = 0
                            elif elapsed <= -60:
                                elapsed = 999999
                            


                            current_price = safe_float(stock.get('prpr', stock.get('now_prc', stock.get('cur_prc', 0))))
                            buy_price = safe_float(stock.get('avg_prc', stock.get('pchs_avg_pric', 0)))

                            # [v1.9.0] 불타기 5관문 시스템 (5-Gate System) 복구
                            # [v5.0.8] 진입 상태 결정 고도화: 불타기 완료 여부 또는 HTS(직점매매) 여부를 통합 판단
                            bultagi_done = info.get('bultagi_done', False) or info.get('strat') == 'HTS'
                            
                            current_gate = info.get('current_gate', 1)
                            gate_status = ["⏳", "⏳", "⏳", "⏳", "⏳"] # 상태 아이콘
                            gate_details = ["-", "-", "-", "-", "-"] # 상세 수치
                            
                            # --- Gate 2: 현재 수익 (수익권 확인) 미리 계산 ---
                            # [v5.1.14] 확장 데이터 조회를 위한 필터링 지표로 사용하기 위해 계산 순서를 위로 본동함
                            is_profit = current_price > 0 and buy_price > 0 and current_price >= buy_price
                            
                            # --- 데이터 수집 (확장 데이터) ---
                            # [v5.1.14 / v5.1.31] 지능형 부하 분산: 
                            # 1. '진입 전'이고 '수익권'일 때만 무거운 확장 데이터를 조회함
                            # 2. 과도한 API 호출 방지를 위해 종목당 최소 0.5초의 간격을 두고 조회함 (반응 속도 최적화)
                            power_en = cached_setting('bultagi_power_enabled', False)
                            slope_en = cached_setting('bultagi_slope_enabled', False)
                            orderbook_en = cached_setting('bultagi_orderbook_enabled', False)
                            
                            ex_data = None
                            try:
                                # [v5.1.30] 스로틀링 체크
                                last_ex_time = info.get('last_ex_update', 0)
                                should_fetch_ex = (time.time() - last_ex_time >= 0.5) # 최소 0.5초 간격 (사용자 요청: 1.0 -> 0.5)

                                if not bultagi_done and is_profit and (power_en or slope_en or orderbook_en) and should_fetch_ex:
                                    from stock_info import get_extended_stock_data
                                    ex_data = get_extended_stock_data(stk_cd, token=token)
                                    info['last_ex_update'] = time.time()
                                    # [v5.1.14] 내부 딜레이(time.sleep)를 완전히 제거하여 전수 조사 속도 극대화
                                elif bultagi_done or not is_profit:
                                    # 진입 완료 후나 수익권이 아닐 때는 캐시된 데이터만 사용 (조회 생략)
                                    pass
                            except Exception as ex_err:
                                if show_diag: print(f"⚠️ [ExData-Err] {safe_stk_nm}: {ex_err}")

                            # --- Gate 1: 경과 시간 (타겟 포착 대기) ---
                            is_time_ok = current_gate > 1 or elapsed >= wait_sec
                            gate_status[0] = "✅" if is_time_ok else "⏳"
                            gate_details[0] = f"{int(elapsed)}/{wait_sec}s"
                            
                            if not bultagi_done and current_gate == 1 and is_time_ok:
                                current_gate = 2

                            # --- Gate 2: 현재 수익 (수익권 확인) ---
                            if is_profit:
                                gate_status[1] = "✅"
                                gate_details[1] = f"{int(current_price):,}/{int(buy_price):,}"
                                if not bultagi_done and current_gate == 2: current_gate = 3
                            else:
                                gate_status[1] = "🚫"
                                gate_details[1] = f"{int(current_price):,}/{int(buy_price):,}"
                                if not bultagi_done and current_gate >= 3: current_gate = 2
                            
                            # --- Gate 3: 체결 강도 ---
                            if power_en:
                                p_limit = safe_float(cached_setting('bultagi_power_val', 120), 120.0)
                                cur_p = ex_data['power'] if ex_data else 0.0
                                if cur_p >= p_limit:
                                    gate_status[2] = "✅"
                                    gate_details[2] = f"{cur_p:.0f}/{p_limit:.0f}"
                                    if not bultagi_done and current_gate == 3: current_gate = 4
                                else:
                                    # [v4.2.0] 현장 진단용 로그 (3관문 상태 실시간 출력, 소수점 1자리로 갱신 확인 가능)
                                    if cur_p > 0:
                                        gate_details[2] = f"{cur_p:.1f}/{p_limit:.0f}"
                                    else: # cur_p <= 0 인 경우에도 기본 포맷으로 표시
                                        gate_details[2] = f"{cur_p:.0f}/{p_limit:.0f}"
                                    gate_status[2] = "🚫"
                            else:
                                gate_status[2] = "⏩"
                                if not bultagi_done and current_gate == 3: current_gate = 4

                            # --- Gate 4: 추세 변화 (상승) ---
                            if slope_en:
                                last_p = info.get('last_power', 0)
                                cur_p = ex_data['power'] if ex_data else 0.0
                                if cur_p > last_p:
                                    gate_status[3] = "✅"
                                    gate_details[3] = "📈"
                                    if not bultagi_done and current_gate == 4: current_gate = 5
                                else:
                                    gate_status[3] = "📉"
                                    gate_details[3] = "📉"
                                info['last_power'] = cur_p
                            else:
                                gate_status[3] = "⏩"
                                if not bultagi_done and current_gate == 4: current_gate = 5

                            # --- Gate 5: 호가 잔량비 ---
                            if orderbook_en:
                                ob_limit = safe_float(cached_setting('bultagi_orderbook_val', 2.0), 2.0)
                                ask_q = ex_data.get('total_ask_qty', 0) if ex_data else 0
                                bid_q = ex_data.get('total_bid_qty', 1) if ex_data else 1
                                ob_ratio = ask_q / bid_q if bid_q > 0 else 0
                                
                                if ex_data and ex_data.get('orderbook_valid'):
                                    if ob_ratio >= ob_limit:
                                        gate_status[4] = "✅"
                                        gate_details[4] = f"{ob_ratio:.1f}/{ob_limit:.1f}"
                                        if not bultagi_done and current_gate == 5: current_gate = 6 
                                    else:
                                        gate_status[4] = "⚖️"
                                        gate_details[4] = f"{ob_ratio:.1f}/{ob_limit:.1f}"
                                else:
                                    gate_status[4] = "⏳"
                                    gate_details[4] = f"0.0/{ob_limit:.1f}"
                            else:
                                gate_status[4] = "⏩"
                                if not bultagi_done and current_gate == 5: current_gate = 6
                            
                            # [v5.0.8 Hotfix] 현재 단계 저장 (상태 유지 및 DB 동기화)
                            if not bultagi_done and current_gate != info.get('current_gate'):
                                info['current_gate'] = current_gate
                                try:
                                    from check_n_buy import update_stock_gate
                                    update_stock_gate(stk_cd, current_gate)
                                except: pass

                            # [v5.0.8] 진입 완료 상태 결정 로직 정밀화 (bultagi_done 플래그 중심)
                            if bultagi_done:
                                phase_txt = "진입완료"
                                for gi in range(5): gate_status[gi] = "✅"
                            else:
                                if current_gate <= 5: 
                                    phase_txt = f"{current_gate}관문"
                                    # [v5.0.8] 5관문 통과 직후 '주문중' 상태 표시로 유저 혼선 방지 (실제 체결 전 단계)
                                    if current_gate == 5 and all(s == "✅" for s in gate_status):
                                         phase_txt = "불타기중" 
                                else: 
                                    phase_txt = "주문대기"
                            
                            # [신규] 종가 베팅 종목일 경우 머리말 추가 (UI 강조용)
                            if info.get('strat') == 'CLOSING_BET':
                                phase_txt = f"종가:{phase_txt}"

                            # [v3.3.0] 매도 조건 시각적 마킹 (✅) - 전 종목 적용
                            diag_pl_rt = pl_rt if pl_rt < 999 else actual_pl_rt_for_diag
                            
                            # [V5.1.34] 설정 로드부 통합 삭제 (상단 통합 변수 재사용)
                            
                            # [v5.0.8] 매도 조건 표시 이원화 ([기본] vs [불타기])
                            conds = []
                            if not bultagi_done:
                                # [진입 전] 원래 설정된 기본 TP/SL 표시
                                specific_tp_val = info.get('tp', specific_tp)
                                specific_sl_val = info.get('sl', specific_sl)
                                is_tp_met = "✅" if diag_pl_rt >= safe_float(specific_tp_val) else ""
                                is_sl_met = "✅" if diag_pl_rt <= safe_float(specific_sl_val) else ""
                                conds.append(f"{is_tp_met}● TP:{specific_tp_val}%")
                                conds.append(f"{is_sl_met}● SL:{specific_sl_val}%")
                            else:
                                # [진입 후] 불타기 전용 매도 룰 표시 (텍스트 간소화 및 감시 도트 도입)
                                if b_ts_en:
                                    peak_val = safe_float(info.get('peak_pl_rt', 0.0))
                                    drop = peak_val - diag_pl_rt
                                    is_mon = "● " if peak_val >= b_ts_start else ""
                                    is_met = "✅" if (peak_val >= b_ts_start and drop >= b_ts_val) else ""
                                    conds.append(f"{is_met}{is_mon}TS:{b_ts_val}(▼{drop:.1f})")
                                if b_pres_en:
                                    is_mon = "● " if peak_rt >= b_pres_trig else ""
                                    is_met = "✅" if peak_rt >= b_pres_trig and diag_pl_rt <= b_pres_lim else ""
                                    conds.append(f"{is_met}{is_mon}P:{b_pres_trig}>{b_pres_lim}(C:{diag_pl_rt:.1f})")
                                
                                # TS나 보존이 꺼져있거나, 켜져있더라도 기본 불타기 TP/SL은 항상 가이드로 표시 (사용자 요청)
                                if b_tp_en:
                                    is_met = "✅" if diag_pl_rt >= b_tp else ""
                                    conds.append(f"{is_met}● TP:{b_tp}%")
                                if b_sl_en:
                                    is_met = "✅" if diag_pl_rt <= b_sl else ""
                                    conds.append(f"{is_met}● SL:{b_sl}%")

                            if not conds: conds.append("-")
                            sell_cond_str = " / ".join(conds)
                            
                            # [v3.3.0] ✅ 마크와 상세 수치를 결합하여 전송
                            def format_gate(status, detail):
                                if status == "✅": return f"✅ {detail}"
                                return f"{status} {detail}"

                            # [V4.0.2] 거래대금 순위 정보 추출 (안정성 강화)
                            rank_val = "-"
                            try:
                                from check_n_buy import TOP_VOLUME_RANK_CACHE
                                if TOP_VOLUME_RANK_CACHE:
                                    if stk_cd in TOP_VOLUME_RANK_CACHE:
                                        rank_val = f"{TOP_VOLUME_RANK_CACHE.index(stk_cd) + 1}위"
                                    else:
                                        rank_val = f"순위밖(/{len(TOP_VOLUME_RANK_CACHE)}위)"
                                else:
                                    rank_val = "미수신"
                            except Exception as rank_e:
                                rank_val = "오류"
                                print(f"⚠️ [Rank-DEBUG] 순위 계산 오류: {rank_e}")

                            stat_payload = f"{safe_stk_nm}|{phase_txt}|{rank_val}|{format_gate(gate_status[0], gate_details[0])}|{format_gate(gate_status[1], gate_details[1])}|{format_gate(gate_status[2], gate_details[2])}|{format_gate(gate_status[3], gate_details[3])}|{format_gate(gate_status[4], gate_details[4])}|{sell_cond_str}"
                            print(f"[BULTAGI_STAT] {stat_payload}")

                            # 최종 트리거 (진입 전일 때만 실행)
                            if not bultagi_done and current_gate >= 6:
                                # [V4.3.4] 일시 정지된 종목은 불타기 발동 스킵
                                if safe_stk_nm in disabled_stocks:
                                    print(f"⏸ <font color='#f39c12'>[정지중]</font> {safe_stk_nm}: 5관문 돌파! 그러나 일시 정지 중이라 주문을 건너뜁니다.")

                                # [V5.3.9] 불타기 가격 상한선 가드 (고점 추격 방지) - 핵심 수정
                                elif cached_setting('bultagi_limit_enabled', True):
                                    from stock_info import get_price_high_data
                                    from login import fn_au10001 as _get_token
                                    _token = token if token else _get_token()
                                    _cur_p, _, _base_p = get_price_high_data(stk_cd, _token)
                                    _limit_rt = float(cached_setting('bultagi_limit_rt', 22.0) or 22.0)
                                    _cur_rt = ((_cur_p - _base_p) / _base_p * 100) if _base_p > 0 else 0
                                    if _cur_rt >= _limit_rt:
                                        phase_txt = "상한초과"
                                        print(f"🛡️ <font color='#ff6b6b'><b>[상한차단]</b></font> {safe_stk_nm} 현재 대비율({_cur_rt:.1f}%)이 상한선({_limit_rt:.1f}%)을 초과하여 불타기 진입을 생략합니다.")
                                        print(f"[BULTAGI_STAT] {safe_stk_nm}|상한초과|{rank_val}|✅|✅|✅|✅|✅|🛡 상한차단({_cur_rt:.1f}%)")
                                    else:
                                        print(f"🔥 <font color='#ff4444'><b>[발송]</b></font> {safe_stk_nm}: 5관문 모두 돌파! (현재 대비율: {_cur_rt:.1f}%) 주문 집행...")
                                        try:
                                            from bultagi_engine import trigger_bultagi_buy
                                            success = trigger_bultagi_buy(stk_cd, token=token)
                                            if success:
                                                print(f"✅ [성공] {safe_stk_nm}: 매수 주문이 성공적으로 발송되었습니다.")
                                                update_stock_condition(stk_cd, name='불타기진입', strat='불타기', seq=info.get('seq'), bultagi_done=True)
                                            else:
                                                print(f"❌ [실패] {safe_stk_nm}: 엔진 호출은 성공했으나 주문 발송에 실패했습니다.")
                                        except Exception as eng_err:
                                            print(f"❌ [오류] {safe_stk_nm}: 엔진 호출 중 예외 발생: {eng_err}")

                                # 상한선 가드 OFF 시 즉시 발사
                                else:
                                    print(f"🔥 <font color='#ff4444'><b>[발송]</b></font> {safe_stk_nm}: 5관문 모두 돌파! 주문 집행...")
                                    try:
                                        from bultagi_engine import trigger_bultagi_buy
                                        success = trigger_bultagi_buy(stk_cd, token=token)
                                        if success:
                                            print(f"✅ [성공] {safe_stk_nm}: 매수 주문이 성공적으로 발송되었습니다.")
                                            update_stock_condition(stk_cd, name='불타기진입', strat='불타기', seq=info.get('seq'), bultagi_done=True)
                                        else:
                                            print(f"❌ [실패] {safe_stk_nm}: 엔진 호출은 성공했으나 주문 발송에 실패했습니다.")
                                    except Exception as eng_err:
                                        print(f"❌ [오류] {safe_stk_nm}: 엔진 호출 중 예외 발생: {eng_err}")

                        except Exception as e_proc_inner:
                            if show_diag: print(f"⚠️ [불타기진단내부오류] {safe_stk_nm}: {e_proc_inner}")

                    # --- [Gate 6] 실제 매도 실행 로직 복구 (V3.1.9) ---
                    # [V4.3.4] 일시 정지 중인 종목은 매도도 스킵
                    if safe_stk_nm in disabled_stocks:
                        if pl_rt > specific_tp or pl_rt < specific_sl:
                            print(f"⏸ <font color='#f39c12'>[정지중]</font> {safe_stk_nm}: 매도 조건 도달! 그러나 일시 정지 중이라 매도를 건너뜁니다.")
                    elif pl_rt > specific_tp or pl_rt < specific_sl:
                        if MarketHour.is_market_open_time():
                            sell_result = sell_stock(stk_cd, str(qty), token=token)
                            
                            # 주문 성공 여부 확인
                            ret_code = sell_result.get('return_code') if isinstance(sell_result, dict) else sell_result
                            if str(ret_code) == '0' or ret_code == 0:
                                result_type = sell_reason if sell_reason else ("익절" if pl_rt > specific_tp else "손절")
                                real_pl_rt = safe_float(stock.get('pl_rt', 0)) if pl_rt == 999 else pl_rt
                                
                                message = f'🚀 {safe_stk_nm} {qty}주 {result_type} 완료 (수익율: {real_pl_rt:.2f}%)'
                                print(f"<font color='#ffdf00'>{message}</font>")
                                tel_send(message, msg_type='log')
                                print(f"[BULTAGI_REMOVE] {safe_stk_nm}") # UI 보드에서 삭제
                                
                                # [v5.0.8] 매도 DB 저장 시 전략명 정규화 (랭크, 불타기, VI 등)
                                try:
                                    raw_strat = info.get('strat', 'none')
                                    if raw_strat == 'SYSTEM_VI' or raw_strat == 'VI':
                                        s_mode_db = 'VI'
                                    elif raw_strat == 'MORNING' or (isinstance(raw_strat, str) and raw_strat.startswith('MORNING')):
                                        s_mode_db = '시초가'
                                    elif raw_strat == 'CLOSING_BET':
                                        s_mode_db = '종가'
                                    elif raw_strat == 'HTS':
                                        s_mode_db = 'HTS'
                                    elif raw_strat == 'BULTAGI' or raw_strat in ['qty', 'amount', 'percent']:
                                        s_mode_db = '불타기' if bultagi_done else '랭크'
                                    else:
                                        s_mode_db = '불타기' if bultagi_done else '랭크'

                                    pnl_amt = safe_float(stock.get('evlu_pfls_amt', 0))
                                    tax_amt = safe_float(stock.get('evlu_pftls_tax', 0))
                                    session_logger.record_sell(
                                        stk_cd, safe_stk_nm, qty, current_price, 
                                        real_pl_rt, pnl_amt, tax=tax_amt, 
                                        seq=seq, strat_mode=s_mode_db
                                    )
                                except Exception as log_err:
                                    print(f"⚠️ [수익기록오류] {log_err}")

                                # 매수 매핑 정보에서도 삭제
                                try:
                                    from check_n_buy import remove_stock_condition
                                    remove_stock_condition(stk_cd)
                                except: pass

                            else:
                                print(f"❌ [매도실패] {safe_stk_nm}: {sell_result}")
            
            return True # 한 루프 성공 완료
            
        except Exception as e_main:
            print(f"⚠️ [불타기엔진오류] {e_main}")
            return False

    except Exception as e_outer:
        print(f"⚠️ [chk_n_sell 최상위오류] {e_outer}")
        return False

# [v1.1.0] 외부 호출용 래퍼 (동기 환경 대응)
def run_chk_n_sell():
    # 이제 chk_n_sell은 다시 동기 함수이므로 별도 이벤트 루프 필요 없음
    return chk_n_sell()

if __name__ == "__main__":
    run_chk_n_sell()
