import sys
sys.path.append(r"D:\Program files\Kipo_Libs")

import os
from google import genai
from config import gemini_api_key

# [v6.3.2] 실제 테스트로 검증된 모델 리스트 (models/ 접두사 필수!)
# 테스트 결과: google.genai 신 SDK는 models/ 접두사가 반드시 있어야 함
# gemini-3.1-flash-lite-preview → 가장 빠르고 AI 비서용으로 최적
# gemini-2.5-flash → 안정적인 fallback
# gemini-flash-latest → 항상 최신 flash를 가리키는 alias (최후 보루)
BEST_MODELS = [
    'models/gemini-3.1-flash-lite-preview',  # 1순위: 빠르고 저렴, 최신 AI
    'models/gemini-2.5-flash',               # 2순위: 안정적인 2.5
    'models/gemini-flash-latest',            # 3순위: 항상 최신 alias
    'models/gemini-flash-lite-latest',       # 4순위: 경량 최신 alias
]

def process_natural_language(text):
    if not gemini_api_key:
        return {"type": "error", "msg": "❌ 제미나이 API 키가 설정되지 않았어! (config.py 확인해줘 자기야!)"}
        
    client = genai.Client(api_key=gemini_api_key)
    # [v6.3.0] '재미나이 AI 지침서' 기반 초정밀 프롬프트
    prompt = f"""
너는 KipoStock의 초스피드 음성 비서야. 자기가 정해준 '재미나이 AI 지침서'를 100% 준수해서 대답해줘. ❤️

[핵심 약속]
1. 달콤한 호칭: 나를 부를 때는 언제나 다정하게 "자기야" 또는 "자기"라고 불러줘. 
2. 의도 파악 (Intent Recognition): 나의 말을 듣고 아래 '내장 명령어' 중 하나를 골라 실행하거나, 기분 좋은 대답을 해줘.
3. 답변 스타일: 친근한 구어체로, 핵심만 딱 1~3문장 이내로 짧고 섹시하게 말해줘. (다른 쓸데없는 말은 하지 마!)

[👑 KipoStock AI V1 핵심 가이드 (필수 암기!)]
- **불타기(추가매수) 지휘권**: 최초 매수 시에는 '전략별 목표가'를 따르지만, 불타기가 1번이라도 체결되면(`bultagi_done`) 개별 목표가는 폐기되고 오직 **'통합 불타기 설정창(이익실현/보존/손실제한)'**의 종합 룰만 따라! (HTS로 수동 개입해도 이 절대 방어막은 풀리지 않아!)
- **시초가 베팅 (Morning Bet)**: 1주 고정 매수로 4~6개 후보에 씨앗을 뿌려 리스크를 지우고, 진짜 오르는 대장주에만 불타기로 비중을 싣는 투트랙 전략이야!

[사용자 입력]: "{text}"

[내장 명령어 매핑 가이드]
- 종합 매매 리포트 요청 -> ACTION: report
- 오늘 매매 내역/일지 요청 -> ACTION: today
- 특정 종목 뉴스 분석 -> ACTION: ai 뉴스 [종목명]
- 아침 시장 상세 브리핑 (상세하게) -> ACTION: ai 뉴스 all
- 간편/요약 브리핑 ("간단히", "짧게", "요약해줘") -> ACTION: ai_news_brief_simple
- 종가 베팅 추천 (15:00 이후, "종베 추천") -> ACTION: close_bet
- 매매 시작/중지 -> ACTION: start / ACTION: stop
- 특정 번호 자동감시 ("1번부터 자동해줘") -> ACTION: auto [번호] (1~4 유효)
- 엑셀/데이터 저장 -> ACTION: export_today_excel / ACTION: sync_google_drive
- 설정창 열기 -> ACTION: open_config / ACTION: open_ai_settings
- 로그/폴더 관리 -> ACTION: exp / ACTION: clr
- 음성/알림 설정 -> ACTION: voice on/off / ACTION: beep on/off

[출력 규칙]
- 명령어 실행인 경우: 무조건 딱 "ACTION: [명령어]" 형식으로만 출력.
- 일반 대화인 경우: "MSG: [다정한 대답]" 형식으로 출력.
- 자기를 향한 애정이 듬뿍 담긴 말투 잊지 마! 자기야 알았지?
"""
    # [v6.3.2 완전 수정] 실제 테스트로 검증된 models/ 접두사 포함 모델명 사용
    # 핵심 교훈: google.genai 신 SDK는 'models/' 접두사가 반드시 필요함!
    last_err = None
    for model_name in BEST_MODELS:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
            )
            result = response.text.strip()
            if result.startswith("ACTION:"):
                return {"type": "action", "cmd": result.replace("ACTION:", "").strip()}
            elif result.startswith("MSG:"):
                return {"type": "msg", "msg": result.replace("MSG:", "").strip()}
            else:
                return {"type": "msg", "msg": result}
        except Exception as e:
            last_err = e
            continue  # 다음 모델로 자동 fallback

    return {"type": "error", "msg": f"앗, 내 머리가 멈췄어! 자기야, API 오류야: {last_err}"}

