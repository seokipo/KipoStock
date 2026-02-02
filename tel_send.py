import requests
import json
from get_setting import get_setting
from config import telegram_token, telegram_chat_id

def tel_send(message, parse_mode=None):
    """텔레그램 메시지 전송 (HTML 지원 및 4000자 자동 분할)"""
    if not message: return
    
    url = f"https://api.telegram.org/bot{telegram_token}/sendMessage"
    
    # 4000자 단위로 분할하여 전송
    msg_len = len(message)
    start = 0
    chunk_size = 4000
    
    results = []
    while start < msg_len:
        end = start + chunk_size
        chunk = message[start:end]
        
        # HTML 모드일 때 태그가 잘리지 않도록 배려 (간단히 처리)
        if parse_mode == 'HTML' and chunk.count('<') != chunk.count('>'):
             # 마지막 '<' 위치를 찾아 그 전까지만 자름
             last_open = chunk.rfind('<')
             if last_open > chunk.rfind('>'):
                 end = start + last_open
                 chunk = message[start:end]
        
        data = {
            "chat_id": telegram_chat_id,
            "text": f"[{get_setting('process_name', '')}] {chunk}"
        }
        if parse_mode:
            data["parse_mode"] = parse_mode
            
        try:
            response = requests.post(url, json=data, timeout=10)
            results.append(response.json())
        except Exception as e:
            print(f"⚠️ Telegram 전송 실패 chunk({start}-{end}): {e}")
            
        start = end
        
    return results

if __name__ == "__main__":
	tel_send("키움 API 테스트")