# closing_bet_engine.py
# [v1.5.0] AI 추천 종목 차별화 및 중복 제거 (필터가 놓친 잠룡 발굴)
import os
import sys
import json
import datetime
import traceback
from get_setting import get_setting

# -------------------------------------------------------------------------
# 내부 헬퍼
# -------------------------------------------------------------------------
def _get_token():
    try:
        from login import fn_au10001 as get_token
        return get_token()
    except Exception:
        return None

def _get_base_path():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

# -------------------------------------------------------------------------
# 1. KipoStock 필터 조건으로 종목 탐색
# -------------------------------------------------------------------------
def get_kipo_filter_stocks(token=None):
    """
    [v6.7.3 수정] 철저히 '오늘 하루 단 한 주라도 매수한 종목'만 대상으로 
    KipoStock 관점 필터를 적용하여 리스트업합니다. (자기가 원한 정밀 필터!)
    """
    if token is None:
        token = _get_token()

    peak_rt   = float(get_setting('kipostock_peak_rt',    15.0))
    now_min   = float(get_setting('kipostock_now_rt_min',  5.0))
    now_max   = float(get_setting('kipostock_now_rt_max', 12.0))

    results   = []
    from stock_info import get_price_high_data
    from check_n_buy import ACCOUNT_CACHE

    names = ACCOUNT_CACHE.get('names', {})
    
    # --- [v1.3.7] 검사 대상 종목 풀(Pool) 전면 확대 ---
    target_codes = set()
    base = _get_base_path()
    
    # 1. 당일매매일지 API(ka10170)를 통한 가장 정확한 오늘 매매(매수) 종목 수집
    try:
        from acc_diary import fn_ka10170
        diary_res = fn_ka10170(token)
        for item in diary_res.get('list', []):
            stk_cd = str(item.get('stk_cd', '')).strip()
            # KIS API에서 수량은 문자열 형태로 옴
            try: buy_qty = int(item.get('buy_qty', '0'))
            except: buy_qty = 0
            
            # 오늘 매수한 수량이 1주라도 있다면 풀에 추가 (HTS 당일매매 리스트와 100% 일치)
            if stk_cd and len(stk_cd) == 6 and buy_qty > 0:
                target_codes.add(stk_cd)
    except Exception as e:
        print(f"⚠️ [ClosingBet] 당일매매일지 API 연동 오류: {e}")

    # 2. 당일 HTS 실시간 탐색 종목 수집 (매수까진 안 갔지만 알람에 포착된 알짜 종목들)
    try:
        dt_path = os.path.join(base, 'daily_detected_stocks.json')
        if os.path.exists(dt_path):
            with open(dt_path, 'r', encoding='utf-8') as f:
                detected_codes = json.load(f)
                for c in detected_codes:
                    if isinstance(c, str) and len(c) == 6:
                        target_codes.add(c)
    except Exception: pass

    # 3. 현재 보유 중인 종목 수집 (어제 사서 오늘까지 들고 있는 등)
    try:
        holdings = ACCOUNT_CACHE.get('holdings', {})
        for c in holdings.keys():
            if len(str(c)) == 6: target_codes.add(str(c))
    except Exception: pass

    # 4. 불타기 조건(실시간 감시 대상)에 등록된 종목
    try:
        from check_n_sell import get_stock_condition_mapping
        mapping = get_stock_condition_mapping()
        for c in mapping.keys():
            if len(str(c)) == 6: target_codes.add(str(c))
    except Exception: pass

    # --- 취합된 풀을 대상으로 철저한 필터링 수행 ---
    from stock_info import get_current_price
    for code in target_codes:
        try:
            # [v1.4.1] 이름이 코드와 같거나 없으면 실시간 정보에서 이름이라도 가져오기
            name = names.get(code, code)
            if name == code or not name:
                res_name, _ = get_current_price(code, token=token)
                if res_name: name = res_name
                
            cur_price, high_price, prev_close = get_price_high_data(code, token=token)

            if prev_close <= 0 or cur_price <= 0: continue

            cur_rt  = round((cur_price - prev_close) / prev_close * 100, 2)
            high_rt = round((high_price - prev_close) / prev_close * 100, 2)

            # 철저한 조건식 검증 (고가 달성 & 현재 수익률 구간)
            if high_rt >= peak_rt and now_min <= cur_rt <= now_max:
                results.append({
                    'code':      code,
                    'name':      name,
                    'cur_rt':    cur_rt,
                    'high_rt':   high_rt,
                    'cur_price': int(cur_price),
                    'source':    'KipoFilter',
                })
        except: pass

    return results

