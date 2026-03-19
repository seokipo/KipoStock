import requests
from bs4 import BeautifulSoup
import urllib.parse
import re
from config import gemini_api_key
from google import genai
import asyncio
import time

# [신규 v5.3.0] 동일 종목 중복 팝업 방지 캐시 (종목명: 마지막 팝업 시간)
_NEWS_CACHE = {}
_CACHE_EXPIRE_SEC = 600 # 10분 동안 동일 종목 팝업 금지

def fetch_market_news(max_items=5):
    """네이버 증권 주요 뉴스(Main News)를 가져오는 기능"""
    news_items = []
    try:
        url = "https://finance.naver.com/news/mainnews.naver"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        res = requests.get(url, headers=headers)
        res.encoding = 'euc-kr' # 네이버 금융은 euc-kr 사용
        soup = BeautifulSoup(res.text, 'html.parser')
        
        # 주요 뉴스 목록 추출 (ul.block_sub li 또는 dl.newsList dt.articleSubject)
        articles = soup.select('.mainNewsList .articleSubject a')
        if not articles:
            # 다른 패턴 (뉴스 홈인 경우)
            articles = soup.select('.newsList .articleSubject a')
            
        for idx, a in enumerate(articles):
            if idx >= max_items: break
            title = a.get_text(strip=True)
            link = "https://finance.naver.com" + a['href']
            news_items.append({'title': title, 'lead': '(기사 본문 생략)', 'link': link})
            
    except Exception as e:
        print(f"시장 뉴스 크롤링 실패: {e}")
    return news_items

def get_stock_code_by_name(stock_name):
    query = f"{stock_name} 주식"
    url = f"https://search.naver.com/search.naver?query={urllib.parse.quote(query)}"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }
    try:
        res = requests.get(url, headers=headers)
        codes = re.findall(r'code=(\d{6})', res.text)
        if codes:
            return codes[0]
    except Exception as e:
        print(f"종목 코드 검색 실패: {e}")
    return None

def fetch_latest_news(stock_name, max_items=3):
    news_items = []
    try:
        # 1. 종목명으로 먼저 코드를 알아냄
        code = get_stock_code_by_name(stock_name)
        if not code:
            print(f"[{stock_name}] 코드 검색 실패로 뉴스를 가져올 수 없습니다.")
            return news_items
            
        # 2. 모바일 네이버 증권 뉴스 API 호출
        url = f"https://m.stock.naver.com/api/news/stock/{code}?pageSize={max_items}&page=1&category=news"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        res = requests.get(url, headers=headers)
        data = res.json()
        
        # 3. JSON 데이터 파싱
        if isinstance(data, list) and len(data) > 0:
            items = data[0].get('items', [])
        else:
            items = data.get('items', [])
            
        for idx, item in enumerate(items):
            if idx >= max_items: break
            title = item.get('title') or item.get('tit')
            lead = item.get('lead') or item.get('subContent') or ""
            
            if title:
                # 불필요한 HTML 태그 등 제거
                title = title.replace('&quot;', '"').replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
                lead = lead.replace('&quot;', '"').replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
                news_items.append({'title': title, 'lead': lead})
                
    except Exception as e:
        print(f"뉴스 크롤링 실패: {e}")
        
    return news_items

