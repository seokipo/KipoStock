import asyncio
import os
import json
import logging
from flask import Flask
from datetime import datetime
import threading
import requests

# 기존 주식 매매 모듈 임포트
from chat_command import ChatCommand
from config import telegram_token, telegram_chat_id
from market_hour import MarketHour

# Flask 앱 설정 (Cloud Run의 Health Check용)
app = Flask(__name__)

@app.route('/')
def status_check():
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return {
        "status": "RUNNING",
        "service": "KipoStock Cloud Engine",
        "current_time": now,
        "message": "자기야! 클라우드 엔진이 건강하게 숨 쉬고 있어! ❤️🚀"
    }

class CloudEngine:
    def __init__(self):
        self.chat_command = ChatCommand()
        self.last_update_id = 0
        self.keep_running = True
        self.telegram_url = f"https://api.telegram.org/bot{telegram_token}/getUpdates"

    def get_chat_updates(self):
        """텔레그램에서 새로운 명령어를 가져옵니다."""
        try:
            params = {'offset': self.last_update_id + 1, 'timeout': 5}
            response = requests.get(self.telegram_url, params=params, timeout=10)
            if response.status_code == 200:
                data = response.json()
                for update in data.get('result', []):
                    self.last_update_id = update['update_id']
                    if 'message' in update and 'text' in update['message']:
                        chat_id = str(update['message']['chat']['id'])
                        if chat_id == telegram_chat_id:
                            return update['message']['text']
                        else:
                            logging.warning(f"⚠️ 권한 없는 사용자 접근 차단 (ID: {chat_id})")
        except Exception as e:
            logging.error(f"Telegram Polling Error: {e}")
        return None

    async def main_loop(self):
        logging.info("🚀 KipoStock 클라우드 엔진 가동 시작!")
        
        # 초기 조건식 로드
        await self.chat_command.condition(quiet=True)
        
        # 15:30 자동 종료 플래그
        today_stopped = False
        last_check_date = datetime.now().date()

        while self.keep_running:
            try:
                # 1. 텔레그램 명령어 처리
                message = self.get_chat_updates()
                if message:
                    logging.info(f"📩 명령어 수신: {message}")
                    await self.chat_command.process_command(message)

                # 2. 장 종료 시간(15:30) 자동 정산 시퀀스
                now = datetime.now()
                if now.hour == 15 and now.minute == 30 and not today_stopped:
                    today_stopped = True
                    logging.info("🔔 장 종료 시간(15:30) 자동 정산 시작")
                    await self.chat_command.stop(set_auto_start_false=False)
                    await self.chat_command.today(send_telegram=True) # 텔레그램으로 전송
                    await self.chat_command.report()

                # 날짜 변경 시 플래그 초기화
                if last_check_date != now.date():
                    last_check_date = now.date()
                    today_stopped = False

                await asyncio.sleep(2) # 체크 주기
            except Exception as e:
                logging.error(f"Main Loop Error: {e}")
                await asyncio.sleep(5)

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

if __name__ == "__main__":
    # 로깅 설정
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    logging.info("🌟 KipoStock 클라우드 부팅 프로세스 개시...")

    # 1. Flask 앱을 가장 먼저 가동 (Cloud Run Health Check 대응)
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    logging.info("✅ Flask 상태 서버 가동 완료 (Health Check 준비)")
    
    try:
        # 2. 클라우드 엔진 초기화
        logging.info("ℹ️ 엔진 초기화 중...")
        engine = CloudEngine()
        
        # 3. 비동기 메인 루프 실행
        asyncio.run(engine.main_loop())
    except Exception as e:
        logging.critical(f"🚨 엔진 가동 불가능한 치명적 에러: {e}")
        import traceback
        logging.critical(traceback.format_exc())
