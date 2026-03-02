

import sys
import os
import asyncio
import json
import datetime
import traceback
import ast
import requests
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                           QHBoxLayout, QLabel, QLineEdit, QPushButton, 
                           QTextEdit, QFrame, QGridLayout, QMessageBox, QGroupBox,
                           QScrollArea, QRadioButton, QButtonGroup, QCheckBox, QSizePolicy,
                           QSpinBox, QComboBox, QDialog, QFormLayout, QSplitter)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QObject, QTimer, QEvent, QSharedMemory
from PyQt6.QtGui import QFont, QIcon, QColor, QPalette
import winsound
import re
import matplotlib
matplotlib.use('QtAgg')
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import matplotlib.pyplot as plt
from trade_logger import session_logger

# 기존 모듈 임포트
from config import telegram_token, telegram_chat_id
from tel_send import tel_send as real_tel_send
from chat_command import ChatCommand
from get_setting import get_setting, cached_setting
import ctypes # [신규] 윈도우 API 호출용
from market_hour import MarketHour

# ----------------- Custom Widgets -----------------
class ZoomableTextEdit(QTextEdit):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._font_size = 11
        # [신규] 이미지 확대/축소 배율 상태 관리
        self._img_scale_idx = 0
        # 1.0 기준 width=600으로 잡았을 때 (0.8배=480, 1.0배=600, 1.5배=900)
        # 사용자 요청: 기본 -> 더블클릭 -> 더블클릭 -> 더블클릭 무한루프 가능하도록
        # 0.8배 -> 1.0배 -> 1.5배 사이클
        self._img_scales = [480, 600, 900]
        self._img_scale_idx = 0  # 사용자 요청에 따라 디폴트는 제일 작은 80% (480px)


    def wheelEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            if delta > 0:
                self._font_size = min(30, self._font_size + 1)
            elif delta < 0:
                self._font_size = max(6, self._font_size - 1)
            
            # [Fix] HTML(TextEdit) 표 내부 등의 요소들은 zoomIn()이 무시되는 특성이 있으므로
            # StyleSheet를 강제로 덮어씌워 확실하게 뷰포트 글씨를 제어합니다.
            self.setStyleSheet(f"QTextEdit {{ font-size: {self._font_size}pt; }}")
            event.accept()
        else:
            super().wheelEvent(event)
            
    # [신규] 가운데 버튼(휠 클릭) 이벤트 후킹 (그래프 이미지 크기 조절 기능)
    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton:
            # 휠 클릭 시 화면의 여백을 클릭해도 작동하도록, 문서 내부의 모든 이미지 포맷을 찾아 크기를 변경합니다.
            self._img_scale_idx = (self._img_scale_idx + 1) % len(self._img_scales)
            new_width = self._img_scales[self._img_scale_idx]
            
            # HTML 전체 교체(toHtml -> setHtml) 방식은 휠 줌(폰트 크기) 등의 기존 포맷을 초기화하는 문제가 있으므로,
            # QTextDocument 내부 블록을 순회하며 이미지만 골라서 사이즈를 변경합니다.
            doc = self.document()
            for i in range(doc.blockCount()):
                block = doc.findBlockByNumber(i)
                iterator = block.begin()
                while not iterator.atEnd():
                    fragment = iterator.fragment()
                    if fragment.isValid():
                        fmt = fragment.charFormat()
                        if fmt.isImageFormat():
                            img_fmt = fmt.toImageFormat()
                            img_fmt.setWidth(new_width)
                            
                            # 커서를 생성하여 해당 프래그먼트 위치의 포맷을 업데이트
                            cursor = self.textCursor()
                            cursor.setPosition(fragment.position())
                            cursor.setPosition(fragment.position() + fragment.length(), cursor.MoveMode.KeepAnchor)
                            cursor.setCharFormat(img_fmt)
                    iterator += 1
            
            event.accept()
            return
                
        super().mouseReleaseEvent(event)

# ----------------- Worker Thread for Asyncio Loop -----------------
class WorkerSignals(QObject):
    log_signal = pyqtSignal(str)
    status_signal = pyqtSignal(str)  # 상태 표시줄 업데이트용
    clr_signal = pyqtSignal()       # [신규] 로그 초기화용
    request_log_signal = pyqtSignal() # [신규] 로그 파일 출력 요청
    auto_seq_signal = pyqtSignal(int) # [신규] 원격 시퀀스 시작 신호 (프로필 번호)
    condition_loaded_signal = pyqtSignal() # [신규] 조건식 목록 로드 완료 신호
    graph_update_signal = pyqtSignal() # [신규] 수익 그래프 업데이트 시그널

class AsyncWorker(QThread):
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.signals = WorkerSignals()
        self.loop = None
        self.chat_command = None
        self.keep_running = True
        self.pending_start = False # [추가] 장외 시간 예약 시작 기능용
        self.pending_profile_info = None

    def run(self):
        # Create a new event loop for this thread
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        
        # 1. Override tel_send logic
        import chat_command as chat_cmd_module
        
        def gui_log_send(text):
            self.signals.log_signal.emit(text)
        
        # Patch tel_send in chat_command
        chat_cmd_module.tel_send = gui_log_send
        
        # 2. Redirect stdout/stderr to capture prints from get_seq.py and others
        class StreamRedirector:
            def __init__(self, emitter):
                self.emitter = emitter
                self.is_redirecting = False # [신규] 재귀 호출 방지 플래그

            def write(self, text):
                if self.is_redirecting: return # 이미 로그 처리 중이면 무시
                text = text.strip()
                if text:
                    try:
                        self.is_redirecting = True
                        self.emitter(text)
                    except: pass
                    finally:
                        self.is_redirecting = False

            def flush(self):
                pass
                
        sys.stdout = StreamRedirector(gui_log_send)
        sys.stderr = StreamRedirector(gui_log_send)

        # Initialize ChatCommand
        self.chat_command = ChatCommand()
        self.chat_command.on_clear_logs = lambda: self.signals.clr_signal.emit()
        self.chat_command.on_request_log_file = lambda: self.signals.request_log_signal.emit()
        self.chat_command.on_auto_sequence = lambda idx: self.signals.auto_seq_signal.emit(idx)
        self.chat_command.on_condition_loaded = lambda: self.signals.condition_loaded_signal.emit()
        self.chat_command.on_start = lambda: self.signals.status_signal.emit("RUNNING")
        
        # [신규] 외부(텔레그램, 명령창)에서 시작/중지 요청 시 GUI 신호로 전달
        self.chat_command.on_start_request = lambda: self.signals.log_signal.emit("🤖 외부 시작 명령 수신") or self.schedule_command('start')
        self.chat_command.on_stop_request = lambda: self.signals.log_signal.emit("🤖 외부 중지 명령 수신") or self.schedule_command('stop')
        
        def on_stop_cb():
            self.pending_start = False # [신규] 명령어로 중지 시에도 예약 상태 해제
            self.signals.status_signal.emit("READY")
            
        self.chat_command.on_stop = on_stop_cb
        self.chat_command.rt_search.on_connection_closed = self._on_connection_closed_wrapper
        
        self.loop.run_until_complete(self.main_loop())
        self.loop.close()

    async def _on_connection_closed_wrapper(self):
        self.signals.log_signal.emit("⚠️ 연결 끊김 감지. 재연결 시도 중...")
        await self.chat_command._on_connection_closed()

    async def main_loop(self):
        self.signals.log_signal.emit("🚀 시스템 초기화 완료. 대기 중...")
        
        # 설정 로드 및 적용
        self.load_initial_settings()
        
        # 시작 시 자동으로 조건식 목록 가져오기 (마지막 저장된 설정대로 필터링되어 표시됨)
        self.signals.log_signal.emit("ℹ️ 저장된 조건식 목록을 불러옵니다...")
        await self.chat_command.condition()
        
        # [추가] 자동 시작(auto_start) 설정 확인 및 실행
        try:
            settings_path = os.path.join(os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__)), 'settings.json')
            if os.path.exists(settings_path):
                with open(settings_path, 'r', encoding='utf-8') as f:
                    settings = json.load(f)
                
                if settings.get('auto_start', False):
                    self.signals.log_signal.emit("ℹ️ 자동 시작 설정이 활성화되어 있습니다.")
                    # 약간의 딜레이 후 시작 시도 (초기화 안정성 확보)
                    await asyncio.sleep(1.0)
                    # 직접 await 호출 (같은 루프 내이므로 schedule_command 대신 직접 호출)
                    await self._execute_command('start')
        except Exception as e:
            self.signals.log_signal.emit(f"⚠️ 자동 시작 확인 중 오류: {e}")
        
        try:
            while self.keep_running:
                # 텔레그램 메시지 확인 (GUI에서는 필수 아님, 텔레그램 제어 원할 시 유지)
                message = self.get_chat_updates()
                if message:
                    await self.chat_command.process_command(message)
                
                
                # [추가] 장 종료 시 자동 중단 및 보고 시퀀스 (15:30)
                now = datetime.datetime.now()
                if now.hour == 15 and now.minute == 30 and not self.today_stopped:
                    self.today_stopped = True
                    self.signals.log_signal.emit("🔔 장 종료 시간(15:30)이 되어 자동으로 정산 시퀀스를 시작합니다.")
                    
                    # 1. 중지 (STOP)
                    await self.chat_command.stop(set_auto_start_false=False)
                    # 2. 통합 리포트 생성 (Trade Diary + CSV/TXT + Balance)
                    await self.chat_command.report()

                # 날짜가 바뀌면 종료 플래그 초기화
                current_date = now.date()
                if self.last_check_date != current_date:
                    self.last_check_date = current_date
                    self.today_stopped = False

                # 장 시작/종료 시간 자동 확인 로직
                # [수정] 대기 시간(is_waiting_period)이 아닐 때만 자동 시작 진행하여 무한 루프 방지
                if self.pending_start and MarketHour.is_market_open_time() and not MarketHour.is_waiting_period():
                    self.pending_start = False
                    self.signals.log_signal.emit("🔔 장이 시작되었습니다. 감시를 자동으로 시작합니다!")
                    self.schedule_command('start', getattr(self, 'pending_profile_info', None))
                
                await asyncio.sleep(1.0) # 체크 주기 조정
                
        except Exception as e:
            self.signals.log_signal.emit(f"❌ 메인 루프 에러: {e}")

    def load_initial_settings(self):
        try:
            # [수정] 상대 경로 대신 KipoWindow에서 정의한 절대 경로 사용 (없으면 script_dir 기반 생성)
            settings_path = getattr(self.main_window, 'settings_file', None)
            if not settings_path:
                if getattr(sys, 'frozen', False):
                    script_dir = os.path.dirname(sys.executable)
                else:
                    script_dir = os.path.dirname(os.path.abspath(__file__))
                settings_path = os.path.join(script_dir, 'settings.json')

            if os.path.exists(settings_path):
                with open(settings_path, 'r', encoding='utf-8-sig') as f: # utf-8-sig로 BOM 대응
                    settings = json.load(f)
                    
                # 시간 설정 적용
                start_time = settings.get('start_time', "09:00")
                end_time = settings.get('end_time', "15:20")
                
                sh, sm = map(int, start_time.split(':'))
                eh, em = map(int, end_time.split(':'))
                
                MarketHour.set_market_hours(sh, sm, eh, em)
                self.signals.log_signal.emit(f"⚙️ 워커 설정 동기화 완료: {start_time} ~ {end_time}")
            else:
                self.signals.log_signal.emit("ℹ️ 설정 파일(settings.json)이 없어 기본값을 사용합니다.")
                
        except Exception as e:
            self.signals.log_signal.emit(f"⚠️ 워커 초기화 중 오류: {e}")

    # MainApp의 로직 가져옴
    last_update_id = 0
    telegram_url = f"https://api.telegram.org/bot{telegram_token}/getUpdates"
    today_started = False
    today_stopped = False
    last_check_date = None

    def get_chat_updates(self):
        """텔레그램에서 새로운 명령어를 가져옵니다."""
        try:
            params = {'offset': self.last_update_id + 1, 'timeout': 1}
            response = requests.get(self.telegram_url, params=params, timeout=5)
            if response.status_code == 200:
                data = response.json()
                for update in data.get('result', []):
                    self.last_update_id = update['update_id']
                    if 'message' in update and 'text' in update['message']:
                        chat_id = str(update['message']['chat']['id'])
                        
                        # [보안] 설정된 chat_id와 일치할 때만 실행
                        from config import telegram_chat_id
                        if chat_id == telegram_chat_id:
                            return update['message']['text']
                        else:
                            print(f"⚠️ 권한 없는 사용자 접근 차단 (ID: {chat_id})")
        except Exception as e:
            # Polling 에러는 로그에만 간단히 기록
            pass
        return None
            
    # check_market_timing 메서드 제거 (자동 종료 충돌 방지)

    # GUI에서 호출할 비동기 명령들
    def schedule_command(self, cmd_type, *args):
        asyncio.run_coroutine_threadsafe(self._execute_command(cmd_type, *args), self.loop)

    async def _execute_command(self, cmd_type, *args):
        try:
            if cmd_type == 'start':
                # [수정] manual 플래그 추출 (기본값 False)
                profile_info = args[0] if len(args) > 0 else None
                manual = args[1] if len(args) > 1 else False
                
                # [수정] 수동 시작(manual=True)인 경우 사용자 설정 시간 체크(Waiting Period)를 건너뜀
                if not manual and MarketHour.is_waiting_period():
                    # [신규] 대기 상태 진입 시 기존 엔진이 있다면 확실히 정기 (좀비 매매 방지)
                    await self.chat_command.stop(set_auto_start_false=False, quiet=True)
                    
                    if not self.pending_start:
                        self.pending_start = True
                        self.pending_profile_info = profile_info
                        
                        # [수정] 안내 메시지에 실제 설정된 시간 표시 (main_window 위젯 접근 수정)
                        st_str = self.main_window.input_start_time.text()
                        et_str = self.main_window.input_end_time.text()
                        self.signals.log_signal.emit(f"⏳ 현재 장외 대기 시간입니다. ({st_str}~{et_str})")
                        self.signals.log_signal.emit("⌛ 장이 시작되면 자동으로 감시를 개시하겠습니다.")
                        self.signals.status_signal.emit("WAITING")
                    return
                
                # 수동 시작이거나 낮 시간인데 시작 시도
                success = await self.chat_command.start(profile_info=profile_info, manual=manual)
                if success:
                    self.pending_start = False
                    self.signals.status_signal.emit("RUNNING")
                else:
                    self.signals.status_signal.emit("READY")
                    if manual:
                        self.signals.log_signal.emit("⚠️ 실제 장 데이터 수신 시간이 아닙니다. (08:30~15:30 사이에만 가능)")
                    else:
                        self.signals.log_signal.emit("⚠️ 장 시작 조건을 만족하지 않습니다. 시간 설정을 확인하세요.")
                    # [신규] 장외 시간 등 시작 실패 시 경고음 (설정값 확인)
                    if get_setting('beep_sound', True):
                        try:
                            import winsound
                            winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
                        except: pass
                return
            elif cmd_type == 'stop':
                self.pending_start = False # 예약 취소
                await self.chat_command.stop(True)
                # chat_command.stop 내부에서 on_stop() 콜백을 부르면 여기서 READY로 바뀜
                # 혹시 모를 누락 방지를 위해 강제 emit 추가 (중복되더라도 안전)
                self.signals.status_signal.emit("READY")
            elif cmd_type == 'report':
                await self.chat_command.report()
            elif cmd_type == 'custom':
                await self.chat_command.process_command(args[0])
            elif cmd_type == 'update_setting':
                # settings.json 업데이트
                self.chat_command.update_setting(args[0], args[1])
                self.signals.log_signal.emit(f"✅ 설정 변경: {args[0]} = {args[1]}")
                
            elif cmd_type == 'update_settings':
                # [신규] 여러 설정을 한 번에 업데이트
                updates = args[0]
                quiet = args[1] if len(args) > 1 else False
                self.chat_command.update_settings_batch(updates)
                if not quiet:
                    self.signals.log_signal.emit("✅ 일괄 설정 저장 완료")
                
            elif cmd_type == 'today':
                await self.chat_command.today()
                
            elif cmd_type == 'condition_list':
                quiet = args[0] if args else False
                await self.chat_command.condition(quiet=quiet) # quiet 인자 전달
            elif cmd_type == 'sync_marking':
                # [신규] 마킹된 인덱스 목록을 엔진과 동기화
                marked_indices = args[0]
                if hasattr(self.chat_command, 'sync_marked_indices'):
                    await self.chat_command.sync_marked_indices(marked_indices)

        except Exception as e:
            self.signals.log_signal.emit(f"❌ 명령 실행 오류: {e}")

    def stop(self):
        """안전한 종료 처리"""
        self.keep_running = False
        if self.loop and self.loop.is_running():
             # 루프 내에서 정리 작업 수행 후 종료
             self.loop.call_soon_threadsafe(lambda: asyncio.create_task(self.shutdown()))
        
        # 스레드 종료 대기 (최대 3초)
        self.wait(3000)

    async def shutdown(self):
        """비동기 리소스 정리"""
        if self.chat_command:
            await self.chat_command.stop(True)
        # 루프 정지 (pending task cancel은 생략함)
        self.loop.stop()


