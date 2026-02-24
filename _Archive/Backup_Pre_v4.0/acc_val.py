import requests
import pandas as pd
from config import host_url
from login import fn_au10001 as get_token

# 계좌평가현황요청
def fn_kt00004(print_df=False, cont_yn='N', next_key='', token=None):
	# 1. 요청할 API URL
	endpoint = '/api/dostk/acnt'
	url =  host_url + endpoint

	# 2. header 데이터
	headers = {
		'Content-Type': 'application/json;charset=UTF-8', # 컨텐츠타입
		'authorization': f'Bearer {token}', # 접근토큰
		'cont-yn': cont_yn, # 연속조회여부
		'next-key': next_key, # 연속조회키
		'api-id': 'kt00004', # TR명
	}

	# 3. 요청 데이터
	params = {
		'qry_tp': '0', # 상장폐지조회구분 0:전체, 1:상장폐지종목제외
		'dmst_stex_tp': 'KRX', # 국내거래소구분 KRX:한국거래소,NXT:넥스트트레이드
	}

	# 4. http POST 요청
	response = requests.post(url, headers=headers, json=params)
	
	try:
		data = response.json()
		stk_acnt_evlt_prst = data.get('stk_acnt_evlt_prst', [])
		acnt_no = data.get('acnt_no', '')
		
		# [신규] 반환 형식을 딕셔너리로 확장 (계좌번호 포함)
		return {
			'stocks': stk_acnt_evlt_prst,
			'acnt_no': acnt_no
		}
			
	except Exception as e:
		print(f"⚠️ [acc_val] Error: {e}")
		return {'stocks': [], 'acnt_no': ''}

	if print_df:
		df = pd.DataFrame(stk_acnt_evlt_prst)[['stk_cd', 'stk_nm', 'pl_rt', 'rmnd_qty']]
		pd.set_option('display.unicode.east_asian_width', True)
		print(df.to_string(index=False))

	return stk_acnt_evlt_prst

# 실행 구간
if __name__ == '__main__':
	fn_kt00004(True, token=get_token())