import requests
import json
from config import host_url
from login import fn_au10001 as get_token

# 주식기본정보요청
def fn_ka10001(stk_cd, cont_yn='N', next_key='', token=None):
	# 1. 요청할 API URL
	endpoint = '/api/dostk/stkinfo'
	url =  host_url + endpoint

	# 2. header 데이터
	headers = {
		'Content-Type': 'application/json;charset=UTF-8', # 컨텐츠타입
		'authorization': f'Bearer {token}', # 접근토큰
		'cont-yn': cont_yn, # 연속조회여부
		'next-key': next_key, # 연속조회키
		'api-id': 'ka10001', # TR명
	}

	# 3. 요청 데이터
	params = {
		'stk_cd': stk_cd, # 종목코드 거래소별 종목코드 (KRX:039490,NXT:039490_NX,SOR:039490_AL)
	}

	# 4. http POST 요청
	response = requests.post(url, headers=headers, json=params)

	# 4. 응답 상태 코드와 데이터 출력
	# print('Code:', response.status_code)
	# print('Header:', json.dumps({key: response.headers.get(key) for key in ['next-key', 'cont-yn', 'api-id']}, indent=4, ensure_ascii=False))
	# print('Body:', json.dumps(response.json(), indent=4, ensure_ascii=False))  # JSON 응답을 파싱하여 출력

	# 응답 데이터 확인 및 종목명 추출
	try:
		response_data = response.json()
		# 응답 구조 확인: 직접 stk_nm이 있는지, 아니면 data 안에 있는지
		if 'stk_nm' in response_data:
			stk_nm = response_data['stk_nm']
		elif 'data' in response_data and isinstance(response_data['data'], dict) and 'stk_nm' in response_data['data']:
			stk_nm = response_data['data']['stk_nm']
		else:
			# print(f"⚠️ 종목명을 찾을 수 없습니다.")
			return None
		
		# 종목명이 비어있거나 None인 경우
		if not stk_nm or stk_nm.strip() == '':
			# print(f"⚠️ 종목명이 비어있습니다.")
			return None
		
		return stk_nm
	except KeyError:
		# print(f"⚠️ 응답에서 종목명 필드를 찾을 수 없습니다: {e}")
		return None
	except Exception:
		# print(f"⚠️ 종목명 조회 중 오류 발생: {e}")
		return None

# [신규] 종목명과 현재가를 함께 반환
def get_current_price(stk_cd, token=None):
    endpoint = '/api/dostk/stkinfo'
    url =  host_url + endpoint
    headers = {
        'Content-Type': 'application/json;charset=UTF-8',
        'authorization': f'Bearer {token}',
        'api-id': 'ka10001',
    }
    params = {'stk_cd': stk_cd}

    try:
        response = requests.post(url, headers=headers, json=params)
        data = response.json()
        res_data = data.get('data', data)
        name = res_data.get('stk_nm', '')
        
        # [수정] 여러 키 시도 (API별로 상이할 수 있음)
        price = 0
        keys_to_try = ['now_prc', 'clpr', 'stck_prpr', 'prpr', 'price', 'cur_prc', 'vi_stnd_prc']
        
        for key in keys_to_try:
            val = res_data.get(key)
            if val:
                # [Fix v6.2.4] 하락 중일 때 음수로 올 수 있으므로 abs() 처리
                price = abs(int(str(val).replace(',', '')))
                if price > 0:
                    break

        return name, price
    except Exception:
        # print(f"⚠️ 가격 조회 실패: {e}")
        return None, 0

