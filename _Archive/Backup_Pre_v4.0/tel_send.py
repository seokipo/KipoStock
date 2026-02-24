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
    
    # [신규] 세련된 디자인의 헤더 구성
    proc_name = get_setting('process_name', 'KipoStock')
    header_icon = "🤖" # 기본 로봇
    if msg_type == 'log':
        header_icon = "🔔" # 알림/로그는 종 아이콘
    elif msg_type == 'report':
        header_icon = "📊" # 리포트는 차트 아이콘
        
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
        
        # [신규] 텔레그램이 지원하지 않는 <font> 태그 제거
        if parse_mode == 'HTML':
            # <font color="..."> 및 </font> 제거
            chunk = re.sub(r'<font[^>]*>', '', chunk)
            chunk = chunk.replace('</font>', '')

        # HTML 모드일 때 태그가 잘리지 않도록 배려 (간단히 처리)
        if parse_mode == 'HTML' and chunk.count('<') != chunk.count('>'):
             # 마지막 '<' 위치를 찾아 그 전까지만 자름
             last_open = chunk.rfind('<')
             if last_open > chunk.rfind('>'):
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

if __name__ == "__main__":
	tel_send("키움 API 테스트")