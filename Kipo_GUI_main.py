

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
                           QScrollArea, QRadioButton, QButtonGroup, QCheckBox)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QObject, QTimer
from PyQt6.QtGui import QFont, QIcon, QColor, QPalette
import winsound
import re

# 기존 모듈 임포트

# 기존 모듈 임포트
from config import telegram_token, telegram_chat_id
from tel_send import tel_send as real_tel_send
from chat_command import ChatCommand
from get_setting import get_setting, cached_setting
import ctypes # [신규] 윈도우 API 호출용
from market_hour import MarketHour

# ----------------- Worker Thread for Asyncio Loop -----------------
class WorkerSignals(QObject):
    log_signal = pyqtSignal(str)
    status_signal = pyqtSignal(str)  # 상태 표시줄 업데이트용
    clr_signal = pyqtSignal()       # [신규] 로그 초기화용
    request_log_signal = pyqtSignal() # [신규] 로그 파일 출력 요청
    auto_seq_signal = pyqtSignal(int) # [신규] 원격 시퀀스 시작 신호 (프로필 번호)
    condition_loaded_signal = pyqtSignal() # [신규] 조건식 목록 로드 완료 신호

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
            def write(self, text):
                text = text.strip()
                if text:
                    self.emitter(text)
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
            with open('settings.json', 'r', encoding='utf-8') as f:
                settings = json.load(f)
                
            # 시간 설정 적용 (settings.json에 시간이 없다면 기본값 사용)
            start_time = settings.get('start_time', "09:00")
            end_time = settings.get('end_time', "15:20") # 장 종료 10분전
            
            sh, sm = map(int, start_time.split(':'))
            eh, em = map(int, end_time.split(':'))
            
            MarketHour.set_market_hours(sh, sm, eh, em)
            self.signals.log_signal.emit(f"⚙️ 장 운영 시간 설정: {start_time} ~ {end_time}")
            
        except Exception as e:
            self.signals.log_signal.emit(f"⚠️ 설정 로드 중 오류 (기본값 사용): {e}")

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


