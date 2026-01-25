import requests
import json
from config import host_url
from login import fn_au10001 as get_token

# 주식 매수주문
def fn_kt10000(stk_cd, ord_qty, ord_uv, cont_yn='N', next_key='', token=None):
    endpoint = '/api/dostk/ordr'
    url =  host_url + endpoint

    headers = {
        'Content-Type': 'application/json;charset=UTF-8',
        'authorization': f'Bearer {token}',
        'cont-yn': cont_yn,
        'next-key': next_key,
        'api-id': 'kt10000',
    }

    params = {
        'dmst_stex_tp': 'KRX',
        'stk_cd': stk_cd,
        'ord_qty': str(ord_qty), 
        'ord_uv': str(ord_uv),   
        'trde_tp': '3',          # 3:시장가
        'cond_uv': '',
    }

    try:
    # 4. http Post요청.    
        response = requests.post(url, headers=headers, json=params)
        
        # 성공('0') 또는 실패 코드 리턴
        try:
            res_json = response.json()
            ret_code = res_json.get('return_code')
            if str(ret_code) != '0':
                 print(f"❌ 매수 API 실패 응답: {res_json.get('return_msg')}")
            return ret_code
        except:
            print("❌ 응답 파싱 실패:", response.text)
            return "-1"

    except Exception as e:
        print(f"❌ API 요청 중 에러: {e}")
        return "-1"

if __name__ == '__main__':
    # 테스트
    fn_kt10000('005930', '1', '0', token=get_token())