def analyze_news_with_gemini(stock_name, news_list):
    if not news_list:
        return f"🤷‍♂️ {stock_name}에 대한 최근 주요 뉴스를 찾지 못했습니다."
    
    # 2.5-flash 모델로 요약
    if not gemini_api_key:
        return "⚠️ Gemini API 키가 설정되지 않았습니다."
    
    client = genai.Client(api_key=gemini_api_key)
    # 제목과 요약문을 결합하여 AI에게 전달
    news_text = "\n".join([f"제목: {n['title']}\n요약: {n['lead']}\n" for n in news_list])
    
    prompt = f"""[시스템 지침]
당신은 KipoStock의 초단타(스캘핑) 전문 AI 트레이더야. '재미나이 AI 지침서'에 따라 극도로 냉철하게 평가해.
우리 시스템은 이미 이 종목에 '1주(정찰병)'를 자동 매수한 상태야. 
너의 임무는 이 종목에 자금을 더 쏟아부어 **강력한 불타기(비중 확대)를 감행할지 아니면 여기서 멈출지** 결정하는 거야. 
장기 투자가 아닌, 당장 1~5분 내의 폭발력에 집중해. (반말/냉철한 전문가 톤)

[분석 요청]
종목명: '{stock_name}'
뉴스 데이터:
{news_text}

[특별 가산점 키워드] 유가, 가스, 에너지, Project Beat 관련 내용은 가산점을 주어 분석할 것.

[필수 요구사항]
1. **상황 및 재료 분석**: 뉴스 핵심과 시세 반영도를 짧고 날카롭게 요약해. (반말 사용)
2. **불타기 파괴력 점수 (1~10점)**: 이미 너무 올랐거나 재료 소멸이면 가차 없이 0~3점을 날려. (예: "불타기 점수: 8점")
3. **가이드 결론 (한 줄 요약)**: 문장 가장 앞에 [과감한 불타기 요망], [흐름 관망], [추가 매수 절대 금지] 중 하나를 무조건 쓸 것.
4. **섹시한 한 줄 전략**: 분석 끝에는 자기가 지금 당장 어떻게 대응해야 할지 섹시하게 한 줄로 딱 짚어줘!

🚫 'ㅇㅇ 관련주' 같은 모호한 말은 절대 금지! 반드시 구체적인 종목명만 언급할 것.
"""
    # [v6.3.2] 실제 테스트 검증: models/ 접두사 필수! gemini-3.1-flash-lite 이상이엄
    SNIPER_MODELS = ['models/gemini-3.1-flash-lite-preview', 'models/gemini-2.5-flash', 'models/gemini-flash-latest']
    try:
        for model_name in SNIPER_MODELS:
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                )
                return response.text.strip()
            except Exception:
                continue
        return "⚠️ AI 분석에 사용 가능한 모델이 없어, 자기야!"
    except Exception as e:
        return f"⚠️ AI 분석 중 오류가 발생했어: {e}"

def analyze_market_news_with_gemini(news_list):
    """시장 전체 뉴스를 분석하여 브리핑 생성"""
    if not news_list:
        return "🤷‍♂️ 현재 시장의 주요 뉴스를 가져오지 못했어."
    
    if not gemini_api_key:
        return "⚠️ Gemini API 키가 설정되지 않았습니다."
    
    client = genai.Client(api_key=gemini_api_key)
    news_text = "\n".join([f"- {n['title']}" for n in news_list])
    
    prompt = f"""[시스템 지침]
당신은 KipoStock의 아침 시장을 여는 냉철한 전략 분석가야. '재미나이 AI 지침서'를 준수해 브리핑해. (반말/냉철한 전문가 톤)

[뉴스 데이터]
{news_text}

[특별 가산점 키워드] 유가, 가스, 에너지, Project Beat 관련 내용은 깊이 분석할 것.

[필수 요구사항]
1. **시장 날씨**: 현재 시장 분위기를 한 줄로 요약해.
2. **핵심 재료**: 오늘 시장을 사로잡은 가장 강력한 테마가 뭔지 짚어줘.
3. **오늘의 추천 종목 (2~3개)**: ⚠️ **삼성전자, SK하이닉스 같은 "실제 종목명"을 반드시 2~3개 추천할 것.** 'ㅇㅇ 섹터' 같은 말 뒤에 숨지 마. 추천 이유도 아주 강렬하게 덧붙여.
4. **투자 전략**: 자기가 오늘 매매를 어떻게 공략해야 할지 섹시하게 한 줄로 조언해줘!
"""
    # [v6.3.2] 실제 테스트 검증: models/ 접두사 필수!
    SNIPER_MODELS = ['models/gemini-3.1-flash-lite-preview', 'models/gemini-2.5-flash', 'models/gemini-flash-latest']
    try:
        for model_name in SNIPER_MODELS:
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                )
                return response.text.strip()
            except Exception:
                continue
        return "⚠️ AI 시장 분석에 사용 가능한 모델이 없어!"
    except Exception as e:
        return f"⚠️ AI 시장 분석 중 오류가 발생했어: {e}"

