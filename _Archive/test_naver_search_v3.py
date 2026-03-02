import requests
from bs4 import BeautifulSoup
import urllib.parse
query = "삼성전자 주식"
url = f"https://search.naver.com/search.naver?where=news&query={urllib.parse.quote(query)}"
headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
res = requests.get(url, headers=headers)
soup = BeautifulSoup(res.text, 'html.parser')
# find all a tags that have 'title' or 'href' matching news
items = soup.find_all('a', class_='news_tit')
for item in items[:5]:
    print(item.text)
