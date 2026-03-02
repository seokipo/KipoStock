import requests
import json
from config import host_url
from login import fn_au10001 as get_token

# 주식호가요청
def fn_ka10004(stk_cd, cont_yn='N', next_key='', token=None):
    # 1. 요청할 API URL
    endpoint = '/api/dostk/mrkcond'
    url =  host_url + endpoint

    # 2. header 데이터
    headers = {
        'Content-Type': 'application/json;charset=UTF-8', 
        'authorization': f'Bearer {token}', 
        'cont-yn': cont_yn, 
        'next-key': next_key, 
        'api-id': 'ka10004', 
    }

    # 3. 요청 데이터
    params = {
        'stk_cd': stk_cd, 
    }

    try:
        # 4. http POST 요청
        response = requests.post(url, headers=headers, json=params)
        
        if response.status_code != 200:
            return 0

        data = response.json()
        sel_fpr_bid_raw = data.get('sel_fpr_bid')

        if sel_fpr_bid_raw is None:
            return 0

        sel_fpr_bid = abs(float(sel_fpr_bid_raw))
        # print('매도최우선호가: ', sel_fpr_bid) # 로그 너무 많으면 주석
        return int(sel_fpr_bid)

    except Exception as e:
        # print(f"호가 조회 에러: {e}")
        return 0

# 실행 구간
if __name__ == '__main__':
    print(fn_ka10004('005930', token=get_token()))