def analyze_market_news_brief_simple(news_list):
    """[v5.7.32] 시장 뉴스를 종목 중심으로 아주 간결하게 브리핑합니다."""
    if not news_list:
        return "ℹ️ 분석할 뉴스가 없어, 자기야!"
        
    if not gemini_api_key:
        return "⚠️ Gemini API 키가 설정되지 않았습니다."

    client = genai.Client(api_key=gemini_api_key)
    news_text = "\n".join([f"- {n['title']}" for n in news_list])
    
    prompt = f"""다음은 시장 주요 뉴스들이야. 바쁜 나를 위해 핵심만 간결하게 브리핑해줘. (반말/냉철한 전문가 톤)
{news_text}

1. **상황 요약**: 시장 분위기를 딱 한 줄로 요약해.
2. **핵심 종목 (2~3개)**: ⚠️ **'ㅇㅇ 관련주' 금지!** 반드시 **'현대차', '기아' 같은 "실제 상장 종목명"**을 2~3개 골라. 추천 이유는 한 줄로 극도로 짧게 써.
3. **섹시한 한 줄 전략**: 지금 당장 취해야 할 행동을 딱 짚어줘.
"""
    # [v6.3.2] 실제 테스트 검증: models/ 접두사 필수!
    SNIPER_MODELS = ['models/gemini-3.1-flash-lite-preview', 'models/gemini-2.5-flash', 'models/gemini-flash-latest']
    try:
        for model_name in SNIPER_MODELS:
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                )
                return response.text.strip()
            except Exception:
                continue
        return "⚠️ 간단 분석에 사용 가능한 모델이 없어!"
    except Exception as e:
        return f"⚠️ 간단 분석 중 오류가 발생했어: {e}"

def analyze_closing_bet_with_gemini(news_list):
    """오늘 시장을 정리하고 종가 베팅 종목을 추천"""
    if not news_list:
        return "🤷‍♂️ 마감 전 시장 뉴스를 가져오지 못했어."
    
    if not gemini_api_key:
        return "⚠️ Gemini API 키가 설정되지 않았습니다."
    
    client = genai.Client(api_key=gemini_api_key)
    news_text = "\n".join([f"- {n['title']}" for n in news_list])
    
    prompt = f"""오늘 시장을 정리하고 내일이 기대되는 종가 베팅 종목을 뽑아줘. (반말/냉철한 전문가 톤)
{news_text}

1. **오늘 시장 복기**: 주도 섹터와 특징을 한 줄로 요약해.
2. **종가 베팅 추천 (2~3개)**: ⚠️ **반드시 "실제 종목명"만 추천할 것.** 종목명 뒤에 **[BUY:종목명]** 태그를 무조건 붙여야 해. (예: 삼성전자 [BUY:삼성전자])
3. **내일의 관점**: 내일 장초반 분위기와 주의점을 섹시하게 딱 짚어줘.
"""
    # [v6.3.2] 실제 테스트 검증: models/ 접두사 필수!
    SNIPER_MODELS = ['models/gemini-3.1-flash-lite-preview', 'models/gemini-2.5-flash', 'models/gemini-flash-latest']
    try:
        for model_name in SNIPER_MODELS:
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                )
                return response.text.strip()
            except Exception:
                continue
        return "⚠️ 종가 베팅 분석에 사용 가능한 모델이 없어!"
    except Exception as e:
        return f"⚠️ AI 종가 베팅 분석 중 오류가 발생했어: {e}"

