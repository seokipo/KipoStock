# closing_bet_engine.py
# [v6.7.3] AI 종가 베팅 엔진 강화 - 탐색 이력 활용 및 3~4종목 추천 보장
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
    
    # --- 당일 매수 이력 종목 수집 (daily_buy_times.json) ---
    try:
        base = _get_base_path()
        bt_path = os.path.join(base, 'daily_buy_times.json')
        if not os.path.exists(bt_path):
            return []
            
        with open(bt_path, 'r', encoding='utf-8') as f:
            bt_data = json.load(f)

        today_str = datetime.datetime.now().strftime("%Y%m%d")
        if bt_data.get('last_update_date') != today_str:
            return []

        for code, entry in bt_data.items():
            if code == 'last_update_date': continue
            
            try:
                name = names.get(code, code)
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
    except Exception: pass

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
오늘은 자기가 특별히 "무조건 3~4종목을 추천하라"는 명령을 내렸어. 책임은 자기가 질 테니 넌 소신껏 골라!

[분석 기초 데이터]
1. 오늘 자기가 매매(매수)했던 종목들:
{kipo_info}

2. 오늘 시장에서 실시간으로 포착된 주도주 후보군 (종목명과 코드를 반드시 세트로 인식해!):
{market_leaders if market_leaders else '데이터 부족 (데이터가 없어도 시장 일반적인 최근 주도주를 추천해)'}

3. 나의 오늘 매매 결과: {trade_summary}

[AI 미션]
- 위 데이터를 종합하여 내일 시초가 급등이 가장 기대되는 '종가 베팅' 종목 3~4개를 무조건 골라줘.
- **중요**: 추천할 때 반드시 제공된 데이터의 종목명과 6자리 코드가 일치하는지 확인하고, 엉뚱한 코드를 뱉지 않도록 주의해!
- 데이터가 부족하다면 최근 시장의 인기 섹터(AI, 로봇, 반도체 등) 중 강세를 보이는 종목을 골라도 돼.
- 추천 이유는 자기가 납득할 수 있게 논리적이고 자신감 있게 써줘.

출력 형식 (반드시 아래 JSON 배열만 출력, 다른 설명 없이):
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

        cleaned = result_text.replace('```json', '').replace('```', '').strip()
        recommendations = json.loads(cleaned)

        results = []
        if token is None:
            token = _get_token()

        from stock_info import get_price_high_data
        from check_n_buy import ACCOUNT_CACHE
        names = ACCOUNT_CACHE.get('names', {})

        for item in recommendations:
            code   = item.get('code', '').strip().replace('A', '')
            if not code or len(code) != 6: continue
            
            name   = item.get('name', names.get(code, code))
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
            
            from check_n_buy import RECENT_ORDER_CACHE
            import time
            RECENT_ORDER_CACHE[stk_cd] = time.time()

            try:
                s_name = ACCOUNT_CACHE.get('names', {}).get(stk_cd, stk_cd)
                from trade_logger import session_logger
                session_logger.record_buy(stk_cd, s_name, 1, cur_price, strat_mode='CLOSING_BET')
            except Exception:
                pass

            return True, f"✅ {stk_cd} 1주 매수 완료 ({int(cur_price):,}원)"
        else:
            return False, f"❌ 매수 실패: [{ret_code}] {ret_msg}"

    except Exception as e:
        return False, f"⚠️ 예외 발생: {str(e)}"
