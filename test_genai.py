import os
from google import genai
from config import gemini_api_key

print("🔥 [Test] API Key 로드 완료 (Length:", len(gemini_api_key), ")")
client = genai.Client(api_key=gemini_api_key)

print("🔥 [Test] 모델에 프롬프트 전송 중... (gemini-2.5-flash)")
try:
    response = client.models.generate_content(
        model='gemini-2.0-flash',
        contents='자기야 안녕? 아주 짧게 인사 한 마디 해줘!'
    )
    print("🤖 [AI]:", response.text)
except Exception as e:
    print("❌ 에러 발생:", e)
