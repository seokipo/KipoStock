import requests
import json
import env
from login import fn_au10001
import os

def debug_ka10076():
    print("🚀 API 응답 구조 확인 시작...")
    
    # 1. 토큰 발급
    token = fn_au10001()
    if not token:
        print("❌ 토큰 발급 실패")
        return

    # 2. API 호출
    host_url = "https://api.kiwoom.com" # 실전
    # host_url = "https://mockapi.kiwoom.com" # 모의
    if env.MODE == '02': host_url = "https://mockapi.kiwoom.com"
        
    endpoint = '/api/dostk/acnt'
    url = host_url + endpoint

    headers = {
        'Content-Type': 'application/json;charset=UTF-8',
        'authorization': f'Bearer {token}',
        'cont-yn': 'N',
        'next-key': '',
        'api-id': 'ka10076',
    }

    params = {
        'stk_cd': '', 
        'qry_tp': '0', # 전체
        'sell_tp': '0', # 전체
        'ord_no': '',
        'stex_tp': '0',
    }

    try:
        print(f"📡 요청 보내는 중... ({url})")
        response = requests.post(url, headers=headers, json=params)
        data = response.json()
        
        print("\n✅ 응답 수신 완료!")
        print("="*50)
        print(f"Status Code: {response.status_code}")
        print("="*50)
        print("🔑 최상위 키 목록:", list(data.keys()))
        print("-" * 50)
        
        # 주요 데이터 확인
        if 'output1' in data:
            print(f"📂 'output1' 데이터 존재함! (개수: {len(data['output1'])})")
            if len(data['output1']) > 0:
                print("첫 번째 아이템 샘플:")
                print(json.dumps(data['output1'][0], indent=4, ensure_ascii=False))
        elif 'list' in data:
            print(f"📂 'list' 데이터 존재함! (개수: {len(data['list'])})")
            if len(data['list']) > 0:
                print("첫 번째 아이템 샘플:")
                print(json.dumps(data['list'][0], indent=4, ensure_ascii=False))
        elif 'output' in data:
            print("📂 'output' 데이터 존재함 (리스트인지 확인 필요):")
            print(json.dumps(data['output'], indent=4, ensure_ascii=False))
        else:
            print("⚠️ 예상된 키(output1, list)가 없습니다. 전체 데이터:")
            print(json.dumps(data, indent=4, ensure_ascii=False))
            
    except Exception as e:
        print(f"❌ 오류 발생: {e}")

if __name__ == '__main__':
    debug_ka10076()
