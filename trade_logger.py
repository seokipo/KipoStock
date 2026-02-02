import time

class TradeLogger:
    def __init__(self):
        self.trades = []
        self.start_time = time.strftime("%Y-%m-%d %H:%M:%S")

    def record_buy(self, code, name, qty, price):
        """매수 기록"""
        amount = qty * price
        self.trades.append({
            'time': time.strftime("%H:%M:%S"),
            'type': 'BUY',
            'code': code,
            'name': name,
            'qty': qty,
            'price': price,
            'amount': amount
        })

    def record_sell(self, code, name, qty, price, pl_rt, pnl_amt):
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
            'pnl_amt': pnl_amt
        })

    def get_session_report(self):
        """세션 전체 리포트 생성"""
        if not self.trades:
            return None

        # 종목별 집계
        stock_summary = {} # code -> {name, buy_qty, buy_amt, sell_qty, sell_amt, pnl_amt}
        
        for t in self.trades:
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
        total_buy_amt = sum(t['amount'] for t in self.trades if t['type'] == 'BUY')
        total_sell_amt = sum(t['amount'] for t in self.trades if t['type'] == 'SELL')
        total_pnl_amt = sum(t.get('pnl_amt', 0) for t in self.trades if t['type'] == 'SELL')
        
        total_pnl_rt = (total_pnl_amt / total_buy_amt * 100) if total_buy_amt > 0 else 0.0

        return {
            'stock_summary': stock_summary,
            'total_buy': total_buy_amt,
            'total_sell': total_sell_amt,
            'total_pnl': total_pnl_amt,
            'total_rt': total_pnl_rt,
            'trade_count': len(self.trades)
        }

# 싱글톤 인스턴스
session_logger = TradeLogger()