# ---------------------------------------------------------------------------------------------------------
# ✅ 불타기 전용 설정 다이얼로그 (신규)
# ---------------------------------------------------------------------------------------------------------
class BultagiSettingsDialog(QDialog):
    def __init__(self, parent=None):
        # [신규] '부모에게 종속된 창' 속성 대신, 완벽한 독립 창 띄우기를 위해 Window 플래그 추가
        super().__init__(parent, Qt.WindowType.Window)
        self.settings_file = parent.settings_file if parent else 'settings.json'
        self.profile_idx = getattr(parent, 'current_profile_idx', None)

        self.setWindowTitle("🔥 불타기(Fire-up) 상세 설정")
        self.setFixedSize(400, 600)
        self.setStyleSheet("""
            QDialog { background-color: #1e1e1e; color: #ffffff; }
            QLabel { color: #ffffff; font-weight: bold; }
            QLineEdit, QComboBox { 
                background-color: #333333; color: #ffffff; 
                border: 1px solid #555555; border-radius: 4px; padding: 4px;
            }
            QPushButton { 
                background-color: #dc3545; color: white; font-weight: bold;
                border-radius: 6px; padding: 8px; font-size: 13px;
            }
            QPushButton:hover { background-color: #c82333; }
            QPushButton#btn_cancel { background-color: #6c757d; }
            QPushButton#btn_cancel:hover { background-color: #5a6268; }
        """)
        
        layout = QVBoxLayout(self)
        form_layout = QFormLayout()
        form_layout.setSpacing(15)
        
        self.input_wait = QLineEdit()
        self.input_wait.setPlaceholderText("초 단위 (예: 30)")
        form_layout.addRow("⏳ 타겟 포착 대기(초):", self.input_wait)
        
        h_layout = QHBoxLayout()
        self.combo_mode = QComboBox()
        # [UX 피드백] (만원) 텍스트 명확히 하귀 위해 뒤의 라벨 등으로 분리하거나 단순화
        self.combo_mode.addItems(["배수", "금액"])
        self.input_val = QLineEdit()
        self.input_val.setPlaceholderText("숫자 입력")
        # [UX 신규] 콤마(,) 1000단위 자동 입력
        self.input_val.textChanged.connect(self.format_money)
        h_layout.addWidget(self.combo_mode)
        h_layout.addWidget(self.input_val)
        form_layout.addRow("💰 추가 매수 단위:", h_layout)
        
        self.combo_price_type = QComboBox()
        self.combo_price_type.addItems(["시장가", "현재가"])
        form_layout.addRow("🛒 매수 주문 방식:", self.combo_price_type)

        # --- [신규 v4.6.8] 키움 스타일 스탑로스 설정 ---
        line_top = QFrame()
        line_top.setFrameShape(QFrame.Shape.HLine)
        line_top.setStyleSheet("background-color: #444;")
        form_layout.addRow(line_top)

        # 1. 이익실현
        self.chk_tp = QCheckBox(" 이익실현")
        self.input_tp = QLineEdit()
        self.input_tp.setFixedWidth(80)
        self.input_tp.setPlaceholderText("5.0")
        h_tp = QHBoxLayout()
        h_tp.addWidget(self.chk_tp)
        h_tp.addStretch()
        h_tp.addWidget(self.input_tp)
        h_tp.addWidget(QLabel("%"))
        form_layout.addRow(h_tp)

        # 2. 이익보존 (트레일링)
        self.chk_preservation = QCheckBox(" 이익보존")
        self.input_p_trigger = QLineEdit()
        self.input_p_trigger.setFixedWidth(60)
        self.input_p_trigger.setPlaceholderText("3.0")
        self.input_p_limit = QLineEdit()
        self.input_p_limit.setFixedWidth(60)
        self.input_p_limit.setPlaceholderText("2.0")
        h_p = QHBoxLayout()
        h_p.addWidget(self.chk_preservation)
        h_p.addStretch()
        h_p.addWidget(self.input_p_trigger)
        h_p.addWidget(QLabel("% 도달 시"))
        h_p.addWidget(self.input_p_limit)
        h_p.addWidget(QLabel("% 매도"))
        form_layout.addRow(h_p)

        # 3. 손실제한
        self.chk_sl = QCheckBox(" 손실제한")
        self.input_sl = QLineEdit()
        self.input_sl.setFixedWidth(80)
        self.input_sl.setPlaceholderText("-2.0")
        h_sl = QHBoxLayout()
        h_sl.addWidget(self.chk_sl)
        h_sl.addStretch()
        h_sl.addWidget(self.input_sl)
        h_sl.addWidget(QLabel("%"))
        form_layout.addRow(h_sl)

        # [UX 신규] 양수/음수 기호 자동 보정
        self.input_tp.textChanged.connect(lambda t: self.format_percent(self.input_tp, t, is_profit=True))
        self.input_p_trigger.textChanged.connect(lambda t: self.format_percent(self.input_p_trigger, t, is_profit=True))
        self.input_p_limit.textChanged.connect(lambda t: self.format_percent(self.input_p_limit, t, is_profit=True))
        self.input_sl.textChanged.connect(lambda t: self.format_percent(self.input_sl, t, is_profit=False))
        
        # --- [신규 v4.6.6] 체결강도 및 호가잔량 조건 ---
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        line.setStyleSheet("background-color: #444;")
        form_layout.addRow(line)
        
        self.chk_power = QCheckBox(" 체결강도 필터 사용")
        self.input_power = QLineEdit()
        self.input_power.setFixedWidth(80)
        self.input_power.setPlaceholderText("120")
        h_power = QHBoxLayout()
        h_power.addWidget(self.chk_power)
        h_power.addStretch()
        h_power.addWidget(self.input_power)
        h_power.addWidget(QLabel("% 이상"))
        form_layout.addRow(h_power)

        self.chk_slope = QCheckBox(" 체결강도 강화(상승 추세) 시에만 매수")
        form_layout.addRow(self.chk_slope)

        self.chk_orderbook = QCheckBox(" 호가잔량비 역전 필터 사용")
        self.input_orderbook = QLineEdit()
        self.input_orderbook.setFixedWidth(80)
        self.input_orderbook.setPlaceholderText("2.0")
        h_ob = QHBoxLayout()
        h_ob.addWidget(self.chk_orderbook)
        h_ob.addStretch()
        h_ob.addWidget(self.input_orderbook)
        h_ob.addWidget(QLabel("배 이상"))
        form_layout.addRow(h_ob)
        
        lbl_info = QLabel("※ 매도잔량이 매수잔량보다 많아야 에너지가 응축됨")
        lbl_info.setStyleSheet("color: #888; font-size: 11px; font-weight: normal;")
        form_layout.addRow(lbl_info)
        # ----------------------------------------------
        
        layout.addLayout(form_layout)
        
        btn_layout = QHBoxLayout()
        self.btn_save = QPushButton("💾 설정 저장") # [수정] 클래스 변수로 전환
        self.btn_save.clicked.connect(self.apply_settings)
        btn_cancel = QPushButton("취소")
        btn_cancel.setObjectName("btn_cancel")
        btn_cancel.clicked.connect(self.reject)
        
        btn_layout.addStretch()
        btn_layout.addWidget(btn_cancel)
        btn_layout.addWidget(self.btn_save) # [수정] 클래스 변수
        layout.addLayout(btn_layout)
        
        # [신규] 부모 테마에 맞춰 초기 스타일 적용
        if parent:
            self.apply_theme(parent.ui_theme)
        self.load_settings()

    def apply_theme(self, theme):
        """[신규] 부모의 테마 상태에 맞춰 다이얼로그 스타일 갱신"""
        if theme == 'light':
            self.setStyleSheet("""
                QDialog { background-color: #f0f2f5; color: #212529; }
                QLabel { color: #212529; font-weight: bold; }
                QLineEdit, QComboBox { 
                    background-color: #ffffff; color: #212529; 
                    border: 1px solid #ced4da; border-radius: 4px; padding: 4px;
                }
                QCheckBox { color: #495057; font-weight: bold; }
                QPushButton { 
                    background-color: #dc3545; color: white; font-weight: bold;
                    border-radius: 6px; padding: 8px; font-size: 13px;
                }
                QPushButton:hover { background-color: #c82333; }
                QPushButton#btn_cancel { background-color: #adb5bd; color: #212529; }
                QPushButton#btn_cancel:hover { background-color: #9ea7af; }
                QFrame { background-color: #dee2e6; }
            """)
        else:
            self.setStyleSheet("""
                QDialog { background-color: #1e1e1e; color: #ffffff; }
                QLabel { color: #ffffff; font-weight: bold; }
                QLineEdit, QComboBox { 
                    background-color: #333333; color: #ffffff; 
                    border: 1px solid #555555; border-radius: 4px; padding: 4px;
                }
                QCheckBox { color: #aaa; font-weight: bold; }
                QPushButton { 
                    background-color: #dc3545; color: white; font-weight: bold;
                    border-radius: 6px; padding: 8px; font-size: 13px;
                }
                QPushButton:hover { background-color: #c82333; }
                QPushButton#btn_cancel { background-color: #6c757d; }
                QPushButton#btn_cancel:hover { background-color: #5a6268; }
                QFrame { background-color: #444; }
            """)

    # [UX 신규] 1000 단위 콤마 자동 입력
    def format_money(self):
        text = self.input_val.text().replace(',', '')
        if text.isdigit():
            self.input_val.blockSignals(True)
            self.input_val.setText(f"{int(text):,}")
            self.input_val.blockSignals(False)

    # [UX 신규] 소수점 정밀 입력 개선 (소수점 뒤 0이나 마침표 허용)
    def format_percent(self, widget, text, is_profit):
        if not text or text in ["-", "+", "."] or text.endswith("."): return
        try:
            val = float(text.replace('%', ''))
            # 소수점 첫째 자리까지만 표시하되, 사용자가 입력 중인 텍스트와 숫자가 같으면 setText 생략 (입력 방해 방지)
            new_text = str(round(abs(val), 1)) if is_profit else str(round(-abs(val), 1))
            
            # 입력값과 포맷팅값이 다를 때만 업데이트 (단, 소수점 입력 편의를 위해 소수점 포함 시 체크 강화)
            current_float = float(text)
            target_float = float(new_text)
            
            if current_float != target_float:
                widget.blockSignals(True)
                widget.setText(new_text)
                widget.blockSignals(False)
        except ValueError:
            pass

    def _read_json(self):
        try:
            with open(self.settings_file, 'r', encoding='utf-8') as f: return json.load(f)
        except: return {}

    def load_settings(self):
        root = getattr(self.parent(), 'settings', self._read_json()) if getattr(self.parent(), 'settings', None) else self._read_json()
        target = root
        
        # [신규] 생성 당시의 일회성 index가 아닌 부모의 현재 프로필 인덱스 참조
        current_profile = getattr(self.parent(), 'current_profile_idx', None)
        if current_profile is not None and 'profiles' in root:
             target = root['profiles'].get(str(current_profile), root)
             
        self.input_wait.setText(str(target.get('bultagi_wait_sec', 30)))
        
        mode = target.get('bultagi_mode', 'multiplier')
        self.combo_mode.setCurrentIndex(0 if mode == 'multiplier' else 1)
        self.input_val.setText(str(target.get('bultagi_val', '10')))
        
        ptype = target.get('bultagi_price_type', 'market')
        self.combo_price_type.setCurrentIndex(0 if ptype == 'market' else 1)
        
        # [신규 v4.6.8] 3단 스탑로스 로드
        self.chk_tp.setChecked(target.get('bultagi_tp_enabled', True))
        self.input_tp.setText(str(target.get('bultagi_tp', 5.0)))
        
        self.chk_preservation.setChecked(target.get('bultagi_preservation_enabled', False))
        self.input_p_trigger.setText(str(target.get('bultagi_preservation_trigger', 3.0)))
        self.input_p_limit.setText(str(target.get('bultagi_preservation_limit', 2.0)))
        
        self.chk_sl.setChecked(target.get('bultagi_sl_enabled', True))
        self.input_sl.setText(str(target.get('bultagi_sl', -2.0)))
        
        # [신규 v4.6.6]
        self.chk_power.setChecked(target.get('bultagi_power_enabled', False))
        self.input_power.setText(str(target.get('bultagi_power_val', 120)))
        self.chk_slope.setChecked(target.get('bultagi_slope_enabled', False))
        self.chk_orderbook.setChecked(target.get('bultagi_orderbook_enabled', False))
        self.input_orderbook.setText(str(target.get('bultagi_orderbook_val', 2.0)))

    def apply_settings(self):
        try:
            from PyQt6.QtWidgets import QMessageBox
            
            tp_en = self.chk_tp.isChecked()
            tp_val = float(self.input_tp.text() or 5.0)
            p_en = self.chk_preservation.isChecked()
            p_trigger = float(self.input_p_trigger.text() or 3.0)
            p_limit = float(self.input_p_limit.text() or 2.0)
            sl_en = self.chk_sl.isChecked()
            sl_val = float(self.input_sl.text() or -2.0)

            # --- [신규 v4.6.8] 입력 유효성 검사 ---
            if p_en:
                if p_limit >= p_trigger:
                    QMessageBox.warning(self, "설정 오류", "이익보존 매도선은 반드시 도달선보다 낮아야 합니다!\n(예: 4.0% 도달 시 3.0% 매도)")
                    return
                if tp_en and p_trigger >= tp_val:
                    QMessageBox.warning(self, "설정 오류", "이익보존 도달선은 이익실현 목표보다 낮아야 합니다!")
                    return
                if sl_en and sl_val >= p_limit:
                    QMessageBox.warning(self, "설정 오류", "손실제한선은 이익보존 매도선보다 낮아야 합니다!")
                    return

            val_text = self.input_val.text().replace(',', '')
            if not val_text: val_text = '10'
            
            root = self._read_json()
            updates = {
                'bultagi_wait_sec': int(self.input_wait.text() or 30),
                'bultagi_mode': 'multiplier' if self.combo_mode.currentIndex() == 0 else 'amount',
                'bultagi_val': val_text,
                'bultagi_price_type': 'market' if self.combo_price_type.currentIndex() == 0 else 'current',
                # [신규 v4.6.8] 3단 스탑로스 저장
                'bultagi_tp_enabled': tp_en,
                'bultagi_tp': tp_val,
                'bultagi_preservation_enabled': p_en,
                'bultagi_preservation_trigger': p_trigger,
                'bultagi_preservation_limit': p_limit,
                'bultagi_sl_enabled': sl_en,
                'bultagi_sl': sl_val,
                # [신규 v4.6.6]
                'bultagi_power_enabled': self.chk_power.isChecked(),
                'bultagi_power_val': int(self.input_power.text() or 120),
                'bultagi_slope_enabled': self.chk_slope.isChecked(),
                'bultagi_orderbook_enabled': self.chk_orderbook.isChecked(),
                'bultagi_orderbook_val': float(self.input_orderbook.text() or 2.0)
            }
            
            # Update root
            for k, v in updates.items(): root[k] = v
            # Update active profile
            current_profile = getattr(self.parent(), 'current_profile_idx', None)
            if current_profile is not None and 'profiles' in root and str(current_profile) in root['profiles']:
                for k, v in updates.items(): root['profiles'][str(current_profile)][k] = v
            else:
                # [안전장치] 만약 프로필 구조가 없거나 인덱스가 없다면 root 에 같이 업데이트
                for k, v in updates.items(): root[k] = v
            
            with open(self.settings_file, 'w', encoding='utf-8') as f:
                json.dump(root, f, ensure_ascii=False, indent=2)
            
            # Live hot-reload into check_n_sell
            p = self.parent()
            if hasattr(p, 'worker') and p.worker:
                p.worker.schedule_command('update_settings', updates, True)

            # [UX 신규] 저장 시 버튼 시각적 피드백 효과 연출 
            self.btn_save.setText("✅ 저장 완료")
            self.btn_save.setStyleSheet("background-color: #28a745; color: white;")
            QTimer.singleShot(1500, lambda: [
                self.btn_save.setText("💾 설정 저장"),
                self.btn_save.setStyleSheet("QPushButton { background-color: #dc3545; color: white; font-weight: bold; border-radius: 6px; padding: 8px; font-size: 13px; } QPushButton:hover { background-color: #c82333; }")
            ])
            
        except ValueError:
            QMessageBox.warning(self, "입력 오류", "숫자 형식으로 정확히 입력해주세요.")

            pass

# ---------------------------------------------------------------------------------------------------------
# ✅ 실시간 수익 그래프 위젯 (신규 v4.7)
# ---------------------------------------------------------------------------------------------------------
class ProfitGraphWidget(FigureCanvas):
    def __init__(self, parent=None, width=5, height=2, dpi=100):
        # 폰트 깨짐 방지 
        plt.rcParams['font.family'] = 'Malgun Gothic'
        plt.rcParams['axes.unicode_minus'] = False
        
        self.fig = Figure(figsize=(width, height), dpi=dpi)
        self.axes = self.fig.add_subplot(111)
        super().__init__(self.fig)
        self.setParent(parent)
        
        # 초기 그래프 설정
        self.update_theme('dark') # 기본 다크
        self.update_chart()

    def update_theme(self, theme):
        """테마에 따라 그래프 색상 변경"""
        is_dark = (theme == 'dark')
        bg_color = '#000000' if is_dark else '#ffffff'
        fg_color = '#e0e0e0' if is_dark else '#212529'
        grid_color = '#333333' if is_dark else '#e0e0e0'
        
        self.fig.patch.set_facecolor(bg_color)
        self.axes.set_facecolor(bg_color)
        
        self.axes.spines['bottom'].set_color(fg_color)
        self.axes.spines['top'].set_color(fg_color)
        self.axes.spines['left'].set_color(fg_color)
        self.axes.spines['right'].set_color(fg_color)
        
        self.axes.tick_params(axis='x', colors=fg_color, labelsize=8)
        self.axes.tick_params(axis='y', colors=fg_color, labelsize=8)
        self.axes.yaxis.label.set_color(fg_color)
        self.axes.xaxis.label.set_color(fg_color)
        self.axes.title.set_color(fg_color)
        
        self.axes.grid(True, color=grid_color, linestyle='--', alpha=0.5)
        self.line_color = '#00ffff' if is_dark else '#007bff' # 사이언 / 블루
        self.draw()

    def update_chart(self):
        """실시간 데이터로 차트 갱신 (시간축 및 금액 포맷 적용)"""
        if not hasattr(session_logger, 'pnl_history'):
            return

        self.axes.clear()
        raw_data = session_logger.pnl_history
        
        if not raw_data or len(raw_data) < 1:
            self.draw()
            return

        # 데이터 추출 및 시간 변환
        times = []
        pnls = []
        today_str = datetime.datetime.now().strftime("%Y%m%d")
        
        for item in raw_data:
            if isinstance(item, dict):
                t_str = item.get('time', '09:00:00')
                try:
                    ts = datetime.datetime.strptime(f"{today_str} {t_str}", "%Y%m%d %H:%M:%S")
                except:
                    ts = datetime.datetime.now()
                times.append(ts)
                pnls.append(item.get('pnl', 0))
        
        if not times:
            self.draw()
            return

        # 선 및 마커 그리기 (리포트와 유사한 스타일)
        self.axes.plot(times, pnls, color=self.line_color, linewidth=2.5, marker='o', markersize=4, linestyle='-')
        
        # 제로 라인 (빨간 점선)
        self.axes.axhline(y=0, color='#ff4757', linestyle='--', linewidth=1, alpha=0.8)
        
        # X축 시간 포맷 설정 (mdates) - 리포트 일치화
        import matplotlib.dates as mdates
        self.axes.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
        
        # Y축 금액 포맷 설정 (천 단위 콤마)
        self.axes.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, loc: "{:,}".format(int(x))))
        
        # 여백 및 제목 설정
        self.axes.set_title("실시간 수익 현황 (P&L Trend)", fontsize=10, fontweight='bold', pad=10)
        self.fig.autofmt_xdate(rotation=0)
        self.fig.tight_layout()
        self.draw()

# ---------------------------------------------------------------------------------------------------------
# ✅ 더블 클릭 지원 그룹 박스 (불타기 모드 온/오프 토글용)
# ---------------------------------------------------------------------------------------------------------
class DoubleClickGroupBox(QGroupBox):
    doubleClicked = pyqtSignal()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.doubleClicked.emit()
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)

