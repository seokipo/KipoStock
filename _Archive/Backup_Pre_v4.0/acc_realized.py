import requests
import json
import pandas as pd
from config import host_url
from login import fn_au10001 as get_token

# 당일실현손익요청 (kt00006)
def fn_kt00006(token=None):
    # 1. 요청할 API URL
    endpoint = '/api/dostk/acnt'
    url = host_url + endpoint

    # 2. header 데이터
    headers = {
        'Content-Type': 'application/json;charset=UTF-8',
        'authorization': f'Bearer {token}',
        'api-id': 'kt00006', # TR명: 당일실현손익
    }

    # 3. 요청 데이터
    params = {
        'dmst_stex_tp': 'KRX', 
        'qry_tp': '0', # 0: 전체
    }

    try:
        # 4. http POST 요청
        response = requests.post(url, headers=headers, json=params)
        data = response.json()
        
        # [디버그] 응답 데이터를 파일에 기록 (내역이 안 나올 때 원인 파악용)
        with open("debug_api_res.json", "w", encoding="utf-8") as f:
            f.write(json.dumps(data, indent=4, ensure_ascii=False))
        
        # [수정] 모든 가능한 키 조합을 공격적으로 확인
        pnl_lst = []
        possible_lst_keys = ['stk_dmst_pnl_lst', 'output1', 'pnl_lst', 'res_lst', 'data_lst']
        for k in possible_lst_keys:
            if data.get(k):
                pnl_lst = data.get(k)
                break
        
        # 전체 합계 데이터
        pnl_tot = {}
        possible_tot_keys = ['stk_dmst_pnl_tot', 'output2', 'pnl_tot', 'res_tot', 'data_tot']
        for k in possible_tot_keys:
            if data.get(k):
                pnl_tot = data.get(k)
                break
        
        result = {
            'list': pnl_lst,
            'total': pnl_tot
        }
            
        return result
            
    except Exception as e:
        print(f"⚠️ [acc_realized] Error: {e}")
        return {'list': [], 'total': {}}

if __name__ == '__main__':
    res = fn_kt00006(get_token())
    print(res)