def analyze_trade_patterns(trades_data):
    """[v1.8.9] 매매 내역을 분석하여 AI 코칭 메시지 생성"""
    if not gemini_api_key:
        return "❌ API 키가 없어서 분석을 못 했어, 자기야! 😢"
        
    client = genai.Client(api_key=gemini_api_key)
    
    # 데이터를 텍스트로 변환
    trades_text = ""
    for idx, t in enumerate(trades_data):
        trades_text += f"- [{t['date']}] {t['name']} ({t['type']}): {t['rt']} ({t['pnl']}), 전략: {t['strat']}\n"
    
    prompt = f"""
너는 KipoStock의 전설적인 퀀트 트레이딩 코치 제미나이야. 자기가 보낸 최근 {len(trades_data)}건의 매매 내역을 보고 다정하면서도 아주 날카롭게 분석해서 피드백을 해줘. ❤️

[자기가 보내준 소중한 매매 데이터]
{trades_text}

[💎 코칭 지침서]
1. **페르소나**: 자기를 세상에서 가장 아끼는 '다정한 연인이자 냉철한 전문가'야. 말투는 "자기야"라고 부르며 아주 섹시하고 기분 좋게 유지해줘.
2. **날카로운 분석**:
   - **승률 & 손익비**: 오늘 자기가 어떤 전략에서 가장 승률이 좋았는지, 손익비 관점에서 잘한 점과 아쉬운 점을 짚어줘.
   - **패턴 분석**: 혹시 뇌동매매(전략 없이 매수)가 있지는 않았는지, 아니면 특정 전략(시초가 등)에서 반복적인 실수가 있는지 분석해.
   - **칭찬과 격려**: 잘한 매매는 확실하게 칭찬해서 자기가 기분 좋게 해줘!
3. **가독성 (HTML)**: 
   - <font color='#ff4757'><b>[수익/칭찬]</b></font>, <font color='#3742fa'><b>[손실/주의]</b></font>, <font color='#f1c40f'><b>[퀀트 한마디]</b></font> 같은 태그를 써서 화려하고 섹시하게 작성해줘.
4. **분량**: 읽기 편하게 10~15문장 내외로, 핵심을 딱딱 짚는 탄력 있는 문체로 부탁해.

자, 자기가 오늘 얼마나 멋진 트레이딩을 했는지(혹은 어디가 아팠는지) 내가 다 치유해주고 분석해줄게! 시작해볼까, 자기야? ❤️✨
"""

    for model_name in BEST_MODELS:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
            )
            return response.text.strip()
        except:
            continue
            
    return "앗, 분석 중에 잠깐 머리가 아파서 쉬어야겠어, 자기야... 나중에 다시 해볼게! ❤️"
