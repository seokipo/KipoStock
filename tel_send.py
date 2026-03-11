import requests
import json
import re
from get_setting import get_setting
from config import telegram_token, telegram_chat_id

def tel_send(message, parse_mode=None, msg_type='general'):
    """
    텔레그램 메시지 전송 (HTML 지원, 4000자 자동 분할, 필터링 및 디자인 적용)
    :param message: 전송할 메시지
    :param parse_mode: 텔레그램 파싱 모드 ('HTML' 등)
    :param msg_type: 메시지 유형 ('log', 'report', 'general')
    """
    if not message: return
    
    # [신규] 설정에 따른 필터링
    tel_on = get_setting('tel_on', True)
    if not tel_on: return # 전체 전송 꺼짐
    
    if msg_type == 'log':
        tel_log_on = get_setting('tel_log_on', True)
        if not tel_log_on: return # 로그 전송 꺼짐
        
    url = f"https://api.telegram.org/bot{telegram_token}/sendMessage"
    
    # [신규] 세련된 디자인의 헤더 구성 (사용자 요청: 일반 메시지는 간소화, 리포트만 헤더 유지)
    proc_name = get_setting('process_name', 'KipoStock')
    header_icon = "🤖" # 기본 로봇
    
    header = "" # 기본적으로 헤더 없음
    if msg_type == 'report' or msg_type == 'system':
        if msg_type == 'report':
            header_icon = "📊"
        elif msg_type == 'system':
            header_icon = "🔔"
            
        if parse_mode == 'HTML':
            header = f"💎 <b>【 {proc_name} 】</b>\n━━━━━━━━━━━━━━\n{header_icon} <b>Trading Update</b>\n━━━━━━━━━━━━━━\n"
        else:
            header = f"💎 【 {proc_name} 】\n━━━━━━━━━━━━━━\n{header_icon} Trading Update\n━━━━━━━━━━━━━━\n"
    
    # 4000자 단위로 분할하여 전송
    msg_len = len(message)
    start = 0
    chunk_size = 4000
    
    results = []
    while start < msg_len:
        end = start + chunk_size
        chunk = message[start:end]
        
        # [신규] 텔레그램이 지원하지 않는 특수 HTML 태그 제거
        if parse_mode == 'HTML':
            # <font color="..."> 및 </font> 제거
            chunk = re.sub(r'<font[^>]*>', '', chunk)
            chunk = chunk.replace('</font>', '')
            # <br> 태그를 줄바꿈으로 변경
            chunk = re.sub(r'<br\s*/?>', '\n', chunk, flags=re.IGNORECASE)
            # <img> 태그 제거 (텔레그램 HTML 미지원)
            chunk = re.sub(r'<img[^>]*>', '', chunk, flags=re.IGNORECASE)
        if parse_mode == 'HTML' and chunk.count('<') != chunk.count('>'):
             # 마지막 '<' 위치를 찾아 그 전까지만 자름
             last_open = chunk.rfind('<')
             if last_open > chunk.rfind('>') and last_open > 0:
                 end = start + last_open
                 chunk = message[start:end]
        
        data = {
            "chat_id": telegram_chat_id,
            "text": f"{header}{chunk}"
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

def tel_send_photo(photo_path, caption=None):
    """
    텔레그램으로 이미지 파일 전송 (로컬 이미지 지원)
    :param photo_path: 전송할 이미지 파일의 로컬 경로
    :param caption: (선택) 하단에 붙일 캡션 텍스트
    """
    tel_on = get_setting('tel_on', True)
    if not tel_on: return None

    url = f"https://api.telegram.org/bot{telegram_token}/sendPhoto"
    
    try:
        with open(photo_path, 'rb') as photo:
            files = {'photo': photo}
            data = {'chat_id': telegram_chat_id}
            if caption:
                data['caption'] = caption
            response = requests.post(url, files=files, data=data, timeout=30)
            return response.json()
    except Exception as e:
        print(f"⚠️ Telegram 사진 전송 실패: {e}")
        return None

if __name__ == "__main__":
	tel_send("키움 API 테스트")