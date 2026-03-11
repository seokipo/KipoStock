from google import genai
from config import gemini_api_key

def test():
    client = genai.Client(api_key=gemini_api_key)
    try:
        print("👉 gemini-2.0-flash with prefix 시도")
        response = client.models.generate_content(
            model='models/gemini-2.0-flash',
            contents='인사해줘!'
        )
        print(f"✅ 성공: {response.text}")
    except Exception as e:
        print(f"❌ 실패: {e}")

if __name__ == "__main__":
    test()
