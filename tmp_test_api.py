from google import genai
from config import gemini_api_key
import sys

def test():
    try:
        client = genai.Client(api_key=gemini_api_key)
        # 1.0 SDK 에서는 'gemini-1.5-flash' 이렇게 바로 썼던 것 같은데 2.0 SDK(google-genai)도 확인
        print("🚀 테스팅 시도...")
        response = client.models.generate_content(
            model='gemini-2.0-flash',
            contents='안녕? 짧게 인사해줘.'
        )
        print("✅ 성공! 대답:", response.text)
    except Exception as e:
        print("❌ 실패:", e)

if __name__ == "__main__":
    test()
