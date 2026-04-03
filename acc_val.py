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
		# [v3.0.4] API 에러 여부 체크 (문자열 변환 후 비교)
		ret_code = str(data.get('return_code', '0')).strip()
		if ret_code not in ['0', '0000', '00000']:
			msg = data.get('return_msg', '알 수 없는 에러')
			
			# [v5.0.2] 8005 에러(토큰 무효) 발생 시 구조화된 에러 반환
			if ret_code == '8005':
				print(f"🚨 [acc_val] 토큰 무효 에러(8005) 감지!")
				return {'error_code': '8005', 'msg': msg}

			# [v3.0.5] 성공 메시지는 실패로 보지 않음
			if "조회가 완료되었습니다" in msg or "성공" in msg:
				pass 
			elif not next_key: 
				print(f"⚠️ [acc_val] API 조회 실패 ({ret_code}): {msg}")
				return None
		
		stk_acnt_evlt_prst = data.get('stk_acnt_evlt_prst', [])
		acnt_no = data.get('acnt_no', '')
		
		return {
			'stocks': stk_acnt_evlt_prst,
			'acnt_no': acnt_no
		}
			
	except Exception as e:
		print(f"⚠️ [acc_val] Exception: {e}")
		return None

	if print_df:
		df = pd.DataFrame(stk_acnt_evlt_prst)[['stk_cd', 'stk_nm', 'pl_rt', 'rmnd_qty']]
		pd.set_option('display.unicode.east_asian_width', True)
		print(df.to_string(index=False))

	return stk_acnt_evlt_prst

# 실행 구간
if __name__ == '__main__':
	fn_kt00004(True, token=get_token())