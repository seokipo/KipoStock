import requests
import json
from get_setting import get_setting
from config import telegram_token, telegram_chat_id

def tel_send(message):
	url = f"https://api.telegram.org/bot{telegram_token}/sendMessage"

	data = {
		"chat_id": telegram_chat_id,
		"text": f"[{get_setting('process_name', '')}] {message}" 
	}

	try:
		response = requests.post(url, json=data)
		# print(response.json())
		return response.json()
	except Exception as e:
		print(f"Telegram 메시지 전송 중 오류 발생: {e}")

if __name__ == "__main__":
	tel_send("키움 API 테스트")