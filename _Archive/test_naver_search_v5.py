import urllib.request
import urllib.parse
from bs4 import BeautifulSoup
import requests
# 삼성전자 종목코드
code = '005930'
url = f"https://finance.naver.com/item/news_news.naver?code={code}&page=1"
headers = {'User-Agent': 'Mozilla/5.0'}
res = requests.get(url, headers=headers)
soup = BeautifulSoup(res.text, 'html.parser')
# finance.naver.com 기사들은 tbody 하위의 td class="title" 안에 있음
titles = soup.select('tbody td.title a')
for t in titles[:5]:
    print(t.text.strip())
