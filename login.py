import requests
import json
from config import app_key, app_secret, host_url

import os
import time
import threading

# [v5.0.2] 스레드 안전성 및 메모리 캐싱 강화
_token_lock = threading.Lock()
_cached_token = None
_cached_time = 0

# 접근토큰 발급 (캐싱 지원)
def fn_au10001(force=False):
	"""
	접근토큰을 발급받습니다. 
	유효한 토큰이 파일/메모리에 있으면 재사용하고, 없거나 force=True이면 새로 발급받습니다.
	"""
	global _cached_token, _cached_time
	
	from get_setting import get_base_path
	token_file = os.path.join(get_base_path(), 'access_token.json')
	
	with _token_lock:
		# 1. 메모리 캐시 확인 (최우선)
		if not force and _cached_token and (time.time() - _cached_time < 82800):
			return _cached_token
			
		# 2. 파일 캐시 확인 (메모리에 없거나 force인 경우)
		if not force and os.path.exists(token_file):
			try:
				with open(token_file, 'r', encoding='utf-8') as f:
					cached = json.load(f)
					# 24시간 중 여유있게 23시간(82800초) 이내면 재사용
					if time.time() - cached.get('time', 0) < 82800:
						_cached_token = cached.get('token')
						_cached_time = cached.get('time', 0)
						return _cached_token
			except:
				pass

		# 3. 신규 발급 요청 (force=True 이거나 캐시 만료/부재 시)
		endpoint = '/oauth2/token'
		url =  host_url + endpoint

		headers = {
			'Content-Type': 'application/json;charset=UTF-8',
		}

		data = {
			'grant_type': 'client_credentials',
			'appkey': app_key,
			'secretkey': app_secret,
		}

		try:
			response = requests.post(url, headers=headers, json=data)
			res_json = response.json()
			
			# 한국투자증권 API 응답 필드: access_token
			token = res_json.get('access_token') or res_json.get('token')
			if token:
				_cached_token = token
				_cached_time = time.time()
				# 파일 저장
				try:
					with open(token_file, 'w', encoding='utf-8') as f:
						json.dump({'token': token, 'time': _cached_time}, f)
				except: pass
				return token
			else:
				print(f"❌ [login] 토큰 발급 실패: {res_json.get('error_description', '알 수 없는 에러')}")
				return None
		except Exception as e:
			print(f"❌ [login] 네트워크 오류: {e}")
			return None

# 실행 구간
if __name__ == '__main__':
	token = fn_au10001()
	print("토큰: ",token)