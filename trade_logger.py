import time
import math

class TradeLogger:
    def __init__(self):
        self.trades = []
        self.start_time = time.strftime("%Y-%m-%d %H:%M:%S")
        self.cumulative_pnl = 0
        self.pnl_history = [0] # MDD 계산용 누적 손익 히스토리
        self.returns_history = [] # 샤프 지수 계산용 개별 매매 수익률 히스토리

    def record_buy(self, code, name, qty, price, strat_mode='qty', seq=None):
        """매수 기록"""
        amount = qty * price
        self.trades.append({
            'time': time.strftime("%H:%M:%S"),
            'type': 'BUY',
            'code': code,
            'name': name,
            'qty': qty,
            'price': price,
            'amount': amount,
            'strat_mode': strat_mode,
            'seq': seq # [신규] 시퀀스(프로필) 번호 기록
        })

    def record_sell(self, code, name, qty, price, pl_rt, pnl_amt, tax=0, seq=None):
        """매도 기록"""
        amount = qty * price
        self.trades.append({
            'time': time.strftime("%H:%M:%S"),
            'type': 'SELL',
            'code': code,
            'name': name,
            'qty': qty,
            'price': price,
            'amount': amount,
            'pl_rt': pl_rt,
            'pnl_amt': pnl_amt,
            'tax': tax,
            'seq': seq # [신규] 시퀀스(프로필) 번호 기록
        })
        # 퀀트 분석용 데이터 업데이트
        self.cumulative_pnl += pnl_amt
        self.pnl_history.append(self.cumulative_pnl)
        self.returns_history.append(pl_rt)

    def get_session_report(self, target_seq=None):
        """세션 전체 또는 특정 시퀀스 리포트 생성"""
        # [신규] 특정 시퀀스(seq) 필터링 로직 추가
        if target_seq is not None:
             relevant_trades = [t for t in self.trades if str(t.get('seq')) == str(target_seq)]
        else:
             relevant_trades = self.trades

        if not relevant_trades:
            return None

        # 퀀트 분석용 임시 데이터 추출 (필터링된 기준)
        sell_trades = [t for t in relevant_trades if t['type'] == 'SELL']
        filtered_returns = [t['pl_rt'] for t in sell_trades]
        
        # 필터링된 기반 누적 손익 히스토리 생성 (MDD 계산용)
        temp_cumulative_pnl = 0
        filtered_pnl_history = [0]
        for t in sell_trades:
            temp_cumulative_pnl += t.get('pnl_amt', 0)
            filtered_pnl_history.append(temp_cumulative_pnl)

        # 종목별 집계
        stock_summary = {} # code -> {name, buy_qty, buy_amt, sell_qty, sell_amt, pnl_amt}
        
        win_count = sum(1 for t in sell_trades if t['pnl_amt'] > 0)
        total_sell_count = len(sell_trades)
        win_rate = (win_count / total_sell_count * 100) if total_sell_count > 0 else 0.0

        for t in relevant_trades:
            code = t['code']
            if code not in stock_summary:
                stock_summary[code] = {
                    'name': t['name'],
                    'buy_qty': 0, 'buy_amt': 0,
                    'sell_qty': 0, 'sell_amt': 0,
                    'pnl_amt': 0
                }
            
            if t['type'] == 'BUY':
                stock_summary[code]['buy_qty'] += t['qty']
                stock_summary[code]['buy_amt'] += t['amount']
            else:
                stock_summary[code]['sell_qty'] += t['qty']
                stock_summary[code]['sell_amt'] += t['amount']
                stock_summary[code]['pnl_amt'] += t['pnl_amt']

        # 전체 집계
        total_buy_amt = sum(t['amount'] for t in relevant_trades if t['type'] == 'BUY')
        total_sell_amt = sum(t['amount'] for t in relevant_trades if t['type'] == 'SELL')
        total_pnl_amt = sum(t.get('pnl_amt', 0) for t in relevant_trades if t['type'] == 'SELL')
        total_tax_amt = sum(t.get('tax', 0) for t in relevant_trades if t['type'] == 'SELL')
        
        # MDD 계산 (필터링된 데이터 기준)
        peak = -float('inf')
        mdd = 0
        for pnl in filtered_pnl_history:
            if pnl > peak:
                peak = pnl
            drawdown = peak - pnl
            if drawdown > mdd:
                mdd = drawdown

        # [신규] 손익비, 프로핏 팩터, 기댓값 계산
        profit_trades = [t for t in sell_trades if t['pnl_amt'] > 0]
        loss_trades = [t for t in sell_trades if t['pnl_amt'] <= 0]
        
        avg_profit = (sum(t['pnl_amt'] for t in profit_trades) / len(profit_trades)) if profit_trades else 0
        avg_loss = (abs(sum(t['pnl_amt'] for t in loss_trades)) / len(loss_trades)) if loss_trades else 0
        
        # 1. 손익비 (Payoff Ratio)
        payoff_ratio = (avg_profit / avg_loss) if avg_loss > 0 else (float('inf') if avg_profit > 0 else 0)
        
        # 2. 프로핏 팩터 (Profit Factor)
        total_profit = sum(t['pnl_amt'] for t in profit_trades)
        total_loss = abs(sum(t['pnl_amt'] for t in loss_trades))
        profit_factor = (total_profit / total_loss) if total_loss > 0 else (float('inf') if total_profit > 0 else 0)
        
        # 3. 기댓값 (Expectancy)
        win_prob = win_rate / 100
        loss_prob = 1 - win_prob
        expectancy = (win_prob * avg_profit) - (loss_prob * avg_loss)

        # 샤프 지수 계산 (필터링된 데이터 기준)
        sharpe_ratio = 0
        if len(filtered_returns) > 1:
            avg_return = sum(filtered_returns) / len(filtered_returns)
            variance = sum((x - avg_return) ** 2 for x in filtered_returns) / (len(filtered_returns) - 1)
            std_dev = math.sqrt(variance)
            if std_dev > 0:
                sharpe_ratio = avg_return / std_dev

        # 전략별 매수 건수 집계
        strat_counts = {'qty': 0, 'amount': 0, 'percent': 0, 'HTS': 0}
        for t in relevant_trades:
            if t['type'] == 'BUY':
                mode = t.get('strat_mode', 'qty')
                strat_counts[mode] = strat_counts.get(mode, 0) + 1

        total_pnl_rt = (total_pnl_amt / total_buy_amt * 100) if total_buy_amt > 0 else 0.0

        return {
            'stock_summary': stock_summary,
            'total_buy': total_buy_amt,
            'total_sell': total_sell_amt,
            'total_pnl': total_pnl_amt,
            'total_tax': total_tax_amt,
            'total_rt': total_pnl_rt,
            'trade_count': len(relevant_trades),
            'strat_counts': strat_counts,
            'target_seq': target_seq,
            'win_rate': win_rate,
            'mdd': mdd,
            'sharpe_ratio': sharpe_ratio,
            'payoff_ratio': payoff_ratio,
            'profit_factor': profit_factor,
            'expectancy': expectancy
        }

# 싱글톤 인스턴스
session_logger = TradeLogger()
