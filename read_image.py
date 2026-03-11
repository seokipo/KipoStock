import os, sys
import google.generativeai as genai
import PIL.Image

try:
    from config import gemini_api_key
    genai.configure(api_key=gemini_api_key)
except:
    print("API Key not found")
    sys.exit(1)

img_dir = r"C:\Users\서기철\.gemini\antigravity\brain\d7738abd-b2c2-4c23-8a04-4c5edebbce5d"
img_files = [f for f in os.listdir(img_dir) if f.startswith("media__") and f.endswith(".png")]
img_files.sort(key=lambda x: os.path.getmtime(os.path.join(img_dir, x)), reverse=True)

target_model = None
for m in genai.list_models():
    if 'generateContent' in m.supported_generation_methods and ('vision' in m.name or '1.5' in m.name):
        target_model = m.name
        break

if not target_model: target_model = 'gemini-1.5-flash'
print(f"Using model: {target_model}")
model = genai.GenerativeModel(target_model)


for f in img_files:
    img_path = os.path.join(img_dir, f)
    try:
        img = PIL.Image.open(img_path)
        prompt = "이 이미지에 '테크윙', '불타기', '로우데이터', 또는 에러코드(JSON 등)가 있는지 확인해 줘. 있다면 발견된 핵심 텍스트 내용 2~3줄만 요약해 줘. 없으면 '없음'이라고만 적어줘."
        res = model.generate_content([prompt, img])
        text = res.text.strip()
        if text and "없음" not in text:
            print(f"[{f}] -> {text}")
    except Exception as e:
        print(f"Error reading {f}: {e}")

