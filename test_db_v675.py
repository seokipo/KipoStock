import sys
import os

# 현재 디렉토리를 경로에 추가
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from kipodb import kipo_db
import sqlite3

def test_db():
    print("🔍 [테스트] SQLite DB 조회 기능 테스트 시작...")
    
    # 1. 데이터 삽입 테스트 (임시)
    sample_trade = {
        'time': '16:00:00',
        'type': 'BUY',
        'code': 'TEST01',
        'name': '테스트종목',
        'qty': 10,
        'price': 15000,
        'amount': 150000,
        'strat_mode': 'qty',
        'seq': 'M'
    }
    kipo_db.insert_trade(sample_trade)
    print("✅ 테스트 데이터 삽입 완료")
    
    # 2. 전체 조회 테스트
    trades = kipo_db.get_all_trades(limit=5)
    print(f"✅ 전체 내역 조회 결과: {len(trades)}건 발견")
    for t in trades:
        print(f"   [{t['id']}] {t['trade_date']} {t['trade_time']} | {t['type']} | {t['name']} ({t['code']}) | {t['price']:,}원")
    
    # 3. 날짜별 조회 테스트
    import datetime
    today = datetime.datetime.now().strftime("%Y%m%d")
    today_trades = kipo_db.get_trades_by_date(today)
    print(f"✅ 오늘({today}) 내역 조회 결과: {len(today_trades)}건 발견")

if __name__ == "__main__":
    test_db()