# [신규] 불타기 상세 조건을 위한 확장 데이터 조회 (체결강도, 호가잔량)
def get_price_high_data(stk_cd, token=None):
    # [v1.4.0] 고가 및 기준가 매핑 보강 및 헤더 누락 해결
    headers = { 'Content-Type': 'application/json;charset=UTF-8', 'authorization': f'Bearer {token}', 'api-id': 'ka10001' }
    try:
        from config import host_url
        import requests
        res = requests.post(host_url + '/api/dostk/stkinfo', headers=headers, json={'stk_cd': stk_cd}, timeout=5)
        data = res.json().get('data', res.json())
        
        def _clean(v):
            if v is None: return 0
            return abs(int(str(v).replace(',', '').replace('+', '').replace('-', '')))

        # 현재가 (cur_prc, now_prc 등)
        now = 0
        for k in ['cur_prc', 'now_prc', 'clpr', 'stck_prpr', 'price']:
            if data.get(k):
                now = _clean(data.get(k))
                if now > 0: break
        
        # 고가 (high_pric, high_prc, hgpr 등)
        high = 0
        for k in ['high_pric', 'high_prc', 'hgpr', 'stck_hgpr', 'high']:
            if data.get(k):
                high = _clean(data.get(k))
                if high > 0: break
                
        # 전일종가/기준가 (base_pric, base_prc, prev_clpr 등)
        base = 0
        for k in ['base_pric', 'base_prc', 'prev_clpr', 'stck_sdpr']:
            if data.get(k):
                base = _clean(data.get(k))
                if base > 0: break
        
        return now, high, base
    except:
        return 0, 0, 0

def get_morning_data(stk_cd, token=None):
    """[신규 v6.9.7] 시초가 배팅 베이스 데이터 (현재가, 시가, 전일종가) 조회"""
    headers = { 'Content-Type': 'application/json;charset=UTF-8', 'authorization': f'Bearer {token}', 'api-id': 'ka10001' }
    try:
        import requests
        from config import host_url
        res = requests.post(host_url + '/api/dostk/stkinfo', headers=headers, json={'stk_cd': stk_cd}, timeout=5)
        data = res.json().get('data', res.json())
        
        now = 0
        for k in ['now_prc', 'clpr', 'stck_prpr', 'price', 'cur_prc']:
            if data.get(k): now = abs(int(str(data.get(k)).replace(',', ''))); break
        
        oprc = 0
        for k in ['stck_oprc', 'oprc', 'open_prc', 'open']:
            if data.get(k): oprc = abs(int(str(data.get(k)).replace(',', ''))); break
            
        base = 0
        for k in ['base_prc', 'prev_clpr', 'stck_sdpr', 'prdy_clpr']:
            if data.get(k): base = abs(int(str(data.get(k)).replace(',', ''))); break
            
        return now, oprc, base
    except Exception as e:
        print(f"⚠️ [MorningData] 조회 실패: {e}")
        return 0, 0, 0

