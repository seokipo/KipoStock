import os
import sys
from datetime import datetime, timedelta
from kipodb import kipo_db
from gemini_bot import analyze_trade_patterns

def analyze_master(days=7):
    """
    최근 n일간의 매매 데이터를 분석하여 리포트를 생성합니다.
    """
    end_date = datetime.now().strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
    
    print(f"🔍 [AI 분석 시작] {start_date} ~ {end_date} (최근 {days}일)")
    
    trades = kipo_db.get_trades_by_range(start_date, end_date)
    
    if not trades:
        print("📭 분석할 매매 내역이 없습니다. (DB가 비어있음)")
        return
    
    # 1. 기초 통계 계산
    total_pnl = sum(t['pnl_amt'] for t in trades if t['type'] == 'SELL')
    win_trades = [t for t in trades if t['type'] == 'SELL' and t['pnl_amt'] > 0]
    lose_trades = [t for t in trades if t['type'] == 'SELL' and t['pnl_amt'] <= 0]
    
    win_rate = (len(win_trades) / (len(win_trades) + len(lose_trades)) * 100) if (len(win_trades) + len(lose_trades)) > 0 else 0
    
    # 2. 전략별 통계
    strat_stats = {}
    for t in trades:
        if t['type'] == 'SELL':
            sm = t['strat_mode'] or 'none'
            if sm not in strat_stats:
                strat_stats[sm] = {'pnl': 0, 'count': 0, 'wins': 0}
            strat_stats[sm]['pnl'] += t['pnl_amt']
            strat_stats[sm]['count'] += 1
            if t['pnl_amt'] > 0: strat_stats[sm]['wins'] += 1
            
    # 3. AI 분석을 위한 데이터 포맷팅
    ai_rows = []
    for t in trades:
        if t['type'] == 'SELL':
            ai_rows.append({
                'date': t['trade_date'],
                'name': t['name'],
                'type': 'SELL',
                'rt': f"{t['pl_rt']:.2f}%",
                'pnl': f"{int(t['pnl_amt']):,}원",
                'strat': t['strat_mode']
            })
            
    # 최근 20개 매매만 AI에게 전달 (프롬프트 길이 제한 고려)
    ai_feedback = analyze_trade_patterns(ai_rows[-20:])
    
    # 4. 리포트 출력
    report = f"""
=========================================
📊 [KipoStock AI 마스터 리포트]
=========================================
📅 기간: {start_date} ~ {end_date} ({days}일간)
💰 총 누적 손익 : {int(total_pnl):+,}원
📈 전체 승률 : {win_rate:.1f}% ({len(win_trades)}승 {len(lose_trades)}패)
─────────────────────────────────────────
📂 [전략별 성적 요약]
"""
    for sm, data in sorted(strat_stats.items(), key=lambda x: x[1]['pnl'], reverse=True):
        wr = (data['wins'] / data['count'] * 100) if data['count'] > 0 else 0
        report += f"🔹 {sm:<12}: {int(data['pnl']):+,}원 ({wr:.1f}%)\n"
        
    report += f"""─────────────────────────────────────────
🤖 [AI 코칭 & 패턴 분석]
{ai_feedback}
=========================================
"""
    print(report)
    
    # 파일로 저장
    log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'LogData')
    if not os.path.exists(log_dir): os.makedirs(log_dir)
    
    filename = f"AI_Master_Report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    with open(os.path.join(log_dir, filename), 'w', encoding='utf-8') as f:
        f.write(report)
    print(f"✅ 리포트가 저장되었습니다: {filename}")

if __name__ == "__main__":
    # 기본 최근 7일 분석
    analyze_master(days=7)
