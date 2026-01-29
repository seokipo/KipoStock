import asyncio
import requests
import datetime
from config import telegram_token
from chat_command import ChatCommand
from get_setting import get_setting
from market_hour import MarketHour

class MainApp:
	def __init__(self):
		self.chat_command = ChatCommand()
		self.last_update_id = 0
		self.telegram_url = f"https://api.telegram.org/bot{telegram_token}/getUpdates"
		self.keep_running = True
		self.today_started = False  # 오늘 start가 실행되었는지 추적
		self.today_stopped = False  # 오늘 stop이 실행되었는지 추적
		self.last_check_date = None  # 마지막으로 확인한 날짜
		
	def get_chat_updates(self):
		"""텔레그램 채팅 업데이트를 가져옵니다."""
		try:
			params = {
				'offset': self.last_update_id + 1,
				'timeout': 10
			}
			response = requests.get(self.telegram_url, params=params)
			data = response.json()
			
			if data.get('ok'):
				updates = data.get('result', [])
				for update in updates:
					self.last_update_id = update['update_id']
					
					if 'message' in update and 'text' in update['message']:
						text = update['message']['text']
						print(f"받은 메시지: {text}")
						return text
			return None
		except Exception as e:
			print(f"채팅 업데이트 가져오기 실패: {e}")
			return None
	
	
	async def check_market_timing(self):
		"""장 시작/종료 시간을 확인하고 자동 실행합니다."""
		auto_start = get_setting('auto_start', False)
		today = datetime.datetime.now().date()
		
		# 새로운 날이 되면 플래그 리셋
		if self.last_check_date != today:
			self.today_started = False
			self.today_stopped = False
			self.last_check_date = today
		
		if MarketHour.is_market_start_time() and auto_start and not self.today_started:
			print(f"장 시작 시간({MarketHour.MARKET_START_HOUR:02d}:{MarketHour.MARKET_START_MINUTE:02d})입니다. 자동으로 start 명령을 실행합니다.")
			await self.chat_command.start()
			self.today_started = True  # 오늘 start 실행 완료 표시
		elif MarketHour.is_market_end_time() and not self.today_stopped:
			print(f"장 종료 시간({MarketHour.MARKET_END_HOUR:02d}:{MarketHour.MARKET_END_MINUTE:02d})입니다. 자동으로 stop 명령을 실행합니다.")
			await self.chat_command.stop(False)  # auto_start를 false로 설정하지 않음
			print("자동으로 계좌평가 보고서를 발송합니다.")
			await self.chat_command.report()  # 장 종료 시 report도 자동 발송
			self.today_stopped = True  # 오늘 stop 실행 완료 표시
	
	async def run(self):
		"""메인 실행 루프"""
		print("채팅 모니터링을 시작합니다...")
		
		try:
			while self.keep_running:
				# 채팅 메시지 확인
				message = self.get_chat_updates()
				if message:
					await self.chat_command.process_command(message)
				
				# 장 시작/종료 시간 확인
				await self.check_market_timing()
				
				# 대기 시간을 0.1초로 감소하여 반응 속도 향상
				await asyncio.sleep(0.1)
				
		except KeyboardInterrupt:
			print("\n프로그램을 종료합니다...")
			self.keep_running = False
			await self.chat_command.stop(False)

async def main():
	app = MainApp()
	await app.run()

if __name__ == '__main__':
	asyncio.run(main())
