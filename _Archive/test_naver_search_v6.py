import requests

code = '005930'
# 모바일 네이버 금융 뉴스 API 시도
url = f"https://m.stock.naver.com/api/news/stock/{code}?pageSize=5&page=1"
headers = {'User-Agent': 'Mozilla/5.0'}
try:
    res = requests.get(url, headers=headers)
    data = res.json()
    for item in data[:5]:
        print(item.get('title'))
except Exception as e:
    print("API 요청 실패:", e)