# ----------------- Main Window -----------------
class KipoWindow(QMainWindow):
    async def wait_for_ready(self):
        """Worker가 준비(chat_command 객체 생성)될 때까지 대기"""
        while not self.worker.chat_command:
            await asyncio.sleep(0.1)

    def log_and_tel(self, msg):
        """GUI 로그와 텔레그램 모두에 전송 (중요 이벤트용)"""
        self.append_log(msg)
        real_tel_send(msg)

    def __init__(self):
        super().__init__()
        # [신규] 로그 변수는 최우선 초기화 (load_settings_to_ui 호출 시 사용됨)
        self.last_log_message = None
        self.log_buffer = [] # [신규] 파일 저장용 클린 로그 버퍼
        
        # [최우선] 현재 프로필 기본값 M으로 선언 (UI 초기화 시 참조됨)
        self.current_profile_idx = "M"

        self.setWindowTitle("🚀 KipoStock Lite V2.5 GOLD")
        # 파일 경로 설정 (중요: 리소스와 설정 파일 분리)
        if getattr(sys, 'frozen', False):
            # 실행 파일 위치 (settings.json, 로그 저장용)
            self.script_dir = os.path.dirname(sys.executable)
            # 임시 리소스 위치 (아이콘 등 번들된 파일용)
            self.resource_dir = sys._MEIPASS
        else:
            self.script_dir = os.path.dirname(os.path.abspath(__file__))
            self.resource_dir = self.script_dir
            
        # [신규] 로그 및 데이터 저장 폴더 (LogData)
        self.data_dir = os.path.join(self.script_dir, 'LogData')
        if not os.path.exists(self.data_dir):
            try: os.makedirs(self.data_dir)
            except: pass
            
        self.settings_file = os.path.join(self.script_dir, 'settings.json')
        
        # [신규] 중복 로그 파일 정리 (번호 없는 파일 제거 요청 반영)
        try:
            today_str = datetime.datetime.now().strftime("%Y%m%d")
            redundant_log = os.path.join(self.data_dir, f"Log_{today_str}.txt")
            if os.path.exists(redundant_log):
                os.remove(redundant_log)
        except: pass

        # 아이콘 설정 (리소스 경로에서 로드)
        icon_path = os.path.join(self.resource_dir, 'kipo_yellow.png')
        icon_path_ico = os.path.join(self.resource_dir, 'kipo_yellow.ico')
        
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        elif os.path.exists(icon_path_ico):
            self.setWindowIcon(QIcon(icon_path_ico))
        else:
            # Fallback checks in script directory
            for ext in ['png', 'ico']:
                p = os.path.join(self.script_dir, f'kipo_yellow.{ext}')
                if os.path.exists(p):
                    self.setWindowIcon(QIcon(p))
                    break
                
        self.resize(1000, 700)
        
        self.setup_ui()
        self.setup_worker()
        
        # [수정] 사용자의 제안: 프로그램 로딩 후 'M' 버튼을 누른 효과를 강제로 줌
        # [중요] 인자를 4(인덱스)가 아닌 "M"(식별자)으로 정확히 전달하여 로직 완결성 확보
        QTimer.singleShot(1000, lambda: self.on_profile_clicked("M"))

        # 알람 관련 초기화
        self.alarm_playing = False
        self.last_alarm_time = None # 이전 알람 발생 시간 (중복 발생 방지)
        self.app_start_time = datetime.datetime.now() # 시작 시간 기록 (안전장치)
        self.last_auto_start_time = None # [신규] 시작 알람 중복 방지용

        # 알람 반복 타이머 제거 (소리 기능 완전 비활성화)
        # self.sound_repeater = QTimer(self)
        
        self.alarm_timer = QTimer(self)
        self.alarm_timer.setInterval(1000) # 1초마다 체크
        self.alarm_timer.timeout.connect(self.check_alarm)
        self.alarm_timer.start()

        # 알람 버튼 깜빡임 타이머
        self.blink_timer = QTimer(self)
        self.blink_timer.setInterval(500) # 0.5초마다 반전
        self.blink_timer.timeout.connect(self.toggle_blink)
        self.is_blink_on = False

        # 프로필 관련 초기화
        self.is_save_mode = False
        self.profile_blink_timer = QTimer(self)
        self.profile_blink_timer.setInterval(400) # 점멸 속도
        self.profile_blink_timer.timeout.connect(self.toggle_profile_blink)
        self.is_profile_blink_on = False
        self.current_profile_idx = None # 현재 선택된 프로필 인덱스
        self.active_alert = None # [신규] 자동 종료 알림창 인스턴스 보관용
        
        # [신규] 매매 타이머 초기화 (MM:SS)
        self.trade_timer = QTimer(self)
        self.trade_timer.setInterval(1000)
        self.trade_timer.timeout.connect(self.update_trade_timer)
        self.trade_timer_seconds = 0
        self.original_timer_text = "01:00"
        
        # [신규] 안전한 알림 종료를 위한 단일 타이머 (SingleShot 대체)
        self.alert_close_timer = QTimer(self)
        self.alert_close_timer.setSingleShot(True)
        self.alert_close_timer.timeout.connect(self._close_active_alert)
        


    # [신규] 툴팁 스타일 통일용 헬퍼 메서드
    def _style_tooltip(self, text):
        """툴팁 텍스트에 HTML 스타일을 적용하여 폰트와 크기를 강제합니다."""
        # 폰트: 맑은 고딕, 크기: 9pt (약 12px), 색상: #333
        return f"<html><head/><body><p style='font-family:\"Malgun Gothic\"; font-size:9pt; color:#333; margin:0;'>{text.replace(chr(10), '<br>')}</p></body></html>"

    def setup_ui(self):
        # --- Styles ---
        self.setStyleSheet("""
            QMainWindow { background-color: #f0f2f5; }
            QGroupBox { font-weight: bold; border: 1px solid #ccc; border-radius: 8px; margin-top: 10px; padding-top: 15px; background-color: white; }
            QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; left: 10px; padding: 0 5px; }
            QLabel { color: #333; }
            QLineEdit { padding: 5px; border: 1px solid #ddd; border-radius: 4px; background-color: #f9f9f9; }
            
            /* 버튼 스타일을 특정 클래스로 제한하거나 QMessageBox 버튼을 위한 예외 처리 */
            QPushButton { padding: 8px 15px; border-radius: 5px; font-weight: bold; color: white; border: none; }
            QPushButton:hover { opacity: 0.9; }
            
            /* QMessageBox 버튼 복구 */
            QMessageBox QPushButton {
                background-color: #007bff; /* 파란색 */
                color: white;
                border: 1px solid #0056b3;
                min-width: 60px;
            }
            QMessageBox QPushButton:hover {
                background-color: #0056b3;
            }
            
            QTextEdit { background-color: #1e1e1e; color: #00ff00; font-family: 'Consolas', 'Monospace'; border-radius: 5px; padding: 10px; }
            
            /* [신규] 툴팁 기본 박스 스타일 (내부 텍스트는 HTML로 제어) */
            QToolTip { 
                background-color: #ffffff; 
                border: 1px solid #767676; 
                padding: 1px; 
                border-radius: 2px;
                opacity: 230; 
            }
        """)

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
        
        self.lbl_main_title = QLabel("🚀 KipoStock Lite V2.64 GOLD")
        self.lbl_main_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_main_title.setFont(QFont("ARockwell Extra Bold", 26, QFont.Weight.Bold))
        self.lbl_main_title.setStyleSheet("color: #2c3e50;")
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
        self.input_timer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.input_timer.setStyleSheet("""
            QLineEdit {
                background-color: #ffffff;
                border: 2px solid #adb5bd;
                border-radius: 6px;
                font-weight: bold;
                font-size: 15px;
                color: #2c3e50;
            }
        """)
        
        self.btn_timer_toggle = QPushButton("▶")
        self.btn_timer_toggle.setFixedSize(28, 28)
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
        
        # Always on Top Button (Fixed to Right)
        self.btn_top = QPushButton("📍")
        self.btn_top.setCheckable(True)
        self.btn_top.setFixedSize(40, 40)
        self.btn_top.setToolTip(self._style_tooltip("📍 [핀 고정: 항상 위에]\n창을 맨 앞으로 고정"))
        self.btn_top.setStyleSheet("""
            QPushButton { background-color: #f8f9fa; border-radius: 5px; font-size: 18px; border: 1px solid #ddd; color: #aaa; }
            QPushButton:checked { background-color: #17a2b8; color: white; border: 1px solid #138496; }
            QPushButton:hover { background-color: #e2e6ea; }
        """)
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
        settings_group = QGroupBox("⚙️ Settings")
        # [수정] 배경색: 은은한 크림색 (#fffcf5) + 폰트 스타일 강화
        settings_group.setStyleSheet("QGroupBox { background-color: #fffcf5; border: 1px solid #ccc; border-radius: 8px; margin-top: 10px; padding-top: 15px; } QGroupBox::title { font-size: 15px; font-weight: bold; color: #333; subcontrol-origin: margin; left: 10px; }")
        settings_layout = QVBoxLayout()
        settings_layout.setSpacing(12)

        # Condition Select (0-19) & Max Stocks
        cond_row_layout = QHBoxLayout()
        # [수정] 라벨 볼드 처리
        cond_label = QLabel("<b>조건식 선택 (0-9)</b>")
        cond_row_layout.addWidget(cond_label)
        
        cond_row_layout.addStretch()
        
        # [이동] 종목수 (Max Stocks) / [수정] 라벨 볼드 처리
        cond_row_layout.addWidget(QLabel("<b>종목수</b>"))
        self.input_max = QLineEdit()
        self.input_max.setFixedWidth(35)
        self.input_max.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.input_max.setStyleSheet("border: 2px solid black; border-radius: 4px; padding: 2px; font-weight: bold;")
        self.input_max.setToolTip(self._style_tooltip("🎯 [최대 종목수]\n계좌 최대 보유 개수"))
        cond_row_layout.addWidget(self.input_max)
        
        self.cond_btn_layout = QGridLayout() # [Lite V1.0] 10개 원형 레이아웃
        self.cond_btn_layout.setSpacing(8) # [수정] 가로/세로 간격 8px로 통일 (0-1 세로와 0-2 가로 일치)
        self.cond_buttons = []
        # State: 0 (Gray/Off), 1 (Red/Qty), 2 (Green/Amt), 3 (Blue/Pct)
        self.cond_states = [0] * 10
        
        for i in range(10):
            btn = QPushButton(str(i))
            # [Lite] 원형 버튼 디자인: 지름 36px, Border-radius 18px (완전한 원형)
            btn.setFixedSize(36, 36) 
            btn.setStyleSheet("background-color: #e0e0e0; color: #333; font-weight: bold; border-radius: 18px; padding: 0px; font-size: 14px;")
            btn.setToolTip(self._style_tooltip(f"🔍 [조건식 {i}번]\n클릭하여 전략 변경"))
            btn.clicked.connect(lambda checked, idx=i: self.on_cond_clicked(idx))
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
        
        # Start
        lbl_start = QLabel("시작")
        lbl_start.setFixedWidth(25) # 너비 고정으로 가변성 억제
        time_layout.addWidget(lbl_start)
        self.input_start_time = QLineEdit()
        self.input_start_time.setFixedWidth(50)
        self.input_start_time.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.input_start_time.setStyleSheet("border: 1px solid #ccc; border-radius: 4px; font-weight: bold; font-size: 14px; padding: 1px;")
        time_layout.addWidget(self.input_start_time)
        
        time_layout.addSpacing(6) # 간격 최적화
        
        # End
        lbl_end = QLabel("종료")
        lbl_end.setFixedWidth(25)
        time_layout.addWidget(lbl_end)
        self.input_end_time = QLineEdit()
        self.input_end_time.setFixedWidth(50)
        self.input_end_time.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.input_end_time.setStyleSheet("border: 1px solid #ccc; border-radius: 4px; font-weight: bold; font-size: 14px; padding: 1px;")
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
        strategy_group = QGroupBox("💎 매수 전략 (Buying Strategy)")
        # [수정] 배경색: 신뢰감을 주는 은은한 민트색 (#f0fbf5)
        strategy_group.setStyleSheet("QGroupBox { background-color: #f0fbf5; border: 1px solid #28a745; border-radius: 8px; margin-top: 5px; padding: 5px; font-weight: bold; } QGroupBox::title { font-size: 14px; font-weight: bold; color: #155724; }")
        strat_vbox = QVBoxLayout()
        strat_vbox.setContentsMargins(5, 10, 5, 5) # [수정] 좌측 여백 축소
        strat_vbox.setSpacing(6)

        # Helper function to create TP/SL inputs
        def create_tpsl_inputs(color):
            tp = QLineEdit("12.0")
            tp.setFixedWidth(45) # [수정] 너비 확장 (35 -> 45)
            tp.setAlignment(Qt.AlignmentFlag.AlignCenter)
            # [수정] 폰트 크기 확대 (12px -> 15px) 및 패딩 조정
            tp.setStyleSheet(f"border: 1px solid {color}; border-radius: 4px; font-weight: bold; font-size: 15px; color: #dc3545; padding: 1px;")
            tp.setToolTip(self._style_tooltip("📈 [익절 (%)]\n목표 수익률 달성 시 매도"))
            
            sl = QLineEdit("-1.2")
            sl.setFixedWidth(45) # [수정] 너비 확장 (35 -> 45)
            sl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            # [수정] 폰트 크기 확대 (12px -> 15px) 및 패딩 조정
            sl.setStyleSheet(f"border: 1px solid {color}; border-radius: 4px; font-weight: bold; font-size: 15px; color: #007bff; padding: 1px;")
            sl.setToolTip(self._style_tooltip("📉 [손절 (%)]\n손실 제한 수익률 도달 시 매도"))
            return tp, sl

        # Strategy UI Header (TP/SL labels)
        header_layout = QHBoxLayout()
        # [수정] 헤더와 아래 입력창 사이의 간격을 줄이기 위해 여백 조정
        header_layout.setContentsMargins(0, 8, 0, 0) # 위쪽에만 마진을 주어 아래쪽과 밀착
        # 타이틀이 위로 올라가 있으므로, 입력창(60) + 토글(28) 너비만큼 띄워줌 (여백 포함 약 100)
        header_layout.addSpacing(100) 
        header_layout.addStretch()
        
        lbl_tp_hdr = QLabel("익절(%)")
        lbl_sl_hdr = QLabel("손절(%)")
        lbl_tp_hdr.setFixedWidth(45); lbl_sl_hdr.setFixedWidth(45)
        lbl_tp_hdr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_sl_hdr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_tp_hdr.setStyleSheet("color: #666; font-size: 11px; font-weight: bold;")
        lbl_sl_hdr.setStyleSheet("color: #666; font-size: 11px; font-weight: bold;")
        
        header_layout.addWidget(lbl_tp_hdr)
        header_layout.addWidget(lbl_sl_hdr)
        strat_vbox.addLayout(header_layout)

        # 1. Qty Mode (Red)
        qty_vbox = QVBoxLayout()
        qty_vbox.setSpacing(2)
        lbl_qty = QLabel("🔴 1주 매수")
        lbl_qty.setStyleSheet("color: #dc3545; font-weight: bold; font-size: 13px;")
        
        qty_row = QHBoxLayout()
        self.input_qty_val = QLineEdit("1")
        self.input_qty_val.setReadOnly(True)
        self.input_qty_val.setFixedWidth(50) # [수정] 슬림화 (60 -> 50)
        self.input_qty_val.setStyleSheet("background-color: #f0f0f0; border: 2px solid #dc3545; border-radius: 5px; padding: 2px; font-weight: bold; font-size: 15px; color: #555;")
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
        self.input_amt_val.setFixedWidth(90)
        self.input_amt_val.setStyleSheet("border: 2px solid #28a745; border-radius: 5px; padding: 2px; font-weight: bold; font-size: 15px;")
        self.input_amt_val.setToolTip(self._style_tooltip("🟢 [금액 매수]\n설정 금액만큼 주문 (예: 100만)"))
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
        self.input_pct_val.setFixedWidth(50) # [수정] 슬림화 (60 -> 50)
        self.input_pct_val.setStyleSheet("border: 2px solid #007bff; border-radius: 5px; padding: 2px; font-weight: bold; font-size: 15px;")
        self.input_pct_val.setToolTip(self._style_tooltip("🔵 [비율 매수]\n예수금 대비 % 비율 주문"))
        
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
        self.input_hts_val.setReadOnly(True)
        self.input_hts_val.setFixedWidth(60)
        self.input_hts_val.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.input_hts_val.setStyleSheet("background-color: #f0f0f0; border: 2px solid #fd7e14; border-radius: 5px; padding: 2px; font-weight: bold; font-size: 13px; color: #555;")
        self.input_hts_val.setToolTip(self._style_tooltip("🖐 [직접/HTS 매수]\nHTS 등 외부에서 매수한 종목의 전략"))
        
        self.input_hts_tp, self.input_hts_sl = create_tpsl_inputs("#fd7e14")
        self.input_hts_tp.setFixedWidth(45); self.input_hts_sl.setFixedWidth(45)
        
        hts_row.addWidget(self.input_hts_val)
        hts_row.addStretch()
        hts_row.addWidget(self.input_hts_tp)
        hts_row.addWidget(self.input_hts_sl)
        
        hts_vbox.addWidget(lbl_hts)
        hts_vbox.addLayout(hts_row)
        strat_vbox.addLayout(hts_vbox)

        strategy_group.setLayout(strat_vbox)
        settings_layout.addWidget(strategy_group)

        # Save & Profile Slots Layout
        save_profile_layout = QHBoxLayout()
        save_profile_layout.setSpacing(6) # [수정] 6px 등간격 강제 적용
        
        # [삭제] 시퀀스 자동 버튼 이동 (상단으로) - 타이머는 유지
        
        # 2. 설정 저장 버튼 (그 다음)
        self.btn_save = QPushButton("💾")
        self.btn_save.setToolTip(self._style_tooltip("💾 [설정 저장: 보관소]\n1~3번 슬롯에 현재 설정 저장"))
        self.btn_save.setFixedSize(35, 35) # 35x35 통일
        # [수정] 버튼 폰트 크기 조정 (20px -> 18px)
        self.btn_save.setStyleSheet("background-color: #6c757d; border-radius: 4px; color: white; border: 1px solid #5a6268; font-size: 18px; padding: 0px; text-align: center;")
        self.btn_save.clicked.connect(self.on_save_button_clicked)
        save_profile_layout.addWidget(self.btn_save)

        # 시퀀스 버튼용 타이머
        self.seq_blink_timer = QTimer(self)
        self.seq_blink_timer.setInterval(1000)
        self.seq_blink_timer.timeout.connect(self.blink_seq_button)
        self.is_seq_blink_on = False
        
        self.profile_buttons = []
        for i in range(1, 4):
            btn = QPushButton(str(i))
            btn.setFixedSize(35, 35) # 크기 유지
            # [수정] 다른 버튼들과 폰트 크기(18px) 통일
            btn.setStyleSheet("background-color: #ffffff; border: 1px solid #999; border-radius: 4px; font-weight: 900; color: #000000; padding: 0px; font-size: 18px; font-family: 'Arial';")
            btn.setToolTip(self._style_tooltip(f"📂 [프로필 {i}번: 슬롯]\n설정 불러오기 또는 저장"))
            btn.clicked.connect(lambda checked, idx=i: self.on_profile_clicked(idx))
            save_profile_layout.addWidget(btn)
            self.profile_buttons.append(btn)
            
        settings_layout.addLayout(save_profile_layout)
        
        # [신규] 'M' 버튼 (수동 전용)
        self.btn_manual = QPushButton("M")
        self.btn_manual.setFixedSize(35, 35)
        # [수정] M 버튼 초록색으로 변경 (START 버튼과 통일)
        self.btn_manual.setStyleSheet("background-color: #28a745; border: 1px solid #1e7e34; border-radius: 4px; font-weight: 900; color: white; padding: 0px; font-size: 18px; font-family: 'Arial';")
        self.btn_manual.setToolTip(self._style_tooltip("💚 [수동 모드: M]\n자동 시퀀스 없이 수동 시작 (1~3번은 수동 불가)"))
        self.btn_manual.clicked.connect(lambda: self.on_profile_clicked("M"))
        save_profile_layout.addWidget(self.btn_manual)
        
        settings_layout.addStretch()
        settings_group.setLayout(settings_layout)
        settings_group.setContentsMargins(5, 5, 5, 5) # 여백 축소
        left_layout.addWidget(settings_group)

        # 2. Real-time List
        rt_group = QGroupBox("📋 실시간 조건식")
        # [신규] 배경색: 차분한 웜 그레이 (#fdfaf8)
        rt_group.setStyleSheet("QGroupBox { background-color: #fdfaf8; border: 1px solid #ccc; border-radius: 8px; margin-top: 10px; padding-top: 15px; } QGroupBox::title { font-size: 14px; font-weight: bold; color: #333; subcontrol-origin: margin; left: 10px; }")
        rt_layout = QVBoxLayout()
        rt_layout.setContentsMargins(5, 5, 5, 5) # 여백 최소화
        rt_layout.setSpacing(2)
        self.rt_list = QTextEdit()
        self.rt_list.setReadOnly(True)
        self.rt_list.setStyleSheet("background-color: white; color: black; border: 1px solid #ddd;")
        rt_layout.addWidget(self.rt_list)
        
        rt_group.setLayout(rt_layout)
        left_layout.addWidget(rt_group)

        # === Right Panel: Controls & Logs ===

        right_panel = QFrame()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)

        # Header Layout Removed (Moved to Global)

        # Control Buttons
        btn_layout = QHBoxLayout()
        
        # [이동 완료] 오토시퀀스 버튼 (파란색 대형)
        self.btn_seq_auto = QPushButton("▶ SEQ AUTO")
        self.btn_seq_auto.setCheckable(True)
        self.btn_seq_auto.setToolTip(self._style_tooltip("🔄 [SEQ AUTO: 자동 항법]\n시간표에 따라 프로필 자동 전환 (점멸 시 작동 중)"))
        self.btn_seq_auto.setStyleSheet("background-color: #17a2b8; min-height: 35px; max-height: 35px; padding: 0px; font-size: 14px; color: white; border: 2px solid #138496; border-radius: 4px; font-weight: bold;")
        self.btn_seq_auto.clicked.connect(self.on_seq_auto_toggled)
        
        self.btn_start = QPushButton("▶ START")
        self.btn_start.setToolTip(self._style_tooltip("🚀 [START: 수동 점화]\n설정된 값으로 즉시 매매 시작"))
        self.btn_start.setStyleSheet("background-color: #28a745; min-height: 35px; max-height: 35px; padding: 0px; font-size: 14px; border: 2px solid #1e7e34; border-radius: 4px; font-weight: bold; color: white;")
        self.btn_start.clicked.connect(self.on_start_clicked)
        
        self.btn_stop = QPushButton("⏹ STOP")
        self.btn_stop.setToolTip(self._style_tooltip("⏹ [STOP: 긴급 정지]\n모든 매매 감시 즉시 중단"))
        self.btn_stop.setStyleSheet("background-color: #dc3545; min-height: 35px; max-height: 35px; padding: 0px; font-size: 14px; border: 2px solid #bd2130; border-radius: 4px; color: white; font-weight: bold;")
        self.btn_stop.clicked.connect(self.on_stop_clicked)
        self.btn_stop.setEnabled(False) # [수정] 초기 상태는 비활성화 (READY)
        
        self.btn_report = QPushButton("📊 REPORT")
        self.btn_report.setToolTip(self._style_tooltip("📊 [REPORT: 실시간 성과]\n매매 손익/계좌 현황 요약"))
        self.btn_report.setStyleSheet("background-color: #ffc107; min-height: 35px; max-height: 35px; padding: 0px; font-size: 14px; border: 2px solid #e0a800; border-radius: 4px; color: #212529; font-weight: bold;")
        def on_report():
            self.animate_button_click(self.btn_report)
            self.worker.schedule_command('report')
        self.btn_report.clicked.connect(on_report)

        btn_layout.addWidget(self.btn_seq_auto) # [신규] 맨 앞에 추가
        btn_layout.addWidget(self.btn_start)
        btn_layout.addWidget(self.btn_stop)
        btn_layout.addWidget(self.btn_report)
        right_layout.addLayout(btn_layout)

        # System Log
        log_group = QGroupBox("📄 System Logs")
        log_layout = QVBoxLayout()
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        log_layout.addWidget(self.log_text)
        log_group.setLayout(log_layout)
        right_layout.addWidget(log_group)

        # Command Input
        input_layout = QHBoxLayout()
        input_label = QLabel("명령어 입력:")
        self.cmd_input = QLineEdit()
        self.cmd_input.setToolTip(self._style_tooltip("⌨️ [명령어 직접 입력]\nstart, stop 등 텍스트 명령"))
        self.cmd_input.returnPressed.connect(self.send_command)
        
        btn_send = QPushButton("전송")
        btn_send.setStyleSheet("background-color: #fff; color: #333; border: 1px solid #ccc;")
        btn_send.clicked.connect(self.send_command)

        input_layout.addWidget(input_label)
        input_layout.addWidget(self.cmd_input)
        input_layout.addWidget(btn_send)
        right_layout.addLayout(input_layout)

        # Add panels to body layout
        body_layout.addWidget(left_panel)
        body_layout.addWidget(right_panel)
        body_layout.setStretch(1, 1) # Right panel takes remaining space

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
        if self.btn_seq_auto.isChecked():
           self.btn_seq_auto.setChecked(False)
           self.on_seq_auto_toggled() # 타이머 정지 및 로그 출력
           
        # [신규] 중지 시 UI 잠금 공식 다시 계산 (READY 상태가 될 것이므로)
        QTimer.singleShot(500, lambda: self.lock_ui_for_sequence(self.btn_seq_auto.isChecked()))

    def setup_worker(self):
        self.worker = AsyncWorker(self)
        self.worker.signals.log_signal.connect(self.append_log)
        self.worker.signals.status_signal.connect(self.update_status_ui)
        self.worker.signals.clr_signal.connect(self.log_text.clear)
        self.worker.signals.request_log_signal.connect(self.save_logs_to_file)
        self.worker.signals.auto_seq_signal.connect(self.on_remote_auto_sequence)
        self.worker.signals.condition_loaded_signal.connect(self.refresh_condition_list_ui)
        self.worker.start()

    def on_remote_auto_sequence(self, idx):
        """원격 명령어(auto) 수신 시 특정 프로필부터 시퀀스 시작 또는 중지"""
        # [수정] 끄는 명령(idx=0)인 경우는 매매 중이라도 허용
        if idx == 0:
            self.append_log("🤖 원격 명령어 수신: 시퀀스 자동 모드를 중지합니다.")
            if self.btn_seq_auto.isChecked():
                self.btn_seq_auto.setChecked(False)
                self.on_seq_auto_toggled()
            return

        # [신규] 매매 진행 중(RUNNING)일 때 켜는 명령(idx>=1)은 거부
        current_status = self.lbl_status.text()
        if "RUNNING" in current_status:
            self.log_and_tel("⚠️ 매매 진행 중(RUNNING)에는 자동 시퀀스를 시작할 수 없습니다. 중지(STOP) 후 다시 시도하세요.")
            return

        if not (1 <= idx <= 3):
            self.append_log(f"⚠️ 올바르지 않은 프로필 번호입니다: {idx}")
            return

        self.append_log(f"🤖 원격 명령어 수신: {idx}번 프로필부터 시퀀스를 시작합니다.")
        # [수정] 버튼 상태를 먼저 변경하고 토글 이벤트를 발생시켜야 on_profile_clicked에서 자동 시작이 작동함
        if not self.btn_seq_auto.isChecked():
            self.btn_seq_auto.setChecked(True)
            self.on_seq_auto_toggled()
            
        self.on_profile_clicked(idx)

    def update_status_ui(self, status):
        if status == "RUNNING":
            self.lbl_status.setText("● RUNNING")
            self.lbl_status.setStyleSheet("color: #28a745; margin-left: 10px;")
            self.btn_start.setEnabled(False)
            self.btn_start.setStyleSheet("background-color: #6c757d; min-height: 35px; max-height: 35px; padding: 0px; font-size: 14px; border: 2px solid #545b62; border-radius: 4px; font-weight: bold; color: #ddd;")
        elif status == "WAITING":
            self.lbl_status.setText("● WAITING")
            self.lbl_status.setStyleSheet("color: #ffc107; margin-left: 10px;") # 노란색
            self.btn_start.setEnabled(True) 
            self.btn_start.setStyleSheet("background-color: #28a745; min-height: 35px; max-height: 35px; padding: 0px; font-size: 14px; border: 2px solid #1e7e34; border-radius: 4px; font-weight: bold; color: white;")
        else:
            self.lbl_status.setText("● READY")
            self.lbl_status.setStyleSheet("color: #6c757d; margin-left: 10px;")
            
            # [수정] READY 상태에서는 현재 모드(M vs Auto)에 따라 버튼 활성화를 엄격히 구분
            # M모드(Manual)라면 START 활성화, SEQ AUTO 비활성화(회색)
            # [보강] getattr와 strip, upper를 사용하여 어떤 환경에서도 M 모드를 정확히 인식하도록 함
            p_idx = str(getattr(self, 'current_profile_idx', '')).strip().upper()
            if p_idx == "M":
                 self.btn_start.setEnabled(True)
                 self.btn_start.setStyleSheet("background-color: #28a745; min-height: 35px; max-height: 35px; padding: 0px; font-size: 14px; border: 2px solid #1e7e34; border-radius: 4px; font-weight: bold; color: white;")
                 # M 모드 시 오토시퀀스 버튼 비활성화 (회색)
                 self.btn_seq_auto.setEnabled(False)
                 self.btn_seq_auto.setStyleSheet("background-color: #6c757d; min-height: 35px; max-height: 35px; padding: 0px; font-size: 14px; color: #ddd; border: 2px solid #545b62; border-radius: 4px; font-weight: bold;")
            else:
                 # Auto 모드에서는 Start 버튼 기본 비활성화 (시퀀스 사용 유도)
                 self.btn_start.setEnabled(False)
                 self.btn_start.setStyleSheet("background-color: #6c757d; min-height: 35px; max-height: 35px; padding: 0px; font-size: 14px; border: 2px solid #545b62; border-radius: 4px; font-weight: bold; color: #ddd;")
                 # Auto 모드에서는 오토시퀀스 버튼 활성화 (파란색)
                 self.btn_seq_auto.setEnabled(True)
                 if not self.btn_seq_auto.isChecked():
                     self.btn_seq_auto.setStyleSheet("background-color: #17a2b8; min-height: 35px; max-height: 35px; padding: 0px; font-size: 14px; color: white; border: 2px solid #138496; border-radius: 4px; font-weight: bold;")
        
        # [신규] 상태 변경 시 UI 잠금 상태 동적 업데이트 (READY 시 잠금 해제 목적)
        self.lock_ui_for_sequence(self.btn_seq_auto.isChecked())

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
                <td valign="top" style="width: 70px; color: #ccc; font-family: 'Courier New'; font-size: 11px; white-space: nowrap;">
                    [{timestamp}]
                </td>
                <td valign="top" style="padding-left: 5px; color: #00ff00; font-family: 'Consolas', 'Monospace';">
                    {text_html if '<font color' in text_html or '<span style' in text_html else f"<span>{text_html}</span>"}
                </td>
            </tr>
        </table>
        """
        self.log_text.append(full_html)
        
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
        sb = self.log_text.verticalScrollBar()
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

    def send_command(self):
        cmd = self.cmd_input.text().strip()
        if cmd:
            if cmd.upper() == 'PRINT': self.export_log()
            elif cmd.lower() == 'clr':
                self.log_text.clear()
                self.append_log("🧹 로그가 초기화되었습니다.")
            elif cmd.lower() == 'start': self.on_start_clicked()
            elif cmd.lower() == 'stop': self.on_stop_clicked()
            else: self.worker.schedule_command('custom', cmd)
            self.cmd_input.clear()

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
        
        # 완전한 원형 스타일 (Border-radius: 18px / Width=Height=36px)
        btn.setStyleSheet(f"""
            QPushButton {{ 
                background-color: {bg_color}; 
                color: {text_color}; 
                font-weight: bold; 
                border-radius: 18px;
                border: 1px solid rgba(0,0,0,0.1);
                font-size: 14px;
                padding: 0px;
            }}
            QPushButton:hover {{
                opacity: 0.9;
                border: 2px solid white;
            }}
        """)

    def refresh_condition_list_ui(self):
        """실시간 조건식 리스트 패널을 현재 선택된 상태에 맞춰 갱신"""
        try:
            # 1. 고유한 검색식 이름 사전 및 활성 상태 접근
            condition_map = {}
            active_set = set()
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
                if state > 0:
                    active_count += 1
                    name = condition_map.get(str(i), f"조건식 {i}")
                    m_name = mode_names[state]
                    m_color = mode_colors[state]
                    
                    # [신규] 활성 상태(API 등록 완료) 아이콘
                    status_icon = " 📡" if str(i) in active_set else ""
                    
                    # HTML 포맷: 색상 적용된 이름과 모드 표시 + 아이콘
                    html += f"&nbsp;• <span style='color:{m_color};'><b>{i}: {name}</b> ({m_name}){status_icon}</span><br>"
            
            if active_count == 0:
                html = "<br><center>(선택된 조건식이 없습니다)</center>"
                
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
        """[V2.0] 매수 방식(시장/현재) 토글 스타일 업데이트"""
        btn_map = {
            'qty': (self.btn_qty_type, "#dc3545"),
            'amount': (self.btn_amt_type, "#28a745"),
            'percent': (self.btn_pct_type, "#007bff")
        }
        btn, color = btn_map.get(strat_key)
        if not btn: return

        if btn.isChecked():
            btn.setText("현")
            # 현재가는 차분한 실버/회색 (완전 원형)
            btn.setStyleSheet("background-color: #f1f3f5; color: #495057; border: 2px solid #adb5bd; border-radius: 13px; font-weight: bold; font-size: 11px; padding: 0px;")
        else:
            btn.setText("시")
            # 시장가는 강렬한 유색 (완전 원형)
            btn.setStyleSheet(f"background-color: {color}; color: white; border: 2px solid {color}; border-radius: 13px; font-weight: bold; font-size: 11px; padding: 0px;")

    def update_strategy_ui(self, from_user_click=False):
        # Legacy stub for backward compatibility if called elsewhere
        pass

    def format_input_value(self, text):
        # Legacy stub
        pass

    def load_settings_to_ui(self, profile_idx=None, keep_seq_auto=False):
        try:
            with open(self.settings_file, 'r', encoding='utf-8') as f:
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

            # [수정] 시퀀스 버튼 로드 및 UI 반영 (전환 시에는 현재 상태 유지)
            if not keep_seq_auto:
                is_seq = target.get('sequence_auto', False)
                self.btn_seq_auto.setChecked(is_seq)
                self.on_seq_auto_toggled() # 상태에 따른 스타일 적용
            
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

            # [최우선] 현재 프로필 인덱스 즉시 설정
            self.current_profile_idx = profile_idx
            self.update_profile_buttons_ui()

            # [신규] 상호 배타적 모드 적용 (M vs 1,2,3)
            # update_profile_buttons_ui 내부 로직과 별개로 기능적 제한 적용
            if str(profile_idx).strip().upper() == "M":
                # M (수동) 모드: 시작 버튼 활성화, 시퀀스 버튼 비활성화 & 끄기
                # [보강] 데이터 로딩 실패 여부와 상관없이 M모드면 START 버튼을 무조건 활성화
                self.btn_start.setEnabled(True)
                self.btn_start.setStyleSheet("background-color: #28a745; min-height: 35px; max-height: 35px; padding: 0px; font-size: 14px; border: 2px solid #1e7e34; border-radius: 4px; font-weight: bold; color: white;")
                self.btn_seq_auto.setChecked(False) # 강제 끄기
                self.btn_seq_auto.setEnabled(False) 
                self.btn_seq_auto.setStyleSheet("background-color: #6c757d; min-height: 35px; max-height: 35px; padding: 0px; font-size: 14px; color: #ddd; border: 2px solid #545b62; border-radius: 4px; font-weight: bold;")
            else:
                # 1,2,3 (오토) 모드: 시작 버튼 비활성화 (오토시퀀스로만 작동 유도), 시퀀스 버튼 활성화
                self.btn_start.setEnabled(False)
                self.btn_start.setStyleSheet("background-color: #6c757d; min-height: 35px; max-height: 35px; padding: 0px; font-size: 14px; border: 2px solid #545b62; border-radius: 4px; font-weight: bold; color: #ddd;")
                self.btn_seq_auto.setEnabled(True)
                if not self.btn_seq_auto.isChecked():
                    self.btn_seq_auto.setStyleSheet("background-color: #17a2b8; min-height: 35px; max-height: 35px; padding: 0px; font-size: 14px; color: white; border: 2px solid #138496; border-radius: 4px; font-weight: bold;")


            # [신규] 로드 직후 리스트 리프레시 및 운영 시간 동기화
            QTimer.singleShot(700, self.refresh_condition_list_ui)
            # [수정] 무조건 현재 상태를 다시 업데이트하여 START 버튼 활성화 보장 (READY 강제)
            # 0.5s 뒤에 한 번 더 확실하게 호출하여 초기화 지연 문제 해결
            QTimer.singleShot(500, lambda: self.update_status_ui("READY"))
            
            # [강제 보강] 만약 M 모드라면 START 버튼 스타일 더 확실하게 한 번 더 적용
            if str(profile_idx).strip().upper() == "M":
                QTimer.singleShot(600, lambda: self.btn_start.setEnabled(True))
                QTimer.singleShot(600, lambda: self.btn_start.setStyleSheet("background-color: #28a745; min-height: 35px; max-height: 35px; padding: 0px; font-size: 14px; border: 2px solid #1e7e34; border-radius: 4px; font-weight: bold; color: white;"))
            
            # [신규] 로드된 설정에 맞춰 MarketHour 즉시 동기화 (WAITING 버그 해결)
            try:
                sh, sm = map(int, target.get('start_time', '09:00').split(':'))
                eh, em = map(int, target.get('end_time', '15:20').split(':'))
                MarketHour.set_market_hours(sh, sm, eh, em)
            except: pass
            
        except Exception as e:
            self.append_log(f"설정 불러오기 실패: {e}")

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
                'sequence_auto': self.btn_seq_auto.isChecked(), # [수정] 시퀀스 버튼 상태 저장
                'trade_timer_val': self.input_timer.text().strip() # [신규] 타이머 값 저장
            }

            if profile_idx is not None:
                # 특정 프로필에 저장
                with open(self.settings_file, 'r', encoding='utf-8') as f:
                    settings = json.load(f)
                
                if 'profiles' not in settings: settings['profiles'] = {}
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
                    'trade_timer_val': self.input_timer.text().strip() # [신규] 루트 타이머 값 저장
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
                    self.on_start_clicked() # UI 동기화
                elif "READY" in self.lbl_status.text() and not restart_if_running:
                    # If engine is READY and not restarting, but settings changed,
                    # ensure UI reflects the new state without starting the engine.
                    # This might be a no-op for UI sync if no start/stop is involved.
                    pass
                elif "STOPPED" in self.lbl_status.text() and not restart_if_running:
                    # If engine is STOPPED and not restarting, ensure UI reflects new state.
                    # This might be a no-op for UI sync if no start/stop is involved.
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
        is_seq_before_load = self.btn_seq_auto.isChecked()

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
            if str(idx) != "M" and is_seq_before_load and self.btn_seq_auto.isChecked():
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
        self.btn_save.setStyleSheet("background-color: #6c757d; border-radius: 4px; color: white; border: 1px solid #5a6268; font-size: 18px; padding: 0px; text-align: center;")
        self.update_profile_buttons_ui()

    # [미씽 메서드 복구] 프로필 버튼 UI 업데이트 (데이터 유무 표시)
    def update_profile_buttons_ui(self):
        try:
            settings = {}
            if os.path.exists(self.settings_file):
                with open(self.settings_file, 'r', encoding='utf-8') as f:
                    settings = json.load(f)
            
            profiles = settings.get('profiles', {})
            
            for i, btn in enumerate(self.profile_buttons):
                idx = i + 1
                has_data = str(idx) in profiles
                is_selected = (str(self.current_profile_idx) == str(idx))
                
                # 기본 스타일
                base_style = "border-radius: 4px; font-weight: 900; padding: 0px; font-size: 16px; font-family: 'Arial';"
                
                if is_selected:
                    # 선택됨: 파란색 테두리 또는 배경
                    style = f"background-color: #e3f2fd; border: 2px solid #007bff; color: #007bff; {base_style}"
                elif has_data:
                    # 데이터 있음: 회색 배경 (사용자 요청)
                    style = f"background-color: #cccccc; border: 1px solid #999; color: #333; {base_style}"
                else:
                    # 비어있음: 흰색
                    style = f"background-color: #ffffff; border: 1px solid #ddd; color: #ccc; {base_style}"
                
                btn.setStyleSheet(style)

            # [신규] M 버튼 스타일 업데이트
            if hasattr(self, 'btn_manual'):
                is_m_selected = (str(self.current_profile_idx) == "M")
                has_m_data = "M" in profiles
                
                base_m_style = "border-radius: 4px; font-weight: 900; padding: 0px; font-size: 18px; font-family: 'Arial';"
                
                if is_m_selected:
                    # M 선택됨: 진한 초록색 배경 + 흰색 글씨 + 테두리 강조 (START와 통일)
                    style = f"background-color: #28a745; border: 2px solid #1e7e34; color: white; {base_m_style}"
                elif has_m_data:
                    # M 데이터 있음: 약간 밝은 초록
                    style = f"background-color: #34ce57; border: 1px solid #28a745; color: white; {base_m_style}"
                else:
                    # M 비어있음
                    style = f"background-color: #d1f2d1; border: 1px solid #28a745; color: #1e7e34; {base_m_style}"
                
                self.btn_manual.setStyleSheet(style)
                    
        except Exception as e:
            self.append_log(f"UI 업데이트 오류: {e}")

    def on_save_button_clicked(self):
        """설정 저장 버튼 클릭 시: 저장 모드 진입 및 점멸 시작"""
        if not self.is_save_mode:
            self.is_save_mode = True
            self.profile_blink_timer.start()
            self.append_log("💡 저장할 번호(1~3, M)를 선택하세요. (다시 누르면 취소)")
            self.btn_save.setStyleSheet("background-color: #ffc107; color: black; border-radius: 4px; font-weight: bold; font-size: 18px; padding: 0px; text-align: center; border: 1px solid #e0a800;")
        else:
            self.stop_save_mode()
            self.append_log("❌ 저장 모드가 취소되었습니다.")

    def on_seq_auto_toggled(self):
        """시퀀스 자동 버튼 토글 시 처리"""
        is_on = self.btn_seq_auto.isChecked()
        
        if is_on:
            # [신규] 매매 진행 중(RUNNING)일 때는 시퀀스 켜기 차단
            current_status = self.lbl_status.text()
            if "RUNNING" in current_status:
                self.log_and_tel("⚠️ 매매 진행 중(RUNNING)에는 자동 시퀀스를 시작할 수 없습니다. 중지(STOP) 후 다시 시도하세요.")
                self.btn_seq_auto.blockSignals(True)
                self.btn_seq_auto.setChecked(False) # 다시 끔
                self.btn_seq_auto.blockSignals(False)
                return
            
            # [신규] 장외 시간 및 예약 시간 체크
            now = datetime.datetime.now()
            
            # 1. 휴장일 또는 주말 체크
            if not MarketHour._is_weekday() or MarketHour.is_holiday():
                self.show_timed_message("작동 제한", "오늘은 주말 또는 공휴일(휴장일)입니다.\n2초 후 자동으로 닫힙니다.", 2000)
                self.btn_seq_auto.blockSignals(True)
                self.btn_seq_auto.setChecked(False)
                self.btn_seq_auto.blockSignals(False)
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
                self.btn_seq_auto.blockSignals(True)
                self.btn_seq_auto.setChecked(False)
                self.btn_seq_auto.blockSignals(False)
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
                        next_idx = self.current_profile_idx + 1
                        if next_idx <= 3:
                            # 다음 프로필 로드 시도
                            self.append_log(f"⏩ 현재 시간({now_time.strftime('%H:%M')})이 {self.current_profile_idx}번 종료 시간({et_str})보다 늦어 다음 프로필로 건너뜁니다.")
                            self.load_settings_to_ui(profile_idx=next_idx, keep_seq_auto=True)
                            skipped = True
                            continue # 다시 루프 돌며 시간 체크
                        else:
                            self.append_log("🏁 모든 프로필의 운영 시간이 지났습니다. 시퀀스를 종료합니다.")
                            self.btn_seq_auto.setChecked(False)
                            self.on_seq_auto_toggled()
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
                    current_idx = self.current_profile_idx if self.current_profile_idx is not None else 1
                    
                    # 1. 고유한 검색식 이름 사전 접근 (RT 서버 연동)
                    condition_map = {}
                    if self.worker and hasattr(self.worker, 'chat_command') and hasattr(self.worker.chat_command, 'rt_search'):
                         condition_map = self.worker.chat_command.rt_search.condition_map

                    self.append_log("="*50)
                    self.append_log("📋 [시퀀스 작동 예약 상세 목록]")
                    
                    found_any = False
                    # [수정] 파일에서 읽는 대신 현재 UI 메모리(혹은 저장된 데이터)를 기반으로 하되
                    # 현재 프로필의 "실제 UI 상태"를 우선적으로 반영하여 리포트 출력
                    for i in range(current_idx, 4):
                        p = profiles.get(str(i))
                        if not p and i != current_idx: continue
                        
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
                        if i == current_idx:
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
                self.btn_seq_auto.setStyleSheet("background-color: #6c757d; min-height: 35px; max-height: 35px; padding: 0px; font-size: 14px; color: #ddd; border: 2px solid #545b62; border-radius: 4px; font-weight: bold;")
            else:
                # 일반 모드면 파란색 활성화
                self.btn_seq_auto.setStyleSheet("background-color: #17a2b8; min-height: 35px; max-height: 35px; padding: 0px; font-size: 14px; color: white; border: 2px solid #138496; border-radius: 4px; font-weight: bold;")
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
        if not self.btn_seq_auto.isChecked():
            self.seq_blink_timer.stop()
            return

        self.is_seq_blink_on = not self.is_seq_blink_on
        if self.is_seq_blink_on:
            # 밝은 노랑 (눈에 확 띔)
            self.btn_seq_auto.setStyleSheet("background-color: #fff59d; min-height: 35px; max-height: 35px; padding: 0px; font-size: 14px; color: #0000ff; border: 2px solid #fbc02d; border-radius: 4px; font-weight: bold;")
        else:
            # 진한 파랑 (작동 중임을 강조) - [수정] 경계선 두께 2px로 통일하여 크기 변동(Jitter) 방지
            self.btn_seq_auto.setStyleSheet("background-color: #17a2b8; min-height: 35px; max-height: 35px; padding: 0px; font-size: 14px; color: white; border: 2px solid #138496; border-radius: 4px; font-weight: bold;")

    def handle_end_time_event(self, current_time_str):
        """매 초마다 호출되는 이벤트 처리 (9시 예약 시작 및 프로필 전환)"""
        # [신규] 장 시작 예약 처리 (사용자 설정 시작 시간에 맞춰 자동 가동)
        user_start_time = self.input_start_time.text() + ":00"
        if current_time_str == user_start_time and self.btn_seq_auto.isChecked():
            # 만약 현재 실행 중이 아니라면 (예약 대기 상태였다면) 시작
            status = self.lbl_status.text()
            if "READY" in status or "WAITING" in status:
                self.log_and_tel(f"🔔 [장 시작 예약] 설정된 시작 시간({self.input_start_time.text()}) 정각입니다. 시퀀스를 자동으로 시작합니다!")
                self.on_start_clicked(force=True)
                return

        """종료 시간 도달 시 시퀀스 로직 처리"""
        # 1. 시퀀스 자동 모드인지 확인
        is_seq_auto = self.btn_seq_auto.isChecked() # [수정] 버튼 상태 확인
        current_idx = self.current_profile_idx

        if is_seq_auto and current_idx is not None:
            # [시퀀스 ON] 다음 프로필로 전환 시도
            next_idx = current_idx + 1
            if next_idx <= 3: # 최대 3번 프로필까지만
                # 다음 프로필 데이터 확인
                try:
                    if os.path.exists(self.settings_file):
                        with open(self.settings_file, 'r', encoding='utf-8') as f:
                            settings = json.load(f)
                            if 'profiles' in settings and str(next_idx) in settings['profiles']:
                                self.log_and_tel(f"🔄 시퀀스 자동: 프로필 {current_idx}번 종료 -> {next_idx}번으로 전환합니다.")
                                
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
            self.btn_seq_auto.setChecked(False)
            self.on_seq_auto_toggled() 
            
            # [추가] UI 완전 초기화 및 버튼 상태 복구
            self.lock_ui_for_sequence(False)
            self.update_status_ui("READY")
            self.append_log("🔓 시퀀스 종료: 모든 UI 조작이 가능합니다.")
            
            self.start_alarm() # 마지막 종료 알람
            self.worker.schedule_command('stop') # 매매 중단
            
            # [수정] 중단 후 약간의 여유를 두고 최종 보고 전송 (worker에 today 추가됨)
            QTimer.singleShot(5000, lambda: self.worker.schedule_command('today'))
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
            
            if self.trade_timer_seconds == 0:
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
