import requests
from bs4 import BeautifulSoup
import urllib.parse
word = "삼성전자"
url = f"https://finance.naver.com/search/searchList.naver?query={urllib.parse.quote(word.encode('euc-kr'))}"
res = requests.get(url)
soup = BeautifulSoup(res.text, 'html.parser')
table = soup.find('table', {'class': 'tbl_search'})
if table:
    print("Found table")
    a = table.find('a')
    if a:
        print(a.get('href'))
else:
    print("No tbl_search")