# -------------------------------------------------------------------------
# 2. Gemini AI 종가 베팅 추천
# -------------------------------------------------------------------------
def get_ai_closing_recommendations(token=None, kipo_stocks=None):
    """
    [v6.7.3 강화] 전체 시장 탐색 이력을 토대로 Gemini AI가 3~4종목을 필히 추천합니다.
    """
    try:
        from config import gemini_api_key
        from google import genai

        if not gemini_api_key: return []

        # 1. 오늘 탐색된 모든 시장 주도주 데이터 수집
        market_leaders = []
        try:
            base = _get_base_path()
            fpath = os.path.join(base, 'daily_detected_stocks.json')
            if os.path.exists(fpath):
                with open(fpath, 'r', encoding='utf-8') as f:
                    codes = json.load(f)
                
                from stock_info import get_price_high_data, get_current_price
                for cd in codes[-30:]: # 최근 30개까지만 (토큰 절약 및 집중)
                    # [v6.7.4] 종목명 실시간 조회 추가 (코드 오매칭 방지)
                    s_name, _ = get_current_price(cd, token=token)
                    if not s_name: s_name = "이름모름"
                    
                    p, h, b = get_price_high_data(cd, token=token)
                    if b > 0:
                        crt = round((p - b) / b * 100, 2)
                        hrt = round((h - b) / b * 100, 2)
                        market_leaders.append(f"- {s_name}({cd}): 고가:{hrt}%, 현재가:{crt}%")
        except: pass

        trade_summary = _build_trade_summary()
        kipo_info     = _format_kipo_stocks(kipo_stocks or [])
        now_str       = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        
        # 2. 강력한 AI 프롬프트 (3~4개 추천 명문화 + 매칭 강화)
        prompt = f"""
너는 주식 시장 전체를 꿰뚫어보는 KipoStock의 천재 종가 베팅 AI야. 현재 시각: {now_str}
오늘은 자기가 특별히 "데이터가 부족하더라도 반드시 3~4종목을 추천하라"는 특명을 내렸어. 책임은 자기가 질 테니 넌 소신껏 골라!

[분석 기초 데이터]
1. 오늘 자기가 직접 필터링하거나 매수한 종목들:
{kipo_info}

2. 오늘 시장에서 실시간으로 포착된 주도주 후보군:
{market_leaders if market_leaders else '포착된 실시간 데이터 없음 (최근 시장 주도주를 바탕으로 추천 수행)'}

3. 나의 오늘 매매 결과 요약: {trade_summary}

[AI 미션]
- 위 데이터를 종합하여 내일 시초가 급등이 가장 기대되는 '종가 베팅' 종목 3~4개를 엄선해서 골라줘.
- **최우선 가이드라인 (중복 금지!!)**: 
  1. 아래 제공된 '[1. 오늘 매수한 종목(필터 통과 종목)]'은 이미 사용자가 알고 있는 종목들이야. **이들과 중복되지 않는 새로운 알짜 종목**을 우선적으로 발굴해줘.
  2. 만약 제공된 주도주 목록도 이미 필터 종목들과 많이 겹친다면, 네가 가진 자체 지식(최근 시장 테마, 기술적 수렴, 바닥권 탈출 등)을 총동원해 "필터는 놓쳤지만 내일 급등할 잠룡"을 3~4개 채워줘.
  3. 절대 상상 속의 종목을 만들지 말고, 실제 코스피/코스닥에 상장된 종목과 6자리 코드를 정확히 매칭해.
- 추천 이유는 자기가 무조건 납득할 수 있게 구체적인 기술적/테마적 근거를 들어 자신감 있게 써줘.

출력 형식 (반드시 아래 JSON 배열만 출력, 다른 군더더기 설명 없이):
[
  {{"code": "6자리코드", "name": "종목명", "reason": "자신감 넘치는 추천 이유 (2줄)"}},
  {{"code": "6자리코드", "name": "종목명", "reason": "자신감 넘치는 추천 이유 (2줄)"}},
  {{"code": "6자리코드", "name": "종목명", "reason": "자신감 넘치는 추천 이유 (2줄)"}},
  {{"code": "6자리코드", "name": "종목명", "reason": "자신감 넘치는 추천 이유 (2줄)"}}
]
"""
        BEST_MODELS = [
            'models/gemini-2.0-flash',
            'models/gemini-flash-lite-latest',
        ]
        client = genai.Client(api_key=gemini_api_key)
        result_text = None
        for model_name in BEST_MODELS:
            try:
                resp = client.models.generate_content(model=model_name, contents=prompt)
                result_text = resp.text.strip()
                break
            except Exception:
                continue

        if not result_text:
            return []

        # [v1.3.6] JSON 추출 강화 (re 도입)
        import re
        try:
            match = re.search(r'\[\s*\{.*\}\s*\]', result_text, re.DOTALL)
            if match:
                cleaned = match.group(0)
            else:
                cleaned = result_text.replace('```json', '').replace('```', '').strip()
            recommendations = json.loads(cleaned)
        except Exception as e:
            print(f"⚠️ AI 결과 파싱 실패: {e}\nRaw: {result_text}")
            return []

        results = []
        if token is None:
            token = _get_token()

        import time
        from stock_info import get_price_high_data
        from check_n_buy import ACCOUNT_CACHE
        from news_sniper import get_stock_code_by_name
        names = ACCOUNT_CACHE.get('names', {})
        
        # [v6.7.4 BugFix] 이름으로 코드 역추적을 위한 리버스 매핑 생성
        name_to_code = {v: k for k, v in names.items()}

        for item in recommendations:
            raw_code = item.get('code', '').strip().replace('A', '')
            raw_name = item.get('name', names.get(raw_code, raw_code)).replace('(주)', '').strip()
            
            # [Fix v6.7.5] AI가 종목명과 코드를 헷갈리거나 조작한 경우(Mismatch)를 강력히 교정
            # 전략: AI가 추천한 "이름(name)"에 맞춰 코드를 찾아가는 것이 가장 정확함
            code = raw_code
            name = raw_name
            
            if raw_name in name_to_code:
                # 1. 내 캐시에 있는 종목명이면 해당 코드 적용 (가장 빠름)
                code = name_to_code[raw_name]
                name = raw_name
            else:
                # 2. 내 캐시에 없으면, 네이버 금융 검색 API로 진짜 코드 발굴
                searched_code = get_stock_code_by_name(raw_name)
                time.sleep(0.1) # 짧은 대기 방어
                if searched_code:
                    code = searched_code
                    name = raw_name
                else:
                    # 3. 네이버 검색도 실패했다면, AI가 뱉은 raw_code가 진짜 존재하는지 증권사 API에 최종 확인
                    from stock_info import get_current_price
                    off_name, off_price = get_current_price(raw_code, token=token)
                    if off_name:
                        # 유효한 거래 코드이므로, 이 코드의 본래 '오피셜 명칭'으로 화면에 출력할 이름을 강제 덮어쓰기
                        code = raw_code
                        name = off_name
                    else:
                        continue # 이도 저도 아닌 가짜 데이터면 과감하게 버림!

            if not code or len(code) != 6: continue
            
            # [v1.5.0] KipoStock 필터 종목과 중복되는 경우 최종 필터링 (새로운 종목만 보고 싶어하는 자기 요청 반영)
            overlap = False
            for ks in (kipo_stocks or []):
                if ks.get('code') == code:
                    overlap = True
                    break
            if overlap: continue
            
            reason = item.get('reason', '')
            
            cur_price, _, prev_close = get_price_high_data(code, token=token)
            cur_rt = 0.0
            if prev_close > 0:
                cur_rt = round((cur_price - prev_close) / prev_close * 100, 2)

            results.append({
                'code':      code,
                'name':      name,
                'reason':    reason,
                'cur_rt':    cur_rt,
                'cur_price': int(cur_price),
                'source':    'AI',
            })
        return results

    except Exception:
        return []

