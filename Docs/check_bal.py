import requests
import json
from config import host_url
from login import fn_au10001 as get_token

# 예수금상세현황요청
# [수정] quiet 파라미터 추가 (기본값 False)
def fn_kt00001(cont_yn='N', next_key='', token=None, quiet=False):
    # 1. 요청할 API URL
    endpoint = '/api/dostk/acnt'
    url =  host_url + endpoint

    # 2. header 데이터
    headers = {
        'Content-Type': 'application/json;charset=UTF-8', 
        'authorization': f'Bearer {token}', 
        'cont-yn': cont_yn, 
        'next-key': next_key, 
        'api-id': 'kt00001', 
    }

    # 3. 요청 데이터
    params = {
        'qry_tp': '3', 
    }

    try:
        # 4. http POST 요청
        response = requests.post(url, headers=headers, json=params)
        
        # [수정] quiet가 False일 때만 상세 로그 출력
        if not quiet:
            print('Code:', response.status_code)
            # print('Body:', json.dumps(response.json(), indent=4, ensure_ascii=False)) 

        if response.status_code != 200:
            if not quiet: print(f"❌ 예수금 조회 실패: {response.status_code}")
            return None

        entry = response.json()['entr']
        
        # [수정] quiet가 False일 때만 출력
        if not quiet:
            entry_formatted = f"{int(entry):,}원"
            print('예수금: ', entry_formatted)
            
        return entry
        
    except Exception as e:
        if not quiet: print(f"⚠️ 예수금 조회 에러: {e}")
        return None

# 실행 구간
if __name__ == '__main__':
    fn_kt00001(token=get_token())