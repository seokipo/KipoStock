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

        res_json = response.json()
        entry = res_json.get('entr', '0')
        # [Fix] 예수금(인출가능)이 아닌 주문가능금액(ord_psbl_amt)이 실제 매수 재원임
        # 1.5버전 참조: ord_psbl_amt > d2_auto_ord_amt > entr 순으로 확인
        ord_amt = res_json.get('ord_psbl_amt')
        if not ord_amt or int(ord_amt) == 0:
             ord_amt = res_json.get('d2_auto_ord_amt')
        if not ord_amt or int(ord_amt) == 0:
             ord_amt = entry

        acnt_no = res_json.get('acnt_no', '')
        
        # [디버그] 계좌번호가 없으면 RAW 데이터 출력
        if not acnt_no and not quiet:
            print(f"📡 [DEBUG] 계좌번호 누락! 서버 응답: {res_json}")
            
        # [수정] quiet가 False일 때만 출력
        if not quiet:
            ord_formatted = f"{int(ord_amt):,}원"
            print(f"주문가능: {ord_formatted} (예수금: {int(entry):,})")
            
        return {"balance": ord_amt, "acnt_no": acnt_no}
        
    except Exception as e:
        if not quiet: print(f"⚠️ 예수금 조회 에러: {e}")
        return None

# 실행 구간
if __name__ == '__main__':
    fn_kt00001(token=get_token())