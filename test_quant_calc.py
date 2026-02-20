
import math
import sys
import os

# 현재 경로를 sys.path에 추가하여 trade_logger를 불러옵니다.
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from trade_logger import TradeLogger

def test_quant_logic():
    logger = TradeLogger()
    
    # 자기가 말한 예시: 10만 원짜리 종목 vs 1,000원짜리 종목
    # 1. 비싼 종목 (10만 원 * 10주 = 1,000,000원 투자) -> 1% 익절 (+10,000원)
    logger.record_buy("BIG_STOCK", "비싼종목", 10, 100000)
    logger.record_sell("BIG_STOCK", "비싼종목", 10, 101000, 1.0, 10000)
    
    # 2. 싼 종목 (1,000원 * 10주 = 10,000원 투자) -> 10% 손절 (-1,000원)
    logger.record_buy("SMALL_STOCK", "싼종목", 10, 1000)
    logger.record_sell("SMALL_STOCK", "싼종목", 10, 900, -10.0, -1000)

    report = logger.get_session_report()
    
    print("=== 금액 가중(Weighting) 테스트 결과 ===")
    print(f"1. 비싼 종목 (100만 원 투자): 1% 익절 -> +10,000원")
    print(f"2. 싼 종목 (1만 원 투자): 10% 손절 -> -1,000원")
    print("-" * 40)
    print(f"승률: {report['win_rate']:.2f}% (기대: 50.00%)")
    print(f"손익비(Payoff Ratio): {report['payoff_ratio']:.2f} (기대: 10.00)")
    print(f"프로핏 팩터(Profit Factor): {report['profit_factor']:.2f} (기대: 10.00)")
    print(f"기댓값(Expectancy): {report['expectancy']:.0f}원 (기대: 4,500원)")
    
    # 검증: 싼 종목은 -10%나 빠졌지만, 비싼 종목의 +1% 수익금이 훨씬 크기 때문에 프로핏 팩터는 10이 나와야 함.
    assert abs(report['payoff_ratio'] - 10.0) < 0.1
    assert report['profit_factor'] == 10.0
    assert abs(report['expectancy'] - 4500) < 0.1
    print("\n✅ 비싼 종목의 무게감이 프로핏 팩터와 기댓값에 정확히 반영되었습니다!")

if __name__ == "__main__":
    test_quant_logic()
