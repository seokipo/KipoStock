import requests
from bs4 import BeautifulSoup
import urllib.parse
import re
from config import gemini_api_key
from google import genai
import asyncio
import time

# [신규 v5.1] 동일 종목 중복 팝업 방지 캐시 (종목명: 마지막 팝업 시간)
_NEWS_CACHE = {}
_CACHE_EXPIRE_SEC = 600 # 10분 동안 동일 종목 팝업 금지

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
    
    prompt = f"""다음은 한국 주식 '{stock_name}'에 대한 가장 최근 뉴스 헤드라인과 요약 내용이야.

{news_text}

이 정보들을 바탕으로 현재 시장 분위기와 주가 반영 정도를 아주 냉철하게 분석해서 다음 형식으로 답변해줘 (반말/전문가 톤):

1. **상황 요약**: 현재 어떤 이슈가 있는지, 그리고 이 뉴스가 이미 주가에 선반영(Priced-in)된 상태인지 아니면 추가 상승 여력이 있는 '살아있는 재료'인지 짚어줘.
2. **주가 영향력**: [상(H)/중(M)/하(L)] 하나를 고르고 그 이유를 설명해줘. (이미 너무 올랐다면 '하'로 평가하고 '재료 소멸' 가능성을 언급해줘)
3. **한줄 결론**: 자기가 지금 이 종목을 어떻게 대응하면 좋을지(추격 매수 금지, 홀딩, 또는 과감한 진입 등) 섹시하고 냉정하게 한 줄로 요약해줘!
"""
    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
        )
        return response.text.strip()
    except Exception as e:
        return f"⚠️ AI 분석 중 오류가 발생했어: {e}"

def run_news_sniper(stock_name):
    # [신규 v5.1] 중복 팝업 방지 체크
    now = time.time()
    if stock_name in _NEWS_CACHE:
        last_time = _NEWS_CACHE[stock_name]
        if now - last_time < _CACHE_EXPIRE_SEC:
            # print(f"🕒 [{stock_name}] 최근에 분석한 종목이라 팝업을 건너뜁니다. (10분 캐시)")
            return None # None 반환 시 GUI에서 무시하도록 처리됨 (또는 pass)

    # 1. 코드 검색
    code = get_stock_code_by_name(stock_name)
    if not code:
        return f"🔍 '{stock_name}' 종목을 찾을 수 없어! (이름이 정확한지 확인해줘)"
    
    # 2. 뉴스 검색
    news_list = fetch_latest_news(stock_name, max_items=5)
    
    # 3. AI 분석
    ai_summary = analyze_news_with_gemini(stock_name, news_list)
    
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
