import time
import math
import json
import os
import sys
from datetime import datetime

class TradeLogger:
    def __init__(self):
        self.trades = []
        self.start_time = time.strftime("%Y-%m-%d %H:%M:%S")
        self.cumulative_pnl = 0
        self.pnl_history = [0] # MDD 계산용 누적 손익 히스토리
        self.returns_history = [] # 샤프 지수 계산용 개별 매매 수익률 히스토리
        self.sync_required = False # [v5.5] API 리포트 차트 강제 동기화 플래그
        
        # [신규] 경로 설정
        # [V2.4.6] 사용자 요청에 따른 데이터 고정 경로 적용
        fixed_path = r"D:\Work\Python\AutoBuy\ExeFile\KipoStockAi_V1.0"
        if os.path.exists(fixed_path):
            self.script_dir = fixed_path
        elif getattr(sys, 'frozen', False):
            self.script_dir = os.path.dirname(sys.executable)
        else:
            self.script_dir = os.path.dirname(os.path.abspath(__file__))
        
        self.data_dir = os.path.join(self.script_dir, 'LogData')
        if not os.path.exists(self.data_dir):
            try: os.makedirs(self.data_dir)
            except: pass
        self.backup_file = os.path.join(self.data_dir, 'session_trades.json')
        
        # [v3.0.9] 차트 시작점을 08:59:00으로 고정 (사용자 요청: 08:55 -> 08:59)
        if not self.load_session() or not self.pnl_history:
            self.pnl_history = [{'time': "08:59:00", 'pnl': 0}]

    def save_session(self):
        """[신규] 현재 세션 데이터를 파일로 백업"""
        try:
            data = {
                'date': datetime.now().strftime("%Y%m%d"),
                'trades': self.trades,
                'cumulative_pnl': self.cumulative_pnl,
                'pnl_history': self.pnl_history,
                'returns_history': self.returns_history
            }
            with open(self.backup_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"⚠️ [TradeLogger] 세션 저장 실패: {e}")

    def load_session(self):
        """[신규] 파일에서 세션 데이터 로드 (당일 데이터인 경우에만)"""
        if not os.path.exists(self.backup_file):
            return False
            
        try:
            with open(self.backup_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # 날짜 확인 (오늘 데이터가 아니면 초기화)
            today_str = datetime.now().strftime("%Y%m%d")
            if data.get('date') == today_str:
                self.trades = data.get('trades', [])
                self.cumulative_pnl = data.get('cumulative_pnl', 0)
                
                # [v5.4.1] pnl_history 데이터 형식 정규화 (호환성 보장)
                raw_pnl_history = data.get('pnl_history', [])
                self.pnl_history = []
                
                for item in raw_pnl_history:
                    if isinstance(item, dict) and 'time' in item and 'pnl' in item:
                        self.pnl_history.append(item)
                    elif isinstance(item, (int, float)):
                        # 레거시 데이터 형식([0, 100, ...]) 대응
                        self.pnl_history.append({'time': datetime.now().strftime("%H:%M:%S"), 'pnl': item})
                
                # 데이터가 비어있으면 초기값 설정
                if not self.pnl_history:
                    # [v3.0.9] 장전(09:00 이전) 기동 시에는 08:59:00으로 시작점 고정
                    now_t = datetime.now()
                    if now_t.hour < 9:
                        start_t = "08:59:00"
                    else:
                        start_t = now_t.strftime("%H:%M:%S")
                    self.pnl_history = [{'time': start_t, 'pnl': 0}]
                
                self.returns_history = data.get('returns_history', [])
                print(f"✅ [TradeLogger] 이전 세션 복원 완료 ({len(self.trades)}건의 거래, 그래프 데이터 {len(self.pnl_history)}건)")
                return True
            else:
                print(f"ℹ️ [TradeLogger] 이전 세션이 오늘 데이터가 아니므로 새로 시작합니다.")
                return False
        except Exception as e:
            print(f"⚠️ [TradeLogger] 세션 로드 실패: {e}")
            return False

    def record_buy(self, code, name, qty, price, strat_mode='qty', seq=None):
        """매수 기록"""
        current_time_str = time.strftime("%H:%M:%S")
        amount = qty * price
        self.trades.append({
            'time': current_time_str,
            'type': 'BUY',
            'code': code,
            'name': name,
            'qty': qty,
            'price': price,
            'amount': amount,
            'strat_mode': strat_mode,
            'seq': seq # [신규] 시퀀스(프로필) 번호 기록
        })
        # [v6.0.4] 매수 시에는 P&L 히스토리를 추가하지 않음 (사용자 요청: 매도 시만 타점 기록)
        # self.pnl_history.append({'time': current_time_str, 'pnl': self.cumulative_pnl})
        self.save_session() # [신규] 실시간 백업
        # [신규 v6.2.0] SQLite 로컬 DB에도 영구 저장
        from kipodb import kipo_db
        kipo_db.insert_trade(self.trades[-1])

    def record_sell(self, code, name, qty, price, pl_rt, pnl_amt, tax=0, seq=None, strat_mode=None):
        """매도 기록"""
        current_time_str = time.strftime("%H:%M:%S")
        amount = qty * price
        self.trades.append({
            'time': current_time_str,
            'type': 'SELL',
            'code': code,
            'name': name,
            'qty': qty,
            'price': price,
            'amount': amount,
            'pl_rt': pl_rt,
            'pnl_amt': pnl_amt,
            'tax': tax,
            'seq': seq, # [신규] 시퀀스(프로필) 번호 기록
            'strat_mode': strat_mode # [신규 v1.0.7] 매도 시점에도 전략 모드 기록 보존
        })
        # 퀀트 분석용 데이터 업데이트
        self.cumulative_pnl += pnl_amt
        self.pnl_history.append({'time': current_time_str, 'pnl': self.cumulative_pnl})
        self.returns_history.append(pl_rt)
        self.sync_required = True # [v5.5] API 싱크 시그널 활성화
        self.save_session() # [신규] 실시간 백업
        # [신규 v6.2.0] SQLite 로컬 DB에도 영구 저장
        from kipodb import kipo_db
        kipo_db.insert_trade(self.trades[-1])

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

        # 전략별 매수 건수 집계 (v5.0.8 세분화된 전략명 대응)
        strat_counts = {}
        for t in relevant_trades:
            if t['type'] == 'BUY':
                mode = t.get('strat_mode', '미상')
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

    def get_kipostock_perspective(self, token):
        """[신규 v6.1.17] 4번 항목: 당일 급등 후 조정 중인 종목 추출"""
        report = self.get_session_report()
        if not report or 'stock_summary' not in report:
            return []
            
        from stock_info import get_price_high_data
        perspective_list = []
        
        for code, info in report['stock_summary'].items():
            if info['buy_qty'] > 0:
                avg_buy_price = info['buy_amt'] / info['buy_qty']
                now_prc, high_prc, base_prc = get_price_high_data(code, token)
                
                if avg_buy_price > 0 and high_prc > 0:
                    # 1. 고가 수익률 (피크) - 매수가 기준이 아닌 당일 시가(기준가) 대비로 볼지, 매수가 대비로 볼지 결정 필요
                    # 사용자 요청: "최고점에 도달한 것 중에 15% 이상" -> 보통 당일 상승률을 의미함
                    day_peak_rt = ((high_prc - base_prc) / base_prc * 100) if base_prc > 0 else 0
                    day_now_rt = ((now_prc - base_prc) / base_prc * 100) if base_prc > 0 else 0
                    
                    # 조건: 당일 고가 15% 이상 AND 현재가 5%~12% 사이
                    if day_peak_rt >= 15.0 and 5.0 <= day_now_rt <= 12.0:
                        perspective_list.append({
                            'code': code,
                            'name': info['name'],
                            'peak_rt': day_peak_rt,
                            'now_rt': day_now_rt,
                            'avg_buy': avg_buy_price,
                            'now_prc': now_prc
                        })
        
        return perspective_list

# 싱글톤 인스턴스
session_logger = TradeLogger()
