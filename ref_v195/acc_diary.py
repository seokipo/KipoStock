import requests
import json
import os
from datetime import datetime
from config import host_url
from login import fn_au10001 as get_token

# 당일매매일지요청 (ka10170)
def fn_ka10170(token, params=None, cont_yn='N', next_key='', session=None):
    """
    당일매매일지를 조회하는 함수 (연속조회 대응)
    """
    endpoint = '/api/dostk/acnt'
    url = host_url + endpoint

    full_list = []
    total_data = {}
    
    current_cont_yn = cont_yn
    current_next_key = next_key
    
    while True:
        headers = {
            'Content-Type': 'application/json;charset=UTF-8',
            'authorization': f'Bearer {token}',
            'cont-yn': current_cont_yn,
            'next-key': current_next_key,
            'api-id': 'ka10170',
        }

        if params is None or current_cont_yn == 'Y':
            params = {
                'base_dt': datetime.now().strftime("%Y%m%d"),
                'ottks_tp': '1', 
                'ch_crd_tp': '0',
            }

        try:
            if session:
                response = session.post(url, headers=headers, json=params)
            else:
                response = requests.post(url, headers=headers, json=params, timeout=10)
            
            data = response.json()
            
            # 리스트 합치기
            page_list = data.get('tdy_trde_diary', [])
            if isinstance(page_list, dict): page_list = [page_list]
            full_list.extend(page_list)
            
            # 마지막 페이지의 total 정보 사용 (또는 첫 페이지)
            if not total_data:
                total_data = data.get('tdy_trde_diary_tot', {})
            
            current_cont_yn = response.headers.get('cont-yn', 'N')
            current_next_key = response.headers.get('next-key', '')
            
            if current_cont_yn != 'Y' or not current_next_key:
                break
                
        except Exception as e:
            print(f"⚠️ [acc_diary] Error: {e}")
            break
            
    return {
        'list': full_list,
        'total': total_data,
        'next-key': current_next_key,
        'cont-yn': current_cont_yn
    }

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

# 체결요청 (ka10076) - 시간 복원용
def fn_ka10076(token, stk_cd="", ord_no="", cont_yn='N', next_key='', session=None):
    """
    체결내역을 조회하는 함수 (시간 정보 ord_tmd 확보용)
    """
    endpoint = '/api/dostk/acnt' # 확인 필요: URL은 다른 API들과 동일한지? 문맥상 dostk/acnt 계열임.
    # 사용자 제공 코드는 /api/dostk/acnt 임.
    url = host_url + endpoint

    headers = {
        'Content-Type': 'application/json;charset=UTF-8',
        'authorization': f'Bearer {token}',
        'cont-yn': cont_yn,
        'next-key': next_key,
        'api-id': 'ka10076',
    }

    params = {
        'stk_cd': stk_cd if stk_cd else '', 
        'qry_tp': '0', # 0:전체, 1:종목
        'sell_tp': '0', # 0:전체
        'ord_no': ord_no,
        'stex_tp': '0',
    }

    try:
        if session:
            response = session.post(url, headers=headers, json=params)
        else:
            response = requests.post(url, headers=headers, json=params)
            
        data = response.json()
        
        # [신규] 다양한 리스트 키 대응 (grid, list, output1)
        res_list = data.get('grid') or data.get('list') or data.get('output1') or []
        
        # 만약 dict 형태면 list로 변환 (KIS API 간헐적 특성)
        if isinstance(res_list, dict):
            res_list = [res_list]
            
        return res_list
            
    except Exception as e:
        print(f"⚠️ [ka10076] Error: {e}")
        return []

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