def get_extended_stock_data(stk_cd, token=None):
    """
    체결강도, 총매도잔량, 총매수잔량 등 불타기 필터링에 필요한 정밀 데이터를 반환합니다.
    """
    result = {
        'name': '',
        'price': 0,
        'total_ask_qty': 0, # 총 매도 잔량
        'total_bid_qty': 0, # 총 매수 잔량
        'power': 0.0,       # [v1.2.9 Fix] 누락된 키 복구
        'raw_log': ""       # [v1.2.7] 상세 로그용 원시 데이터 샘플
    }
    
    # 1. 기본 정보 및 체결강도 조회 (ka10001)
    try:
        headers = { 'Content-Type': 'application/json;charset=UTF-8', 'authorization': f'Bearer {token}', 'api-id': 'ka10001' }
        res = requests.post(host_url + '/api/dostk/stkinfo', headers=headers, json={'stk_cd': stk_cd}, timeout=5)
        data = res.json().get('data', res.json())
        
        result['name'] = data.get('stk_nm', '')
        # 가격 추출
        for k in ['now_prc', 'clpr', 'stck_prpr', 'price', 'cur_prc']:
            v = data.get(k)
            if v:
                result['price'] = abs(int(str(v).replace(',', '')))
                if result['price'] > 0: break
        
        # [v4.2.1] ka10001 체결강도는 상대 수치일 가능성이 높으므로 로깅만 수행 (V3.3.7 데이터원 ka10046 복원을 위해 우선순위 하향)
        import re
        pwr_val = data.get('cntr_str')
        if pwr_val:
            try:
                # 로깅용으로만 보관하고 result['power']는 ka10046에서 결정하도록 함
                result['raw_log'] += f"[ka10001-Pwr:{pwr_val}] "
            except: pass

        # [v1.2.7] 상세 로그용 원시 데이터 보관
        result['raw_log'] += f"[ka10001] {str(data)[:200]}... "
    except: pass

    # 2. 호가 잔량 정보 조회 (ka10004)
    try:
        headers = { 'Content-Type': 'application/json;charset=UTF-8', 'authorization': f'Bearer {token}', 'api-id': 'ka10004' }
        res = requests.post(host_url + '/api/dostk/mrkcond', headers=headers, json={'stk_cd': stk_cd}, timeout=5)
        res_json = res.json()
        data = res_json.get('data', res_json)
        
        # [v3.1.0] 호가 필드 매핑 숫자형 필드 전격 추가 (1237: 매도총량, 1238: 매수총량 추정)
        keys_ask = [
            '1237', 'tot_sel_req', 'ttlr_asqn', 'total_askp_rsqn', 'asqn_ttlr', 'total_ask_qty', 'ask_qty', 'total_askp_sqn', 
            'asqn_ttlr_10', 'total_askp_rsqn_10', 'sel_rem_ttlr', 'sel_rem_qty', 'ask_rem_ttlr'
        ]
        found_ask = False
        for k in keys_ask:
            v = data.get(k)
            if v is not None and str(v).strip() != "":
                try:
                    val_str = "".join(filter(str.isdigit, str(v)))
                    if val_str:
                        result['total_ask_qty'] = int(val_str)
                        found_ask = True
                        break
                except: pass
        
        found_bid = False
        keys_bid = [
            '1238', 'tot_buy_req', 'ttlr_bsqn', 'total_bidp_rsqn', 'bsqn_ttlr', 'total_bid_qty', 'bid_qty', 'total_bidp_sqn', 
            'bsqn_ttlr_10', 'total_bidp_rsqn_10', 'bid_rem_ttlr', 'bid_rem_qty', 'bid_rem_ttlr'
        ]
        for k in keys_bid:
            v = data.get(k)
            if v is not None and str(v).strip() != "":
                try:
                    val_str = "".join(filter(str.isdigit, str(v)))
                    if val_str:
                        result['total_bid_qty'] = int(val_str)
                        found_bid = True
                        break
                except: pass
                
        # [v3.1.0] 상세 분석을 위한 전수 필드 로깅 (15개씩 끊어서 가독성 확보)
        all_items = []
        if isinstance(data, dict):
            for k, v in data.items():
                all_items.append(f"{k}:{v}")
        
        # [v1.3.0] 상세 로그용 원시 데이터 보관 (호가잔량비 추가)
        ob_ratio_str = "N/A"
        if found_ask and found_bid and result['total_bid_qty'] > 0:
            ob_ratio_str = f"{result['total_ask_qty'] / result['total_bid_qty']:.2f}"
            
        result['raw_log'] += f"[ka10004] (A:{result['total_ask_qty']:,}/B:{result['total_bid_qty']:,}/R:{ob_ratio_str}) ALL_KEYS: {', '.join(all_items[:15])}... "
        result['orderbook_valid'] = found_ask and found_bid
    except Exception as e: 
        result['raw_log'] += f"[ka10004-Error] {e} "
        result['orderbook_valid'] = False

    # 3. [신규 v4.7.5] 정밀 체결강도 추이 조회 (ka10046)
    try:
        headers = { 'Content-Type': 'application/json;charset=UTF-8', 'authorization': f'Bearer {token}', 'api-id': 'ka10046' }
        res = requests.post(host_url + '/api/dostk/mrkcond', headers=headers, json={'stk_cd': stk_cd}, timeout=5)
        res_json = res.json()
        
        # [v1.2.4 Fix] 응답 구조 유연성 확보 (dict/list 케이스 통합 대응)
        data_obj = res_json.get('data', res_json)
        data_list = []
        if isinstance(data_obj, list):
            data_list = data_obj
        elif isinstance(data_obj, dict):
            # [v1.2.7] cntr_str_tm 필수 추가 (사용자 제공 힌트 반영)
            data_list = data_obj.get('cntr_str_tm') or data_obj.get('pwr_st_list') or data_obj.get('output') or data_obj.get('data_list') or []
        
        if data_list and len(data_list) > 0:
            latest = data_list[0]
            
            # [v3.1.0] 사용자가 제보한 1238 필드를 최우선 검색 (어제까지 잘 되었다는 필드)
            # 숫자형 필드와 기존 필드 명칭 혼합 매핑
            pwr_candidates = [
                '1238', 'cntr_str_20min', 'cntr_str', 'pwr_st', 'pwr_sg', 'pwr_st', 
                'cntr_str_5min', 'vol_power', 'dstr_rt'
            ]
            
            found_pwr = None
            for pk in pwr_candidates:
                val = latest.get(pk)
                if val is not None and str(val).strip() != "":
                    try:
                        f_val = float(str(val).replace(',', ''))
                        if f_val > 0:
                            found_pwr = f_val
                            break
                    except: pass
            
            # [v3.1.0] 전수 필드 로깅 추가 (latest 아이템 기준)
            all_p_items = [f"{pk}:{pv}" for pk, pv in latest.items()]
            result['raw_log'] += f"[ka10046] ALL_KEYS: {', '.join(all_p_items[:15])}... "
            
            if found_pwr is not None:
                result['power'] = found_pwr
    except Exception as e:
        result['raw_log'] += f"[ka10046-Error] {e} "

    return result