def _build_trade_summary():
    """오늘 매매 요약 텍스트 생성"""
    try:
        from trade_logger import session_logger
        pnl_data = session_logger.get_pnl_timeline()
        if not pnl_data:
            return "오늘 매매 데이터 없음"

        total_pnl = sum(d.get('pnl', 0) for d in pnl_data)
        trades    = len(pnl_data)
        return f"총 {trades}건 매매, 누적 손익 {total_pnl:,}원"
    except Exception:
        return "매매 데이터 조회 불가"

def _format_kipo_stocks(stocks):
    """KipoFilter 종목 리스트를 프롬프트용 텍스트로 변환"""
    if not stocks:
        return "없음"
    lines = []
    for s in stocks:
        lines.append(
            f"- {s['name']}({s['code']}): 고가달성 {s.get('high_rt', 0)}%, 현재수익 {s.get('cur_rt', 0)}%"
        )
    return "\n".join(lines)

# -------------------------------------------------------------------------
# 3. 종목 1주 매수
# -------------------------------------------------------------------------
def buy_stock_qty1(stk_cd, token=None, seq_name="종베직접매수"):
    """선택된 종목을 시장가로 1주 매수."""
    try:
        if token is None:
            token = _get_token()
        if not token:
            return False, "토큰 발급 실패"

        stk_cd = stk_cd.replace('A', '')

        from buy_stock import fn_kt10000 as buy_stock_fn
        from stock_info import get_current_price
        from check_n_buy import ACCOUNT_CACHE

        _, cur_price = get_current_price(stk_cd, token=token)

        # 시장가 주문 (trde_tp='3')
        ret_code, ret_msg = buy_stock_fn(stk_cd, 1, '0', trde_tp='3', token=token)

        is_success = str(ret_code) == '0' or ret_code == 0
        if is_success:
            # 계좌 캐시 업데이트
            holdings = ACCOUNT_CACHE.get('holdings', {})
            cur_qty = holdings.get(stk_cd, 0)
            holdings[stk_cd] = cur_qty + 1
            
            from check_n_buy import RECENT_ORDER_CACHE, update_stock_condition
            import time
            RECENT_ORDER_CACHE[stk_cd] = time.time()

            try:
                s_name = ACCOUNT_CACHE.get('names', {}).get(stk_cd, stk_cd)
                from trade_logger import session_logger
                
                # [v5.0.6] 매핑 파일(stock_conditions.json)에도 즉시 기록하여 GUI 표시 및 불타기 연동 보장
                update_stock_condition(stk_cd, name=s_name, strat='CLOSING_BET')
                
                session_logger.record_buy(stk_cd, s_name, 1, cur_price, strat_mode='CLOSING_BET')
            except Exception:
                pass

            return True, f"✅ {stk_cd} 1주 매수 완료 ({int(cur_price):,}원)"
        else:
            return False, f"❌ 매수 실패: [{ret_code}] {ret_msg}"

    except Exception as e:
        return False, f"⚠️ 예외 발생: {str(e)}"