def run_news_sniper(target_name, is_all=False, is_closing=False, is_brief_simple=False):
    """AI 뉴스 스나이퍼 실행 (종목, 전체 시장, 종가 베팅, 또는 간편 브리핑)"""
    if is_brief_simple:
        # 시장 간편 브리핑 모드 (종목 위주)
        news_list = fetch_market_news(max_items=8)
        ai_summary = analyze_market_news_brief_simple(news_list)
        
        result_msg = f"""🔍 <b>AI 시장 간편 요약 (v5.7)</b>
<code>===========================</code>
<b>💡 AI 핵심 종목 & 한 줄 요약:</b>
{ai_summary}"""
        return result_msg

    if is_closing:
        # 종가 베팅 모드
        news_list = fetch_market_news(max_items=10)
        ai_summary = analyze_closing_bet_with_gemini(news_list)
        
        result_msg = f"""🎯 <b>AI 종가 베팅 추천 (v5.5)</b>
<code>===========================</code>
<b>💡 AI 마감 분석 & 추천:</b>
{ai_summary}"""
        return result_msg

    if is_all:
        # 시장 전체 브리핑 모드
        news_list = fetch_market_news(max_items=8)
        ai_summary = analyze_market_news_with_gemini(news_list)
        
        news_html = ""
        for idx, item in enumerate(news_list[:5]):
            news_html += f"<b>• {item['title']}</b>\n"
            
        result_msg = f"""📊 <b>AI 시장 종합 브리핑 (v5.3)</b>
<code>===========================</code>
{news_html}
<hr>
<b>💡 AI 시장 인사이트:</b>
{ai_summary}"""
        return result_msg

    # 종목별 브리핑 모드 (기존 로직)
    stock_name = target_name
    now = time.time()
    if stock_name in _NEWS_CACHE:
        last_time = _NEWS_CACHE[stock_name]
        if now - last_time < _CACHE_EXPIRE_SEC:
            return f"SKIP: {stock_name} 종목은 최근 10분 이내에 분석되었습니다. 팝업을 생략합니다."

    # 1. 코드 검색
    code = get_stock_code_by_name(stock_name)
    if not code:
        return f"🔍 '{stock_name}' 종목을 찾을 수 없어! (이름이 정확한지 확인해줘)"
    
    # 2. 뉴스 검색
    news_list = fetch_latest_news(stock_name, max_items=5)
    
    # 3. AI 분석
    ai_summary = analyze_news_with_gemini(stock_name, news_list)
    
    # [신규 v6.2.2] AI 응답 HTML 컬러 시각화 처리 (불타기 점수 기반)
    if "[과감한 불타기 요망]" in ai_summary:
        ai_summary = ai_summary.replace("[과감한 불타기 요망]", "<span style='color:red; font-size:12pt; font-weight:bold;'>[과감한 불타기 요망] 🔥🚀🎯</span>")
    elif "[흐름 관망]" in ai_summary:
        ai_summary = ai_summary.replace("[흐름 관망]", "<span style='color:orange; font-size:11pt; font-weight:bold;'>[흐름 관망] 🧐👀</span>")
    elif "[추가 매수 절대 금지]" in ai_summary:
        ai_summary = ai_summary.replace("[추가 매수 절대 금지]", "<span style='color:#0055ff; font-size:11pt; font-weight:bold;'>[추가 매수 절대 금지] ❄️🛑💀</span>")
    
    # 4. 결과 조립 (HTML)
    news_html = ""
    for idx, item in enumerate(news_list[:3]):
        news_html += f"<b>({idx+1}) {item['title']}</b>\n"
        if item['lead']:
            # 요약문은 조금 작게 표시 (GUI에서 가독성 확보)
            lead_summary = item['lead'][:80] + "..." if len(item['lead']) > 80 else item['lead']
            news_html += f"<i><span style='font-size: 9pt; color: #aaaaaa;'>└ {lead_summary}</span></i>\n"
        
    result_msg = f"""📰 <b>[{stock_name}] AI 뉴스 브리핑 (v5.0)</b>
<code>===========================</code>
{news_html}
<hr>
<b>💡 AI 인텔리전트 분석:</b>
{ai_summary}"""
    
    # [신규 v5.1] 캐시 업데이트 (팝업 성공 시점 기록)
    _NEWS_CACHE[stock_name] = time.time()
    
    return result_msg

def run_market_sniper(is_simple=False):
    """AI 시장 브리핑 전용 실행 함수 (ChatCommand용)"""
    return run_news_sniper(None, is_all=(not is_simple), is_brief_simple=is_simple)

def extract_target_stocks_from_msg(msg):
    """[신규 v6.1.16] AI 답변에서 [BUY:종목명] 형태의 태그를 추출하여 리스트로 반환"""
    if not msg: return []
    try:
        # [BUY:삼성전자] 형태의 패턴 매칭
        targets = re.findall(r'\[BUY:([^\]]+)\]', msg)
        # 중복 제거 및 공백 정리
        return list(set([t.strip() for t in targets if t.strip()]))
    except:
        return []

if __name__ == "__main__":
    import re
    print("==================================================")
    print(" 🎯 KipoStock [News Sniper] AI 뉴스 브리핑 시스템 🎯")
    print("==================================================\n")
    while True:
        try:
            stock_name = input("🔍 뉴스를 검색할 종목명을 입력하세요 (종료하려면 엔터): ").strip()
            if not stock_name:
                print("👋 News Sniper를 종료합니다. 오늘도 성투하세요!")
                break
            
            print(f"\n⏳ '{stock_name}' 최신 뉴스를 수집 중입니다... (최대 10초 소요)")
            result = run_news_sniper(stock_name)
            
            # HTML 태그 제거 및 가시성 개선
            clean_result = re.sub(r'<[^<]+?>', '', result)
            clean_result = clean_result.replace('&quot;', '"').replace('&amp;', '&')
            
            print("\n" + clean_result)
            print("\n--------------------------------------------------\n")
            
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"\n⚠️ 오류 발생: {e}\n")
            break
            
    input("\n엔터 키를 누르면 창이 닫혀요! 😊")
