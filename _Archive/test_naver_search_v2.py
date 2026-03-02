import requests
from bs4 import BeautifulSoup
import urllib.parse
import re

def test_search(name):
    query = f"{name} 주식"
    url = f"https://search.naver.com/search.naver?query={urllib.parse.quote(query)}"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.0.0 Safari/537.36'
    }
    
    res = requests.get(url, headers=headers)
    
    # 1. code=005930 형식 찾기
    codes = re.findall(r'code=(\d{6})', res.text)
    if codes:
        print(f"✅ 발견된 종목 코드들: {codes}")
        print(f"가장 유력한 코드: {codes[0]}")
    else:
        print("❌ 코드 검색 실패")

test_search("삼성전자")
test_search("카카오")
test_search("SK하이닉스")
