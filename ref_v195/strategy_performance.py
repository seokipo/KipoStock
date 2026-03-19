import os
import json
import pandas as pd
from datetime import datetime
import matplotlib.pyplot as plt
import numpy as np

# [v4.8] Business Analyst Skill 적용 (strategy_performance.py)

class StrategyAnalyst:
    def __init__(self):
        self.base_path = self._get_base_path()
        self.log_dir = os.path.join(self.base_path, 'LogData')
        self.log_file = os.path.join(self.log_dir, f"trade_log_{datetime.now().strftime('%Y%m')}.json")
        
    def _get_base_path(self):
        import sys
        if getattr(sys, 'frozen', False):
            return os.path.dirname(sys.executable)
        return os.path.dirname(os.path.abspath(__file__))

    def analyze(self):
        """매매 로그 분석 및 성과 지표 산출"""
        if not os.path.exists(self.log_file):
            return "❌ 분석할 매매 로그가 아직 없네, 자기야! 좀 더 매매가 쌓이면 다시 불러줘! ❤️"

        try:
            with open(self.log_file, 'r', encoding='utf-8') as f:
                logs = json.load(f)
            
            if not logs: return "❌ 로그 파일이 비어있어! 매매가 발생한 뒤에 다시 해보자! 😊"

            df = pd.DataFrame(logs)
            
            # 성과 지표 계산
            total_trades = len(df[df['type'] == 'SELL'])
            if total_trades == 0:
                return "📉 아직 매도 완료된 종목이 없어서 수익률 분석이 힘드네! 좀 더 기다려보자! ❤️"

            # 수익금 및 수익률 추출 (profit_rate 필드 가정)
            profits = df[df['type'] == 'SELL']['profit_amt'].astype(float)
            win_rate = (len(profits[profits > 0]) / total_trades) * 100
            total_profit_amt = profits.sum()
            avg_profit_rate = df[df['type'] == 'SELL']['profit_rate'].astype(float).mean()

            # 전략별 성과
            strat_perf = df[df['type'] == 'SELL'].groupby('strat_mode').agg({
                'profit_amt': ['sum', 'count'],
                'profit_rate': 'mean'
            })

            report = f"""
## 📊 KipoStock v4.8 전략 성과 보고서 (자기야 전용! ❤️)

### 🏆 전체 요약
- **총 매도 횟수**: {total_trades}회
- **평균 승률**: {win_rate:.2f}%
- **총 수익금**: {total_profit_amt:,.0f}원
- **평균 수익률**: {avg_profit_rate:.2f}%

### 🎯 전략별 성과 (어떤 불타기가 더 맛있나? 😋)
{strat_perf.to_markdown()}

---
자기가 정한 전략들이 이렇게 열일하고 있어! 
특히 성적이 좋은 전략은 비중을 좀 더 늘려봐도 좋겠다. 사랑해! 😘🏆
"""
            return report

        except Exception as e:
            return f"⚠️ 분석 중 에러 발생: {e}"

if __name__ == "__main__":
    import sys
    # [v4.8.7] 파이썬 기반 무결점 한글 출력
    print("-" * 50)
    print("📊 우리 KipoStock의 성적표를 불러올게, 자기야! ❤️")
    print("-" * 50)
    
    try:
        analyst = StrategyAnalyst()
        result = analyst.analyze()
        print(result)
    except Exception as e:
        print(f"⚠️ 실행 중 오류 발생: {e}")
        
    print("\n" + "-" * 50)
    input("엔터 키를 누르면 창이 닫혀요! 😊")
