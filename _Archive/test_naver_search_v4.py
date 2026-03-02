import urllib.request
import urllib.parse
from bs4 import BeautifulSoup

query = "삼성전자 주식"
encoded_query = urllib.parse.quote(query)
req = urllib.request.Request(f'https://search.naver.com/search.naver?where=news&query={encoded_query}', headers={'User-Agent': 'Mozilla/5.0'})
html = urllib.request.urlopen(req).read().decode('utf-8')
soup = BeautifulSoup(html, 'html.parser')

items = soup.select('.news_contents a.news_tit')
for item in items[:5]:
    print(item.text)
