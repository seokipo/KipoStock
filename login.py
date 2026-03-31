import requests
import json
from config import app_key, app_secret, host_url

import os
import time

# 접근토큰 발급 (캐싱 지원)
def fn_au10001(force=False):
	"""
	접근토큰을 발급받습니다. 
	유효한 토큰이 파일에 있으면 재사용하고, 없거나 force=True이면 새로 발급받습니다.
	"""
	from get_setting import get_base_path
	token_file = os.path.join(get_base_path(), 'access_token.json')
	
	if not force and os.path.exists(token_file):
		try:
			with open(token_file, 'r', encoding='utf-8') as f:
				cached = json.load(f)
				# 24시간 중 여유있게 23시간(82800초) 이내면 재사용
				if time.time() - cached.get('time', 0) < 82800:
					return cached.get('token')
		except:
			pass

	# 1. 요청할 API URL
	endpoint = '/oauth2/token'
	url =  host_url + endpoint

	# 2. header 데이터
	headers = {
		'Content-Type': 'application/json;charset=UTF-8', # 컨텐츠타입
	}

	# 3. 요청 데이터
	data = {
		'grant_type': 'client_credentials',  # grant_type
		'appkey': app_key,  # 앱키
		'secretkey': app_secret,  # 시크릿키
	}

	# 4. http POST 요청
	try:
		response = requests.post(url, headers=headers, json=data)
		res_json = response.json()
		
		token = res_json.get('token')
		if token:
			# 성공 시 토큰과 발급시간 저장
			try:
				with open(token_file, 'w', encoding='utf-8') as f:
					json.dump({'token': token, 'time': time.time()}, f)
			except: pass
			return token
		else:
			# 발급 실패 시 상세 에러 출력
			print(f"❌ [login] 토큰 발급 실패: {res_json.get('error_description', '알 수 없는 에러')}")
			return None
	except Exception as e:
		print(f"❌ [login] 네트워크 오류: {e}")
		return None


# 실행 구간
if __name__ == '__main__':
	token = fn_au10001()
	print("토큰: ",token)