def get_morning_scan_data(token=None):
    """
    [신규 v1.1.5] 전장/장전 등락률 및 예상체결 상위 종목 스캔 (ka10019)
    키움 opt10019(전차등락률상위) 대응
    """
    endpoint = '/api/dostk/stkinfo'
    url = host_url + endpoint
    headers = {
        'Content-Type': 'application/json;charset=UTF-8',
        'authorization': f'Bearer {token}',
        'api-id': 'ka10019'
    }
    
    # [V5.0.8] 최신 API 필수 파라미터 규격 적용 (mrkt_tp, vol_tp, flu_tp, tm_tp, tm, trde_qty_tp, stk_cnd, crd_cnd, pric_cnd, updown_incls, stex_tp)
    params = {
        'mrkt_tp': '000',       # 시장구분 (000:전체, 001:코스피, 101:코스닥)
        'vol_tp': '1',         # 거래량구분 (1:예상체결거래량)
        'flu_tp': '1',         # 등락구분 (1:상승)
        'tm_tp': '1',          # 시간구분 (1:장전)
        'tm': '085000',        # 시간 (08:50:00)
        'trde_qty_tp': '1',    # 거래량구분 (1:전체)
        'stk_cnd': '1',        # 종목조건 (1:전체)
        'crd_cnd': '0',        # 신용조건 (0:전체)
        'pric_cnd': '0',       # 가격조건 (0:전체)
        'updown_incls': '0',   # 상하한포함 (0:포함)
        'stex_tp': '3'         # 거래소구분 (3:통합)
    }

    try:
        response = requests.post(url, headers=headers, json=params, timeout=10)
        res_json = response.json()
        
        data = res_json.get('data', {})
        if isinstance(data, list):
            items = data
        else:
            items = data.get('pwr_st_list') or data.get('data_list') or data.get('output', [])
            
        if not items:
            # [v1.2.1] 스캔 실패 시 상세 원인 파악을 위한 로그 강화
            print(f"⚠️ [MorningScan] 데이터가 비어있습니다. 응답: {res_json}")
            return []
            
        scan_results = []
        for item in items:
            code = item.get('stk_cd') or item.get('code')
            if not code: continue
            
            scan_results.append({
                'code': code.replace('A', ''),
                'name': item.get('stk_nm') or item.get('name', ''),
                'expect_prc': abs(int(str(item.get('expect_prc', item.get('clpr', 0))).replace(',', ''))),
                'expect_rt': float(str(item.get('expect_rt', item.get('cur_rt', 0))).replace(',', '')),
                'expect_vol': int(str(item.get('expect_vol', 0)).replace(',', ''))
            })
            
        return scan_results
    except Exception as e:
        print(f"❌ [MorningScan] API 호출 중 예외 발생: {e}")
        return []

