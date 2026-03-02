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
			print(f"⚠️ 종목명을 찾을 수 없습니다. 응답 구조: {list(response_data.keys())}")
			return None
		
		# 종목명이 비어있거나 None인 경우
		if not stk_nm or stk_nm.strip() == '':
			print(f"⚠️ 종목명이 비어있습니다.")
			return None
		
		return stk_nm
	except KeyError as e:
		print(f"⚠️ 응답에서 종목명 필드를 찾을 수 없습니다: {e}")
		return None
	except Exception as e:
		print(f"⚠️ 종목명 조회 중 오류 발생: {e}")
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
        keys_to_try = ['now_prc', 'clpr', 'stck_prpr', 'price', 'cur_prc', 'vi_stnd_prc']
        
        for key in keys_to_try:
            val = res_data.get(key)
            if val:
                price = int(str(val).replace(',', ''))
                if price > 0:
                    break

        return name, price
    except Exception as e:
        print(f"⚠️ 가격 조회 실패: {e}")
        return None, 0

# [신규] 불타기 상세 조건을 위한 확장 데이터 조회 (체결강도, 호가잔량)
def get_extended_stock_data(stk_cd, token=None):
    """
    체결강도, 총매도잔량, 총매수잔량 등 불타기 필터링에 필요한 정밀 데이터를 반환합니다.
    """
    result = {
        'name': '',
        'price': 0,
        'power': 0.0,       # 체결강도 (%)
        'total_ask_qty': 0, # 총 매도 잔량
        'total_bid_qty': 0  # 총 매수 잔량
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
        
        # 체결강도 추출 (vol_strength, strength, 228 등)
        for k in ['vol_strength', 'strength', 'vol_power', '228']:
            v = data.get(k)
            if v:
                result['power'] = float(str(v).replace(',', ''))
                break
    except: pass

    # 2. 호가 잔량 정보 조회 (ka10004)
    try:
        headers = { 'Content-Type': 'application/json;charset=UTF-8', 'authorization': f'Bearer {token}', 'api-id': 'ka10004' }
        res = requests.post(host_url + '/api/dostk/mrkcond', headers=headers, json={'stk_cd': stk_cd}, timeout=5)
        data = res.json().get('data', res.json())
        
        # 총매도잔량/총매수잔량 (total_askp_rsqn, total_bidp_rsqn 등)
        for k_ask, k_bid in [('total_askp_rsqn', 'total_bidp_rsqn'), ('total_ask_qty', 'total_bid_qty'), ('ask_qty', 'bid_qty')]:
            v1, v2 = data.get(k_ask), data.get(k_bid)
            if v1 is not None and v2 is not None:
                result['total_ask_qty'] = int(str(v1).replace(',', ''))
                result['total_bid_qty'] = int(str(v2).replace(',', ''))
                break
    except: pass

    # 3. [신규 v4.7.5] 정밀 체결강도 추이 조회 (ka10046) - 자기가 찾아준 보물!
    try:
        headers = { 'Content-Type': 'application/json;charset=UTF-8', 'authorization': f'Bearer {token}', 'api-id': 'ka10046' }
        res = requests.post(host_url + '/api/dostk/mrkcond', headers=headers, json={'stk_cd': stk_cd}, timeout=5)
        res_json = res.json()
        data_list = res_json.get('data', {}).get('pwr_st_list', [])
        
        if data_list and len(data_list) > 0:
            latest = data_list[0] # 가장 최신(첫번째) 데이터
            pwr = latest.get('pwr_sg')
            if pwr:
                result['power'] = float(str(pwr).replace(',', ''))
                # print(f"✨ [KA10046] 정밀 체결강도 획득: {result['power']}%")
    except Exception as e:
        # print(f"⚠️ [KA10046] 조회 실패: {e}")
        pass

    return result

# 실행 구간
if __name__ == '__main__':
    token = get_token()
    print(fn_ka10001('005930', token=token))
    print(get_current_price('005930', token=token))