import requests
import json
import os
from datetime import datetime
from config import host_url
from login import fn_au10001 as get_token

# 당일매매일지요청 (ka10170)
def fn_ka10170(token, params=None, cont_yn='N', next_key='', session=None):
    """
    당일매매일지를 조회하는 함수
    :param token: 접근토큰
    :param session: (선택) requests.Session 객체
    """
    endpoint = '/api/dostk/acnt'
    url = host_url + endpoint

    headers = {
        'Content-Type': 'application/json;charset=UTF-8',
        'authorization': f'Bearer {token}',
        'cont-yn': cont_yn,
        'next-key': next_key,
        'api-id': 'ka10170',
    }

    if params is None:
        params = {
            'base_dt': datetime.now().strftime("%Y%m%d"),
            'ottks_tp': '1', 
            'ch_crd_tp': '0',
        }

    try:
        if session:
            response = session.post(url, headers=headers, json=params)
        else:
            response = requests.post(url, headers=headers, json=params)
        
        data = response.json()
        
        result = {
            'list': data.get('tdy_trde_diary', []),
            'total': data.get('tdy_trde_diary_tot', {}),
            'next-key': response.headers.get('next-key', ''),
            'cont-yn': response.headers.get('cont-yn', 'N')
        }
        return result
            
    except Exception as e:
        print(f"⚠️ [acc_diary] Error: {e}")
        return {'list': [], 'total': {}, 'next-key': '', 'cont-yn': 'N'}

# 당일실현손익상세 (ka10077)
def fn_ka10077(token, stk_cd="", cont_yn='N', next_key='', session=None):
    """
    당일실현손익상세를 조회하는 함수 (세금 정보 포함)
    :param token: 접근토큰
    :param session: (선택) requests.Session 객체
    """
    endpoint = '/api/dostk/acnt'
    url = host_url + endpoint

    headers = {
        'Content-Type': 'application/json;charset=UTF-8',
        'authorization': f'Bearer {token}',
        'cont-yn': cont_yn,
        'next-key': next_key,
        'api-id': 'ka10077',
    }

    params = {
        'stk_cd': stk_cd, 
    }

    try:
        if session:
            response = session.post(url, headers=headers, json=params)
        else:
            response = requests.post(url, headers=headers, json=params)
            
        data = response.json()
        
        result = {
            'list': data.get('tdy_rlzt_pl_dtl', []),
            'total': data.get('tdy_rlzt_pl', "0"),
            'next-key': response.headers.get('next-key', ''),
            'cont-yn': response.headers.get('cont-yn', 'N')
        }
        return result
            
    except Exception as e:
        print(f"⚠️ [acc_diary_detailed] Error: {e}")
        return {'list': [], 'total': "0", 'next-key': '', 'cont-yn': 'N'}

if __name__ == '__main__':
    print("🚀 Starting acc_diary debug test...")
    token = get_token()
    print(f"Token: {token[:10]}...")
    res = fn_ka10170(token)
    print("\n--- TOTAL SECTION ---")
    print(json.dumps(res.get('total', {}), indent=4, ensure_ascii=False))
    print("\n--- LIST SECTION (Length: {}) ---".format(len(res.get('list', []))))
    for i, item in enumerate(res.get('list', [])[:5]):
        print(f"\nItem {i}:")
        print(json.dumps(item, indent=4, ensure_ascii=False))
    print("\n--- End of test ---")