def get_realtime_ranking_data(token=None, qry_tp='5'):
    """
    [v2.4.0 Fix] 실시간 종목 조회 순위 데이터 (ka00198)
    - 엔드포인트: /api/dostk/stkinfo (API 명세 이미지 기준으로 수정! ✅)
    - qry_tp: 1:1분, 2:10분, 3:1시간, 4:당일누적, 5:30초
    """
    # [v2.4.0 Fix] 엔드포인트 오류 수정: mrkcond -> stkinfo (API 명세 가이드 기준 ✅)
    endpoint = '/api/dostk/stkinfo'
    url = host_url + endpoint
    headers = {
        'Content-Type': 'application/json;charset=UTF-8',
        'authorization': f'Bearer {token}',
        'api-id': 'ka00198'
    }
    
    # [v2.4.0 Fix] 파라미터 정규화: API 명세 Body에는 qry_tp 단독 (❤️)
    params = {
        'qry_tp': str(qry_tp)
    }

    try:
        response = requests.post(url, headers=headers, json=params, timeout=10)
        
        # [v3.3.1] HTTP 상태 코드 먼저 확인
        if response.status_code != 200:
            # print(f"⚠️ [RankingData] HTTP 오류: {response.status_code}")
            return []

        # [v3.3.1] JSON 파싱 예외 처리 강화
        try:
            res_json = response.json()
        except Exception:
            # print(f"⚠️ [RankingData] JSON 파싱 실패 (응답이 비어있거나 올바르지 않음)")
            return []
        
        # [ka00198] 응답 구조: "item_inq_rank" 리스트 사용
        data = res_json.get('data', res_json)
        items = data.get('item_inq_rank') or []

        if not items:
            print(f"⚠️ [RankingData] 데이터 없음. 응답 키 목록: {list(data.keys()) if isinstance(data, dict) else type(data)}")
            return []
            
        def _safe_int(v):
            """부호(+/-) 및 쉼표가 포함된 문자열을 안전하게 정수로 변환"""
            try: return abs(int(str(v).replace(',', '').replace('+', '').replace(' ', '')))
            except: return 0

        def _safe_float(v):
            """부호(+/-) 및 쉼표가 포함된 문자열을 안전하게 실수로 변환"""
            try: return float(str(v).replace(',', '').replace(' ', ''))
            except: return 0.0

        ranking_results = []
        for item in items:
            code = item.get('stk_cd') or item.get('code')
            if not code: continue
            
            # 순위 데이터 파싱 (ka00198 필드명 기준, 부호 처리 강화)
            rank = _safe_int(item.get('bigd_rank', 0))
            rank_chg_str = str(item.get('rank_chg', '0')).strip()
            rank_st = item.get('rank_chg_sign', '')   # N:신규, 1:상승, 2:하락, 3:보합
            rank_gap = _safe_int(rank_chg_str)

            if not rank: continue  # 순위가 0이면 의미 없는 데이터이므로 스킵
            
            ranking_results.append({
                'code': code.replace('A', ''),
                'name': item.get('stk_nm') or item.get('name', ''),
                'rank': rank,
                'rank_st': rank_st,
                'rank_gap': rank_gap,
                'current_price': _safe_int(item.get('past_curr_prc', 0)),
                'change_rate': _safe_float(item.get('base_comp_chgr', 0))
            })
            
        return ranking_results
    except Exception as e:
        print(f"⚠️ [RankingData] API 호출 실패: {e}")
        return []

def get_top_trading_value(token=None, market_gb='0'):
    """
    [v4.0.1 Fix] 거래대금 상위 종목 데이터 조회 (ka10032 명세 적용)
    - market_gb: 0:전체(코스피+코스닥), 1:코스피, 2:코스닥
    """
    from config import host_url
    import requests
    # [v4.0.3 Fix] 엔드포인트 오기 정정: mrkcond -> rkinfo (사용자 제보 ✅)
    endpoint = '/api/dostk/rkinfo'
    url = host_url + endpoint
    headers = {
        'Content-Type': 'application/json;charset=UTF-8',
        'authorization': f'Bearer {token}',
        'api-id': 'ka10032' # [v4.0.1] ka00184 -> ka10032 변경
    }
    
    # [v4.0.1] ka10032 전용 바디 파라미터 (이미지 명세 기반)
    # mrkt_tp: 시장구분 (000:전체, 001:코스피, 101:코스닥)
    m_tp = '000'
    if market_gb == '1': m_tp = '001'
    elif market_gb == '2': m_tp = '101'

    params = {
        'mrkt_tp': m_tp,           # 시장구분
        'mang_stk_incls': '1',     # 관리종목포함 (0:미포함, 1:포함)
        'stex_tp': '3'             # 거래소구분 (1:KRX, 2:NXT, 3:통합)
    }

    try:
        response = requests.post(url, headers=headers, json=params, timeout=10)
        if response.status_code != 200: return [], {"return_msg": f"HTTP {response.status_code}"}
        
        try:
            res_json = response.json()
        except: return [], {"return_msg": "JSON Parsing Error"}
        
        # [v4.0.3 Fix] rkinfo 응답 구조: trde_prica_upper (LIST)
        data = res_json.get('data', res_json)
        items = data.get('trde_prica_upper') or []
        
        if not items: return [], res_json
            
        results = []
        for item in items:
            # [v4.2.4] 종목 코드 정규화: 비숫자 문자(_AL 등)를 제거하고 순수 숫자 6자리만 추출하여 매칭 오류 방지
            import re
            code = item.get('stk_cd') or item.get('code')
            if not code: continue
            clean_code = re.sub(r'[^0-9]', '', str(code))[:6]
            if clean_code:
                results.append(clean_code)
            if len(results) >= 150: break
            
        return results, res_json
    except Exception as e:
        # print(f"⚠️ [TopTradingValue] API 호출 실패: {e}")
        return [], {"return_msg": str(e)}

