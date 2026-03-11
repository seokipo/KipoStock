import os
import google.generativeai as genlib
from config import gemini_api_key

genlib.configure(api_key=gemini_api_key)

print("🔍 사용 가능한 모델 목록:")
for m in genlib.list_models():
    if 'generateContent' in m.supported_generation_methods:
        print(f" - {m.name}")
