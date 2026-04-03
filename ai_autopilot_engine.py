import time
import json
from PyQt6.QtCore import QThread, pyqtSignal
from login import fn_au10001
import stock_info
import gemini_bot
from check_n_buy import ACCOUNT_CACHE

class AiAutopilotEngine(QThread):
    def __init__(self, gui_ref):
        super().__init__()
        self.gui = gui_ref
        self.running = True
        self.check_interval = 60 # 60초 주기
        
    def run(self):
        """AI 오토파일럿 핵심 엔진 메인 루프"""
        while self.running:
            try:
                ai_stocks = getattr(self.gui, 'ai_autopilot_stocks', {})
                if not ai_stocks:
                    time.sleep(5)
                    continue
                
                # 60초마다 활성화된 종목을 스캔
                target_codes = list(ai_stocks.keys())
                for code in target_codes:
                    if not self.running: break
                    stk_info = ai_stocks.get(code)
                    if not stk_info or not stk_info.get("enabled"): continue
                    
                    stk_nm = stk_info['stk_nm']
                    # 조용하게 로그 남기기
                    self.gui.append_log(f"<font color='#8e44ad'>🧠 [AI 오토파일럿 모의분석] '{stk_nm}' 60초 진단 스캔 시작...</font>")
                    
                    # 1. 보유 종목 정보 결합
                    acc_data = ACCOUNT_CACHE.get('realtime_holdings', {}).get(code, {})
                    profit_pct = acc_data.get('profit_rt', 0.0)
                    buy_qty = acc_data.get('qty', 0)
                    buy_price = acc_data.get('buy_price', 0)
                    
                    # 2. 실시간 정보 결합
                    token = fn_au10001()
                    ext_data = stock_info.get_extended_stock_data(code, token)
                    current_price = ext_data.get('price', 0)
                    power = ext_data.get('power', 0.0)
                    ask_qty = ext_data.get('total_ask_qty', 0)
                    bid_qty = ext_data.get('total_bid_qty', 0)
                    
                    # 3. AI에게 보낼 JSON Payload 조립
                    stock_context = json.dumps({
                        "stk_nm": stk_nm,
                        "current_price": current_price,
                        "my_average_price": buy_price,
                        "holding_qty": buy_qty,
                        "current_profit_rate": profit_pct,
                        "chegyul_power": power,
                        "total_ask_qty": ask_qty,
                        "total_bid_qty": bid_qty
                    }, ensure_ascii=False)
                    
                    # 4. Gemini API 호출
                    ai_res_str = gemini_bot.analyze_autopilot_action(stock_context)
                    
                    try:
                        res_json = json.loads(ai_res_str)
                        action = res_json.get("action", "HOLD")
                        reason = res_json.get("reason", "판단 보류")
                    except json.JSONDecodeError:
                        action = "HOLD"
                        reason = "AI 응답 형식이 깨졌어 자기야 ㅠㅠ"
                    
                    # 5. 모의 트레이딩 진단 로그 출력
                    if action == "BUY_BULTAGI":
                        msg = f"🟢 [AI 권고: 매수] {reason}"
                        self.gui.append_log(f"<font color='#1abc9c'>   ↳ {msg}</font>")
                        try:
                            import winsound
                            winsound.PlaySound("SystemAsterisk", winsound.SND_ALIAS | winsound.SND_ASYNC)
                        except: pass
                    elif action == "SELL_ALL":
                        msg = f"🔴 [AI 권고: 전량 매도] {reason}"
                        self.gui.append_log(f"<font color='#e74c3c'>   ↳ {msg}</font>")
                        try:
                            import winsound
                            winsound.PlaySound("SystemExclamation", winsound.SND_ALIAS | winsound.SND_ASYNC)
                        except: pass
                    else:
                        msg = f"⚪ [AI 권고: 관망] {reason}"
                        self.gui.append_log(f"<font color='#95a5a6'>   ↳ {msg}</font>")
                        
                    # 약간의 지연(Rate Limit 방지)
                    time.sleep(2)
                    
            except Exception as e:
                self.gui.append_log(f"<font color='#e74c3c'>⚠️ [AI Autopilot] 루프 에러: {e}</font>")
                
            # 60초 대기(종목 루프가 끝난 뒤)
            for _ in range(self.check_interval):
                if not self.running: break
                time.sleep(1)

    def stop(self):
        self.running = False
        self.wait()