# [신규] 코스피/코스닥 지수 정보 조회 (업종현재가)
def get_market_index_data(token=None):
    """
    [V4.4.6 Gemini Real-time Hybrid Edition] 통합 지수 정보 조회 (Primary: Naver Polling, Secondary: ka10011)
    - 5초 주기 실시간 업데이트를 위해 네이버 파이낸스 폴링 API 사용으로 교체
    """
    try:
        import requests
        
        result = {}
        # 1. Naver Finance Polling API 우선 시도 (실시간)
        try:
            for symbol, key in [('KOSPI', 'kospi'), ('KOSDAQ', 'kosdaq')]:
                url = f"https://polling.finance.naver.com/api/realtime/domestic/index/{symbol}"
                # 5초 주기이므로 가볍고 짧은 타임아웃
                res = requests.get(url, timeout=3)
                data_list = res.json().get('datas', [])
                if data_list:
                    data = data_list[0]
                    curr_price_str = str(data.get('closePrice', '0')).replace(',', '')
                    rate_str = str(data.get('fluctuationsRatio', '0')).replace('%', '')
                    
                    curr_price = float(curr_price_str)
                    rate = float(rate_str)
                    
                    result[key] = f"{curr_price:,.2f}"
                    result[f"{key}_rate"] = round(rate, 2)
            
            if 'kospi' in result and 'kosdaq' in result:
                # print("✅ [IndexData] Naver Polling 하이브리드 수집 성공")
                return result
        except Exception as naver_e:
            pass # Naver 실패 시 증권사 API 폴백
            
        # 2. 증권사 API (ka10011) 폴백 시도
        headers = { 'Content-Type': 'application/json;charset=UTF-8', 'authorization': f'Bearer {token}', 'api-id': 'ka10011' }
        indices = {'001': 'KOSPI', '101': 'KOSDAQ'}
        
        from config import host_url
        import requests
        
        for code, name in indices.items():
            res = requests.post(host_url + '/api/dostk/stkinfo', headers=headers, json={'stk_cd': code}, timeout=5)
            data = res.json().get('data', res.json())
            
            rate = 0.0
            for k in ['bstp_nmix_prdy_ctrt', 'prdy_ctrt', 'fltt_rt', 'n_diff_rate', 'chg_rate']:
                val = data.get(k)
                if val is not None:
                    try:
                        rate = float(str(val).replace(',', '').replace('+', ''))
                        break
                    except: pass
            
            price = 0.0
            for k in ['bstp_nmix_prpr', 'stck_prpr', 'now_prc', 'clpr', 'price', 'cur_prc']:
                val = data.get(k)
                if val:
                    try:
                        price = float(str(val).replace(',', '').replace('+', ''))
                        break
                    except: pass
            
            key = name.lower()
            result[key] = f"{price:,.2f}"
            result[f"{key}_rate"] = rate
                
        return result
    except Exception as e:
        # print(f"⚠️ [IndexData] 최종 수집 실패: {e}")
        return None
        return None

# 실행 구간
if __name__ == '__main__':
    token = get_token()
    print(fn_ka10001('005930', token=token))
    print(get_current_price('005930', token=token))
    # [v1.1.5] 스캔 테스트 추가
    print("🌅 장전 스캔 테스트:", get_morning_scan_data(token=token))
    # [신규] 거래대금 랭킹 테스트
    codes, _ = get_top_trading_value(token=token)
    print("💎 거래대금 상위 10종목:", codes[:10])
    # [신규] 지수 테스트
    print("📈 지수 정보:", get_market_index_data(token=token))