from google import genai
from config import gemini_api_key

def test():
    client = genai.Client(api_key=gemini_api_key)
    # 2.0-flash 가 안되면 1.5-flash (표준) 시도
    # 또는 'gemini-1.5-flash' 이렇게 바로 써도 되는지 확인 (그 전에는 됐으니까)
    models_to_try = [
        'gemini-1.5-flash',
        'gemini-1.5-pro',
        'gemini-2.0-flash-lite',
        'gemini-flash-latest'
    ]
    
    for m in models_to_try:
        print(f"👉 {m} 시도 중...")
        try:
            response = client.models.generate_content(
                model=m,
                contents='짧게 인사해줘!'
            )
            print(f"✅ [{m}] 성공! : {response.text}")
            break
        except Exception as e:
            print(f"❌ [{m}] 실패: {e}")

if __name__ == "__main__":
    test()