# ----------------- Main Window -----------------
class KipoWindow(QMainWindow):
    async def wait_for_ready(self):
        """Worker가 준비(chat_command 객체 생성)될 때까지 대기"""
        while not self.worker.chat_command:
            await asyncio.sleep(0.1)

    def log_and_tel(self, msg, *args, **kwargs):
        """GUI 로그와 텔레그램 모두에 전송 (중요 이벤트용)"""
        self.append_log(msg)
        real_tel_send(msg, *args, **kwargs)

    def __init__(self):
        super().__init__()
        # [최우선] 로그 및 상태 변수 초기화 (UI/Worker 호출 전 반드시 선행되어야 함)
        self.last_log_message = None
        self.log_buffer = [] 
        self.current_profile_idx = "M"
        self.is_save_mode = False
        self.is_blink_on = False
        self.is_profile_blink_on = False
        self.is_seq_blink_on = False
        self.alarm_playing = False
        self.last_alarm_time = None
        self.app_start_time = datetime.datetime.now()
        self.last_auto_start_time = None
        self.marked_states = [False] * 10
        self.active_alert = None
        self.last_buy_time = None # [신규 v4.7.3] 최근 매수 시간 기록
        
        # [최우선] 타이머 전체 초기화 (AttributeError 원천 차단)
        self.alarm_timer = QTimer(self)
        self.alarm_timer.setInterval(1000)
        self.alarm_timer.timeout.connect(self.check_alarm)
        
        self.blink_timer = QTimer(self)
        self.blink_timer.setInterval(500)
        self.blink_timer.timeout.connect(self.toggle_blink)
        
        self.profile_blink_timer = QTimer(self)
        self.profile_blink_timer.setInterval(400)
        self.profile_blink_timer.timeout.connect(self.toggle_profile_blink)
        
        self.trade_timer = QTimer(self)
        self.trade_timer.setInterval(1000)
        self.trade_timer.timeout.connect(self.update_trade_timer)
        self.trade_timer_seconds = 0
        self.original_timer_text = "01:00"
        
        self.alert_close_timer = QTimer(self)
        self.alert_close_timer.setSingleShot(True)
        self.alert_close_timer.timeout.connect(self._close_active_alert)
        
        self.seq_blink_timer = QTimer(self)
        self.seq_blink_timer.setInterval(1000)
        self.seq_blink_timer.timeout.connect(self.blink_seq_button)

        self.bultagi_dialog = None # [신규] 모달리스 인스턴스 유지 변수

        self.setWindowTitle("KipoStock v4.7.3 - AI Auto Trading (Diamond Edition)")
        
        # 파일 경로 설정
        if getattr(sys, 'frozen', False):
            self.script_dir = os.path.dirname(sys.executable)
            self.resource_dir = sys._MEIPASS
        else:
            self.script_dir = os.path.dirname(os.path.abspath(__file__))
            self.resource_dir = self.script_dir
            
        self.data_dir = os.path.join(self.script_dir, 'LogData')
        if not os.path.exists(self.data_dir):
            try: os.makedirs(self.data_dir)
            except: pass
            
        self.settings_file = os.path.join(self.script_dir, 'settings.json')
        
        # [신규] 테마 설정 실시간 로드
        self.ui_theme = get_setting('ui_theme', 'dark')
        
        # 중복 로그 파일 정리
        try:
            today_str = datetime.datetime.now().strftime("%Y%m%d")
            redundant_log = os.path.join(self.data_dir, f"Log_{today_str}.txt")
            if os.path.exists(redundant_log):
                os.remove(redundant_log)
        except: pass

        # 아이콘 설정
        icon_path = os.path.join(self.resource_dir, 'kipo_yellow.png')
        icon_path_ico = os.path.join(self.resource_dir, 'kipo_yellow.ico')
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        elif os.path.exists(icon_path_ico):
            self.setWindowIcon(QIcon(icon_path_ico))
        
        self.resize(1000, 700)
        
        # UI 및 Worker 시작 (이제 타이머들이 모두 준비됨)
        self.setup_ui()
        self.setup_worker()
        
        # 타이머 구동
        self.alarm_timer.start()

        # [수정] 프로그램 로딩 후 'M' 버튼 클릭 효과 (정확히 식별자 전달)
        QTimer.singleShot(1000, lambda: self.on_profile_clicked("M"))
        


    # [신규] 툴팁 스타일 통일용 헬퍼 메서드
    def _style_tooltip(self, text):
        """툴팁 텍스트에 HTML 스타일을 적용하여 폰트와 크기를 강제합니다."""
        # 밝은 회색(#f8f9fa) 텍스트로 변경하여 대비를 높임
        return f"<html><head/><body><p style='font-family:\"Malgun Gothic\"; font-size:9pt; color:#f8f9fa; margin:0;'>{text.replace(chr(10), '<br>')}</p></body></html>"

    # -----------------------------------------------------------------------------------------------------
    # 이벤트 핸들러 모음
    # -----------------------------------------------------------------------------------------------------
    
    # [신규] 불타기 상세 다이얼로그 호출 (Modeless)
    def open_bultagi_dialog(self):
        if self.bultagi_dialog is None:
            self.bultagi_dialog = BultagiSettingsDialog(self)
        self.bultagi_dialog.load_settings() # 창 열 때 최신 상태 갱신
        self.bultagi_dialog.show()
        self.bultagi_dialog.raise_()
        self.bultagi_dialog.activateWindow()

    def on_bultagi_toggled(self, checked):
        if hasattr(self, 'worker') and self.worker:
            self.worker.schedule_command('update_settings', {'bultagi_enabled': checked}, True)
        self.append_log(f"🔥 불타기 감시 모드가 {'[활성화]' if checked else '[비활성화]'} 되었습니다.")
        self.update_bultagi_group_style(checked)

    # [신규] 더블 클릭 시 상태 반전 및 저장 처리
    def toggle_bultagi_enabled(self):
        try:
            with open(self.settings_file, 'r', encoding='utf-8') as f:
                root = json.load(f)
        except Exception:
            root = {}
            
        target = root
        if self.current_profile_idx is not None and 'profiles' in root:
            if str(self.current_profile_idx) not in root['profiles']:
                root['profiles'][str(self.current_profile_idx)] = {}
            target = root['profiles'][str(self.current_profile_idx)]
            
        current_state = target.get('bultagi_enabled', True)
        new_state = not current_state
        target['bultagi_enabled'] = new_state
        
        with open(self.settings_file, 'w', encoding='utf-8') as f:
            json.dump(root, f, ensure_ascii=False, indent=2)
            
        self.on_bultagi_toggled(new_state)

    def update_bultagi_group_style(self, checked):
        # [신규] 켜졌을 때만 테두리 붉게, 꺼지면 일반 그룹박스 스타일로 원복
        is_light = getattr(self, 'ui_theme', 'dark') == 'light'
        border_color = "#dc3545" if checked else ("#dcdcdc" if is_light else "#555555")
        text_color = "#dc3545" if checked else ("#333333" if is_light else "#888888")
        
        self.bultagi_group.setStyleSheet(f"""
            QGroupBox::title {{
                subcontrol-origin: margin;
                subcontrol-position: top center;
                padding: 0 5px;
                color: {text_color};
            }}
            QGroupBox {{
                border: 2px solid {border_color};
                margin-top: 10px;
                border-radius: 5px;
            }}
        """)
    def get_theme_stylesheet(self, theme_mode):
        if theme_mode == 'light':
            return """
            QMainWindow { background-color: #f0f2f5; }
            QGroupBox { 
                font-weight: bold; 
                border: 2px solid #ced4da; 
                border-radius: 12px; 
                margin-top: 15px; 
                padding-top: 20px; 
                background-color: #ffffff; 
            }
            QGroupBox::title {
                color: #495057;
                background-color: #f8f9fa;
                border: 1px solid #ced4da;
                border-radius: 6px;
                padding: 2px 8px;
                subcontrol-origin: margin;
                subcontrol-position: top left;
                left: 10px;
                top: 0px;
            }
            QLabel { color: #212529; }
            QCheckBox { color: #495057; font-weight: bold; }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
                border: 2px solid #adb5bd;
                border-radius: 4px;
                background: #f8f9fa;
            }
            QCheckBox::indicator:checked {
                background: #f1c40f;
                border: 2px solid #f1c40f;
            }
            
            QPushButton { 
                padding: 8px 15px; 
                border-radius: 8px; 
                font-weight: bold; 
                color: #212529; 
                border: 1px solid #ced4da;
                background-color: #e9ecef;
            }
            QPushButton:hover { background-color: #dee2e6; }
            
            QMessageBox {
                background-color: #ffffff;
                color: #212529;
            }
            QMessageBox QLabel { color: #212529; }
            QMessageBox QPushButton {
                background-color: #f8f9fa;
                color: #212529;
                border: 1px solid #ced4da;
                min-width: 80px;
                padding: 5px;
            }
            
            QTextEdit { 
                background-color: #ffffff; 
                color: #212529; 
                font-family: 'Consolas', 'Courier New'; 
                font-size: 13px;
                border: 1px solid #ced4da;
                border-radius: 10px; 
                padding: 10px; 
            }
            
            QToolTip { 
                background-color: #333333; 
                color: #ffffff;
                border: 2px solid #f1c40f; 
                padding: 6px; 
                border-radius: 6px;
                font-family: 'Malgun Gothic';
                font-size: 13px;
            }
            QGroupBox#settings_group { 
                background-color: #ffffff; 
                border: 2px solid #dc3545; 
                border-radius: 12px; 
                margin-top: 10px; 
                padding-top: 8px; 
            }
            QGroupBox#settings_group::title { font-size: 15px; font-weight: bold; color: #dc3545; subcontrol-origin: margin; subcontrol-position: top center; left: 0px; top: 0px; padding: 0 8px; }
            
            QGroupBox#strategy_group { background-color: #ffffff; border: 2px solid #27ae60; border-radius: 12px; margin-top: 10px; padding-top: 15px; }
            QGroupBox#strategy_group::title { color: #27ae60; font-size: 13px; font-weight: bold; subcontrol-origin: margin; subcontrol-position: top center; left: 0px; top: 0px; padding: 0 8px; }
            
            QGroupBox#profile_group { background-color: #f8f9fa; border: 2px solid #2980b9; border-radius: 12px; margin-top: 10px; padding-top: 8px; }
            QGroupBox#profile_group::title { color: #3498db; font-size: 13px; font-weight: bold; subcontrol-origin: margin; subcontrol-position: top center; left: 0px; top: 0px; padding: 0 8px; }
            
            QGroupBox#rt_group { background-color: #f8f9fa; border: 2px solid #e67e22; border-radius: 12px; margin-top: 10px; padding-top: 8px; }
            QGroupBox#rt_group::title { color: #e67e22; font-size: 13px; font-weight: bold; subcontrol-origin: margin; subcontrol-position: top center; left: 0px; top: 0px; padding: 0 8px; }

            QGroupBox#bultagi_group { background-color: #ffffff; border: 2px solid #f1c40f; border-radius: 12px; margin-top: 10px; padding-top: 8px; }
            QGroupBox#bultagi_group::title { color: #f1c40f; font-size: 13px; font-weight: bold; subcontrol-origin: margin; subcontrol-position: top center; left: 0px; top: 0px; padding: 0 8px; }

            QPushButton#btn_top { background-color: #f8f9fa; border-radius: 5px; font-size: 18px; border: 1px solid #ddd; color: #aaa; text-align: center; padding: 0px; }
            QPushButton#btn_top:checked { background-color: #17a2b8; color: white; border: 1px solid #138496; }
            QPushButton#btn_top:hover { background-color: #e2e6ea; }

            QLineEdit#input_max { border: 2px solid #adb5bd; border-radius: 6px; padding: 2px; font-weight: bold; color: #212529; background-color: #f8f9fa; }
            QLineEdit#input_start_time { border: 1px solid #ced4da; border-radius: 4px; font-weight: bold; font-size: 14px; padding: 1px; color: #212529; background-color: #ffffff; }
            QLineEdit#input_end_time { border: 1px solid #ced4da; border-radius: 4px; font-weight: bold; font-size: 14px; padding: 1px; color: #212529; background-color: #ffffff; }
            QLineEdit#input_cmd { background-color: #ffffff; color: #212529; border: 1px solid #ced4da; border-radius: 15px; padding-left: 15px; font-size: 12px; }
            
            QLineEdit#input_qty_val { background-color: #ffffff; border: 2px solid #e74c3c; border-radius: 6px; padding: 2px; font-weight: bold; font-size: 15px; color: #e74c3c; }
            QLineEdit#input_amt_val { background-color: #ffffff; border: 2px solid #28a745; border-radius: 5px; padding: 2px; font-weight: bold; font-size: 15px; color: #dc3545; }
            QLineEdit#input_pct_val { background-color: #ffffff; border: 2px solid #007bff; border-radius: 5px; padding: 2px; font-weight: bold; font-size: 15px; color: #dc3545; }
            QLineEdit#input_hts_val { background-color: #e9ecef; border: 2px solid #fd7e14; border-radius: 5px; padding: 2px; font-weight: bold; font-size: 13px; color: #495057; }
            
            QLineEdit#input_bultagi_wait { background-color: #ffffff; border: 2px solid #f1c40f; border-radius: 6px; padding: 2px; font-weight: bold; font-size: 15px; color: #dc3545; }
            QLineEdit#input_bultagi_val { background-color: #ffffff; border: 2px solid #f1c40f; border-radius: 6px; padding: 2px; font-weight: bold; font-size: 15px; color: #dc3545; }
            
            QTextEdit#log_display { background-color: #1e1e1e; color: #00ff00; font-family: 'Consolas', 'Courier New'; font-size: 13px; border: 2px solid #adb5bd; border-radius: 10px; padding: 10px; }
            QTextEdit#rt_list { background-color: #f8f9fa; color: #333333; border: 1px solid #ced4da; border-radius: 4px; font-family: 'Malgun Gothic'; font-size: 12px; padding: 5px; }
            """
        else:
            return """
            QMainWindow { background-color: #121212; }
            QGroupBox { font-weight: bold; border: 2px solid #3d3d3d; border-radius: 12px; margin-top: 15px; padding-top: 20px; background-color: #1e1e1e; }
            QGroupBox::title { color: #f1c40f; background-color: #2c2c2c; border: 1px solid #f1c40f; border-radius: 6px; padding: 2px 8px; subcontrol-origin: margin; subcontrol-position: top left; left: 10px; top: 0px; }
            QLabel { color: #e0e0e0; }
            QCheckBox { color: #aaa; font-weight: bold; }
            QCheckBox::indicator { width: 16px; height: 16px; border: 2px solid #555; border-radius: 4px; background: #2a2a2a; }
            QCheckBox::indicator:checked { background: #f1c40f; border: 1px solid #f1c40f; }
            QPushButton { padding: 8px 15px; border-radius: 8px; font-weight: bold; color: white; border: none; background-color: #333333; }
            QPushButton:hover { background-color: #444444; }
            QMessageBox { background-color: #2a2a2a; color: #e0e0e0; }
            QMessageBox QLabel { color: #e0e0e0; }
            QMessageBox QPushButton { background-color: #34495e; color: white; border: 1px solid #2c3e50; min-width: 80px; padding: 5px; }
            QTextEdit { background-color: #000000; color: #00ff00; font-family: 'Consolas', 'Courier New'; font-size: 13px; border: 2px solid #333; border-radius: 10px; padding: 10px; }
            QToolTip { background-color: #2c3e50; color: #f8f9fa; border: 1px solid #f1c40f; padding: 5px; border-radius: 5px; font-family: 'Malgun Gothic'; }
            
            QGroupBox#settings_group { background-color: #1a1a1a; border: 2px solid #dc3545; border-radius: 12px; margin-top: 10px; padding-top: 8px; }
            QGroupBox#settings_group::title { font-size: 15px; font-weight: bold; color: #dc3545; subcontrol-origin: margin; subcontrol-position: top center; top: 0px; left: 0px; padding: 0 8px; }
            
            QGroupBox#strategy_group { background-color: #1a1a1a; border: 2px solid #27ae60; border-radius: 12px; margin-top: 10px; padding-top: 15px; font-weight: bold; }
            QGroupBox#strategy_group::title { color: #2ecc71; font-size: 13px; font-weight: bold; subcontrol-origin: margin; subcontrol-position: top center; top: 0px; left: 0px; padding: 0 8px; }
            
            QGroupBox#profile_group { background-color: #1a1a1a; border: 2px solid #2980b9; border-radius: 12px; margin-top: 10px; padding-top: 8px; }
            QGroupBox#profile_group::title { color: #3498db; font-size: 13px; font-weight: bold; subcontrol-origin: margin; subcontrol-position: top center; top: 0px; left: 0px; padding: 0 8px; }
            
            QGroupBox#rt_group { background-color: #1a1a1a; border: 2px solid #e67e22; border-radius: 12px; margin-top: 10px; padding-top: 8px; font-weight: bold; }
            QGroupBox#rt_group::title { color: #e67e22; font-size: 13px; font-weight: bold; subcontrol-origin: margin; subcontrol-position: top center; top: 0px; left: 0px; padding: 0 8px; }

            QGroupBox#bultagi_group { background-color: #1a1a1a; border: 2px solid #f1c40f; border-radius: 12px; margin-top: 10px; padding-top: 8px; }
            QGroupBox#bultagi_group::title { color: #f1c40f; font-size: 13px; font-weight: bold; subcontrol-origin: margin; subcontrol-position: top center; left: 0px; top: 0px; padding: 0 8px; }

            QPushButton#btn_top { background-color: #1a1a1a; border-radius: 5px; font-size: 18px; border: 1px solid #444; color: #888; text-align: center; padding: 0px; }
            QPushButton#btn_top:checked { background-color: #17a2b8; color: white; border: 1px solid #138496; }
            QPushButton#btn_top:hover { background-color: #333; }

            QLineEdit#input_max { border: 2px solid #f1c40f; border-radius: 6px; padding: 2px; font-weight: bold; color: #f1c40f; background-color: #000000; }
            QLineEdit#input_start_time { border: 1px solid #444; border-radius: 4px; font-weight: bold; font-size: 14px; padding: 1px; color: #ffffff; background-color: #1a1a1a; }
            QLineEdit#input_end_time { border: 1px solid #444; border-radius: 4px; font-weight: bold; font-size: 14px; padding: 1px; color: #ffffff; background-color: #1a1a1a; }
            QLineEdit#input_cmd { background-color: #000000; color: #f1c40f; border: 1px solid #444; border-radius: 15px; padding-left: 15px; font-size: 12px; }
            
            QLineEdit#input_qty_val { background-color: #000000; border: 2px solid #e74c3c; border-radius: 6px; padding: 2px; font-weight: bold; font-size: 15px; color: #e74c3c; }
            QLineEdit#input_amt_val { background-color: #000000; border: 2px solid #28a745; border-radius: 5px; padding: 2px; font-weight: bold; font-size: 15px; color: #e0e0e0; }
            QLineEdit#input_pct_val { background-color: #000000; border: 2px solid #007bff; border-radius: 5px; padding: 2px; font-weight: bold; font-size: 15px; color: #e0e0e0; }
            QLineEdit#input_hts_val { background-color: #2a2a2a; border: 2px solid #fd7e14; border-radius: 5px; padding: 2px; font-weight: bold; font-size: 13px; color: #aaa; }
            
            QLineEdit#input_bultagi_wait { background-color: #1a1a1a; border: 2px solid #f1c40f; border-radius: 6px; padding: 2px; font-weight: bold; font-size: 15px; color: #f1c40f; }
            QLineEdit#input_bultagi_val { background-color: #1a1a1a; border: 2px solid #f1c40f; border-radius: 6px; padding: 2px; font-weight: bold; font-size: 15px; color: #f1c40f; }
            
            QTextEdit#log_display { background-color: #000000; color: #00ff00; font-family: 'Consolas', 'Courier New'; font-size: 13px; border: 2px solid #333; border-radius: 10px; padding: 10px; }
            QTextEdit#rt_list { background-color: #000000; color: #ffffff; border: 1px solid #444; border-radius: 4px; font-family: 'Malgun Gothic'; font-size: 12px; padding: 5px; }
            """

    def toggle_theme(self):
        """[신규] 테마 변경 토글 메서드. JSON 저장 및 런타임 CSS 갱신"""
        self.ui_theme = 'light' if self.ui_theme == 'dark' else 'dark'
        self.btn_theme.setText("🌞" if self.ui_theme == 'light' else "🌙")
        
        try:
            import json
            s_data = {}
            if os.path.exists(self.settings_file):
                with open(self.settings_file, 'r', encoding='utf-8-sig') as f:
                    s_data = json.load(f)
            s_data['ui_theme'] = self.ui_theme
            with open(self.settings_file, 'w', encoding='utf-8') as f:
                json.dump(s_data, f, ensure_ascii=False, indent=4)
        except Exception as e:
            print(f"Theme save error: {e}")
            
        self.apply_theme()
        
        # [수정] load_settings_to_ui()를 부르면 입력값이 초기화되므로, 스타일만 개별적으로 갱신
        self.update_profile_buttons_ui()
        for i in range(10):
            self.update_button_style(i) # 조건식 버튼 스타일 갱신
        
        # 하단 컨트롤 버튼 스타일 갱신 (현재 상태 유지)
        current_status = "READY"
        status_text = self.lbl_status.text()
        if "RUNNING" in status_text: current_status = "RUNNING"
        elif "WAITING" in status_text: current_status = "WAITING"
        self.update_status_ui(current_status)

        for k in ['qty', 'amount', 'percent']:
            self.update_price_type_style(k)
            
        # [신규] 만약 불타기 설정창이 열려 있다면 테마 즉시 동기화
        if hasattr(self, 'bultagi_dialog') and self.bultagi_dialog and self.bultagi_dialog.isVisible():
            self.bultagi_dialog.apply_theme(self.ui_theme)
            
        # [신규 v4.7] 수익 그래프 테마 동기화
        if hasattr(self, 'profit_graph'):
            self.profit_graph.update_theme(self.ui_theme)

    def append_log(self, text):
        """로그 메시지를 QTextEdit에 추가하고 스크롤을 맨 아래로 내립니다."""
        current_time = datetime.datetime.now().strftime("[%H:%M:%S]")
        log_message = f"{current_time} {text}"
        self.log_display.append(log_message)
        self.log_display.verticalScrollBar().setValue(self.log_display.verticalScrollBar().maximum())

        # [v4.7] 실시간 그래프 갱신 트리거 (v4.7.2: '체결' 키워드 추가)
        if hasattr(self, 'profit_graph') and ("완료" in text or "체결" in text):
            self.profit_graph.update_chart()

        # [v4.7.3] 최근 매수 타이머 리셋 트리거
        if "매수체결" in text or "불타기" in text or "추가매수" in text:
            self.last_buy_time = datetime.datetime.now()
            if hasattr(self, 'lbl_last_buy_timer'):
                self.lbl_last_buy_timer.setText("경과: 00:00")
                self.lbl_last_buy_timer.setStyleSheet("color: #2ecc71; font-weight: bold;") # 리셋 시 초록색 강조

    def apply_theme(self):
        """현재 ui_theme 변수에 맞춰 QMainWindow 및 기본 색상을 적용합니다."""
        css = self.get_theme_stylesheet(self.ui_theme)
        self.setStyleSheet(css)

    def setup_ui(self):
        # --- Styles ---
        self.apply_theme() # 하드코딩된 스타일시트를 동적 메서드 호출로 교체

        # [신규] Voice 안내 기본값 보장 (사용자가 끈 적 없으면 켜기)
        if get_setting('voice_guidance', None) is None:
             # 설정 파일에 키 자체가 없으면 True로 초기화
             try:
                 import json
                 s_path = os.path.join(self.script_dir, 'settings.json')
                 s_data = {}
                 if os.path.exists(s_path):
                     with open(s_path, 'r', encoding='utf-8') as f: s_data = json.load(f)
                 
                 if 'voice_guidance' not in s_data:
                     s_data['voice_guidance'] = True
                     with open(s_path, 'w', encoding='utf-8') as f:
                         json.dump(s_data, f, ensure_ascii=False, indent=4)
             except Exception as e:
                 print(f"Error setting default voice_guidance: {e}") # 디버깅용
                 pass

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        # Root Layout: Vertical (Header + Body)
        root_layout = QVBoxLayout(central_widget)
        root_layout.setContentsMargins(10, 10, 10, 10)
        root_layout.setSpacing(10)

        # === 0. Global Header (Nested Layout for V2.1) ===
        header_widget = QWidget()
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(0, 0, 0, 10)
        
        # Left Spacer
        header_layout.addSpacing(40)
        header_layout.addStretch()
        
        # Center Vertical Container (Title / Info Bar)
        center_container = QWidget()
        center_vbox = QVBoxLayout(center_container)
        center_vbox.setContentsMargins(0, 0, 0, 0)
        center_vbox.setSpacing(5)
        
        self.lbl_main_title = QLabel("KipoStock v4.7.3 AI Auto Trading")
        self.lbl_main_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_main_title.setFont(QFont("Arial Black", 28, QFont.Weight.Bold))
        self.lbl_main_title.setStyleSheet("color: #f1c40f; letter-spacing: 2px;") # 골드 타이틀
        center_vbox.addWidget(self.lbl_main_title)
        
        # Info Bar (Timer + Status + Clock)
        info_bar = QHBoxLayout()
        info_bar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        info_bar.setSpacing(30)
        
        # [신규] 매매 타이머 섹션 (가장 왼쪽 - 심플 버전)
        timer_box = QHBoxLayout()
        timer_box.setSpacing(5)
        
        self.input_timer = QLineEdit("01:00")
        self.input_timer.setFixedWidth(65)
        self.input_timer.setFixedHeight(30) # 높이 미세 조정 (28->30) 글자 잘림 방지
        self.input_timer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.input_timer.setStyleSheet("""
            QLineEdit {
                background-color: #ecf0f1; /* 연회색 배경 */
                border: 2px solid #adb5bd;
                border-radius: 6px;
                font-weight: bold;
                font-size: 15px;
                color: #2c3e50;
            }
        """)
        
        self.btn_timer_toggle = QPushButton("▶")
        self.btn_timer_toggle.setFixedSize(28, 28)
        self.btn_timer_toggle.setToolTip(self._style_tooltip("⏳ [타이머 시작/중지]\n정해진 시간 다 되면 알람 울려요!"))
        self.btn_timer_toggle.setStyleSheet("""
            QPushButton {
                background-color: #007bff;
                color: white;
                border-radius: 14px;
                font-size: 11px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #0056b3; }
        """)
        self.btn_timer_toggle.clicked.connect(self.toggle_trade_timer)
        
        timer_box.addWidget(self.input_timer)
        timer_box.addWidget(self.btn_timer_toggle)

        # 상태 표시창 (중앙)
        self.lbl_status = QLabel("● READY")
        self.lbl_status.setFont(QFont("Arial", 22, QFont.Weight.Bold)) # 크기 2배 확대 (11 -> 22)
        self.lbl_status.setStyleSheet("color: #6c757d;")
        
        # 현재 시간 (오른쪽) - 아이콘 없이 더 심플하고 고급스럽게
        clock_layout = QHBoxLayout()
        clock_layout.setSpacing(10)
        
        self.lbl_clock = QLabel(datetime.datetime.now().strftime("%H:%M:%S"))
        self.lbl_clock.setFont(QFont("Arial", 22, QFont.Weight.Bold, True))
        self.lbl_clock.setStyleSheet("color: #007bff;")
        
        clock_layout.addWidget(self.lbl_clock)
        
        info_bar.addLayout(timer_box)
        info_bar.addWidget(self.lbl_status)
        info_bar.addLayout(clock_layout)
        
        center_vbox.addLayout(info_bar)
        header_layout.addWidget(center_container)
        
        header_layout.addStretch()
        
        # [신규] Theme Toggle Button (📌 앞 배치)
        self.btn_theme = QPushButton("🌞" if self.ui_theme == 'light' else "🌙")
        self.btn_theme.setFixedSize(40, 40)
        self.btn_theme.setToolTip(self._style_tooltip("💡 [테마 전환]\n클릭 시 다크 ↔ 라이트 모드 전환"))
        self.btn_theme.setStyleSheet("""
            QPushButton { 
                background-color: transparent; 
                font-size: 24px; 
                border: none; 
                padding: 0px; 
                text-align: center; 
            }
            QPushButton:hover { 
                background-color: rgba(128, 128, 128, 0.2); 
                border-radius: 20px; 
            }
        """)
        self.btn_theme.clicked.connect(self.toggle_theme)
        header_layout.addWidget(self.btn_theme)
        
        # Always on Top Button (Fixed to Right)
        self.btn_top = QPushButton("📌")
        self.btn_top.setObjectName("btn_top")
        self.btn_top.setCheckable(True)
        self.btn_top.setFixedSize(40, 40)
        self.btn_top.setToolTip(self._style_tooltip("📍 [핀 고정: 항상 위에]\n창을 맨 앞으로 고정"))
        self.btn_top.clicked.connect(self.toggle_always_on_top)
        
        header_layout.addWidget(self.btn_top)
        
        root_layout.addWidget(header_widget)

        # === Body Layout (Left + Right) ===
        body_layout = QHBoxLayout()
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(10)
        root_layout.addLayout(body_layout)

        # === Left Panel: Settings ===
        left_panel = QFrame()
        left_panel.setFixedWidth(240) # [수정] 너비 축소 (280 -> 240)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        
        # 1. Settings Group
        self.settings_group = QGroupBox("⚙️ Settings")
        self.settings_group.setObjectName("settings_group")
        
        settings_layout = QVBoxLayout()
        settings_layout.setSpacing(6) # 요소 간 간격 축소

        # Condition Select (0-19) & Max Stocks
        cond_row_layout = QHBoxLayout()
        # [수정] 라벨 볼드 처리
        cond_label = QLabel("<b>조건식 선택 (0-9)</b>")
        cond_row_layout.addWidget(cond_label)
        
        cond_row_layout.addStretch()
        
        # [이동] 종목수 (Max Stocks) / [수정] 라벨 볼드 처리
        cond_row_layout.addWidget(QLabel("<b>종목수</b>"))
        self.input_max = QLineEdit()
        self.input_max.setObjectName("input_max")
        self.input_max.setFixedWidth(40)
        self.input_max.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.input_max.setToolTip(self._style_tooltip("🎯 [최대 종목수]\n계좌 최대 보유 종목 개수를 정해요!"))
        cond_row_layout.addWidget(self.input_max)
        
        self.cond_btn_layout = QGridLayout() # [Lite V1.0] 10개 원형 레이아웃
        self.cond_btn_layout.setSpacing(8) # [수정] 가로/세로 간격 8px로 통일 (0-1 세로와 0-2 가로 일치)
        self.cond_buttons = []
        # State: 0 (Gray/Off), 1 (Red/Qty), 2 (Green/Amt), 3 (Blue/Pct)
        self.cond_states = [0] * 10
        
        for i in range(10):
            btn = QPushButton(str(i))
            # [Lite] 원형 버튼 디자인: 지름 36px, Border-radius 18px (완전한 원형)
            btn.setFixedSize(38, 38) 
            btn.setStyleSheet("""
                QPushButton {
                    background-color: #333; 
                    color: #bbb; 
                    font-weight: bold; 
                    border-radius: 19px; 
                    border: 1px solid #444;
                    font-size: 15px;
                }
                QPushButton:hover {
                    border: 1px solid #f1c40f;
                    color: #f1c40f;
                }
            """)
            btn.setToolTip(self._style_tooltip(f"🔍 [조건식 {i}번]\n클릭하여 전략 변경\n(우클릭 시 마킹/해제)"))
            btn.clicked.connect(lambda checked, idx=i: self.on_cond_clicked(idx))
            # [신규] 우클릭(컨텍스트 메뉴) 감지를 위한 정책 설정
            btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            btn.customContextMenuRequested.connect(lambda pos, idx=i: self.on_cond_right_clicked(idx))
            self.cond_buttons.append(btn)
            
            # [Lite] 배분: 상단(짝수: 0, 2, 4, 6, 8) / 하단(홀수: 1, 3, 5, 7, 9)
            if i % 2 == 0:
                row = 0
                col = i // 2
            else:
                row = 1
                col = i // 2
            self.cond_btn_layout.addWidget(btn, row, col)
        
        settings_layout.addLayout(cond_row_layout)
        settings_layout.addLayout(self.cond_btn_layout)


        # Time Settings (Horizontal)
        time_layout = QHBoxLayout()
        time_layout.setSpacing(2) # [유지] 레이블-입력창 밀착 (약 절반 거리)
        
        # 시작 (위치 원복: 앞 여백 제거)
        lbl_start = QLabel("시작")
        lbl_start.setFixedWidth(25)
        time_layout.addWidget(lbl_start)
        self.input_start_time = QLineEdit()
        self.input_start_time.setObjectName("input_start_time")
        self.input_start_time.setFixedWidth(50)
        self.input_start_time.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.input_start_time.setToolTip(self._style_tooltip("🕒 [시작 시간]\n이 시간이 되면 자동으로 매매가 뙇! 시작돼요!"))
        time_layout.addWidget(self.input_start_time)
        
        # [수정] 종료 레이블의 원래 위치 유지를 위해 중간 여백 대폭 확대 (12 -> 20)
        time_layout.addSpacing(20) 
        
        # 종료
        lbl_end = QLabel("종료")
        lbl_end.setFixedWidth(25)
        time_layout.addWidget(lbl_end)
        self.input_end_time = QLineEdit()
        self.input_end_time.setObjectName("input_end_time")
        self.input_end_time.setFixedWidth(50)
        self.input_end_time.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.input_end_time.setToolTip(self._style_tooltip("🕕 [종료 시간]\n이 시간이 되면 매매를 멈추거나 다음 프로필로 넘어가요!"))
        time_layout.addWidget(self.input_end_time)
        
        # 🔔 알람 해제 버튼 (종 모양 복원)
        self.btn_alarm_stop = QPushButton("🔕")
        self.btn_alarm_stop.setFixedWidth(30) # 너비 축소
        self.btn_alarm_stop.setFixedHeight(30) # 높이 확보 (찌그러짐 방지)
        self.btn_alarm_stop.clicked.connect(self.stop_alarm)
        self.btn_alarm_stop.setEnabled(False)
        self.btn_alarm_stop.setStyleSheet("""
            QPushButton {
                background-color: #f8f9fa;
                border: 1px solid #ddd;
                border-radius: 4px;
                font-size: 14px; /* 폰트 살짝 축소하여 여유 확보 */
                color: #aaa;
                padding: 0px; 
            }
            QPushButton:enabled {
                background-color: #ffc107; /* 종 모양이 울릴 때는 노란색 */
                color: #000;
                border: 1px solid #e0a800;
            }
        """)
        time_layout.addSpacing(10)
        time_layout.addWidget(self.btn_alarm_stop)
        time_layout.addStretch()
        settings_layout.addLayout(time_layout)

        # 💎 Buying Strategy Group (Revised for Color Matching)
        self.strategy_group = QGroupBox("💎 매수 전략 (Buying Strategy)")
        self.strategy_group.setObjectName("strategy_group")
        
        strat_vbox = QVBoxLayout()
        strat_vbox.setContentsMargins(5, 0, 5, 2) # 상단 여백 0으로 밀착
        strat_vbox.setSpacing(2) # 줄 간격 콤팩트하게 최소화

        # Helper function to create TP/SL inputs
        def create_tpsl_inputs(color):
            tp = QLineEdit("12.0")
            tp.setFixedWidth(45) # [수정] 너비 확장 (35 -> 45)
            tp.setAlignment(Qt.AlignmentFlag.AlignCenter)
            # [수정] 폰트 크기 확대 (12px -> 15px) 및 패딩 조정
            tp.setStyleSheet(f"QLineEdit {{ border: 1px solid {color}; border-radius: 4px; font-weight: bold; font-size: 15px; color: #dc3545; padding: 1px; }}")
            tp.setToolTip(self._style_tooltip("📈 [익절 (%)]\n목표 수익률 달성 시 기분 좋게 매도!"))
            
            sl = QLineEdit("-1.2")
            sl.setFixedWidth(45) # [수정] 너비 확장 (35 -> 45)
            sl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            # [수정] 폰트 크기 확대 (12px -> 15px) 및 패딩 조정
            sl.setStyleSheet(f"QLineEdit {{ border: 1px solid {color}; border-radius: 4px; font-weight: bold; font-size: 15px; color: #007bff; padding: 1px; }}")
            sl.setToolTip(self._style_tooltip("📉 [손절 (%)]\n위험 감지! 손실 제한 도달 시 자동 매도!"))
            return tp, sl

        # Strategy UI Header (TP/SL labels)
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(5, 0, 0, 0)
        
        lbl_tp_hdr = QLabel("익절(%)")
        lbl_sl_hdr = QLabel("손절(%)")
        lbl_tp_hdr.setFixedWidth(45); lbl_sl_hdr.setFixedWidth(45)
        lbl_tp_hdr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_sl_hdr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_tp_hdr.setStyleSheet("color: #aaa; font-size: 11px; font-weight: bold;")
        lbl_sl_hdr.setStyleSheet("color: #aaa; font-size: 11px; font-weight: bold;")
        
        # [구조체 변경] 하단 입력창(qty_row 등)의 간격과 100% 동일한 텐션 로직 적용
        # 버튼칸(val, type), 빈 텐션(Stretch), 익절 박스, 손절 박스 순서
        header_layout.addStretch() # 입력창들의 addStretch()와 위아래 라인을 맞춤
        header_layout.addWidget(lbl_tp_hdr)
        # 하단 입력창 레이아웃은 AddWidget 사이에 추가 Spacing이 없으므로 여기도 제거 또는 최소 패턴 일치
        header_layout.addWidget(lbl_sl_hdr)

        strat_vbox.addLayout(header_layout)

        # 1. Qty Mode (Red)
        qty_vbox = QVBoxLayout()
        qty_vbox.setSpacing(2)
        lbl_qty = QLabel("🔴 1주 매수")
        lbl_qty.setStyleSheet("color: #dc3545; font-weight: bold; font-size: 13px;")
        
        qty_row = QHBoxLayout()
        self.input_qty_val = QLineEdit("1")
        self.input_qty_val.setObjectName("input_qty_val")
        self.input_qty_val.setReadOnly(True)
        self.input_qty_val.setFixedWidth(50) # [수정] 슬림화 (60 -> 50)
        self.input_qty_val.setToolTip(self._style_tooltip("🔴 [1주 매수]\n조건 만족 시 1주 주문"))
        
        self.btn_qty_type = QPushButton("시")
        self.btn_qty_type.setCheckable(True)
        self.btn_qty_type.setFixedSize(26, 26) # 더 컴팩트한 원형 (28->26)
        self.btn_qty_type.clicked.connect(lambda: self.update_price_type_style('qty'))
        
        self.input_qty_tp, self.input_qty_sl = create_tpsl_inputs("#dc3545")
        self.input_qty_tp.setFixedWidth(45); self.input_qty_sl.setFixedWidth(45)
        
        qty_row.addWidget(self.input_qty_val)
        qty_row.addWidget(self.btn_qty_type)
        qty_row.addStretch()
        qty_row.addWidget(self.input_qty_tp)
        qty_row.addWidget(self.input_qty_sl)
        
        qty_vbox.addWidget(lbl_qty)
        qty_vbox.addLayout(qty_row)
        strat_vbox.addLayout(qty_vbox)

        # 2. Amount Mode (Green)
        amt_vbox = QVBoxLayout()
        amt_vbox.setSpacing(2)
        lbl_amt = QLabel("🟢 금액 매수")
        lbl_amt.setStyleSheet("color: #28a745; font-weight: bold; font-size: 13px;")
        
        amt_row = QHBoxLayout()
        self.input_amt_val = QLineEdit("100,000")
        self.input_amt_val.setObjectName("input_amt_val")
        self.input_amt_val.setFixedWidth(90)
        self.input_amt_val.setToolTip(self._style_tooltip("🟢 [금액 매수]\n설정된 든든한 금액만큼 주문해요 (예: 100만)"))
        self.input_amt_val.textEdited.connect(lambda: self.format_comma(self.input_amt_val))
        
        self.btn_amt_type = QPushButton("시")
        self.btn_amt_type.setCheckable(True)
        self.btn_amt_type.setFixedSize(26, 26) # 더 컴팩트한 원형
        self.btn_amt_type.clicked.connect(lambda: self.update_price_type_style('amount'))
        
        self.input_amt_tp, self.input_amt_sl = create_tpsl_inputs("#28a745")
        self.input_amt_tp.setFixedWidth(45); self.input_amt_sl.setFixedWidth(45)
        
        amt_row.addWidget(self.input_amt_val)
        amt_row.addWidget(self.btn_amt_type)
        amt_row.addStretch()
        amt_row.addWidget(self.input_amt_tp)
        amt_row.addWidget(self.input_amt_sl)
        
        amt_vbox.addWidget(lbl_amt)
        amt_vbox.addLayout(amt_row)
        strat_vbox.addLayout(amt_vbox)

        # 3. Percent Mode (Blue)
        pct_vbox = QVBoxLayout()
        pct_vbox.setSpacing(2)
        lbl_pct = QLabel("🔵 비율 매수")
        lbl_pct.setStyleSheet("color: #007bff; font-weight: bold; font-size: 13px;")
        
        pct_row = QHBoxLayout()
        self.input_pct_val = QLineEdit("10")
        self.input_pct_val.setObjectName("input_pct_val")
        self.input_pct_val.setFixedWidth(50) # [수정] 슬림화 (60 -> 50)
        self.input_pct_val.setToolTip(self._style_tooltip("🔵 [비율 매수]\n내 예수금 대비 % 비율로 유연하게 주문!"))
        
        self.btn_pct_type = QPushButton("시")
        self.btn_pct_type.setCheckable(True)
        self.btn_pct_type.setFixedSize(26, 26) # 더 컴팩트한 원형
        self.btn_pct_type.clicked.connect(lambda: self.update_price_type_style('percent'))
        
        self.input_pct_tp, self.input_pct_sl = create_tpsl_inputs("#007bff")
        self.input_pct_tp.setFixedWidth(45); self.input_pct_sl.setFixedWidth(45)
        
        pct_row.addWidget(self.input_pct_val)
        pct_row.addWidget(self.btn_pct_type)
        pct_row.addStretch()
        pct_row.addWidget(self.input_pct_tp)
        pct_row.addWidget(self.input_pct_sl)
        
        pct_vbox.addWidget(lbl_pct)
        pct_vbox.addLayout(pct_row)
        strat_vbox.addLayout(pct_vbox)

        # 4. HTS/Direct Mode (Orange)
        hts_vbox = QVBoxLayout()
        hts_vbox.setSpacing(2)
        lbl_hts = QLabel("🖐 직접/HTS 관리")
        lbl_hts.setStyleSheet("color: #fd7e14; font-weight: bold; font-size: 13px;")
        
        hts_row = QHBoxLayout()
        self.input_hts_val = QLineEdit("HTS")
        self.input_hts_val.setObjectName("input_hts_val")
        self.input_hts_val.setReadOnly(True)
        self.input_hts_val.setFixedWidth(60)
        self.input_hts_val.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.input_hts_val.setToolTip(self._style_tooltip("🖐 [직접/HTS 감시]\nHTS 등 밖에서 산 종목들도 똑똑하게 감시!"))
        
        self.input_hts_tp, self.input_hts_sl = create_tpsl_inputs("#fd7e14")
        self.input_hts_tp.setFixedWidth(45); self.input_hts_sl.setFixedWidth(45)
        
        hts_row.addWidget(self.input_hts_val)
        hts_row.addStretch()
        hts_row.addWidget(self.input_hts_tp)
        hts_row.addWidget(self.input_hts_sl)
        
        hts_vbox.addWidget(lbl_hts)
        hts_vbox.addLayout(hts_row)
        strat_vbox.addLayout(hts_vbox)

        self.strategy_group.setLayout(strat_vbox)
        settings_layout.addWidget(self.strategy_group)

        # 🔥 불타기(Fire-up) 설정 그룹
        self.bultagi_group = DoubleClickGroupBox("🔥 불타기(Fire-up) 설정")
        self.bultagi_group.setObjectName("bultagi_group")
        self.bultagi_group.doubleClicked.connect(self.toggle_bultagi_enabled)
        self.bultagi_group.setToolTip(self._style_tooltip("💡 [더블 클릭] 시 현재 프로필의 불타기 기능 활성/비활성화 전환"))

        bultagi_layout = QVBoxLayout()
        bultagi_layout.setContentsMargins(10, 20, 10, 15)
        
        # [신규] 독립 팝업 호출 버튼
        self.btn_bultagi_open = QPushButton("⚙️ 상세 설정 열기")
        self.btn_bultagi_open.setFont(QFont("Arial", 11, QFont.Weight.Bold))
        self.btn_bultagi_open.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_bultagi_open.setFixedHeight(45)
        self.btn_bultagi_open.clicked.connect(self.open_bultagi_dialog)
        
        self.btn_bultagi_open.setStyleSheet("""
            QPushButton {
                background-color: #dc3545; color: white;
                border: 2px solid #C82333; border-radius: 8px;
            }
            QPushButton:hover { background-color: #c82333; }
        """)
        
        bultagi_layout.addWidget(self.btn_bultagi_open)
        self.bultagi_group.setLayout(bultagi_layout)
        settings_layout.addWidget(self.bultagi_group)

        settings_layout.addStretch()
        self.settings_group.setLayout(settings_layout)
        self.settings_group.setContentsMargins(5, 5, 5, 5) # 여백 축소
        left_layout.addWidget(self.settings_group)

        # 3. Profile & Sequence & Control Group
        self.profile_group = QGroupBox("📌 Profile Sequence")
        self.profile_group.setObjectName("profile_group")
        
        profile_layout = QVBoxLayout()
        profile_layout.setContentsMargins(5, 5, 5, 5)
        profile_layout.setSpacing(4)

        # 상단 행: Profile Buttons + Save Button
        top_row = QHBoxLayout()
        top_row.setSpacing(4)
        
        self.profile_buttons = []
        profile_ids = ["M", "1", "2", "3", "4"]
        for pid in profile_ids:
            btn = QPushButton(pid)
            btn.setFixedSize(32, 32)
            btn.setCheckable(True)
            if pid == "M":
                btn.setToolTip(self._style_tooltip("<b>🎛️ [M: 수동 모드]</b><br>시작, 정지를 내 맘대로 자유롭게!"))
            else:
                btn.setToolTip(self._style_tooltip(f"<b>📑 [{pid}번 프로필]</b><br>저장해둔 {pid}번 설정을 짠! 불러와요."))
            btn.setStyleSheet("""
                QPushButton {
                    background-color: #333; 
                    color: #fff; 
                    font-weight: bold; 
                    border-radius: 4px; /* 사각 타이트 디자인 복구 */
                    border: 1px solid #2980b9;
                    font-size: 14px;
                    padding: 0px;
                }
                QPushButton:checked {
                    background-color: #3498db;
                    color: #fff;
                    border: 2px solid #fff;
                }
                QPushButton:hover {
                    background-color: #555;
                }
                QPushButton:disabled {
                    background-color: #222;
                    color: #555;
                }
            """)
            btn.clicked.connect(lambda checked, idx=pid: self.on_profile_clicked(idx))
            self.profile_buttons.append(btn)
            top_row.addWidget(btn)
        
        top_row.addStretch()
        
        # 설정 저장 버튼 (이전처럼 사각 모양으로 복구하여 프로파일 박스 내 배치)
        self.btn_save = QPushButton("💾")
        self.btn_save.setFixedSize(32, 32)
        self.btn_save.setToolTip(self._style_tooltip("💾 [프로필 저장]\n요 버튼 누르고, 깜빡이는 번호를 누르면 현재 설정 찰칵! 저장해!"))
        self.btn_save.setStyleSheet("""
            QPushButton { 
                background-color: #495057; 
                border-radius: 4px; 
                font-size: 16px; 
                border: 1px solid #6c757d; 
                color: white; 
                padding: 0px;
            }
            QPushButton:hover { background-color: #6c757d; }
        """)
        self.btn_save.clicked.connect(self.on_save_button_clicked)
        top_row.addWidget(self.btn_save)
        
        profile_layout.addLayout(top_row)
        
        # 하단 행: AUTO Toggle(확장형) + START(정사각형) + STOP(정사각형) (여백 8px)
        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(8) 
        
        self.btn_auto_seq = QPushButton("🔂")
        self.btn_auto_seq.setCheckable(True)
        self.btn_auto_seq.setToolTip(self._style_tooltip("🔂 [자동 프로필 전환]\n설정된 시간이 지나면 다음 번호로 자동 점프!"))
        # [수정] START, STOP(44px)과 높이를 맞춰 텍스트 변경 시 레이아웃 출렁임 방지 (Rev.12)
        self.btn_auto_seq.setFixedHeight(44)
        self.btn_auto_seq.setFont(QFont("Arial", 16, QFont.Weight.Bold)) 
        self.btn_auto_seq.setStyleSheet("""
            QPushButton {
                background-color: #AED9E0; /* 연한 파랑 (Light Blue) */
                color: #2c3e50;
                border-radius: 8px;
                border: 1px solid #95C3C9;
                text-align: center;
                font-size: 28px; /* [초정밀] 아이콘 크기 확대 */
                padding: 0px;
                margin: 0px; /* [신규] 여백 강제 초기화 (Rev.12.1 출렁임 방지) */
            }
            QPushButton:checked {
                background-color: #3498db;
                color: white;
                border: 2px solid #fff;
            }
        """)
        self.btn_auto_seq.toggled.connect(self.on_auto_seq_toggled)
        
        # AUTO 버튼을 왼쪽에 배치하고 남은 공간을 다 비우게(Stretch=1)
        bottom_row.addWidget(self.btn_auto_seq, stretch=1)
        
        # START / STOP 아이콘 (순수 기호 ▶, ■ 사용) - 프레임리스 디자인 개편 (Rev.10)
        self.btn_start = QPushButton("▶")
        self.btn_start.setFixedSize(44, 44) # [초정밀] 아이콘 확대에 따른 클릭 영역 확보
        self.btn_start.setToolTip(self._style_tooltip("▶ [시작]\n퀀트 로봇, 출격 준비 완료!"))
        self.btn_start.setStyleSheet("""
            QPushButton {
                background-color: transparent; /* [초정밀] 박스 제거 */
                color: #27ae60;
                border: none;
                font-size: 34px; /* [초정밀] 아이콘 대폭 확대 */
                font-weight: normal; /* 사각형 일그러짐 방지 */
                padding: 0px; padding-bottom: 3px; padding-left: 5px; margin: 0px; /* 초정밀 센터링 (Rev.13.3) */
            }
            QPushButton:hover { color: #2ecc71; }
            QPushButton:disabled { 
                background-color: transparent;
                color: #444; 
                font-size: 34px;
                padding: 0px; padding-bottom: 3px; padding-left: 5px; margin: 0px; /* 초정밀 센터링 (Rev.13.3) */
            }
        """)
        self.btn_start.clicked.connect(self.on_start_clicked)
        bottom_row.addWidget(self.btn_start)
        
        self.btn_stop = QPushButton("■")
        self.btn_stop.setFixedSize(44, 44)
        self.btn_stop.setToolTip(self._style_tooltip("■ [정지]\n일단 멈춤! 전략을 다시 점검해봐요."))
        self.btn_stop.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #c0392b;
                border: none;
                font-size: 30px; /* [초정밀] START(34px) 대비 2사이즈 축소 */
                font-weight: normal;
                padding: 0px; 
                padding-bottom: 4px; /* [초정밀] 4포인트 상단 이동 반영 (Rev.11.2) */
                margin: 0px;
            }
            QPushButton:hover { color: #e74c3c; }
            QPushButton:disabled { 
                background-color: transparent;
                color: #444; 
                font-size: 30px;
                padding-bottom: 4px;
            }
        """)
        self.btn_stop.clicked.connect(self.on_stop_clicked)
        
        bottom_row.addWidget(self.btn_stop)
        
        profile_layout.addLayout(bottom_row)
        self.profile_group.setLayout(profile_layout)
        left_layout.addWidget(self.profile_group)

        # 4. 실시간 조건식 (Real-time Condition List)
        self.rt_group = QGroupBox("📋 실시간 조건식")
        self.rt_group.setObjectName("rt_group")
        self.rt_group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        
        rt_layout = QVBoxLayout()
        rt_layout.setContentsMargins(5, 5, 5, 5)
        
        self.rt_list = QTextEdit()
        self.rt_list.setObjectName("rt_list")
        self.rt_list.setReadOnly(True)
        self.rt_list.setMinimumHeight(120) # 최소 높이만 지정하고 남은 공간 모두 활용
        rt_layout.addWidget(self.rt_list)
        
        self.rt_group.setLayout(rt_layout)
        left_layout.addWidget(self.rt_group)

        # 액션 버튼 완전히 삭제되었음 (여백 처리도 삭제하여 타이트하게)
        body_layout.addWidget(left_panel)

        # === Right Panel: Logs & Graph (v4.7 분할형) ===
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        
        # 1. 상단 타이틀 및 명령창
        log_header = QHBoxLayout()
        lbl_log = QLabel("📊 Analysis & Logs") 
        lbl_log.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        lbl_log.setStyleSheet("color: #f1c40f;")
        log_header.addWidget(lbl_log)

        # [신규 v4.7.3] 최근 매수 후 경과 시간 타이머 레이블
        self.lbl_last_buy_timer = QLabel("구매 대기")
        self.lbl_last_buy_timer.setFont(QFont("Consolas", 10))
        self.lbl_last_buy_timer.setStyleSheet("color: #95a5a6; margin-left: 10px;")
        log_header.addWidget(self.lbl_last_buy_timer)

        log_header.addStretch()
        
        self.input_cmd = QLineEdit()
        self.input_cmd.setObjectName("input_cmd")
        self.input_cmd.setPlaceholderText("명령어를 입력하세요...")
        self.input_cmd.setFixedWidth(250)
        self.input_cmd.returnPressed.connect(self.send_custom_command)
        log_header.addWidget(self.input_cmd)
        
        right_layout.addLayout(log_header)
        
        # 2. QSplitter를 이용한 상단 그래프 / 하단 로그 분할
        self.log_splitter = QSplitter(Qt.Orientation.Vertical)
        
        # [NEW] 실시간 수익 그래프 위젯
        self.profit_graph = ProfitGraphWidget(self)
        self.log_splitter.addWidget(self.profit_graph)
        
        # [기존] 로그 화면
        self.log_display = ZoomableTextEdit()
        self.log_display.setObjectName("log_display")
        self.log_display.setReadOnly(True)
        self.log_display.setFont(QFont("Consolas", 11))
        self.log_splitter.addWidget(self.log_display)
        
        # 초기 비율 설정 (그래프 3: 로그 7)
        self.log_splitter.setStretchFactor(0, 3)
        self.log_splitter.setStretchFactor(1, 7)
        self.log_splitter.setSizes([200, 400])
        
        right_layout.addWidget(self.log_splitter)

        # [신규] 누락된 rt_list 위젯 추가 (활성 조건식 목록 표시용) - 이제 좌측 패널에 추가됨
        # AttributeError 방지를 위해 UI 내부적으로만 존재하도록 설정 (또는 필요 시 레이아웃에 배치)
        # self.rt_list = QTextEdit()
        # self.rt_list.setVisible(False) # 우선 보이지 않게 설정하여 레이아웃 영향 최소화
        
        body_layout.addWidget(right_panel)

    def setup_worker(self):
        self.worker = AsyncWorker(self)
        self.worker.signals.log_signal.connect(self.append_log)
        self.worker.signals.status_signal.connect(self.update_status_ui)
        self.worker.signals.clr_signal.connect(self.log_display.clear)
        self.worker.signals.request_log_signal.connect(self.save_logs_to_file)
        self.worker.signals.auto_seq_signal.connect(self.on_remote_auto_sequence)
        self.worker.signals.condition_loaded_signal.connect(self.refresh_condition_list_ui)
        self.worker.signals.graph_update_signal.connect(self.profit_graph.update_chart) # [신규] 그래프 업데이트 연동
        self.worker.start()

    def animate_button_click(self, btn):
        """버튼 클릭 시 색상 반전 애니메이션 효과 (아이콘 찌그러짐 방지)"""
        original_style = btn.styleSheet()
        
        # [효과] 본래의 레이아웃(min/max/padding)을 해치지 않으면서 배경과 보더만 잠시 변경
        # styleSheet()에 이미 들어있는 폰트 크기나 패딩을 유지하기 위해 '전체 덮어쓰기'가 아닌 '추가/변경' 방식으로 접근이 이상적이나,
        # 단순화를 위해 스타일을 임시로 주되, 색상 위주로만 변경함.
        # [수정] 찌그러짐의 주범인 min-height/max-height 강제 설정을 제거하고 투명도/색상 위주로 피드백
        btn.setStyleSheet(original_style + "background-color: #555; color: white; border: 2px solid #fff;")
        QTimer.singleShot(150, lambda: btn.setStyleSheet(original_style))

    def on_start_clicked(self, force=False, manual=None):
        # [신규] 버튼 애니메이션 및 중복 방지
        self.animate_button_click(self.btn_start)
        
        # [수정] force가 True이면 버튼 상태와 관계없이 진행 (시퀀스 전환용)
        # force는 이제 '수동 강제 시작(manual)'의 의미도 포함함
        # manual 인자가 명시적으로 전달되면 그 값을 따르고, 없으면 버튼 클릭으로 간주하여 True(수동) 처리
        if manual is None:
            manual_override = True # 기본값: 직접 클릭은 수동 모드 (설정 시간 무시하고 즉시 시작)
        else:
            manual_override = manual

        if not force and not self.btn_start.isEnabled(): return
        self.btn_start.setEnabled(False) # 즉시 비활성화하여 중복 클릭 방지

        # 1. UI의 현재 모든 설정을 기본(root) 설정에 동기화
        try:
            # [수정] restart_if_running=False로 설정하여 on_start_clicked 내부에서의 무한 루프/중복 실행 방지
            self.save_settings(restart_if_running=False) 
            
            # [수정] 로그 순서 조정 (엔진 시작 이후에 나오도록 정보를 전달)
            target_profile = f"{self.current_profile_idx}번 프로필" if self.current_profile_idx else "기본 설정"
            
        except Exception as e:
            self.append_log(f"⚠️ 설정 동기화 실패: {e}")
            target_profile = None
            self.btn_start.setEnabled(True) # 실패 시 다시 활성화
            
        # 2. 시작 명령 전달 (target_profile, manual_override 전달)
        # [수정] START 버튼을 통한 직접 클릭은 manual=True이지만, 오토 시퀀스는 manual=False로 전달됨
        QTimer.singleShot(500, lambda: self.worker.schedule_command('start', target_profile, manual_override))

    def on_stop_clicked(self):
        """STOP 버튼 클릭 핸들러 (메서드로 분리)"""
        self.animate_button_click(self.btn_stop)
        self.worker.schedule_command('stop')
        
        # [신규] 공용 STOP: 시퀀스 자동 모드도 함께 종료
        if self.btn_auto_seq.isChecked():
           self.btn_auto_seq.setChecked(False)
           self.on_auto_seq_toggled() # 타이머 정지 및 로그 출력
           
        # [신규] 중지 시 UI 잠금 공식 다시 계산 (READY 상태가 될 것이므로)
        QTimer.singleShot(500, lambda: self.lock_ui_for_sequence(self.btn_auto_seq.isChecked()))

        self.worker.signals.log_signal.connect(self.append_log)
        self.worker.signals.status_signal.connect(self.update_status_ui)
        self.worker.signals.clr_signal.connect(self.log_display.clear)
        self.worker.signals.request_log_signal.connect(self.save_logs_to_file)
        self.worker.signals.auto_seq_signal.connect(self.on_remote_auto_sequence)
        self.worker.signals.condition_loaded_signal.connect(self.refresh_condition_list_ui)
        self.worker.signals.graph_update_signal.connect(self.profit_graph.update_chart) # [신규] 그래프 업데이트 연동
        self.worker.start()

    def on_remote_auto_sequence(self, idx):
        """원격 명령어(auto) 수신 시 특정 프로필부터 시퀀스 시작 또는 중지"""
        # [수정] 끄는 명령(idx=0)인 경우는 매매 중이라도 허용
        if idx == 0:
            self.append_log("🤖 원격 명령어 수신: 시퀀스 자동 모드를 중지합니다.")
            if self.btn_auto_seq.isChecked():
                self.btn_auto_seq.setChecked(False)
                self.on_auto_seq_toggled()
            return

        # [신규] 매매 진행 중(RUNNING)일 때 켜는 명령(idx>=1)은 거부
        current_status = self.lbl_status.text()
        if "RUNNING" in current_status:
            self.log_and_tel("⚠️ 매매 진행 중(RUNNING)에는 자동 시퀀스를 시작할 수 없습니다. 중지(STOP) 후 다시 시도하세요.")
            return

        if not (1 <= idx <= 4):
            self.append_log(f"⚠️ 올바르지 않은 프로필 번호입니다: {idx}")
            return

        self.append_log(f"🤖 원격 명령어 수신: {idx}번 프로필부터 시퀀스를 시작합니다.")
        # [수정] 버튼 상태를 먼저 변경하고 토글 이벤트를 발생시켜야 on_profile_clicked에서 자동 시작이 작동함
        if not self.btn_auto_seq.isChecked():
            self.btn_auto_seq.setChecked(True)
            self.on_auto_seq_toggled()
            
        self.on_profile_clicked(idx)

    def on_cond_right_clicked(self, idx):
        """조건식 버튼 우클릭 시 마킹 토글"""
        self.marked_states[idx] = not self.marked_states[idx]
        self.update_button_style(idx)
        # status = "마킹됨" if self.marked_states[idx] else "해제됨"
        
        # [신규] 엔진에 마킹 상태 동기화 요청
        marked = [i for i, m in enumerate(self.marked_states) if m]
        self.worker.schedule_command('sync_marking', marked)

    def update_status_ui(self, status):
        """매매 상태에 따른 하단 컨트롤 버튼의 디자인 및 활성화 상태를 유동적으로 변경"""
        is_light = getattr(self, 'ui_theme', 'dark') == 'light'
        disabled_gray = "#adb5bd" if is_light else "#444"
        auto_disabled_bg = "#e9ecef" if is_light else "#333"
        auto_disabled_color = "#adb5bd" if is_light else "#aaa"
        auto_disabled_border = "#ced4da" if is_light else "#555"

        # [신규] 개별 위젯의 setStyleSheet가 전역 QToolTip 스타일을 덮어쓰지 않도록 명시적 추가
        tooltip_fix = ""
        if is_light:
            tooltip_fix = "QToolTip { background-color: #333333; color: #ffffff; border: 2px solid #f1c40f; padding: 6px; border-radius: 6px; font-family: 'Malgun Gothic'; font-size: 13px; }"
        
        # [신규] 개별 위젯의 setStyleSheet가 전역 QToolTip 스타일을 덮어쓰지 않도록 명시적 추가
        tooltip_fix = ""
        if is_light:
            tooltip_fix = "QToolTip { background-color: #333333; color: #ffffff; border: 2px solid #f1c40f; padding: 6px; border-radius: 6px; font-family: 'Malgun Gothic'; font-size: 13px; }"

        if status == "RUNNING":
            self.lbl_status.setText("● RUNNING")
            self.lbl_status.setStyleSheet("color: #28a745; margin-left: 10px;")
            
            # RUNNING: START 버튼 (프레임리스 비활성)
            self.btn_start.setText("▶")
            self.btn_start.setFixedSize(44, 44)
            self.btn_start.setEnabled(False)
            self.btn_start.setStyleSheet(f"""
                QPushButton {{
                    background-color: transparent;
                    color: {disabled_gray};
                    border: none;
                    font-size: 34px;
                    padding: 0px; padding-bottom: 3px; padding-left: 5px; margin: 0px;
                }}
            """)
            
            # RUNNING: AUTO 버튼에 상태 텍스트 추가
            if self.btn_auto_seq.isChecked():
                self.btn_auto_seq.setText("🔂 AUTO: ON")
                self.btn_auto_seq.setFont(QFont("Arial", 11, QFont.Weight.Bold))
                self.btn_auto_seq.setStyleSheet("""
                    QPushButton {
                        background-color: #3498db;
                        color: white;
                        border: 2px solid #fff;
                        border-radius: 8px;
                        font-size: 18px; /* [신규] 'AUTO: ON' 가로 팽창 방지를 위해 18px로 제한 */
                        padding: 0px; margin: 0px; /* [신규] 여백 강제 초기화 */
                    }
                """)
            else:
                self.btn_auto_seq.setText("🔂")
                self.btn_auto_seq.setFont(QFont("Arial", 28, QFont.Weight.Bold))
                self.btn_auto_seq.setStyleSheet("""
                    QPushButton {
                        background-color: #AED9E0;
                        color: #2c3e50;
                        border-radius: 8px;
                        border: 1px solid #95C3C9;
                        font-size: 28px;
                        padding: 0px; margin: 0px; /* [신규] 여백 강제 초기화 */
                    }
                """)
            
            # RUNNING: STOP 버튼 (프레임리스 활성 - 튜닝 반영)
            self.btn_stop.setText("■")
            self.btn_stop.setEnabled(True)
            self.btn_stop.setStyleSheet("""
                QPushButton {
                    background-color: transparent;
                    color: #e74c3c;
                    border: none;
                    font-size: 30px;
                    font-weight: normal;
                    padding: 0px;
                    padding-bottom: 4px;
                    margin: 0px;
                }
                QPushButton:hover { color: #c0392b; }
            """)

        elif status == "WAITING":
            self.lbl_status.setText("● WAITING")
            self.lbl_status.setStyleSheet("color: #ffc107; margin-left: 10px;")
            
            # WAITING: START 버튼 (활성)
            self.btn_start.setText("▶")
            self.btn_start.setEnabled(True) 
            self.btn_start.setStyleSheet("""
                QPushButton {
                    background-color: transparent;
                    color: #27ae60;
                    border: none;
                    padding: 0px; padding-bottom: 3px; padding-left: 5px; margin: 0px; /* 초정밀 위치 보정 */
                    font-size: 34px;
                    font-weight: normal;
                }
                QPushButton:hover { color: #2ecc71; }
            """)
            
            self.btn_auto_seq.setText("🔂")
            self.btn_auto_seq.setFont(QFont("Arial", 28, QFont.Weight.Bold))
            self.btn_auto_seq.setStyleSheet("""
                QPushButton {
                    background-color: #AED9E0;
                    color: #2c3e50;
                    border-radius: 8px;
                    border: 1px solid #95C3C9;
                    font-size: 28px;
                    padding: 0px; margin: 0px; /* [신규] 여백 강제 초기화 */
                }
            """)

            # WAITING: STOP 버튼 (활성 - 튜닝 반영)
            self.btn_stop.setText("■")
            self.btn_stop.setEnabled(True)
            self.btn_stop.setStyleSheet("""
                QPushButton {
                    background-color: transparent;
                    color: #e74c3c;
                    border: none;
                    font-size: 30px;
                    font-weight: normal;
                    padding: 0px;
                    padding-bottom: 4px;
                    margin: 0px;
                }
                QPushButton:hover { color: #c0392b; }
            """)

        elif status == "READY":
            self.lbl_status.setText("● READY")
            self.lbl_status.setStyleSheet("color: #6c757d; margin-left: 10px;")
            
            self.btn_start.setText("▶")
            # [버그 픽스] 기존 38x38로 강제 축소시키는 잘못된 코드 제거 (44x44 유지)
            
            self.btn_auto_seq.setText("🔂")
            self.btn_auto_seq.setFont(QFont("Arial", 28, QFont.Weight.Bold))
            
            # READY 상태: p_idx가 "M"이면 START 활성화
            p_idx = str(getattr(self, 'current_profile_idx', '')).strip().upper()
            if p_idx == "M":
                self.btn_start.setEnabled(True)
                self.btn_start.setStyleSheet("""
                    QPushButton {
                        background-color: transparent;
                        color: #27ae60;
                        border: none;
                        padding: 0px; padding-bottom: 3px; padding-left: 5px; margin: 0px; /* 초정밀 위치 보정 */
                        font-size: 34px;
                        font-weight: normal;
                    }
                    QPushButton:hover { color: #2ecc71; }
                """)
                self.btn_auto_seq.setEnabled(False)
                self.btn_auto_seq.setStyleSheet(f"""
                    QPushButton {{
                        background-color: {auto_disabled_bg};
                        color: {auto_disabled_color};
                        border-radius: 8px;
                        border: 1px solid {auto_disabled_border};
                        font-size: 28px;
                        padding: 0px; margin: 0px; /* [신규] 여백 강제 초기화 */
                    }}
                 """)
                # ... (생략)
            else:
                self.btn_start.setEnabled(False)
                self.btn_start.setStyleSheet(f"""
                    QPushButton {{
                        background-color: transparent;
                        color: {disabled_gray};
                        border: none;
                        font-size: 34px;
                        font-weight: normal;
                        padding: 0px; padding-bottom: 3px; padding-left: 5px; margin: 0px; /* 초정밀 위치 보정 */
                    }}
                """)
                self.btn_auto_seq.setEnabled(True)
                # ... (생략)

            # READY 상태: STOP 버튼 (비활성 프레임리스 - 튜닝 반영)
            self.btn_stop.setText("■")
            self.btn_stop.setEnabled(False)
            self.btn_stop.setStyleSheet(f"""
                QPushButton {{
                    background-color: transparent;
                    color: {disabled_gray};
                    border: none;
                    font-size: 30px;
                    font-weight: normal;
                    padding: 0px;
                    padding-bottom: 4px;
                    margin: 0px;
                }}
            """)

        # [공통 마무리] 상태 변경 시 UI 잠금 상태 동적 업데이트
        self.lock_ui_for_sequence(self.btn_auto_seq.isChecked())

    def show_timed_message(self, title, text, timeout=2000):
        """2초(기본값) 후 자동으로 사라지는 플로팅 오버레이 알림 (안전한 타이머 사용)"""
        # 기존 알림이 있다면 즉시 제거 및 타이머 중단
        if self.active_alert:
            self.alert_close_timer.stop() # 타이머 중단이 먼저
            try:
                # [수정] Double Deletion 방지: deleteLater만 사용하고 참조를 먼저 끊음
                alert = self.active_alert
                self.active_alert = None
                alert.close()
                alert.deleteLater()
            except: pass
            
        # [신규] 윈도우 중앙 상단에 떠있는 라벨 형태의 오버레이 생성
        self.active_alert = QLabel(text, self)
        self.active_alert.setObjectName("ToastAlert")
        # 스타일링: 검은 배경, 흰색 글자, 둥근 모서리, 그림자 효과
        self.active_alert.setStyleSheet("""
            QLabel#ToastAlert {
                background-color: rgba(33, 33, 33, 230);
                color: white;
                padding: 15px 25px;
                border-radius: 10px;
                font-size: 14px;
                font-weight: bold;
                border: 1px solid #555;
            }
        """)
        self.active_alert.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.active_alert.adjustSize()
        
        # 위치 계산 (정중앙 상단)
        x = (self.width() - self.active_alert.width()) // 2
        y = 50 # 상단에서 50px 내려온 위치
        self.active_alert.move(x, y)
        self.active_alert.show()
        
        # 안전한 타이머로 자동 소멸 예약
        self.alert_close_timer.setInterval(timeout)
        self.alert_close_timer.start()

    def _close_active_alert(self):
        """타이머에 의해 호출되는 알림 닫기 메서드"""
        if self.active_alert:
            try:
                # [수정] Double Deletion 방지
                alert = self.active_alert
                self.active_alert = None
                alert.close()
                alert.deleteLater()
            except: pass

    def append_log(self, text):
        # [신규] '완료' 키워드가 포함된 로그(매수/매도 완료) 등이 오면 그래프 실시간 갱신 트리거
        if "완료" in text and hasattr(self, 'profit_graph'):
            self.profit_graph.update_chart()
        # [추가] 불필요하거나 기술적인 로그 필터링
        filter_keywords = [
            "Disconnected from WebSocket server",
            "Message sent:",
            "실시간 시세 서버 응답 수신(data):",
            "서버와 연결을 시도 중입니다.",
            "실시간 시세 서버로 로그인 패킷을 전송합니다.",
            "로그인 성공하였습니다.",
            "Connection error:"
        ]
        
        if any(keyword in text for keyword in filter_keywords):
            return

        # [신규] 연속된 중복 메시지 필터링 (내용이 100% 동일할 경우만)
        if text == self.last_log_message:
            return
        self.last_log_message = text

        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        
        # [신규] 개행 문자 정규화 및 트림
        raw_msg = text.replace('\r\n', '\n').replace('\r', '\n')

        # 1. 실시간 파일 로그 기록 (콤팩트 형식, 개행 유지)
        # HTML 태그 제거
        msg_file = re.sub('<[^<]+?>', '', raw_msg)
        # 각 줄의 끝 공백만 제거하고 빈 줄은 가급적 유지 (Today 리포트 가독성)
        msg_file_compact = "\n".join([line.rstrip() for line in msg_file.splitlines()])
        
        log_line = f"[{timestamp}] {msg_file_compact}\n"
        self.log_buffer.append(log_line) # 버퍼에 저장 (메모리 보관)
        
        # [삭제] 실시간 중복 로그 저장 방지 (번호 없는 파일 제거 요청)
        # try:
        #     today_str = datetime.datetime.now().strftime("%Y%m%d")
        #     log_file_path = os.path.join(self.data_dir, f"Log_{today_str}.txt")
        #     with open(log_file_path, 'a', encoding='utf-8', newline='') as f:
        #         f.write(log_line)
        # except: pass

        # 2. GUI용 로그 (V5.7 호환 레이아웃 복원)
        text_html = raw_msg.replace('\n', '<br>')
        
        # TABLE 형태의 레이아웃을 사용하여 시간과 메시지를 분리 (GUI 표시용)
        # V5.7과 동일한 70px 너비와 2px 마진 복원
        full_html = f"""
        <table border="0" cellpadding="0" cellspacing="0" style="margin-bottom: 2px;">
            <tr>
                <td valign="top" style="color: #ccc; font-family: 'Courier New'; white-space: nowrap;">
                    [{timestamp}]
                </td>
                <td valign="top" style="padding-left: 5px; color: #00ff00; font-family: 'Consolas', 'Monospace';">
                    {text_html if '<font color' in text_html or '<span style' in text_html else f"<span>{text_html}</span>"}
                </td>
            </tr>
        </table>
        """
        self.log_display.append(full_html)
        
        # 조건식 목록이면 왼쪽 패널에는 **선택된 조건식만** 필터링하여 표시
        if "📋 [조건식 목록]" in text:
            filtered_msg = ""
            lines = text.split('\n')
            
            # 현재 UI에서 체크된 번호들 가져오기 (cond_states가 0보다 크면 활성)
            checked_indices = [str(i) for i, state in enumerate(self.cond_states) if state > 0]
            
            found_any = False
            for line in lines:
                if line.strip().startswith('•'):
                    try:
                        # "• 0: 조건식이름" 또는 "• 0: 이름" 형태 파싱
                        idx_part = line.split(':')[0].replace('•', '').strip()
                        if idx_part in checked_indices:
                            filtered_msg += line + "<br>"
                            found_any = True
                    except: pass
            
            if not found_any:
                filtered_msg = "<br><center>(선택된 조건식이 목록에 없습니다)</center>"
                
            self.rt_list.setHtml(filtered_msg)
            
        # Auto scroll
        sb = self.log_display.verticalScrollBar()
        sb.setValue(sb.maximum())

    def save_logs_to_file(self):
        """현재 로그창의 내용을 Log_YYYYMMDD_y.txt 형식으로 저장합니다."""
        try:
            # [수정] QTextEdit.toPlainText() 대신 클린 오리지널 버퍼 사용 (여백 문제 해결)
            raw_text = "".join(self.log_buffer)
            today_str = datetime.datetime.now().strftime("%Y%m%d")
            y = 1
            while True:
                filename = f"Log_{today_str}_{y}.txt"
                filepath = os.path.join(self.data_dir, filename)
                if not os.path.exists(filepath): break
                y += 1
            # [수정] newline='' 사용하여 윈도우 중복 개행 방지
            with open(filepath, 'w', encoding='utf-8', newline='') as f:
                f.write(raw_text)
            msg = f"💾 로그 파일 저장 완료: {filename}"
            self.append_log(msg)
            from tel_send import tel_send
            tel_send(msg)
        except Exception as e:
            err_msg = f"❌ 로그 저장 실패: {e}"
            self.append_log(err_msg)
            from tel_send import tel_send
            tel_send(err_msg)

    def send_custom_command(self):
        cmd = self.input_cmd.text().strip()
        if cmd:
            if cmd.upper() == 'PRINT': self.export_log()
            elif cmd.lower() == 'clr':
                self.log_display.clear()
                self.append_log("🧹 로그가 초기화되었습니다.")
            elif cmd.lower() == 'start': self.on_start_clicked()
            elif cmd.lower() == 'stop': self.on_stop_clicked()
            else: self.worker.schedule_command('custom', cmd)
            self.input_cmd.clear()

    def clear_logs(self):
        self.log_display.clear()
        self.append_log("🧹 로그가 초기화되었습니다.")

    def export_log(self):
        try:
            now_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"KIPOSTOCK_LOG_{now_str}.txt"
            log_path = os.path.join(self.script_dir, filename)
            # [수정] QTextEdit.toPlainText() 대신 클린 오리지널 버퍼 사용
            content = "".join(self.log_buffer)
            # [수정] newline='' 사용하여 윈도우 중복 개행 방지
            with open(log_path, 'w', encoding='utf-8', newline='') as f:
                f.write(content)
            save_msg = f"💾 로그가 저장되었습니다:<br>" + "&nbsp;"*11 + f"<u><i>{filename}</i></u>"
            self.append_log(save_msg)
        except Exception as e:
            self.append_log(f"❌ 로그 저장 실패: {e}")

    def on_cond_clicked(self, idx):
        self.cond_states[idx] = (self.cond_states[idx] + 1) % 4
        self.update_button_style(idx)
        self.refresh_condition_list_ui()
        self.save_settings(show_limit_warning=False, restart_if_running=False, quiet=True)
        if self.lbl_status.text() == "● RUNNING":
            self.worker.schedule_command('refresh_conditions')

    def update_button_style(self, idx):
        # [Lite V1.0] 번호 강제 설정 및 원형 스타일(36x36, Radius 18px) 적용
        if idx >= len(self.cond_buttons): return
        btn = self.cond_buttons[idx]
        state = self.cond_states[idx]
        btn.setText(str(idx))
        
        # State colors: Off(Gray), 🔴(Red), 🟢(Green), 🔵(Blue)
        colors = {0: "#e0e0e0", 1: "#dc3545", 2: "#28a745", 3: "#007bff"}
        text_colors = {0: "#333", 1: "white", 2: "white", 3: "white"}
        
        bg_color = colors.get(state, "#e0e0e0")
        text_color = text_colors.get(state, "#333")
        
        # [신규] 마킹 상태(우클릭)에 따른 골드 테두리 효과
        border_style = "2px solid #ffbb33" if self.marked_states[idx] else "1px solid rgba(0,0,0,0.1)"
        
        # 완전한 원형 스타일 (Border-radius: 18px / Width=Height=36px)
        btn.setStyleSheet(f"""
            QPushButton {{ 
                background-color: {bg_color}; 
                color: {text_color}; 
                font-weight: bold; 
                border-radius: 18px;
                border: {border_style};
                font-size: 14px;
                padding: 0px;
            }}
            QPushButton:hover {{
                opacity: 0.9;
                border: 3px solid white;
            }}
        """)

    def refresh_condition_list_ui(self):
        """실시간 조건식 리스트 패널을 현재 선택된 상태에 맞춰 갱신"""
        try:
            # 1. 고유한 검색식 이름 사전 및 활성 상태 접근
            condition_map = {}
            active_set = set() # 엔진에 등록 완료된 조건식 목록
            if self.worker and hasattr(self.worker, 'chat_command') and hasattr(self.worker.chat_command, 'rt_search'):
                 condition_map = self.worker.chat_command.rt_search.condition_map
                 active_set = self.worker.chat_command.rt_search.active_conditions

            # html = "<b>[ 현재 선택된 조건식 ]</b><br><br>" # 제거 요청
            html = ""
            active_count = 0
            
            # 2. 버튼 상태 순회
            mode_names = {1: "1주", 2: "금액", 3: "비율"}
            mode_colors = {1: "#dc3545", 2: "#28a745", 3: "#007bff"}
            
            for i, state in enumerate(self.cond_states):
                # 사용자가 선택한(색상이 입혀진) 조건식만 표시 (state > 0)
                if state > 0:
                    active_count += 1
                    name = condition_map.get(str(i), f"조건식 {i}")
                    m_name = mode_names[state]
                    m_color = mode_colors[state]
                    
                    # [신규] 활성 상태(API 등록 완료) 안테나 아이콘
                    status_icon = " 📡" if str(i) in active_set else ""
                    
                    # HTML 포맷: 색상 적용된 이름과 모드 표시 + 안테나 아이콘
                    html += f"&nbsp;• <span style='color:{m_color};'><b>{i}: {name}</b> ({m_name}){status_icon}</span><br>"
            
            if active_count == 0:
                html = "<br><center><span style='color:#777;'>(선택된 조건식이 없습니다)</span></center>"
                
            self.rt_list.setHtml(html)
            
        except Exception as e:
            print(f"⚠️ 리스트 갱신 실패: {e}")

    def format_comma(self, line_edit):
        text = line_edit.text().replace(',', '')
        if not text: return
        try:
            val = int(text)
            line_edit.setText(f"{val:,}")
        except:
            pass

    def toggle_blink(self):
        if not self.alarm_playing:
            self.blink_timer.stop()
            return
            
        self.is_blink_on = not self.is_blink_on
        # 아이콘(텍스트) 유실 방지를 위해 폰트 크기 고정 및 텍스트 명시
        if self.is_blink_on:
            self.btn_alarm_stop.setStyleSheet("""
                QPushButton { background-color: #ffc107; color: #000; border: 1px solid #e0a800; border-radius: 4px; font-size: 14px; padding: 0px; }
            """)
        else:
            self.btn_alarm_stop.setStyleSheet("""
                QPushButton { background-color: #dc3545; color: #fff; border: 1px solid #c82333; border-radius: 4px; font-size: 14px; padding: 0px; }
            """)

    def check_alarm(self):
        # 이미 울리고 있으면 패스
        if self.alarm_playing:
            return

        # 프로그램 시작 후 5초간은 알람 체크 스킵 (초기화 안정화 대기)
        if (datetime.datetime.now() - self.app_start_time).total_seconds() < 5:
            return

        # [신규] 상단 시계 업데이트
        now = datetime.datetime.now()
        self.lbl_clock.setText(now.strftime("%H:%M:%S"))

        current_time_str = now.strftime("%H:%M")
        
        # -------------------------------------------------------------
        # ✅ 1. 시작 시간 체크 (Start Time Check)
        # -------------------------------------------------------------
        # 설정된 시작 시간과 일치하고, 현재 상태가 READY라면 자동 시작
        try:
            start_time_str = self.input_start_time.text().strip()
            # 시간 포맷 정규화
            target_start = datetime.datetime.strptime(start_time_str, "%H:%M").strftime("%H:%M")
        except:
            target_start = start_time_str

        if current_time_str == target_start:
            # [수정] 분 단위 중복 실행 방지 (이미 실행한 시간대면 패스)
            if self.last_auto_start_time != current_time_str:
                # 중복 실행 방지 (분 단위 체크이므로 1분 동안 계속 실행될 수 있음 -> last_check_time 등으로 방지 필요하지만 
                # 여기서는 상태가 READY일 때만 동작하므로 자연스럽게 방어됨)
                if self.lbl_status.text() == "● READY":
                    self.last_auto_start_time = current_time_str # 실행 시간 기록
                    self.append_log(f"⏰ 시작 시간({target_start}) 도달: 자동 시작합니다.")
                    # 짧은 비프음 (설정값 확인)
                    if get_setting('beep_sound', True):
                         winsound.MessageBeep(winsound.MB_ICONASTERISK)
                    # 시작 명령 실행
                    self.on_start_clicked() # 저장 후 시작 로직 재사용

        # -------------------------------------------------------------
        # ✅ 2. 종료 시간 체크 (End Time Check)
        # -------------------------------------------------------------
        end_time_str = self.input_end_time.text().strip()
        try:
            target_end = datetime.datetime.strptime(end_time_str, "%H:%M").strftime("%H:%M")
        except:
            target_end = end_time_str

        # 시간이 일치하고, 방금 끈 시간(last_alarm_time)이 아니라면
        # [수정] 동일한 분에 시작과 종료가 동시에 일어나는 레이스 컨디션 방지
        if current_time_str == target_end:
            if self.last_alarm_time != current_time_str and self.last_auto_start_time != current_time_str:
                self.handle_end_time_event(current_time_str)

 

    # def play_subprocess_sound(self):  <-- 메서드 제거
    #     pass

    def stop_alarm(self):
        if self.alarm_playing:
            # 소리 중단
            try:
                winsound.PlaySound(None, winsound.SND_PURGE)
            except: pass
            
            self.alarm_playing = False
            self.last_alarm_time = datetime.datetime.now().strftime("%H:%M") # 현재 분에는 다시 안 울림
            
            self.blink_timer.stop() # 깜빡임 중단
            self.btn_alarm_stop.setEnabled(False)
            self.btn_alarm_stop.setText("🔕")
            self.btn_alarm_stop.setStyleSheet("""
                QPushButton {
                    background-color: #f8f9fa;
                    border: 1px solid #ddd;
                    border-radius: 4px;
                    font-size: 14px;
                    color: #aaa;
                    padding: 0px;
                }
            """)
            self.append_log("🔕 알람이 해제되었습니다.")

    def update_price_type_style(self, strat_key):
        """[V2.0] 매수 방식(시장/현재) 토글 스타일 업데이트 (테마 반영)"""
        btn_map = {
            'qty': (self.btn_qty_type, "#dc3545"),
            'amount': (self.btn_amt_type, "#28a745"),
            'percent': (self.btn_pct_type, "#007bff")
        }
        # [버그 픽스] strat_key가 없을 경우 None을 반환하여 언패킹 에러(TypeError)가 나던 현상 수정
        btn, color = btn_map.get(strat_key, (None, None))
        if not btn: return

        if btn.isChecked():
            btn.setText("현")
            if self.ui_theme == 'light':
                btn.setStyleSheet("background-color: #f1f3f5; color: #495057; border: 2px solid #adb5bd; border-radius: 13px; font-weight: bold; font-size: 11px; padding: 0px;")
            else:
                btn.setStyleSheet("background-color: #2a2a2a; color: #aaa; border: 2px solid #555; border-radius: 13px; font-weight: bold; font-size: 11px; padding: 0px;")
        else:
            btn.setText("시")
            btn.setStyleSheet(f"background-color: {color}; color: white; border: 2px solid {color}; border-radius: 13px; font-weight: bold; font-size: 11px; padding: 0px;")

    def update_bultagi_ui_style(self):
        """[v4.5.1] 불타기 모드(배수/금액) 콤보박스 선택 시 (스타일은 전역 CSS 참조)"""
        # CSS에서 설정된 테마 스타일이 깨지지 않도록 인라인 스타일은 사용하지 않습니다.
        pass

    def update_strategy_ui(self, from_user_click=False):
        # Legacy stub for backward compatibility if called elsewhere
        pass

    def format_input_value(self, text):
        # Legacy stub
        pass

    def load_settings_to_ui(self, profile_idx=None, keep_seq_auto=False):
        try:
            # [수정] 파일이 없을 경우를 대비한 방어 로직 강화
            if not os.path.exists(self.settings_file):
                self.append_log(f"⚠️ 설정 파일이 없습니다: {os.path.basename(self.settings_file)}")
                # 파일이 없으면 빈 딕셔너리로 진행하여 기본값 UI 출력 유도
                settings = {}
            else:
                with open(self.settings_file, 'r', encoding='utf-8-sig') as f:
                    settings = json.load(f)
            
            target = settings
            if profile_idx is not None:
                profiles = settings.get('profiles', {})
                target = profiles.get(str(profile_idx))
                if not target:
                    # [수정] 데이터가 없어도 중단하지 않고 기본값으로 UI를 갱신하도록 함 (구버전 호환성)
                    self.append_log(f"ℹ️ 프로필 {profile_idx}번 데이터가 없어 기본 설정을 적용합니다.")
                    target = {} 
                self.append_log(f"📂 프로필 {profile_idx}번 설정을 불러왔습니다.")

            self.input_max.setText(str(target.get('max_stocks', '20')))
            
            # Condition Button Set
            seq_data = target.get('search_seq', [])
            if isinstance(seq_data, str):
                try:
                    parsed = ast.literal_eval(seq_data)
                    seq_data = parsed if isinstance(parsed, list) else [seq_data]
                except: seq_data = [seq_data]
            elif isinstance(seq_data, int): seq_data = [str(seq_data)]
                
            seq_set = set(map(str, seq_data))
            for i, btn in enumerate(self.cond_buttons):
                btn.setChecked(str(i) in seq_set)
            
            self.input_start_time.setText(target.get('start_time', '09:00'))
            self.input_end_time.setText(target.get('end_time', '15:20'))
            self.input_qty_val.setText(str(target.get('qty_val', '1')))
            
            amt_val = target.get('amt_val', '100,000')
            try: amt_val = f"{int(str(amt_val).replace(',', '')):,}"
            except: pass
            self.input_amt_val.setText(amt_val)
            self.input_pct_val.setText(str(target.get('pct_val', '10')))
            
            # [신규] 전략별 익절/손절 로드
            st_data = target.get('strategy_tp_sl', {})
            
            def load_strategy_tpsl(key, tp_widget, sl_widget):
                val = st_data.get(key, {})
                tp_widget.setText(str(val.get('tp', '12.0')))
                sl_widget.setText(str(val.get('sl', '-1.2')))
            
            load_strategy_tpsl('qty', self.input_qty_tp, self.input_qty_sl)
            load_strategy_tpsl('amount', self.input_amt_tp, self.input_amt_sl)
            load_strategy_tpsl('percent', self.input_pct_tp, self.input_pct_sl)
            load_strategy_tpsl('HTS', self.input_hts_tp, self.input_hts_sl)

            # [최우선] 현재 프로필 인덱스 즉시 설정 (on_auto_seq_toggled 호출 시 참조됨)
            self.current_profile_idx = profile_idx
            self.update_profile_buttons_ui()

            # [수정] 시퀀스 버튼 로드 및 UI 반영 (전환 시에는 현재 상태 유지)
            if not keep_seq_auto:
                is_seq = target.get('sequence_auto', False)
                self.btn_auto_seq.setChecked(is_seq)
                self.on_auto_seq_toggled() # 상태에 따른 스타일 적용
            
            # Condition 4-State logic
            strat_map = target.get('condition_strategies', {})
            active_seqs = set(map(str, seq_data)) if isinstance(seq_data, (list, set)) else set()

            for i in range(10):
                mode = strat_map.get(str(i))
                if mode == 'qty': self.cond_states[i] = 1
                elif mode == 'amount': self.cond_states[i] = 2
                elif mode == 'percent': self.cond_states[i] = 3
                else:
                    self.cond_states[i] = 1 if str(i) in active_seqs else 0
                self.update_button_style(i)
            
            # [V2.0] 매수 방식 로드
            pts = target.get('strategy_price_types', {})
            self.btn_qty_type.setChecked(pts.get('qty') == 'current')
            self.btn_amt_type.setChecked(pts.get('amount') == 'current')
            self.btn_pct_type.setChecked(pts.get('percent') == 'current')
            
            # 스타일 즉시 반영
            for k in ['qty', 'amount', 'percent']:
                self.update_price_type_style(k)


            # [신규] 매매 타이머 값 로드
            saved_timer_val = target.get('trade_timer_val', '01:00')
            self.input_timer.setText(saved_timer_val)
            self.original_timer_text = saved_timer_val

            # [신규] 상호 배타적 모드 적용 (M vs 1,2,3)
            # update_profile_buttons_ui 내부 로직과 별개로 기능적 제한 적용
            is_light = getattr(self, 'ui_theme', 'dark') == 'light'
            disabled_gray = "#adb5bd" if is_light else "#444"
            auto_disabled_bg = "#e9ecef" if is_light else "#333"
            auto_disabled_color = "#adb5bd" if is_light else "#aaa"
            auto_disabled_border = "#ced4da" if is_light else "#555"

            if str(profile_idx).strip().upper() == "M":
                # M (수동) 모드: 시작 버튼 활성화, 시퀀스 버튼 비활성화 & 끄기
                # [보강] 데이터 로딩 실패 여부와 상관없이 M모드면 START 버튼을 무조건 활성화
                self.btn_start.setStyleSheet("""
                    QPushButton {
                        background-color: transparent;
                        color: #27ae60;
                        border: none;
                        padding: 0px; padding-bottom: 3px; padding-left: 5px; margin: 0px; /* 초정밀 위치 보정 */
                        font-size: 34px;
                        font-weight: normal;
                    }
                    QPushButton:hover { color: #2ecc71; }
                 """)
                self.btn_auto_seq.setChecked(False) # 강제 끄기
                self.btn_auto_seq.setEnabled(False) 
                self.btn_auto_seq.setStyleSheet(f"""
                    QPushButton {{
                        background-color: {auto_disabled_bg};
                        color: {auto_disabled_color};
                        border-radius: 8px;
                        border: 1px solid {auto_disabled_border};
                        font-size: 28px;
                        padding: 0px; margin: 0px; /* [신규] 여백 강제 초기화 */
                    }}
                 """)
            else:
                # 1,2,3 (오토) 모드: 시작 버튼 비활성화 (오토시퀀스로만 작동 유도), 시퀀스 버튼 활성화
                self.btn_start.setEnabled(False)
                self.btn_start.setStyleSheet(f"""
                    QPushButton {{
                        background-color: transparent;
                        color: {disabled_gray};
                        border: none;
                        padding: 0px; padding-bottom: 3px; padding-left: 5px; margin: 0px; /* 여백 강제 고정 */
                        font-size: 34px;
                    }}
                 """)
                self.btn_auto_seq.setEnabled(True)
                if not self.btn_auto_seq.isChecked():
                    self.btn_auto_seq.setStyleSheet(f"""
                        QPushButton {{
                            background-color: {auto_disabled_bg};
                            color: {auto_disabled_color};
                            border-radius: 8px;
                            border: 1px solid {auto_disabled_border};
                            font-size: 28px;
                            padding: 0px; margin: 0px; /* [신규] 여백 강제 초기화 */
                        }}
                     """)


            # [신규] 로드 직후 리스트 리프레시 및 운영 시간 동기화
            QTimer.singleShot(700, self.refresh_condition_list_ui)
            # [수정] 무조건 현재 상태를 다시 업데이트하여 START 버튼 활성화 보장 (READY 강제)
            # 0.5s 뒤에 한 번 더 확실하게 호출하여 초기화 지연 문제 해결
            QTimer.singleShot(500, lambda: self.update_status_ui("READY"))
            
            # [강제 보강] 만약 M 모드라면 START 버튼 스타일 더 확실하게 한 번 더 적용
            if str(profile_idx).strip().upper() == "M":
                QTimer.singleShot(600, lambda: self.btn_start.setEnabled(True))
                QTimer.singleShot(600, lambda: self.btn_start.setStyleSheet("""
                    QPushButton {
                        background-color: transparent;
                        color: #27ae60;
                        border: none;
                        padding: 0px; padding-bottom: 3px; padding-left: 5px; margin: 0px; /* 초정밀 위치 보정 */
                        font-size: 34px;
                        font-weight: normal;
                    }
                    QPushButton:hover { color: #2ecc71; }
                 """))
            
            # [신규] 로드된 설정에 맞춰 MarketHour 즉시 동기화 (WAITING 버그 해결)
            try:
                sh, sm = map(int, target.get('start_time', '09:00').split(':'))
                eh, em = map(int, target.get('end_time', '15:20').split(':'))
                MarketHour.set_market_hours(sh, sm, eh, em)
            except: pass
            
            # [신규] 프로필 불러오기 후, 팝업창(Bultagi)이 열려있다면 즉시 동기화 및 그룹박스 렌더링 처리
            is_bultagi_enabled = target.get('bultagi_enabled', True)
            self.update_bultagi_group_style(is_bultagi_enabled)
            
            if hasattr(self, 'bultagi_dialog') and self.bultagi_dialog and self.bultagi_dialog.isVisible():
                self.bultagi_dialog.load_settings()
            
        except Exception as e:
            self.append_log(f"❌ 설정 불러오기 실패: {e}")
            # [중요] 실패하더라도 READY 상태로 전환하여 UI 조작이 가능하게 함
            QTimer.singleShot(500, lambda: self.update_status_ui("READY"))

    def save_settings(self, profile_idx=None, show_limit_warning=True, restart_if_running=True, quiet=False):
        try:
            max_s = self.input_max.text()
            st = self.input_start_time.text()
            et = self.input_end_time.text()
            
            # [수정] 운영 시간 제한 (08:30 ~ 15:30)로 확대
            def clamp_time(t_str, default_val):
                try:
                    h, m = map(int, t_str.strip().split(':'))
                    t_val = h * 100 + m
                    if t_val < 830: return "08:30"
                    if t_val > 1530: return "15:30"
                    return f"{h:02d}:{m:02d}"
                except: return default_val
            
            st = clamp_time(st, "08:30")
            et = clamp_time(et, "15:30")
            
            # UI 강제 갱신
            self.input_start_time.setText(st)
            self.input_end_time.setText(et)
            
            selected_seq = []
            cond_strategies = {}
            mode_map = {1: 'qty', 2: 'amount', 3: 'percent'}
            
            for i, state in enumerate(self.cond_states):
                if state > 0:
                    selected_seq.append(str(i))
                    cond_strategies[str(i)] = mode_map[state]

            # [신규] 10개 초과 경고 (증권사 정책)
            if show_limit_warning and len(selected_seq) > 10:
                msg = f"⚠️ [주의] 선택된 조건식이 {len(selected_seq)}개입니다.\n증권사 API 정책상 동시에 최대 10개까지만 실시간 감시가 가능합니다.\n초과된 항목은 서버에서 등록을 거부할 수 있습니다."
                QMessageBox.warning(self, "조건식 개수 초과", msg)
                self.append_log(msg.replace("\n", " "))

                        # [수정] 숫자 형식 오류 방지를 위한 안전한 변환 함수
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

            qty_val = self.input_qty_val.text()
            amt_val = self.input_amt_val.text()
            pct_val = self.input_pct_val.text()
            
            # [수정] 성향별 대표값 변수 정의 및 자동 보정 (안전하게 변환)
            def sanitize_tp(v): return abs(safe_float(v, 1.0))
            def sanitize_sl(v): return -abs(safe_float(v, -1.0))

            q_tp = f"{sanitize_tp(self.input_qty_tp.text())}"; q_sl = f"{sanitize_sl(self.input_qty_sl.text())}"
            a_tp = f"{sanitize_tp(self.input_amt_tp.text())}"; a_sl = f"{sanitize_sl(self.input_amt_sl.text())}"
            p_tp = f"{sanitize_tp(self.input_pct_tp.text())}"; p_sl = f"{sanitize_sl(self.input_pct_sl.text())}"
            h_tp = f"{sanitize_tp(self.input_hts_tp.text())}"; h_sl = f"{sanitize_sl(self.input_hts_sl.text())}"

            # UI에 보정된 값 즉시 반영
            self.input_qty_tp.setText(q_tp); self.input_qty_sl.setText(q_sl)
            self.input_amt_tp.setText(a_tp); self.input_amt_sl.setText(a_sl)
            self.input_pct_tp.setText(p_tp); self.input_pct_sl.setText(p_sl)
            self.input_hts_tp.setText(h_tp); self.input_hts_sl.setText(h_sl)

            # 현재 설정을 딕셔너리로 구성
            current_data = {
                'take_profit_rate': safe_float(q_tp, 1.0), # 1주 전략값을 기본값으로 사용
                'stop_loss_rate': safe_float(q_sl, -1.0),   # 1주 전략값을 기본값으로 사용
                'max_stocks': safe_int(max_s, 20),
                'start_time': st,
                'end_time': et,
                'qty_val': qty_val,
                'amt_val': amt_val,
                'pct_val': pct_val,
                'strategy_tp_sl': {
                    'qty': {'tp': safe_float(q_tp, 1.0), 'sl': safe_float(q_sl, -1.0)},
                    'amount': {'tp': safe_float(a_tp, 1.0), 'sl': safe_float(a_sl, -1.0)},
                    'percent': {'tp': safe_float(p_tp, 1.0), 'sl': safe_float(p_sl, -1.0)},
                    'HTS': {'tp': safe_float(h_tp, 1.0), 'sl': safe_float(h_sl, -1.0)}
                },
                'strategy_price_types': {
                    'qty': 'current' if self.btn_qty_type.isChecked() else 'market',
                    'amount': 'current' if self.btn_amt_type.isChecked() else 'market',
                    'percent': 'current' if self.btn_pct_type.isChecked() else 'market'
                },
                'condition_strategies': cond_strategies,
                'search_seq': selected_seq,
                'sequence_auto': self.btn_auto_seq.isChecked(), # [수정] 시퀀스 버튼 상태 저장
                'trade_timer_val': self.input_timer.text().strip(), # [신규] 타이머 값 저장
                # [v4.6] 불타기 관련 세팅은 이제 BultagiSettingsDialog에서 다이렉트로 관리함 (여기서는 덮어쓰지 않음)
            }

            if profile_idx is not None:
                # 특정 프로필에 저장
                with open(self.settings_file, 'r', encoding='utf-8') as f:
                    settings = json.load(f)
                
                if 'profiles' not in settings: settings['profiles'] = {}
                
                # [v4.6] 기존 프로필의 불타기 설정 유지
                old_profile = settings['profiles'].get(str(profile_idx), {})
                for k in ['bultagi_enabled', 'bultagi_wait_sec', 'bultagi_mode', 'bultagi_price_type', 'bultagi_val', 'bultagi_tp', 'bultagi_sl']:
                    if k in old_profile: current_data[k] = old_profile[k]
                    
                settings['profiles'][str(profile_idx)] = current_data
                
                with open(self.settings_file, 'w', encoding='utf-8') as f:
                    json.dump(settings, f, ensure_ascii=False, indent=2)
                
                # [신규] 저장 시에도 MarketHour 즉시 동기화
                try:
                    sh, sm = map(int, st.split(':'))
                    eh, em = map(int, et.split(':'))
                    MarketHour.set_market_hours(sh, sm, eh, em)
                except: pass

                if not quiet:
                    self.append_log(f"💾 프로필 {profile_idx}번에 설정이 저장되었습니다.")
                    # [수정] 일관된 서식으로 로그 출력
                    summary = f"📋 [저장] 1주({q_tp}/{q_sl}%) | 금액({a_tp}/{a_sl}%) | 비율({p_tp}/{p_sl}%) | 직접({h_tp}/{h_sl}%)"
                    self.append_log(f"<font color='#28a745'>{summary}</font>")
            else:
                # [수정] 레이스 컨디션 방지를 위해 일괄 업데이트(update_settings) 사용
                root_updates = {
                    'qty_val': qty_val,
                    'amt_val': amt_val,
                    'pct_val': pct_val,
                    'strategy_tp_sl': {
                        'qty': {'tp': safe_float(q_tp, 1.0), 'sl': safe_float(q_sl, -1.0)},
                        'amount': {'tp': safe_float(a_tp, 1.0), 'sl': safe_float(a_sl, -1.0)},
                        'percent': {'tp': safe_float(p_tp, 1.0), 'sl': safe_float(p_sl, -1.0)},
                        'HTS': {'tp': safe_float(h_tp, 1.0), 'sl': safe_float(h_sl, -1.0)}
                    },
                    'strategy_price_types': {
                        'qty': 'current' if self.btn_qty_type.isChecked() else 'market',
                        'amount': 'current' if self.btn_amt_type.isChecked() else 'market',
                        'percent': 'current' if self.btn_pct_type.isChecked() else 'market'
                    },
                    'condition_strategies': cond_strategies,
                    'search_seq': selected_seq,
                    'take_profit_rate': safe_float(q_tp, 1.0),
                    'stop_loss_rate': safe_float(q_sl, -1.0),
                    'max_stocks': safe_int(max_s, 20),
                    'start_time': st,
                    'end_time': et,
                    'trade_timer_val': self.input_timer.text().strip(), # [신규] 루트 타이머 값 저장
                    # [v4.6] 루트 설정값 전송 시 기존 불타기 세팅 누락을 막기 위해 현재 파일에서 가져와 재주입
                    'bultagi_enabled': getattr(self.bultagi_group, 'isChecked', lambda: True)(),
                    'bultagi_wait_sec': get_setting('bultagi_wait_sec', 30),
                    'bultagi_mode': get_setting('bultagi_mode', 'multiplier'),
                    'bultagi_price_type': get_setting('bultagi_price_type', 'market'),
                    'bultagi_val': get_setting('bultagi_val', '10'),
                    'bultagi_tp': get_setting('bultagi_tp', 5.0),
                    'bultagi_sl': get_setting('bultagi_sl', -3.0)
                }
                self.worker.schedule_command('update_settings', root_updates, quiet)
                
                # 시간 설정 즉시 반영
                try:
                    sh, sm = map(int, st.split(':'))
                    eh, em = map(int, et.split(':'))
                    MarketHour.set_market_hours(sh, sm, eh, em)
                except: pass
                
                # [제거] 저장 시마다 리스트를 새로 요청할 필요 없음 (UI 갱신으로 충분)
                # self.worker.schedule_command('condition_list', quiet) 
                if hasattr(cached_setting, "_cache"): cached_setting._cache = {}
                
                # [수정] 엔진 재시작 여부 제어 (조건식 단순 변경 시에는 재시작 안 함)
                if restart_if_running and "RUNNING" in self.lbl_status.text():
                    self.worker.schedule_command('start')
                    # [신규] 시작 시 현재 마킹 상태도 동기화
                    marked = [i for i, m in enumerate(self.marked_states) if m]
                    self.worker.schedule_command('sync_marking', marked)
                    self.on_start_clicked() # UI 동기화
                elif "READY" in self.lbl_status.text() and not restart_if_running:
                    # 마킹 상태 동기화는 READY/STOPPED 상태에서도 저장 시 수행
                    marked = [i for i, m in enumerate(self.marked_states) if m]
                    self.worker.schedule_command('sync_marking', marked)
                    pass
                elif "STOPPED" in self.lbl_status.text() and not restart_if_running:
                    marked = [i for i, m in enumerate(self.marked_states) if m]
                    self.worker.schedule_command('sync_marking', marked)
                    pass
                
                if not quiet:
                    self.append_log("💾 기본 설정이 저장되었습니다.")
                    # [수정] NameError(tpr, slr) 해결 및 상세 로그 출력
                    summary = f"📋 [저장] 1주({q_tp}/{q_sl}%) | 금액({a_tp}/{a_sl}%) | 비율({p_tp}/{p_sl}%) | 직접({h_tp}/{h_sl}%) | 종목수:{max_s} | 시간:{st}~{et}"
                    self.append_log(f"<font color='#28a745'>{summary}</font>")

            self.refresh_condition_list_ui()
            
        except ValueError:
            QMessageBox.warning(self, "입력 오류", "숫자 형식이 올바르지 않습니다.")
        except Exception as e:
             QMessageBox.critical(self, "오류", f"저장 중 오류 발생: {e}")

    # [미씽 메서드 복구] 프로필 버튼 클릭 핸들러
    def on_profile_clicked(self, idx):
        # [신규] 로드 전 시퀀스 버튼 상태 백업
        is_seq_before_load = self.btn_auto_seq.isChecked()

        if self.is_save_mode:
            # 저장 모드일 때: 클릭한 프로필에 저장
            self.save_settings(profile_idx=idx)
            self.stop_save_mode()
        else:
            # [수정] M 프로필 클릭 시 동작
            if str(idx) == "M":
                self.load_settings_to_ui(profile_idx="M", keep_seq_auto=False) # M은 오토시퀀스 끔
                self.current_profile_idx = "M"
                self.update_profile_buttons_ui()
                # 로직은 load_settings_to_ui 하단에 추가된 상호 배타 로직에서 처리됨
            else:
                # 일반 모드일 때: 프로필 로드 (현재 시퀀스 버튼 상태 강제 유지)
                self.load_settings_to_ui(profile_idx=idx, keep_seq_auto=True)
                self.current_profile_idx = idx
                self.update_profile_buttons_ui()
            
            # [수정] 시퀀스 자동 모드 조건 강화 (기존에 이미 켜져 있었을 때만 로드 후 자동 시작)
            # 단, M모드일 때는 절대 자동 시작 안 함
            if str(idx) != "M" and is_seq_before_load and self.btn_auto_seq.isChecked():
                self.append_log(f"🚀 시퀀스 자동: 프로필 {idx}번 선택됨 - 엔진을 자동 재기동합니다.")
                # [수정] 이미 실행 중일 수도 있으므로 force=True로 재시작 강제 (원격에서 온 경우 이미 READY 체크됨)
                # [중요] 오토 시퀀스에 의한 자동 시작이므로 manual=False로 시간 체크를 강제함!
                QTimer.singleShot(1000, lambda: self.on_start_clicked(force=True, manual=False))

    # [미씽 메서드 복구] 저장 모드 종료
    def stop_save_mode(self):
        self.is_save_mode = False
        self.profile_blink_timer.stop()
        self.is_profile_blink_on = False
        
        # 버튼 스타일 복구 (18px로 통일)
        if getattr(self, 'ui_theme', 'dark') == 'light':
            self.btn_save.setStyleSheet("background-color: #ced4da; border-radius: 4px; color: #495057; border: 1px solid #adb5bd; font-size: 16px; padding: 0px; text-align: center;")
        else:
            self.btn_save.setStyleSheet("background-color: #6c757d; border-radius: 4px; color: white; border: 1px solid #5a6268; font-size: 16px; padding: 0px; text-align: center;")
        self.update_profile_buttons_ui()

    # [미씽 메서드 복구] 프로필 버튼 UI 업데이트 (데이터 유무 표시)
    def update_profile_buttons_ui(self):
        try:
            settings = {}
            if os.path.exists(self.settings_file):
                with open(self.settings_file, 'r', encoding='utf-8') as f:
                    settings = json.load(f)
            
            profiles = settings.get('profiles', {})
            is_light = getattr(self, 'ui_theme', 'dark') == 'light'
            
            # [신규] 개별 위젯의 setStyleSheet가 전역 QToolTip 스타일을 덮어쓰지 않도록 명시적 추가
            tooltip_fix = ""
            if is_light:
                tooltip_fix = "QToolTip { background-color: #333333; color: #ffffff; border: 2px solid #f1c40f; padding: 6px; border-radius: 6px; font-family: 'Malgun Gothic'; font-size: 13px; }"
            
            profile_ids = ["M", "1", "2", "3", "4"]
            for i, btn in enumerate(self.profile_buttons):
                pid = profile_ids[i]
                btn.setText(pid) # 텍스트 명시적으로 다시 설정
                
                base_style = "border-radius: 4px; font-weight: bold; font-size: 14px; padding: 0px;"
                
                if i == 0: # M 버튼
                    is_m_selected = (str(self.current_profile_idx) == "M")
                    has_m_data = "M" in profiles
                    
                    if is_m_selected:
                        btn_style = f"background-color: #27ae60; color: #fff; border: 2px solid #27ae60; {base_style}"
                    else:
                        bg_c = "#e8f5e9" if is_light else "#145a32"
                        f_c = "#2e7d32" if is_light else "#fff"
                        btn_style = f"background-color: {bg_c}; color: {f_c}; border: 1px solid #27ae60; {base_style}"
                else: # 1, 2, 3, 4 버튼
                    idx = i # 0-indexed for list
                    has_data = str(idx) in profiles
                    is_selected = (str(self.current_profile_idx) == str(idx))
                    
                    if is_selected:
                        btn_style = f"background-color: #3498db; color: #fff; border: 2px solid #3498db; {base_style}"
                    elif has_data:
                        bg_c = "#e2e6ea" if is_light else "#333"
                        f_c = "#212529" if is_light else "#fff"
                        bd_c = "#adb5bd" if is_light else "#2980b9"
                        btn_style = f"background-color: {bg_c}; color: {f_c}; border: 1px solid {bd_c}; {base_style}"
                    else:
                        bg_c = "#f8f9fa" if is_light else "#333"
                        f_c = "#adb5bd" if is_light else "#fff"
                        bd_c = "#dee2e6" if is_light else "#2980b9"
                        btn_style = f"background-color: {bg_c}; color: {f_c}; border: 1px solid {bd_c}; {base_style}"
                
                # [수정] QPushButton 선택자를 사용하여 스타일 범위를 명확히 하고 툴팁 수정 적용
                btn.setStyleSheet(f"QPushButton {{ {btn_style} }} {tooltip_fix}")
                    
        except Exception as e:
            self.append_log(f"UI 업데이트 오류: {e}")

    def on_save_button_clicked(self):
        """설정 저장 버튼 클릭 시: 저장 모드 진입 및 점멸 시작"""
        if not self.is_save_mode:
            self.is_save_mode = True
            self.profile_blink_timer.start()
            self.append_log("💡 저장할 번호(1~4, M)를 선택하세요. (다시 누르면 취소)")
            self.btn_save.setStyleSheet("""
                QPushButton { 
                    background-color: #ffc107; 
                    color: black; 
                    border-radius: 4px; 
                    font-size: 16px; 
                    border: 1px solid #e0a800; 
                    padding: 0px;
                }
            """)
        else:
            self.stop_save_mode()
            self.append_log("❌ 저장 모드가 취소되었습니다.")

    def on_auto_seq_toggled(self):
        """시퀀스 자동 버튼 토글 시 처리"""
        is_on = self.btn_auto_seq.isChecked()
        
        if is_on:
            self.btn_auto_seq.setText("🔄 AUTO: ON")
            # [신규] 매매 진행 중(RUNNING)일 때는 시퀀스 켜기 차단
            current_status = self.lbl_status.text()
            if "RUNNING" in current_status:
                self.log_and_tel("⚠️ 매매 진행 중(RUNNING)에는 자동 시퀀스를 시작할 수 없습니다. 중지(STOP) 후 다시 시도하세요.")
                self.btn_auto_seq.blockSignals(True)
                self.btn_auto_seq.setChecked(False) # 다시 끔
                self.btn_auto_seq.blockSignals(False)
                return
            
            # [신규] 장외 시간 및 예약 시간 체크
            now = datetime.datetime.now()
            
            # 1. 휴장일 또는 주말 체크
            if not MarketHour._is_weekday() or MarketHour.is_holiday():
                self.show_timed_message("작동 제한", "오늘은 주말 또는 공휴일(휴장일)입니다.\n2초 후 자동으로 닫힙니다.", 2000)
                self.btn_auto_seq.blockSignals(True)
                self.btn_auto_seq.setChecked(False)
                self.btn_auto_seq.blockSignals(False)
                return

            # 2. 장전 예약 시간 체크 (08:00 ~ 설정 시작 시간)
            if MarketHour.is_pre_market_reservation_time():
                st_time = f"{MarketHour.MARKET_START_HOUR:02d}:{MarketHour.MARKET_START_MINUTE:02d}"
                self.append_log("="*50)
                self.append_log("⏰ [장 시작 예약 모드] 현재는 장외 시간입니다.")
                self.append_log(f"ℹ️ {st_time} 정각에 시퀀스가 자동으로 시작됩니다.")
                self.append_log("ℹ️ 프로그램을 종료하지 말고 대기해 주세요.")
                self.append_log("="*50)
                # 버튼 상태는 유지 (예약 상태 표기용)
                self.seq_blink_timer.start() # 예약 중임을 알리기 위해 점멸 시작
                self.lock_ui_for_sequence(True)
                return

            # 3. 장 종료 후 체크 (15:30 이후)
            if MarketHour.is_waiting_period() and now.hour >= 15:
                self.show_timed_message("작동 제한", "현재는 장 마감 시간입니다.\n오늘의 거래는 종료되었습니다.\n(2초 후 자동 닫힘)", 2000)
                self.btn_auto_seq.blockSignals(True)
                self.btn_auto_seq.setChecked(False)
                self.btn_auto_seq.blockSignals(False)
                return

            # 4. 정규 장 시간 (정상 작동)
            self.seq_blink_timer.start()
            self.append_log("🔄 시퀀스 자동 모드 ON: 종료 시간 도달 시 다음 프로필로 전환합니다.")
            
            # [신규] 지능형 프로필 건너뛰기: 현재 시간보다 과거인 프로필은 자동으로 다음으로 넘김
            now_time = now.time()
            skipped = False
            
            while True:
                et_str = self.input_end_time.text().strip()
                try:
                    et = datetime.datetime.strptime(et_str, "%H:%M").time()
                    if now_time >= et:
                        # [수정] TypeError 방지를 위한 안전한 타입 변환
                        try:
                            curr_idx_val = int(str(self.current_profile_idx))
                        except (ValueError, TypeError):
                            # 숫자가 아닌 경우(M 등) 시퀀스 다음으로 못 넘김
                            break

                        next_idx = curr_idx_val + 1
                        if next_idx <= 4:
                            # 다음 프로필 로드 시도
                            self.append_log(f"⏩ 현재 시간({now_time.strftime('%H:%M')})이 {self.current_profile_idx}번 종료 시간({et_str})보다 늦어 다음 프로필로 건너뜜 (Next: {next_idx})")
                            self.load_settings_to_ui(profile_idx=next_idx, keep_seq_auto=True)
                            skipped = True
                            continue # 다시 루프 돌며 시간 체크
                        else:
                            self.append_log("🏁 모든 프로필의 운영 시간이 지났습니다. 시퀀스를 종료합니다.")
                            self.btn_auto_seq.setChecked(False)
                            self.on_auto_seq_toggled()
                            return
                except: break
                break

            if not skipped:
                self.append_log("="*60)
                self.append_log(f"🔎 [시퀀스 작동 예약 상세 목록]")
                # ... 기존 로그 출력 로직이 뒤에 이어짐 (필요시 복구)
            
            # [신규] READY 상태에서 시퀀스를 켰다면 엔진도 함께 자동 시작
            if "READY" in self.lbl_status.text():
                self.log_and_tel("🚀 시퀀스 모드 활성화: 엔진을 자동으로 시작합니다.")
                # [중요] 오토 시퀀스 시작이므로 manual=False (시간 체크 필수)
                QTimer.singleShot(1000, lambda: self.on_start_clicked(force=True, manual=False))
            
            # [신규] 현재 이후의 시퀀스 정보 출력
            try:
                if os.path.exists(self.settings_file):
                    with open(self.settings_file, 'r', encoding='utf-8') as f:
                        settings = json.load(f)
                    
                    profiles = settings.get('profiles', {})
                    # 현재 프로필 번호를 기준으로 (없으면 1번)
                    try:
                        current_idx_int = int(str(self.current_profile_idx))
                    except (ValueError, TypeError):
                        current_idx_int = 1
                    
                    # 1. 고유한 검색식 이름 사전 접근 (RT 서버 연동)
                    condition_map = {}
                    if self.worker and hasattr(self.worker, 'chat_command') and hasattr(self.worker.chat_command, 'rt_search'):
                         condition_map = self.worker.chat_command.rt_search.condition_map

                    self.append_log("="*50)
                    self.append_log("📋 [시퀀스 작동 예약 상세 목록]")
                    
                    found_any = False
                    # [수정] 파일에서 읽는 대신 현재 UI 메모리(혹은 저장된 데이터)를 기반으로 하되
                    # 현재 프로필의 "실제 UI 상태"를 우선적으로 반영하여 리포트 출력
                    for i in range(current_idx_int, 5):
                        p = profiles.get(str(i))
                        if not p and i != current_idx_int: continue
                        
                        # 현재 보고 있는 UI 설정이 해당 프로필 인덱스라면 UI 값을 우선 사용
                        is_current_view = (i == self.current_profile_idx or (self.current_profile_idx is None and i == 1))
                        
                        if is_current_view:
                            # 현재 UI 값을 리포트에 반영 (동기화 이슈 해결)
                            st = self.input_start_time.text()
                            et = self.input_end_time.text()
                            # 주: 상세 전략 요약은 file 데이터를 따르거나 UI 데이터를 추출해야 함 
                            # 여기서는 간략히 시간 정보 위주로 UI와 동기화
                        else:
                            st = p.get('start_time', '09:00')
                            et = p.get('end_time', '15:20')
                            
                        log_msg = f"<b>[프로필 {i}번]</b> {st} ~ {et}"
                        if i == current_idx_int:
                            log_msg += " <font color='#ffc107'>[현재]</font>"
                        self.append_log(log_msg)
                        
                        # [수정] 모든 매수 전략(주수/금액/비율) 상세 출력
                        if p:
                            qty_val = p.get('qty_val', '1')
                            amt_val = p.get('amt_val', '100,000')
                            pct_val = p.get('pct_val', '10')
                            
                            st_data = p.get('strategy_tp_sl', {})
                            q_tp = st_data.get('qty', {}).get('tp', '12.0')
                            q_sl = st_data.get('qty', {}).get('sl', '-1.5')
                            a_tp = st_data.get('amount', {}).get('tp', '8.0')
                            a_sl = st_data.get('amount', {}).get('sl', '-1.5')
                            p_tp = st_data.get('percent', {}).get('tp', '6.0')
                            p_sl = st_data.get('percent', {}).get('sl', '-1.5')
                            
                            # [수정] 전략별 개별 컬러 적용 (1주: 적색, 금액: 녹색, 비율: 파랑색)
                            self.append_log(
                                f"  └ <font color='#dc3545'><b>1주:</b> {qty_val}주 ({q_tp}%/{q_sl}%)</font>  "
                                f"<font color='#28a745'><b>금액:</b> {amt_val}원 ({a_tp}%/{a_sl}%)</font>  "
                                f"<font color='#007bff'><b>비율:</b> {pct_val}% ({p_tp}%/{p_sl}%)</font>"
                            )
                            
                            seqs = p.get('search_seq', [])
                            if seqs:
                                cond_details = []
                                color_map = {"qty": "#dc3545", "amount": "#28a745", "percent": "#007bff"}
                                strat_map = p.get('condition_strategies', {})
                                for s_idx in seqs:
                                    name = condition_map.get(str(s_idx), f"조건식 {s_idx}")
                                    mode = strat_map.get(str(s_idx), "qty")
                                    color = color_map.get(mode, "#dc3545")
                                    cond_details.append(f"<font color='{color}'><b>{s_idx}:{name}</b></font>")
                                self.append_log(f"  └ 감시: {', '.join(cond_details)}")
                            else:
                                self.append_log("  └ 감시: (선택된 조건식 없음)")
                        
                        found_any = True
                    
                    if not found_any:
                        self.append_log("  (예약된 프로필 정보가 없습니다)")
                    
                    self.append_log("="*50)
            except Exception as e:
                self.append_log(f"⚠️ 시퀀스 정보 로드 중 오류: {e}")
        else:
            self.seq_blink_timer.stop()
            # [수정] 꺼졌을 때 기본 스타일 복구 (M모드 여부에 따라 색상 분기 - 충돌 방지)
            p_idx = str(getattr(self, 'current_profile_idx', '')).strip().upper()
            if p_idx == "M":
                # M모드면 회색 비활성화 유지
                self.btn_auto_seq.setStyleSheet("background-color: #6c757d; min-height: 35px; max-height: 35px; padding: 0px; font-size: 14px; color: #ddd; border: 2px solid #545b62; border-radius: 4px; font-weight: bold;")
            else:
                # 일반 모드면 파란색 활성화
                self.btn_auto_seq.setStyleSheet("background-color: #17a2b8; min-height: 35px; max-height: 35px; padding: 0px; font-size: 14px; color: white; border: 2px solid #138496; border-radius: 4px; font-weight: bold;")
            self.append_log("⏹ 시퀀스 자동 모드 OFF: 종료 시간 도달 시 알람만 울립니다.")
            self.is_seq_blink_on = False
        
        # [신규] 시퀀스 작동 중 UI 잠금 처리
        self.lock_ui_for_sequence(is_on)

    def lock_ui_for_sequence(self, locked):
        """시퀀스 자동 모드 활성화 시 오조작 방지를 위해 UI 잠금"""
        # [수정] READY 상태일 때는 시퀀스가 켜져 있어도 잠그지 않음 (사용자가 수정 가능하게)
        # 단, 장전 예약 시간(08:00~09:00)에는 수정을 막기 위해 WAITING 상태도 고려
        current_status = self.lbl_status.text()
        is_ready = "READY" in current_status
        
        # 진짜 잠글지 결정: 시퀀스가 On이고, READY 상태가 아닐 때만 잠금
        effective_lock = locked and not is_ready
        
        # 입력 필드 및 버튼 잠금 (신규 필드 반영)
        self.input_qty_tp.setEnabled(not effective_lock)
        self.input_qty_sl.setEnabled(not effective_lock)
        self.input_amt_tp.setEnabled(not effective_lock)
        self.input_amt_sl.setEnabled(not effective_lock)
        self.input_pct_tp.setEnabled(not effective_lock)
        self.input_pct_sl.setEnabled(not effective_lock)
        self.input_max.setEnabled(not effective_lock)
        self.input_start_time.setEnabled(not effective_lock)
        self.input_end_time.setEnabled(not effective_lock)
        self.input_qty_val.setEnabled(not effective_lock)
        self.input_amt_val.setEnabled(not effective_lock)
        self.input_pct_val.setEnabled(not effective_lock)
        
        for btn in self.cond_buttons: btn.setEnabled(not effective_lock)
        for btn in self.profile_buttons: btn.setEnabled(not effective_lock)
        self.btn_save.setEnabled(not effective_lock)
        
        # START 버튼은 READY 상태면 항상 활성화 (시작 가능하게)
        self.btn_start.setEnabled(not effective_lock or is_ready)
        self.btn_stop.setEnabled(not effective_lock or not is_ready) 
        
        if effective_lock:
            self.append_log("🔒 UI 잠구기: 시퀀스 작동 중에는 설정을 변경할 수 없습니다.")
        elif locked and is_ready:
            self.append_log("🔓 UI 대기: 시퀀스 대기 중에는 설정을 변경할 수 있습니다.")

    def blink_seq_button(self):
        """시퀀스 버튼 점멸 효과 (1초 단위)"""
        # 체크된 상태여야만 점멸
        if not self.btn_auto_seq.isChecked():
            self.seq_blink_timer.stop()
            return

        self.is_seq_blink_on = not self.is_seq_blink_on
        if self.is_seq_blink_on:
            # 밝은 노랑 (눈에 확 띔)
            self.btn_auto_seq.setStyleSheet("background-color: #fff59d; min-height: 35px; max-height: 35px; padding: 0px; font-size: 14px; color: #0000ff; border: 2px solid #fbc02d; border-radius: 4px; font-weight: bold;")
        else:
            # 진한 파랑 (작동 중임을 강조) - [수정] 경계선 두께 2px로 통일하여 크기 변동(Jitter) 방지
            self.btn_auto_seq.setStyleSheet("background-color: #17a2b8; min-height: 35px; max-height: 35px; padding: 0px; font-size: 14px; color: white; border: 2px solid #138496; border-radius: 4px; font-weight: bold;")

    def handle_end_time_event(self, current_time_str):
        """매 초마다 호출되는 이벤트 처리 (9시 예약 시작 및 프로필 전환)"""
        # [신규] 장 시작 예약 처리 (사용자 설정 시작 시간에 맞춰 자동 가동)
        user_start_time = self.input_start_time.text() + ":00"
        if current_time_str == user_start_time and self.btn_auto_seq.isChecked():
            # 만약 현재 실행 중이 아니라면 (예약 대기 상태였다면) 시작
            status = self.lbl_status.text()
            if "READY" in status or "WAITING" in status:
                self.log_and_tel(f"🔔 [장 시작 예약] 설정된 시작 시간({self.input_start_time.text()}) 정각입니다. 시퀀스를 자동으로 시작합니다!")
                self.on_start_clicked(force=True)
                return

        """종료 시간 도달 시 시퀀스 로직 처리"""
        # 1. 시퀀스 자동 모드인지 확인
        is_seq_auto = self.btn_auto_seq.isChecked() # [수정] 버튼 상태 확인
        current_idx = self.current_profile_idx

        if is_seq_auto and current_idx is not None:
            # [시퀀스 ON] 다음 프로필로 전환 시도
            try:
                curr_idx_val = int(str(current_idx))
                next_idx = curr_idx_val + 1
            except (ValueError, TypeError):
                # 숫자가 아니거나 올바르지 않은 경우 진행 중단
                return

            if next_idx <= 4: # 최대 4번 프로필까지만
                # 다음 프로필 데이터 확인
                try:
                    if os.path.exists(self.settings_file):
                        with open(self.settings_file, 'r', encoding='utf-8') as f:
                            settings = json.load(f)
                            if 'profiles' in settings and str(next_idx) in settings['profiles']:
                                self.log_and_tel(f"🔄 시퀀스 자동: 프로필 {current_idx}번 종료 -> {next_idx}번으로 전환합니다.")
                                
                                # [신규] 시퀀스 전환 리포트 자동 출력 및 전송 (현재 시퀀스 필터링)
                                self.worker.schedule_command('report', current_idx)
                                
                                # 1) 현재 설정 저장
                                self.save_settings(profile_idx=current_idx, restart_if_running=False) # 전환 중 중복 시작 방지
                                
                                # 2) 다음 프로필 로드 (UI와 내부 변수 동기화, 시퀀스 온 유지)
                                self.load_settings_to_ui(profile_idx=next_idx, keep_seq_auto=True)
                                
                                # 3) 알람 발생 (다음 프로필 전환 알림)
                                self.start_alarm(transition_to=next_idx)
                                
                                # 4) 설정 적용 및 엔진 재가동 (API 재등록 강제 수행)
                                self.append_log("="*40)
                                self.log_and_tel(f"🛰️ [시퀀스] {next_idx}번 프로필로 전환: API 검색식 재등록을 시작합니다...")
                                self.append_log("="*40)
                                
                                # [수정] 전환 중 중복 알람/이벤트 방지를 위해 즉시 시간 기록
                                self.last_alarm_time = current_time_str
                                self.last_auto_start_time = current_time_str # [신규] 전환 중 check_alarm의 중복 실행 방지
                                
                                # [수정] 시퀀스 전환 딜레이를 2.5초 -> 5초로 증가하여 R10001 중복 로그인 방지
                                # 이전 프로필의 세션이 완전히 정리될 시간을 확보합니다.
                                # [중요] 시퀀스 자동 전환은 Time Setting을 준수해야 하므로 manual=False로 전달
                                QTimer.singleShot(5000, lambda: self.on_start_clicked(force=True, manual=False)) 
                                return
                except Exception as e:
                    self.append_log(f"⚠️ 시퀀스 전환 중 오류: {e}")

            # 다음 프로필이 없거나 데이터가 없으면 (최종 시퀀스 종료)
            self.log_and_tel("🏁 시퀀스 종료: 모든 프로필 단계가 완료되었습니다.")
            
            # 시퀀스 종료 시 버튼 끄기 및 UI 잠금 해제
            self.btn_auto_seq.setChecked(False)
            self.on_auto_seq_toggled() 
            
            # [추가] UI 완전 초기화 및 버튼 상태 복구
            self.lock_ui_for_sequence(False)
            self.update_status_ui("READY")
            self.append_log("🔓 시퀀스 종료: 모든 UI 조작이 가능합니다.")
            
            self.start_alarm() # 마지막 종료 알람
            self.worker.schedule_command('stop') # 매매 중단
            
            # [수정] 중단 후 마지막 시퀀스 리포트 및 최종 종합 리포트 전송
            QTimer.singleShot(2000, lambda: self.worker.schedule_command('report', current_idx)) # 마지막 시퀀스
            QTimer.singleShot(7000, lambda: self.worker.schedule_command('report')) # 전체 종합
            return

        # [시퀀스 OFF]
        self.start_alarm(just_sound=True)

    def start_alarm(self, just_sound=False, transition_to=None):
        # ... (기존 start_alarm 로직) ...
        if self.alarm_playing:
            return
            
        try:
            self.alarm_playing = True
            
            # 버튼 상태 변경
            self.btn_alarm_stop.setEnabled(True)
            self.btn_alarm_stop.setText("🔔") 
            self.blink_timer.start() # 깜빡임 시작
            
            if transition_to:
                log_msg = f"🔄 시퀀스 전환: {transition_to}번 프로필로 이동합니다. (매매 계속)"
            elif just_sound:
                log_msg = f"⏰ 종료 시간({self.input_end_time.text()}) 도달! (매매는 계속됩니다)"
            else:
                log_msg = f"⏰ 알람 발생: 종료 시간({self.input_end_time.text()}) 도달!"
                
            self.append_log(log_msg)
            
            sound_path = os.path.join(self.script_dir, "StockAlarm.wav")
            if os.path.exists(sound_path):
                winsound.PlaySound(sound_path, winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_LOOP)
                # [신규] 10초 후 자동 정지 (사용자 요청)
                QTimer.singleShot(10000, self.stop_alarm)
            else:
                self.append_log(f"⚠️ 알람 파일 없음: {sound_path}")
            
        except Exception as e:
            self.append_log(f"⚠️ 알람 처리 중 오류: {e}")
            self.alarm_playing = False


    def closeEvent(self, event):
        reply = QMessageBox.question(self, '종료', '프로그램을 종료하시겠습니까?',
                                   QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, 
                                   QMessageBox.StandardButton.No)

        if reply == QMessageBox.StandardButton.Yes:
            self.worker.stop()
            event.accept()
        else:
            event.ignore()

    def toggle_profile_blink(self):
        """저장 모드 시 번호 버튼 점멸 효과"""
        self.is_profile_blink_on = not self.is_profile_blink_on
        color = "#ffc107" if self.is_profile_blink_on else "#f8f9fa"
        # 1~3번 버튼 점멸
        for btn in self.profile_buttons:
            btn.setStyleSheet(f"background-color: {color}; border: 2px solid #ffc107; border-radius: 4px; font-weight: bold; color: black; padding: 0px; font-size: 14px;")
        # M 버튼도 점멸에 포함
        if hasattr(self, 'btn_manual'):
            self.btn_manual.setStyleSheet(f"background-color: {color}; border: 2px solid #ffc107; border-radius: 4px; font-weight: bold; color: black; padding: 0px; font-size: 14px;")

    # [수정] 항상 위 토글 메서드 (Windows API 사용으로 플리커 제거)
    def toggle_always_on_top(self, checked):
        """압정 핀: 항상 위에 고정 (SetWindowPos 타입 명시로 기능 복구)"""
        try:
            import ctypes
            from ctypes import wintypes
            
            hwnd = int(self.winId()) # 핸들 가져오기
            
            # Windows API 준비
            user32 = ctypes.windll.user32
            
            # SetWindowPos 함수 시그니처 정의 (64비트 호환성 확보)
            user32.SetWindowPos.argtypes = [
                wintypes.HWND, # hWnd
                wintypes.HWND, # hWndInsertAfter
                ctypes.c_int,  # X
                ctypes.c_int,  # Y
                ctypes.c_int,  # cx
                ctypes.c_int,  # cy
                ctypes.c_uint  # uFlags
            ]
            user32.SetWindowPos.restype = wintypes.BOOL
            
            # 상수 정의
            HWND_TOPMOST = -1
            HWND_NOTOPMOST = -2
            SWP_NOMOVE = 0x0002
            SWP_NOSIZE = 0x0001
            SWP_NOACTIVATE = 0x0010
            
            # InsertAfter 핸들 결정 (캐스팅 필요할 수 있음)
            # 파이썬 int -1을 64비트 포인터/핸들로 변환하는 것이 까다로울 수 있으므로
            # ctypes가 처리하도록 일반 정수로 넘기되, argtypes가 HWND이므로 자동 변환 기대
            # 안전하게 c_void_p로 변환
            insert_after = ctypes.c_void_p(HWND_TOPMOST) if checked else ctypes.c_void_p(HWND_NOTOPMOST)
            
            # 실행
            ret = user32.SetWindowPos(hwnd, insert_after, 0, 0, 0, 0, 
                                      SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
            
            if not ret:
                 self.append_log(f"⚠️ 핀 고정 API 실패 (Code: {ctypes.GetLastError()})")
            
            state = "ON" if checked else "OFF"
            self.btn_top.setToolTip(self._style_tooltip(f"📌 항상 위에 고정 ({state})"))
            
        except Exception as e:
            self.append_log(f"⚠️ 핀 고정 오류: {e}")
            # 실패 시 Qt 기본 방식 폴백 (플리커 감수)
            if (self.windowFlags() & Qt.WindowType.WindowStaysOnTopHint) != checked:
                self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, checked)
                self.show()
        self.show()
        self.raise_()

    # [신규] 매매 타이머 토글 (시작/중지)
    def toggle_trade_timer(self):
        if self.trade_timer.isActive():
            self.trade_timer.stop()
            self.btn_timer_toggle.setText("▶")
            self.btn_timer_toggle.setStyleSheet("""
                QPushButton { background-color: #007bff; color: white; border-radius: 14px; font-size: 11px; font-weight: bold; }
                QPushButton:hover { background-color: #0056b3; }
            """)
            self.input_timer.setReadOnly(False)
            self.input_timer.setText(self.original_timer_text)
        else:
            try:
                text = self.input_timer.text().strip()
                if ":" in text:
                    m, s = map(int, text.split(":"))
                else:
                    m, s = int(text), 0
                
                self.trade_timer_seconds = m * 60 + s
                if self.trade_timer_seconds <= 0: return
                
                self.original_timer_text = text
                self.input_timer.setReadOnly(True)
                self.btn_timer_toggle.setText("■")
                self.btn_timer_toggle.setStyleSheet("""
                    QPushButton { background-color: #dc3545; color: white; border-radius: 14px; font-size: 11px; font-weight: bold; }
                    QPushButton:hover { background-color: #a71d2a; }
                """)
                self.trade_timer.start()
            except Exception as e:
                self.append_log(f"⚠️ 타이머 설정 오류: {e}")

    # [신규] 매초 타이머 갱신 및 종료 체크
    def update_trade_timer(self):
        if self.trade_timer_seconds > 0:
            self.trade_timer_seconds -= 1
            m = self.trade_timer_seconds // 60
            s = self.trade_timer_seconds % 60
            self.input_timer.setText(f"{m:02d}:{s:02d}")
            
        # [신규 v4.7.3] 최근 매수 경과 시간 업데이트 (1초마다 동기화)
        if self.last_buy_time:
            elapsed = datetime.datetime.now() - self.last_buy_time
            tot_sec = int(elapsed.total_seconds())
            mm = tot_sec // 60
            ss = tot_sec % 60
            self.lbl_last_buy_timer.setText(f"경과: {mm:02d}:{ss:02d}")
            
            # 10분 경과 시 색상 변경 (경고 의미)
            if mm >= 10:
                self.lbl_last_buy_timer.setStyleSheet("color: #e74c3c; font-weight: bold;")
            else:
                self.lbl_last_buy_timer.setStyleSheet("color: #2ecc71; font-weight: bold;")

        if self.trade_timer_seconds == 0 and self.trade_timer.isActive():
                self.play_timer_alarm()
                # 0초 도달 시 원복 로직 강화
                self.trade_timer.stop()
                self.btn_timer_toggle.setText("▶")
                self.btn_timer_toggle.setStyleSheet("""
                    QPushButton { background-color: #007bff; color: white; border-radius: 14px; font-size: 11px; font-weight: bold; }
                    QPushButton:hover { background-color: #0056b3; }
                """)
                self.input_timer.setReadOnly(False)
                self.input_timer.setText(self.original_timer_text) # 처음 설정값으로 복구

    # [신규] 타이머 종료 알람 (우리 자기 취향의 맑은 소리)
    def play_timer_alarm(self):
        try:
            # 1000Hz의 맑은 소리로 0.4초간 비프음
            import winsound
            winsound.Beep(1000, 400)
        except: pass

if __name__ == '__main__':
    try:
        # [추가] Windows 작업표시줄 아이콘 고정 및 표시를 위한 ID 설정
        if sys.platform == 'win32':
            import ctypes
            myappid = 'kipo.buy.auto.4.2'
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)

        app = QApplication(sys.argv)
        
        # [신규] 앱 전체 기본 아이콘 설정 (작업 표시줄 아이콘 표시용)
        icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'kipo_yellow.ico')
        if getattr(sys, 'frozen', False):
             icon_path = os.path.join(os.path.dirname(sys.executable), 'kipo_yellow.ico')
        if os.path.exists(icon_path):
            app.setWindowIcon(QIcon(icon_path))
        
        # [신규] 중복 실행 방지 로직 (QSharedMemory)
        shared_memory = QSharedMemory("KipoStock_Singleton_Lock")
        if not shared_memory.create(1):
            QMessageBox.warning(None, "실행 오류 (중복 실행 방지)", "KipoStock 프로그램이 이미 실행 중입니다!\n작업 표시줄이나 백그라운드를 확인해주세요.")
            sys.exit(0)
        
        # Font Setup
        font = QFont("Malgun Gothic", 9)
        app.setFont(font)
        
        window = KipoWindow()
        window.show()
        
        retCode = app.exec()
        sys.exit(retCode)
        
    except BaseException as e:
        # [수정] SystemExit(0)은 정상 종료이므로 크래시 로그에서 제외
        if isinstance(e, SystemExit):
            sys.exit(e.code)

        # [수정] 크래시 리포트도 LogData 폴더로 이동 시도
        crash_dir = os.path.dirname(os.path.abspath(__file__))
        if getattr(sys, 'frozen', False):
            crash_dir = os.path.dirname(sys.executable)
        
        data_dir = os.path.join(crash_dir, 'LogData')
        if not os.path.exists(data_dir): os.makedirs(data_dir, exist_ok=True)
        
        crash_path = os.path.join(data_dir, "crash_report.txt")
        with open(crash_path, "a", encoding="utf-8") as f:
            f.write(f"\n[{datetime.datetime.now()}] CRASH/EXIT LOGGED:\n")
            f.write(traceback.format_exc())
            f.write(f"Error Type: {type(e)}\n")
            f.write("-" * 50 + "\n")
        
        if not isinstance(e, SystemExit):
            # [수정] GUI 앱이므로 콘솔 입력(input) 제거 + 메시지 박스 시도
            # Qt 앱이 살아있다면 메시지박스를 띄우지만, 죽었을 수도 있으므로 안전하게 패스 혹은 windows api 사용
            try:
                import ctypes
                ctypes.windll.user32.MessageBoxW(0, f"Critical Error: {e}\nSee crash_report.txt", "Error", 0x10)
            except:
                pass
30