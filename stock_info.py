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
        
        # [v1.2.7] 상세 로그용 원시 데이터 보관
        result['raw_log'] += f"[ka10001] {str(data)[:200]}... "
    except: pass

    # 2. 호가 잔량 정보 조회 (ka10004)
    try:
        headers = { 'Content-Type': 'application/json;charset=UTF-8', 'authorization': f'Bearer {token}', 'api-id': 'ka10004' }
        res = requests.post(host_url + '/api/dostk/mrkcond', headers=headers, json={'stk_cd': stk_cd}, timeout=5)
        data = res.json().get('data', res.json())
        
        # 총매도잔량/총매수잔량 (다양한 API 응답 키 대응 보완)
        keys_ask = ['total_askp_rsqn', 'asqn_ttlr', 'total_ask_qty', 'ask_qty', 'total_askp_sqn']
        keys_bid = ['total_bidp_rsqn', 'bsqn_ttlr', 'total_bid_qty', 'bid_qty', 'total_bidp_sqn']
        
        found_ask = False
        for k in keys_ask:
            v = data.get(k)
            if v is not None:
                result['total_ask_qty'] = int(str(v).replace(',', ''))
                found_ask = True
                break
        
        found_bid = False
        for k in keys_bid:
            v = data.get(k)
            if v is not None:
                result['total_bid_qty'] = int(str(v).replace(',', ''))
                found_bid = True
                break
                
        # [v1.3.0] 상세 로그용 원시 데이터 보관 (호가잔량비 추가)
        ob_ratio_str = "N/A"
        if found_ask and found_bid and result['total_bid_qty'] > 0:
            ob_ratio_str = f"{result['total_ask_qty'] / result['total_bid_qty']:.2f}"
            
        result['raw_log'] += f"[ka10004] (Ask:{result['total_ask_qty']:,}/Bid:{result['total_bid_qty']:,}/Ratio:{ob_ratio_str}) {str(data)[:150]}... "
        result['orderbook_valid'] = found_ask and found_bid
    except: 
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
            # [v1.2.7] HTS와 일치하는 'cntr_str_20min'을 1순위로 채택
            pwr_val = latest.get('cntr_str_20min')
            if pwr_val is None: pwr_val = latest.get('cntr_str')
            if pwr_val is None: pwr_val = latest.get('pwr_sg')
            if pwr_val is None: pwr_val = latest.get('pwr_st')
            if pwr_val is None: pwr_val = latest.get('cntr_str_5min')
            if pwr_val is None: pwr_val = latest.get('vol_power')
            
            # [v1.2.7] 상세 로그용 원시 데이터 보관
            result['raw_log'] += f"[ka10046] {str(latest)[:200]}..."
            
            if pwr_val is not None:
                try:
                    pwr_f = float(str(pwr_val).replace(',', ''))
                    if pwr_f > 0 or result['power'] == 0.0:
                        result['power'] = pwr_f
                except: pass
    except: pass

    return result

def get_morning_scan_data(token=None):
    """
    [신규 v1.1.5] 전장/장전 등락률 및 예상체결 상위 종목 스캔 (ka10019)
    키움 opt10019(전차등락률상위) 대응
    """
    endpoint = '/api/dostk/mrkcond'
    url = host_url + endpoint
    headers = {
        'Content-Type': 'application/json;charset=UTF-8',
        'authorization': f'Bearer {token}',
        'api-id': 'ka10019'
    }
    
    # 0: 전체, 1: 코스피, 2: 코스닥
    params = {
        'market_gb': '0',   # 시장구분
        'vol_gb': '1',      # 거래량구분 (1:예상체결량)
        'rt_gb': '1'        # 등락구분 (1:상승)
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
        print(f"⚠️ [MorningScan] API 호출 실패: {e}")
        return []

# 실행 구간
if __name__ == '__main__':
    token = get_token()
    print(fn_ka10001('005930', token=token))
    print(get_current_price('005930', token=token))
    # [v1.1.5] 스캔 테스트 추가
    print("🌅 장전 스캔 테스트:", get_morning_scan_data(token=token))