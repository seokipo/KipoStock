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
        
        # if price == 0:
            # print(f"⚠️ [API_DEBUG] Price is 0. Keys in data: {list(res_data.keys())}")
            # print(f"⚠️ [API_DEBUG] Full Data: {res_data}")

        return name, price
    except Exception as e:
        print(f"⚠️ 가격 조회 실패: {e}")
        return None, 0

# 실행 구간
if __name__ == '__main__':
    token = get_token()
    print(fn_ka10001('005930', token=token))
    print(get_current_price('005930', token=token))