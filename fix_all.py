import os

def fix_file(file_path, version_title, num_buttons):
    if not os.path.exists(file_path):
        print(f"Skipping {file_path}")
        return
    
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # 1. Update Title Label
    # Look for the specific QLabel line
    content = content.replace('self.lbl_main_title = QLabel("🚀 KipoStock Lite V1.5")', f'self.lbl_main_title = QLabel("🚀 {version_title}")')
    content = content.replace('self.lbl_main_title = QLabel("🚀 KipoStock_Lite_V1.5")', f'self.lbl_main_title = QLabel("🚀 {version_title}")')
    content = content.replace('self.lbl_main_title = QLabel("🚀 KipoStock V5.7")', f'self.lbl_main_title = QLabel("🚀 {version_title}")')

    # 2. Update Condition Label and Count
    content = content.replace('조건식 선택 (0-9)', f'조건식 선택 (0-{num_buttons-1})')
    content = content.replace('조건식 선택 (0-19)', f'조건식 선택 (0-{num_buttons-1})')
    
    # cond_states initialization
    content = content.replace('self.cond_states = [0] * 10 # [Lite] 10개로 축소', f'self.cond_states = [0] * {num_buttons}')
    content = content.replace('self.cond_states = [0] * 20 # [V5.7] 20개로 복구', f'self.cond_states = [0] * {num_buttons}')

    # UI Loop
    if num_buttons == 20:
        old_loop = 'for i in range(10):'
        # Check if it was already 20
        if 'for i in range(20):' not in content:
            # We need to replace the loop body too for 20 buttons (smaller size)
            new_inner = """            btn = QPushButton(str(i))
            # [V5.7] 20개 원형 버튼 디자인: 지름 25px, Border-radius 12px
            btn.setFixedSize(25, 25) 
            btn.setStyleSheet("background-color: #e0e0e0; color: #333; font-weight: bold; border-radius: 12px; padding: 0px; font-size: 11px;")"""
            
            # Find the old body and replace
            old_body = """            btn = QPushButton(str(i))
            # [Lite] 원형 버튼 디자인: 지름 36px, Border-radius 18px (완전한 원형)
            btn.setFixedSize(36, 36) 
            btn.setStyleSheet("background-color: #e0e0e0; color: #333; font-weight: bold; border-radius: 18px; padding: 0px; font-size: 14px;")"""
            content = content.replace(old_body, new_inner)
            
            content = content.replace('for i in range(10):', 'for i in range(20):')
            
            # Layout logic
            old_layout = """            # [Lite] 배분: 상단(짝수: 0, 2, 4, 6, 8) / 하단(홀수: 1, 3, 5, 7, 9)
            if i % 2 == 0:
                row = 0
                col = i // 2
            else:
                row = 1
                col = i // 2"""
            new_layout = """            # [V5.7] 배분: 상단(0-9) / 하단(10-19)
            row = 0 if i < 10 else 1
            col = i % 10"""
            content = content.replace(old_layout, new_layout)

    # 3. Robust Parsing in save_settings
    # We'll inject safe conversion helpers and replace the float/int calls
    safe_helpers = """            # [수정] 숫자 형식 오류 방지를 위한 안전한 변환 함수
            def safe_int(s, default=0):
                try: 
                    cleaned = "".join(c for c in str(s) if c.isdigit() or c in '.-').split('.')[0]
                    return int(cleaned) if cleaned else default
                except: return default
            
            def safe_float(s, default=0.0):
                try: 
                    cleaned = "".join(c for c in str(s) if c.isdigit() or c in '.-')
                    return float(cleaned) if cleaned else default
                except: return default

            qty_val = self.input_qty_val.text()"""
    
    content = content.replace('qty_val = self.input_qty_val.text()', safe_helpers)
    
    # Replace the problematic sanitize functions
    old_sanitize = """            # [수정] 성향별 대표값 변수 정의 및 자동 보정
            # 익절(TP)은 양수, 손절(SL)은 음수로 강제 변환
            def sanitize_tp(v): return abs(float(v))
            def sanitize_sl(v): return -abs(float(v))"""
    
    new_sanitize = """            # [수정] 성향별 대표값 변수 정의 및 자동 보정 (안전하게 변환)
            def sanitize_tp(v): return abs(safe_float(v, 1.0))
            def sanitize_sl(v): return -abs(safe_float(v, -1.0))"""
    
    content = content.replace(old_sanitize, new_sanitize)

    # Replace the current_data dict float/int calls
    content = content.replace("'take_profit_rate': float(q_tp)", "'take_profit_rate': safe_float(q_tp, 1.0)")
    content = content.replace("'stop_loss_rate': float(q_sl)", "'stop_loss_rate': safe_float(q_sl, -1.0)")
    content = content.replace("'max_stocks': int(max_s)", "'max_stocks': safe_int(max_s, 20)")
    
    content = content.replace("'tp': float(q_tp), 'sl': float(q_sl)", "'tp': safe_float(q_tp, 1.0), 'sl': safe_float(q_sl, -1.0)")
    content = content.replace("'tp': float(a_tp), 'sl': float(a_sl)", "'tp': safe_float(a_tp, 1.0), 'sl': safe_float(a_sl, -1.0)")
    content = content.replace("'tp': float(p_tp), 'sl': float(p_sl)", "'tp': safe_float(p_tp, 1.0), 'sl': safe_float(p_sl, -1.0)")
    content = content.replace("'tp': float(h_tp), 'sl': float(h_sl)", "'tp': safe_float(h_tp, 1.0), 'sl': safe_float(h_sl, -1.0)")

    # 4. Load settings loop
    content = content.replace('for i in range(10): # [Lite] 10개로 한정', f'for i in range({num_buttons}):')

    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"Fixed {file_path}")

# Run fixes
fix_file('d:/Work/Python/AutoBuy/KipoStockNow/Kipo_GUI_main.py', 'KipoStock Lite V1.5', 10)
fix_file('d:/Work/Python/AutoBuy/KipoStock_V5.7/Kipo_GUI_main.py', 'KipoStock V5.7', 20)
