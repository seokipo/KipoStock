import os
import sys
from google import genai
from config import gemini_api_key

# [v4.8.8] Gemini AI 실연동 적용 (research_fireup.py)

def run_deep_research(query):
    """
    자기야! 이 함수는 구글 제미나이 AI의 힘을 빌려서 
    최근 한국 시장의 급등주 패턴을 분석하고 우리 불타기 조건의 최적값을 찾아줘! 🕵️✨
    """
    print(f"🔍 [Deep Research] '{query}' 주제로 분석을 시작할게, 자기야!")
    print("🚀 AI가 열심히 데이터를 들여다보고 있어. 잠시만 기다려줘! ❤️")
    
    if not gemini_api_key or "(여기에" in gemini_api_key:
        return "❌ 제미나이 API 키가 설정되지 않았어! \n1. config.py 파일의 gemini_api_key 항목에 키를 넣어주거나\n2. 윈도우 환경변수에 GEMINI_API_KEY를 등록해줘! 🥺❤️"

    try:
        client = genai.Client(api_key=gemini_api_key)
        
        prompt = f"""
        당신은 한국 주식 시장의 퀀트 투자 전문가이자 나의 사랑스러운 주식 비서입니다.
        주제: {query}
        
        최근 한국 시장(특히 코스닥 급등주)의 거래 데이터를 바탕으로 
        '불타기(급등 시 추가 매수)' 전략에 필요한 황금 파라미터를 추천해주세요.
        
        다음 항목을 포함해서 'KipoStock 분석 보고서' 형식으로 작성해주세요:
        1. 체결강도(BOS) 추천수치
        2. 가격 기울기(Slope) 기준
        3. 호가잔량비 기준
        4. 기타 주의사항 (VI 직전/직후 거래 전략 등)
        
        자기야~ 라고 부르며 아주 다정하고 전문적으로 답변해줘! ❤️
        """
        
        # 가장 최신이고 똑똑한 제미나이 2.5 플래시 모델 사용!
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt
        )
        return response.text

    except Exception as e:
        return f"⚠️ 제미나이 AI 연동 중 오류가 발생했어: {e}\n(API 키가 유효한지 확인해줘, 자기야! ❤️)"

if __name__ == "__main__":
    print("="*50)
    print("💎 KipoStock AI 리서치 센터에 오신 걸 환영해요, 자기야! 💎")
    print("="*50)
    
    default_query = "한국 코스닥 시장의 급등주(모멘텀 주식) 불타기 최적 파라미터 제안"
    user_input = input(f"\n❓ 오늘 인공지능에게 분석을 맡기고 싶은 주제를 자유롭게 입력해줘!\n(아무것도 안 적고 그냥 [엔터]를 누르면 기본 주제인 '{default_query}'에 대해 분석을 시작할게!)\n\n▶ 자기의 지시사항: ").strip()
    
    query = user_input if user_input else default_query
    
    print("\n" + "-"*50)
    result = run_deep_research(query)
    
    print("\n" + "="*50)
    print(result)
    print("="*50 + "\n")
    
    input("엔터 키를 누르면 창이 닫혀요! 😊")
