

import sys
import os

sys.path.append(r"D:\Program files\Kipo_Libs")

import asyncio
import json
import datetime
from datetime import timedelta
import traceback
import ast
import time
import requests
import re
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                           QHBoxLayout, QLabel, QLineEdit, QPushButton, 
                           QTextEdit, QFrame, QGridLayout, QMessageBox, QGroupBox,
                           QScrollArea, QRadioButton, QButtonGroup, QCheckBox, QSizePolicy,
                           QSpinBox, QComboBox, QDialog, QFormLayout, QSplitter, QTextBrowser,
                           QStyle, QSlider, QStyleOptionSlider, QWidgetAction, QMenu,
                           QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
                           QFileDialog, QDoubleSpinBox, QProgressBar, QListWidget, QListWidgetItem, QTabWidget, QToolButton) 
from PyQt6.QtCore import (Qt, QThread, pyqtSignal, QObject, QTimer, QEvent, 
                          QSharedMemory, QSize, QUrl, QPoint, QRect)
from PyQt6.QtGui import (QFont, QIcon, QColor, QPalette, QPainter, QPolygon, 
                         QBrush, QPen, QRegion, QKeySequence, QShortcut, QAction)
import winsound
import re
import matplotlib
matplotlib.use('QtAgg')
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter, MaxNLocator # [신규] 명시적 임포트
import warnings
warnings.filterwarnings("ignore", category=UserWarning, message=".*Axes that are not compatible with tight_layout.*")
from trade_logger import session_logger
from kipodb import kipo_db

# 기존 모듈 임포트
from config import telegram_token, telegram_chat_id
from tel_send import tel_send as real_tel_send
from chat_command import ChatCommand
from get_setting import get_setting, cached_setting, get_base_path
import ctypes # [신규] 윈도우 API 호출용
from market_hour import MarketHour
from ranking_bet_engine import RankingBetEngine # [v2.2.0] 실시간 순위 급등 감시 엔진 추가

def load_json_safe(path, retries=5):
    """파일 I/O 충돌을 방지하기 위한 안전한 JSON 로드 함수"""
    for i in range(retries):
        try:
            if not os.path.exists(path): return {}
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            import time
            time.sleep(0.1)
    return {}

# ----------------- Custom Widgets -----------------
class ZoomableTextEdit(QTextEdit):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._font_size = 11
        self._base_style = ""
        # [신규] 이미지 확대/축소 배율 상태 관리
        self._img_scale_idx = 0
        self._img_scales = [480, 600, 900]
        self._img_scale_idx = 0  

    def setBaseStyle(self, style):
        """[신규 v3.0.1] 기본 스타일을 저장하고 현재 줌을 유지하며 적용"""
        self._base_style = style
        self.applyZoomStyle()

    def applyZoomStyle(self, extra_style=""):
        """[신규 v3.0.1] 폰트 크기(줌)를 유지하면서 추가 스타일(테두리 등)을 병합 적용"""
        prop_block = self._base_style
        if extra_style:
            # extra_style에서 중괄호 세트가 올 경우를 대비해 유연하게 병합
            if "{" in extra_style:
                # 이미 셀렉터가 포함된 구문이라면 그대로 이어붙임
                self.setStyleSheet(f"QTextEdit {{ {prop_block} }}\n{extra_style}\nQTextEdit {{ font-size: {self._font_size}pt; }}")
                return
            else:
                prop_block += f" {extra_style}"
        
        # [v3.0.1 Fix] 선택자를 명시적으로 감싸서 스타일이 유실되지 않도록 함
        self.setStyleSheet(f"QTextEdit {{ {prop_block}; font-size: {self._font_size}pt; }}")

    def wheelEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            if delta > 0:
                self._font_size = min(30, self._font_size + 1)
            elif delta < 0:
                self._font_size = max(6, self._font_size - 1)
            
            # [Fix v3.0.1] 개별 setStyleSheet 대신 통합 스타일 업데이트 메서드 호출
            self.applyZoomStyle()
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

class WedgeSlider(QSlider):
    """
    [v6.0.0+] 오른쪽으로 갈수록 두꺼워지는 역삼각형(웨지형) 볼륨 슬라이더
    """
    def __init__(self, orientation=Qt.Orientation.Horizontal, parent=None):
        super().__init__(orientation, parent)
        self.setMinimumHeight(30)
        # 기본 스타일 시트를 제거하여 커스텀 페인팅이 잘 보이게 함
        self.setStyleSheet("QSlider { background: transparent; }")

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = self.rect()
        margin_x = 5
        margin_y = 5 # 하단 마진 유지
        w = rect.width() - 2 * margin_x
        h = rect.height() - 2 * margin_y
        
        # [v6.0.4] 바닥면 고정 (Bottom) - 칼같이 수평 유지
        # rect.height()에서 마진을 뺀 지점을 바닥으로 엄격히 고정
        base_y = rect.height() - margin_y 
        
        # [v6.0.4] 상단 예각(Sharp Edge) 강화 - 가시 높이 최대화
        max_h = h - 2 # 위쪽 여유 공간 최소화하여 더 뾰족하게
        min_h = 2     # 시작 높이를 더 낮춰서 극적인 예각 표현
        
        # 활성 영역 비율
        val_ratio = (self.value() - self.minimum()) / (self.maximum() - self.minimum())
        active_w = int(w * val_ratio)
        
        # 칸칸칸 그리기 (Segments)
        num_segments = 18 # [v6.0.4] 더 세밀하게 18단계
        seg_w = w / num_segments
        gap = 1.5 # 간격을 살짝 좁혀서 더 촘촘하고 세련되게
        
        is_light = (getattr(self.window(), 'ui_theme', 'dark') == 'light')
        # 비활성: 딥그레이, 활성: 강렬한 빨간색 (#e74c3c)
        bg_color = QColor("#dcdde1") if is_light else QColor("#2c3e50")
        active_color = QColor("#ff4757") # 더 선명한 빨간색
        
        for i in range(num_segments):
            seg_x = margin_x + i * seg_w
            # 현재 세그먼트의 높이 (바닥 0에서 시작하여 점차 가파르게 상승)
            x_ratio = (i + 1) / num_segments
            # 단순 선형이 아닌 약간의 가중치를 주어 끝이 더 날카로워 보이게 함
            seg_h = min_h + (max_h - min_h) * x_ratio
            
            # 정확한 정수 변환으로 픽셀 오차 및 바닥 어긋남 방지
            target_rect = QRect(int(seg_x), int(base_y - seg_h), int(seg_w - gap), int(seg_h))
            
            # 현재 값이 이 세그먼트까지 왔는지 확인
            if (i + 0.5) / num_segments <= val_ratio:
                color = active_color
            else:
                color = bg_color
            
            painter.setBrush(QBrush(color))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRect(target_rect)

        # 2. 핸들(Handle) 그리기 (세련된 화이트 링)
        handle_x = margin_x + active_w
        handle_r = 5 # 슬라이더의 엣지를 가리지 않게 살짝 작게
        current_h = min_h + (max_h - min_h) * val_ratio
        handle_y = base_y - (current_h / 2)
        
        painter.setBrush(QBrush(QColor("#ffffff")))
        painter.setPen(QPen(active_color, 2)) 
        painter.drawEllipse(QPoint(int(handle_x), int(handle_y)), handle_r, handle_r)
        
        painter.end()

# ----------------- Worker Thread for Asyncio Loop -----------------
class WorkerSignals(QObject):
    log_signal = pyqtSignal(str)
    status_signal = pyqtSignal(str)  # 상태 표시줄 업데이트용
    clr_signal = pyqtSignal()       # [신규] 로그 초기화용
    request_log_signal = pyqtSignal() # [신규] 로그 파일 출력 요청
    auto_seq_signal = pyqtSignal(int) # [신규] 원격 시퀀스 시작 신호 (프로필 번호)
    condition_loaded_signal = pyqtSignal() # [신규] 조건식 목록 로드 완료 신호
    graph_update_signal = pyqtSignal() # [신규] 수익 그래프 업데이트 시그널
    news_signal = pyqtSignal(str)     # [신규 v5.0.1] AI 뉴스 분석 결과 팝업용 시그널
    ai_voice_signal = pyqtSignal(str) # [NEW V5.6.3] 제미나이 AI 음성 대답용 시그널
    report_signal = pyqtSignal(str) # [v6.3.3] 리포트 데이터 (HTML) - dict에서 str로 수정하여 데이터 누락 해결
    perspective_signal = pyqtSignal(list) # [신규 v6.1.17] KipoStock 관점 종목 리스트
    open_config_signal = pyqtSignal() # [신규 v6.1.21] 메인 설정창 팝업 시그널
    open_ai_settings_signal = pyqtSignal() # [신규 v6.1.21] AI 음성 설정창 팝업 시그널
    index_signal = pyqtSignal(dict)    # [신규 v4.4.4] 지수 정보 업데이트용

class NewsWorker(QThread):
    """[신규 v4.2.5] 종목 뉴스 검색 및 AI 분석을 위한 비동기 워커"""
    finished = pyqtSignal(str)
    
    def __init__(self, stk_nm):
        super().__init__()
        self.stk_nm = stk_nm
        
    def run(self):
        try:
            from news_sniper import run_news_sniper
            result = run_news_sniper(self.stk_nm)
            self.finished.emit(result)
        except Exception as e:
            self.finished.emit(f"⚠️ 뉴스 검색 중 예외가 발생했어: {e}")

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
        self.perspective_opened_today = False # [v6.4.8] 종가 분석 팝업 오늘 실행 여부
        self.last_check_date = datetime.datetime.now().date()

    def run(self):
        # Create a new event loop for this thread
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        
        # 1. Override tel_send logic
        import chat_command as chat_cmd_module
        
        def gui_log_send(text, *args, **kwargs):
            self.signals.log_signal.emit(text)
        
        # Patch tel_send in chat_command
        chat_cmd_module.tel_send = gui_log_send
        
        # 2. Redirect stdout/stderr to capture prints from get_seq.py and others
        # [v5.7.9 핵심 조치] 대용량 리포트 HTML 문자열이나 빈번한 print가 
        # 메인 GUI 이벤트 루프를 장시간 블로킹하는 현상 방지를 위해 즉시 emit 대신 
        # 내부 큐잉 및 청크 분할 방식을 도입합니다.
        # [v6.5.1] 스레드별 리다이렉션 상태를 독립적으로 관리 (threading.local)
        import threading as py_threading
        _tls = py_threading.local()

        class StreamRedirector:
            def __init__(self, emitter, report_emitter=None):
                self.emitter = emitter
                self.report_emitter = report_emitter or emitter

            def write(self, text):
                # 스레드별 재귀 방지 플래그 체크
                if getattr(_tls, 'is_redirecting', False): return
                if not text or text.isspace(): return
                
                from PyQt6.QtCore import QThread, QCoreApplication
                app = QCoreApplication.instance()
                is_main = (app and QThread.currentThread() == app.thread())

                try:
                    _tls.is_redirecting = True
                    if text.startswith('DEBUG_HTML_LOG:'):
                        html_content = text[len('DEBUG_HTML_LOG:'):].strip()
                        self.report_emitter(html_content)
                    elif len(text) > 4000:
                        for i in range(0, len(text), 4000):
                            self.emitter(text[i:i+4000])
                            if not is_main: time.sleep(0.01)
                    else:
                        self.emitter(text.rstrip())
                except: pass
                finally:
                    _tls.is_redirecting = False

            def flush(self):
                pass
                
        def gui_report_send(html_text):
            self.signals.report_signal.emit(html_text)
        
        sys.stdout = StreamRedirector(gui_log_send, gui_report_send)
        sys.stderr = StreamRedirector(gui_log_send, gui_report_send)

        # Initialize ChatCommand
        self.chat_command = ChatCommand()
        self.chat_command.main_window = self.main_window  # [신규] UI 캡처 연동을 위한 의존성 주입
        self.chat_command.on_clear_logs = lambda: self.signals.clr_signal.emit()
        self.chat_command.on_request_log_file = lambda: self.signals.request_log_signal.emit()
        self.chat_command.on_auto_sequence = lambda idx: self.signals.auto_seq_signal.emit(idx)
        self.chat_command.on_condition_loaded = lambda: self.signals.condition_loaded_signal.emit()
        self.chat_command.on_start = lambda: self.signals.status_signal.emit("RUNNING")
        
        # [신규 v5.6.5] 차트 강제 갱신 콜백 연결
        self.chat_command.on_graph_update = lambda: self.signals.graph_update_signal.emit()
        
        # [신규 v5.0.1] 뉴스 분석 결과 수신 시 GUI 팝업 신호 발생
        self.chat_command.on_news_result = lambda msg: self.signals.news_signal.emit(msg)
        
        # [v5.7.16] REPORT 전용 시그널 연결: HTML을 이 콜백으로 안전하게 수신
        self.chat_command.on_report = lambda html: self.signals.report_signal.emit(html)
        
        # [NEW V5.6.3] 제미나이 AI 텍스트 응답 수신 시 TTS 낭독 신호 발생
        self.chat_command.on_ai_voice_response = lambda msg: self.signals.ai_voice_signal.emit(msg)
        
        # [신규 v6.1.21] AI 설정창 및 불타기 설정창 팝업 콜백 연결
        self.chat_command.on_open_config = lambda: self.signals.open_config_signal.emit()
        self.chat_command.on_open_ai_settings = lambda: self.signals.open_ai_settings_signal.emit()
        
        # [신규] 외부(텔레그램, 명령창)에서 시작/중지 요청 시 GUI 신호로 전달
        self.chat_command.on_start_request = lambda: self.signals.log_signal.emit("🤖 외부 시작 명령 수신") or self.schedule_command('start')
        self.chat_command.on_stop_request = lambda: self.signals.log_signal.emit("🤖 외부 중지 명령 수신") or self.schedule_command('stop')
        
        def on_stop_cb():
            self.pending_start = False # [신규] 명령어로 중지 시에도 예약 상태 해제
            self.signals.status_signal.emit("READY")
            
        self.chat_command.on_stop = on_stop_cb
        self.chat_command.rt_search.on_connection_closed = self._on_connection_closed_wrapper
        
        try:
            self.loop.run_until_complete(self.main_loop())
        finally:
            # [v3.0.1] 종료 시 루프 관련 예외가 팝업 에러(Excepthook)로 번지지 않게 원천 봉쇄
            try:
                if self.loop.is_running():
                    self.loop.stop()
                self.loop.close()
            except: pass

    async def _on_connection_closed_wrapper(self):
        self.signals.log_signal.emit("⚠️ 연결 끊김 감지. 재연결 시도 중...")
        await self.chat_command._on_connection_closed()

    async def main_loop(self):
        self.signals.log_signal.emit("🚀 시스템 초기화 완료. 대기 중...")
        
        # [v5.1.4] 초기 시작 시점 차트 그리기 트리거
        self.signals.graph_update_signal.emit()
        
        # 설정 로드 및 적용
        self.load_initial_settings()
        
        # 시작 시 자동으로 조건식 목록 가져오기 (마지막 저장된 설정대로 필터링되어 표시됨)
        self.signals.log_signal.emit("ℹ️ 저장된 조건식 목록을 불러옵니다...")
        await self.chat_command.condition()
        
        # [추가] 자동 시작(auto_start) 설정 확인 및 실행
        try:
            settings_path = os.path.join(get_base_path(), 'settings.json')
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
        
        # [v3.3.1] Ranking Scout 엔진 자동 기동 로직 제거 (사용자 요청: 매매 시작 시에만 가동)
        # try:
        #     if hasattr(self.main_window, 'rank_engine'):
        #         self.main_window.rank_engine.start()
        # except Exception as e:
        #     self.signals.log_signal.emit(f"⚠️ [Ranking Scout] 엔진 자동 기동 실패: {e}")
        
        try:
            sync_counter = 0 # [v5.6.5] 주기적 수익 동기화 카운터
            while self.keep_running:
                # 텔레그램 메시지 확인 (GUI에서는 필수 아님, 텔레그램 제어 원할 시 유지)
                message = self.get_chat_updates()
                if message:
                    await self.chat_command.process_command(message)
                
                # [v5.6.5] 30초마다 API 수익 데이터와 실시간 차트 동기화 (HTS 매매 대응)
                sync_counter += 1
                if sync_counter >= 30: # 1초 sleep이므로 약 30초
                    sync_counter = 0
                    await self.chat_command.today(sync_only=True)

                # [추가] 장 종료 시 자동 중단 및 보고 시퀀스 (15:30)
                now = datetime.datetime.now()
                if now.hour == 15 and now.minute == 30 and not self.today_stopped:
                    self.today_stopped = True
                    self.signals.log_signal.emit("🔔 장 종료 시간(15:30)이 되어 자동으로 정산 시퀀스를 시작합니다.")
                    
                    # 1. 중지 (STOP)
                    await self.chat_command.stop(set_auto_start_false=False)
                    # [V5.1.9 수정] 중복 리포트 방지 (워커 루프의 직접 호출 제거)
                    # 5~7초 뒤 시퀀스 종료부에서 통합 리포트 1회만 출력하도록 일원화
                    # await self.chat_command.report() 

                # [v6.4.8] 종가 분석 시간 자동 팝업 (설정된 kipostock_perspective_time 시각)
                p_time = get_setting('kipostock_perspective_time', '15:10')
                if p_time and now.strftime("%H:%M") == p_time and not self.perspective_opened_today:
                    # 장 중이거나 사용자가 장외 테스트를 원하는 경우 모두 실행 (유저 요청 반영)
                    self.perspective_opened_today = True
                    self.signals.perspective_signal.emit([]) # 슬롯에서 다이얼로그 오픈

                # 날짜가 바뀌면 종료 플래그 초기화
                current_date = now.date()
                if self.last_check_date != current_date:
                    self.last_check_date = current_date
                    self.today_stopped = False
                    self.perspective_opened_today = False # [v6.4.8] 날짜 바뀌면 리셋

                # 장 시작/종료 시간 자동 확인 로직
                # [수정] 대기 시간(is_waiting_period)이 아닐 때만 자동 시작 진행하여 무한 루프 방지
                if self.pending_start and MarketHour.is_market_open_time() and not MarketHour.is_waiting_period():
                    self.pending_start = False
                    self.signals.log_signal.emit("🔔 장이 시작되었습니다. 감시를 자동으로 시작합니다!")
                    self.schedule_command('start', getattr(self, 'pending_profile_info', None))
                
                # [v4.4.4] 지수 갱신 로직 (5초 주기)
                if not hasattr(self, '_index_counter'): self._index_counter = 0
                self._index_counter += 1
                if self._index_counter >= 5:
                    self._index_counter = 0
                    from stock_info import get_market_index_data
                    # login에서 토큰 발급 (캐시된 토큰 사용)
                    from login import fn_au10001
                    idx_token = fn_au10001()
                    # 비동기 루프 차단 방지 (네트워크 I/O를 별도 스레드에서 실행)
                    idx_data = await asyncio.to_thread(get_market_index_data, token=idx_token)
                    if idx_data:
                        # [v5.0.3 Fix] check_n_buy 전역 캐시 업데이트 (구조적 키 매칭 버그 수정)
                        try:
                            from check_n_buy import GLOBAL_MARKET_STATUS
                            # [v4.4.0 구조 대응] KOSPI/KOSDAQ 키 내부에 rate와 price를 각각 업데이트
                            if 'kospi_rate' in idx_data:
                                GLOBAL_MARKET_STATUS['KOSPI']['rate'] = idx_data['kospi_rate']
                                GLOBAL_MARKET_STATUS['KOSPI']['price'] = idx_data.get('kospi', 0.0)
                            if 'kosdaq_rate' in idx_data:
                                GLOBAL_MARKET_STATUS['KOSDAQ']['rate'] = idx_data['kosdaq_rate']
                                GLOBAL_MARKET_STATUS['KOSDAQ']['price'] = idx_data.get('kosdaq', 0.0)
                            
                            GLOBAL_MARKET_STATUS['last_update'] = now
                        except Exception as e:
                            print(f"⚠️ [IndexUpdate] 캐시 업데이트 오류: {e}")
                        # UI 갱신 시그널
                        self.signals.index_signal.emit(idx_data)

                        # [v5.0.4] 지수 급락 상태 실시간 안내 (3분 주기)
                        if not hasattr(self, '_index_msg_timer'): self._index_msg_timer = 0
                        from check_n_buy import is_market_index_ok
                        is_ok, reason = is_market_index_ok()
                        if not is_ok:
                            if time.time() - self._index_msg_timer >= 180: # 3분마다 한 번씩 리마인드
                                self._index_msg_timer = time.time()
                                msg = f"🛡️ [시장감시] 현재 {reason} 급락 상태로, 모든 자동 매수 및 정찰병 투입이 '일시 정지' 중입니다. ✨"
                                self.signals.log_signal.emit(f"<font color='#ff6b6b'><b>{msg}</b></font>")

                await asyncio.sleep(1.0) # 체크 주기 조정
                
        except Exception as e:
            self.signals.log_signal.emit(f"❌ 메인 루프 에러: {e}")

    def load_initial_settings(self):
        try:
            # [수정] 상대 경로 대신 KipoWindow에서 정의한 절대 경로 사용 (없으면 script_dir 기반 생성)
            settings_path = getattr(self.main_window, 'settings_file', None)
            if not settings_path:
                settings_path = os.path.join(get_base_path(), 'settings.json')

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
                    # [v3.3.1] 메인 매매 시작 시 랭킹 스카우트 엔진도 함께 기동
                    try:
                        if hasattr(self.main_window, 'rank_engine'):
                            self.main_window.rank_engine.start()
                    except: pass
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
                # [v3.3.1] 메인 매매 중지 시 랭킹 스카우트 엔진도 함께 정지
                try:
                    if hasattr(self.main_window, 'rank_engine'):
                        self.main_window.rank_engine.stop()
                except: pass
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
                    
            elif cmd_type == 'close_bet':
                # [v6.3.0 버그수정] _execute_command에 close_bet 케이스 누락으로 인한 미실행 버그 수정
                # schedule_command('close_bet') 호출 시 chat_command의 close_bet 로직이 실행되도록 연결
                await self.chat_command.process_command('close_bet')

            # --- Ranking Scout 전용 명령어 (V2.4.4) ---
            elif cmd_type == 'rank_start':
                self.main_window.rank_engine.start()
            elif cmd_type == 'rank_stop':
                self.main_window.rank_engine.stop()
            elif cmd_type == 'rank_reload':
                self.main_window.rank_engine.reload_parameters()

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
            # [v3.0.1] quiet=True를 전달하여 종료 시 불필요한 로그(시그널) 발생 억제
            await self.chat_command.stop(True, quiet=True)
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
        self.setFixedWidth(420)
        self.setStyleSheet("""
            QDialog { background-color: #1e1e1e; color: #ffffff; }
            QLabel { color: #ffffff; font-weight: bold; }
            QLineEdit, QComboBox, QDoubleSpinBox, QTabWidget { 
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

        # [v6.8] 메인 레이아웃 및 탭 위젯 도입 (불타기와 종가 분리)
        main_vbox = QVBoxLayout(self)
        self.tab_widget = QTabWidget()
        self.tab_widget.setStyleSheet("""
            QTabWidget::pane { border: 1px solid #444; top: -1px; background-color: #1e1e1e; }
            QTabBar::tab {
                background: #2b2b2b; color: #888; border: 1px solid #444;
                border-bottom: none; border-top-left-radius: 4px; border-top-right-radius: 4px;
                padding: 8px 12px; min-width: 85px; font-weight: bold; font-size: 12px;
            }
            QTabBar::tab:selected { background: #333; color: #f1c40f; border-bottom: 2px solid #f1c40f; }
            QTabBar::tab:hover { background: #3a3a3a; color: #ddd; }
        """)

        # --- (신규) Tab 1: 🌅 시초가 베팅 ---
        tab_morning = QWidget()
        morning_vbox = QVBoxLayout(tab_morning)
        morning_vbox.setContentsMargins(15, 15, 15, 15)
        
        self.chk_morning_enabled = QCheckBox(" 🌅 시초가 베팅(초단타) 기능 전체 활성화")
        self.chk_morning_enabled.setStyleSheet("font-size: 15px; color: #00e5ff; font-weight: bold; margin-bottom: 15px;")
        morning_vbox.addWidget(self.chk_morning_enabled)

        # 🚀 [전략 A 전용 설정 그룹]
        group_a = QGroupBox("🚀 전략 A: 예상 체결량 상위 (Scan) 상세 설정")
        group_a.setStyleSheet("QGroupBox { font-weight: bold; color: #ff6b6b; border: 1px solid #444; border-radius: 8px; margin-top: 15px; padding-top: 15px; } QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; }")
        group_a_layout = QFormLayout()
        group_a_layout.setVerticalSpacing(12); group_a_layout.setHorizontalSpacing(15)

        self.input_morning_time = QLineEdit(); self.input_morning_time.setPlaceholderText("예: 09:10")
        self.input_morning_time.setFixedWidth(100); self.input_morning_time.setFixedHeight(30)
        group_a_layout.addRow("🕒 시초가 통합 매매 제한 시간:", self.input_morning_time)

        self.spin_morning_gap_min = QDoubleSpinBox(); self.spin_morning_gap_min.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons); self.spin_morning_gap_min.setDecimals(1)
        self.spin_morning_gap_min.setRange(0, 30); self.spin_morning_gap_min.setSuffix(" %"); self.spin_morning_gap_min.setFixedHeight(30)
        self.spin_morning_gap_max = QDoubleSpinBox(); self.spin_morning_gap_max.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons); self.spin_morning_gap_max.setDecimals(1)
        self.spin_morning_gap_max.setRange(0, 30); self.spin_morning_gap_max.setSuffix(" %"); self.spin_morning_gap_max.setFixedHeight(30)
        h_gap = QHBoxLayout(); h_gap.addWidget(self.spin_morning_gap_min); h_gap.addWidget(QLabel("~")); h_gap.addWidget(self.spin_morning_gap_max)
        group_a_layout.addRow("📈 A전용 갭상승 구간:", h_gap)

        self.spin_morning_break = QDoubleSpinBox(); self.spin_morning_break.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons); self.spin_morning_break.setDecimals(1)
        self.spin_morning_break.setRange(0, 30); self.spin_morning_break.setSuffix(" % 돌파 시"); self.spin_morning_break.setFixedHeight(30)
        group_a_layout.addRow("🚀 A전용 시가 대비 돌파:", self.spin_morning_break)

        self.spin_morning_tp = QDoubleSpinBox()
        self.spin_morning_tp.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons) # [V3.0.0] 화살표 버튼 삭제
        self.spin_morning_tp.setRange(0.0, 30.0)
        self.spin_morning_tp.setSingleStep(0.1)
        self.spin_morning_tp.setDecimals(1) # [V3.0.0] 텍스트 잘림 해결 (소수점 1자리)
        self.spin_morning_tp.setFixedWidth(50) # 너비 최적화
        
        self.spin_morning_sl = QDoubleSpinBox()
        self.spin_morning_sl.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons) # [V3.0.0] 화살표 버튼 삭제
        self.spin_morning_sl.setRange(-30.0, 0.0)
        self.spin_morning_sl.setSingleStep(0.1)
        self.spin_morning_sl.setDecimals(1) # [V3.0.0] 텍스트 잘림 해결 (소수점 1자리)
        self.spin_morning_sl.setFixedWidth(50) # 너비 최적화
        
        h_risk = QHBoxLayout()
        h_risk.setContentsMargins(0, 0, 0, 0)
        h_risk.addWidget(QLabel("⚔️ 통합 손익절:          ")) # kipo edit
        h_risk.addWidget(QLabel("익절(%):"))
        h_risk.addWidget(self.spin_morning_tp)
        h_risk.addSpacing(5)
        h_risk.addWidget(QLabel("손절(%):"))
        h_risk.addWidget(self.spin_morning_sl)
        h_risk.addStretch()
        
        # [v3.0.0] 왼쪽으로 당기기: addRow에 라벨을 주지 않고 QWidget 자체를 넣어 양쪽 열 스팬(Span) 적용
        group_a_layout.addRow(h_risk)

        group_a.setLayout(group_a_layout); morning_vbox.addWidget(group_a)

        morning_vbox.addSpacing(10); common_form = QFormLayout(); common_form.setSpacing(10)
        self.chk_morning_ai = QCheckBox(" 🤖 AI 뉴스 스나이퍼 호재 판정 시에만 진입 (공통)")
        self.chk_morning_a = QCheckBox(" 🚀 A전략 활성화"); self.chk_morning_b = QCheckBox(" 🎯 B전략 활성화 (시가 재돌파)")
        self.chk_morning_c = QCheckBox(" ⚡ C전략 활성화 (1분봉 고가 돌파)")

        # [v1.7.6] 전략별 상세 로직 툴팁 복구
        self.chk_morning_a.setToolTip("<b>[전략 A: 예상 체결량 상위]</b><br>장 시작 전 예상 체결량이 높은 종목을 스캔하여,<br>설정된 갭(Gap) 범위 내일 때 9시 정각 시장가로 진입합니다.")
        self.chk_morning_b.setToolTip("<b>[전략 B: 시가 재돌파]</b><br>시가 형성 후 일시적으로 하락(-0.5% 이하)했다가,<br>다시 시가(+0.3%)를 돌파하며 회복하는 강한 흐름을 공략합니다.")
        self.chk_morning_c.setToolTip("<b>[전략 C: 1분봉 고가 돌파]</b><br>장 시작 후 첫 1분(09:00~09:01)의 고점을 기록한 뒤,<br>이 고점을 다시 돌파할 때의 탄력을 활용해 진입합니다.")
        # [V5.3.1] 전략 D(거래량 급증) 영구 제거 (사용자 요청 ❤️)

        for chk in [self.chk_morning_a, self.chk_morning_b, self.chk_morning_c, self.chk_morning_ai]:
            chk.setStyleSheet("font-weight: bold; font-size: 13px; padding: 2px;")
        
        common_form.addRow(self.chk_morning_ai); common_form.addRow(self.chk_morning_a); common_form.addRow(self.chk_morning_b); common_form.addRow(self.chk_morning_c)
        morning_vbox.addLayout(common_form)
        
        # 🎯 [🎯 AI Morning Sniper (추천 매수) 상세 설정] [V5.3.0 신설]
        group_ai = QGroupBox("🎯 AI Morning Sniper (AI 자동 추천 매수)")
        group_ai.setStyleSheet("QGroupBox { font-weight: bold; color: #f1c40f; border: 1px solid #444; border-radius: 8px; margin-top: 5px; padding-top: 15px; } QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; }")
        ai_layout = QFormLayout()
        ai_layout.setContentsMargins(15, 10, 15, 10)
        
        self.chk_morning_ai_selection = QCheckBox(" AI 자동 추천 매수 기능 활성화")
        self.chk_morning_ai_selection.setStyleSheet("font-weight: bold; color: #f1c40f;")
        
        self.spin_morning_ai_count = QSpinBox()
        self.spin_morning_ai_count.setRange(1, 10)
        self.spin_morning_ai_count.setValue(3)
        self.spin_morning_ai_count.setFixedWidth(80)
        self.spin_morning_ai_count.setSuffix(" 종목")
        
        self.chk_morning_ai_news = QCheckBox(" AI 뉴스 스나이퍼 분석 데이터 강제 합산")
        self.chk_morning_ai_news.setStyleSheet("font-size: 11px; color: #aaaaaa;")
        
        ai_layout.addRow(self.chk_morning_ai_selection)
        ai_layout.addRow("🏆 추천 타격 수:", self.spin_morning_ai_count)
        ai_layout.addRow(self.chk_morning_ai_news)
        
        group_ai.setLayout(ai_layout)
        morning_vbox.addWidget(group_ai)

        morning_vbox.addStretch()

        # --- Tab 2: 🔥 실시간 불타기 ---
        tab_fire = QWidget()
        fire_vbox = QVBoxLayout(tab_fire)
        fire_form = QFormLayout()
        fire_form.setVerticalSpacing(12); fire_form.setHorizontalSpacing(12)
        
        self.input_wait = QLineEdit()
        self.input_wait.setPlaceholderText("초 단위 (예: 30)")
        fire_form.addRow("⏳ 타겟 포착 대기(초):", self.input_wait)
        
        h_mode = QHBoxLayout()
        self.combo_mode = QComboBox()
        self.combo_mode.addItems(["배수", "금액"])
        self.input_val = QLineEdit()
        self.input_val.setPlaceholderText("숫자 입력")
        self.input_val.textChanged.connect(self.format_money)
        h_mode.addWidget(self.combo_mode)
        h_mode.addWidget(self.input_val)
        fire_form.addRow("💰 추가 매수 단위:", h_mode)
        
        self.combo_price_type = QComboBox()
        self.combo_price_type.addItems(["시장가", "현재가"])
        fire_form.addRow("🛒 매수 주문 방식:", self.combo_price_type)

        line_top = QFrame()
        line_top.setFrameShape(QFrame.Shape.HLine); line_top.setStyleSheet("background-color: #444;")
        fire_form.addRow(line_top)

        # --- [매도 전략 그룹] ---
        str_group = QGroupBox("🛡️ 매도 전략 (상호 배제: 익절/보존 vs TS)")
        str_group.setStyleSheet("QGroupBox { font-weight: bold; color: #f1c40f; border: 1px solid #444; border-radius: 8px; margin-top: 10px; padding-top: 15px; } QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; }")
        str_layout = QVBoxLayout()
        
        # 1. 익실현
        self.chk_tp = QCheckBox(" 이익실현")
        self.input_tp = QLineEdit(); self.input_tp.setFixedWidth(80); self.input_tp.setPlaceholderText("5.0")
        h_tp = QHBoxLayout(); h_tp.addWidget(self.chk_tp); h_tp.addStretch(); h_tp.addWidget(self.input_tp); h_tp.addWidget(QLabel("%"))
        str_layout.addLayout(h_tp)

        # 2. 이익보존
        self.chk_preservation = QCheckBox(" 이익보존")
        self.input_p_trigger = QLineEdit(); self.input_p_trigger.setFixedWidth(60); self.input_p_trigger.setPlaceholderText("3.0")
        self.input_p_limit = QLineEdit(); self.input_p_limit.setFixedWidth(60); self.input_p_limit.setPlaceholderText("2.0")
        h_p = QHBoxLayout()
        h_p.addWidget(self.chk_preservation); h_p.addStretch(); h_p.addWidget(self.input_p_trigger)
        h_p.addWidget(QLabel("% 도달 시")); h_p.addWidget(self.input_p_limit); h_p.addWidget(QLabel("% 매도"))
        str_layout.addLayout(h_p)

        line_inner = QFrame(); line_inner.setFrameShape(QFrame.Shape.HLine); line_inner.setStyleSheet("background-color: #333;")
        str_layout.addWidget(line_inner)

        # 3. 트레일링 스톱 (독립 공간)
        self.chk_trailing = QCheckBox(" 트레일링 스톱(TS)")
        self.input_trailing = QLineEdit(); self.input_trailing.setFixedWidth(80); self.input_trailing.setPlaceholderText("1.0")
        h_trailing = QHBoxLayout(); h_trailing.addWidget(self.chk_trailing); h_trailing.addStretch(); h_trailing.addWidget(self.input_trailing); h_trailing.addWidget(QLabel("% 하락 시"))
        str_layout.addLayout(h_trailing)

        # [V5.1.15] 트레일링 스톱 감시 시작 기준 (하드코딩 0.5% 탈출)
        h_ts_start = QHBoxLayout()
        h_ts_start.addWidget(QLabel("   ┗ 감시 시작 수익률:"))
        self.input_ts_start = QLineEdit(); self.input_ts_start.setFixedWidth(60); self.input_ts_start.setPlaceholderText("0.5")
        h_ts_start.addStretch()
        h_ts_start.addWidget(self.input_ts_start); h_ts_start.addWidget(QLabel("% 이상 시"))
        str_layout.addLayout(h_ts_start)
        
        str_group.setLayout(str_layout)
        fire_form.addRow(str_group)

        # 4. 손실제한 (공통)
        self.chk_sl = QCheckBox(" 손실제한 (공통)")
        self.input_sl = QLineEdit(); self.input_sl.setFixedWidth(80); self.input_sl.setPlaceholderText("-2.0")
        h_sl = QHBoxLayout(); h_sl.addWidget(self.chk_sl); h_sl.addStretch(); h_sl.addWidget(self.input_sl); h_sl.addWidget(QLabel("%"))
        fire_form.addRow(h_sl)
        
        # [상호 배제 로직 연결]
        self.chk_tp.toggled.connect(self._on_tp_toggled)
        self.chk_preservation.toggled.connect(self._on_preservation_toggled)
        self.chk_trailing.toggled.connect(self._on_trailing_toggled)
        
        # [UX] 텍스트 입력 시그널 연결
        self.input_tp.textChanged.connect(lambda t: self.format_percent(self.input_tp, t, is_profit=True))
        self.input_p_trigger.textChanged.connect(lambda t: self.format_percent(self.input_p_trigger, t, is_profit=True))
        self.input_p_limit.textChanged.connect(lambda t: self.format_percent(self.input_p_limit, t, is_profit=True))
        self.input_sl.textChanged.connect(lambda t: self.format_percent(self.input_sl, t, is_profit=False))
        self.input_trailing.textChanged.connect(lambda t: self.format_percent(self.input_trailing, t, is_profit=False))
        self.input_ts_start.textChanged.connect(lambda t: self.format_percent(self.input_ts_start, t, is_profit=True))

        line_mid = QFrame(); line_mid.setFrameShape(QFrame.Shape.HLine); line_mid.setStyleSheet("background-color: #444;")
        fire_form.addRow(line_mid)
        
        self.chk_power = QCheckBox(" 체결강도 필터 사용")
        self.input_power = QLineEdit(); self.input_power.setFixedWidth(80); self.input_power.setPlaceholderText("120")
        h_power = QHBoxLayout(); h_power.addWidget(self.chk_power); h_power.addStretch(); h_power.addWidget(self.input_power); h_power.addWidget(QLabel("% 이상"))
        fire_form.addRow(h_power)

        self.chk_slope = QCheckBox(" 체결강도 강화(상승 추세) 시에만 매수")
        fire_form.addRow(self.chk_slope)

        self.chk_orderbook = QCheckBox(" 호가잔량비 역전 필터 사용")
        self.input_orderbook = QLineEdit(); self.input_orderbook.setFixedWidth(80); self.input_orderbook.setPlaceholderText("2.0")
        h_ob = QHBoxLayout(); h_ob.addWidget(self.chk_orderbook); h_ob.addStretch(); h_ob.addWidget(self.input_orderbook); h_ob.addWidget(QLabel("배 이상"))
        fire_form.addRow(h_ob)

        line_turbo = QFrame(); line_turbo.setFrameShape(QFrame.Shape.HLine); line_turbo.setStyleSheet("background-color: #444;")
        fire_form.addRow(line_turbo)

        # [V5.3.7/V5.3.8] 불타기 가격 상한선 가드 (Global) - UI 통일 (직접 입력형)
        self.chk_bultagi_limit = QCheckBox(" 현재가 N% 이상 시 불타기 매수 금지")
        self.chk_bultagi_limit.setStyleSheet("font-weight: bold; color: #ff6b6b;")
        self.input_bultagi_limit = QLineEdit()
        self.input_bultagi_limit.setFixedWidth(80); self.input_bultagi_limit.setPlaceholderText("22.0")
        h_limit = QHBoxLayout(); h_limit.addWidget(self.chk_bultagi_limit); h_limit.addStretch(); h_limit.addWidget(self.input_bultagi_limit); h_limit.addWidget(QLabel("%"))
        fire_form.addRow(h_limit)

        fire_vbox.addLayout(fire_form)
        fire_vbox.addStretch()

        # --- Tab 3: 🌙 종가 베팅 (추후 확장용) ---
        tab_jongga = QWidget()
        jongga_vbox = QVBoxLayout(tab_jongga)
        jongga_vbox.addWidget(QLabel("🌙 종가 베팅 상세 설정은 메인 화면의\n 종가 탭에서 더 자세히 볼 수 있습니다."))
        jongga_vbox.addStretch()
        
        # --- Tab 4: 🏹 기타 매매 (Ranking Scout & Turbo VI) [V4.0.0 신설] ---
        tab_extra = QWidget()
        extra_vbox = QVBoxLayout(tab_extra)
        
        # 🔎 [Ranking Scout 정찰병 설정 그룹]
        group_rank = QGroupBox("🔎 Ranking Scout (실시간 순위 급등 정찰병)")
        group_rank.setStyleSheet("QGroupBox { font-weight: bold; color: #00e5ff; border: 1px solid #444; border-radius: 8px; margin-top: 5px; padding-top: 12px; } QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; }")
        rank_layout = QFormLayout()
        rank_layout.setSpacing(10)
        self.chk_rank_scout = QCheckBox(" 실시간 조회 순위 급등 시 1주(정찰병) 즉시 매수")
        self.chk_rank_scout.setStyleSheet("font-weight: bold; font-size: 13px; color: #f1c40f;")
        self.spin_rank_new = QComboBox(); self.spin_rank_new.addItems(["5 위 내 신규 진입 시", "10 위 내 신규 진입 시", "15 위 내 신규 진입 시", "20 위 내 신규 진입 시"]); self.spin_rank_new.setFixedHeight(28)
        self.spin_rank_jump = QComboBox(); self.spin_rank_jump.addItems(["5 단계 이상 급상승 시", "10 단계 이상 급상승 시", "15 단계 이상 급상승 시", "20 단계 이상 급상승 시"]); self.spin_rank_jump.setFixedHeight(28)
        # [신규 v5.2.0] 연속 순위 상승 조건 추가 (자기 요청 반영 ❤️)
        self.spin_rank_consecutive = QComboBox(); self.spin_rank_consecutive.addItems(["사용 안 함", "3 회 연속 상승 시", "4 회 연속 상승 시", "5 회 연속 상승 시"]); self.spin_rank_consecutive.setFixedHeight(28)
        self.spin_rank_interval = QComboBox(); self.spin_rank_interval.addItems(["30 초 간격 감시", "1 분 간격 감시", "10 분 간격 감시", "1 시간 감시", "당일 누적 감시"]); self.spin_rank_interval.setFixedHeight(28)
        rank_layout.addRow(self.chk_rank_scout)
        rank_layout.addRow("✨ 신규 진입:", self.spin_rank_new)
        rank_layout.addRow("🚀 순위 점프:", self.spin_rank_jump)
        rank_layout.addRow("📈 연속 상승:", self.spin_rank_consecutive)
        rank_layout.addRow("⏳ 감지 간격:", self.spin_rank_interval)
        group_rank.setLayout(rank_layout)
        extra_vbox.addWidget(group_rank)

        extra_vbox.addSpacing(10)

        # 🚀 [Turbo VI (VI 해제 즉시 매수) 설정 그룹]
        group_turbo = QGroupBox("🚀 Turbo VI (VI 해제/재개 시 즉시 매수)")
        group_turbo.setStyleSheet("QGroupBox { font-weight: bold; color: #f1c40f; border: 1px solid #444; border-radius: 8px; margin-top: 10px; padding-top: 15px; } QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; }")
        turbo_main_layout = QVBoxLayout()
        
        self.chk_turbo_vi = QCheckBox(" VI 해제 시 즉시 잠입 (Turbo VI 활성화)")
        self.chk_turbo_vi.setStyleSheet("font-weight: bold; font-size: 13px; color: #00e5ff;")
        self.combo_turbo_vi_type = QComboBox(); self.combo_turbo_vi_type.addItems(["시장가", "현재가"]); self.combo_turbo_vi_type.setFixedWidth(80)
        h_turbo_top = QHBoxLayout(); h_turbo_top.addWidget(self.chk_turbo_vi); h_turbo_top.addStretch(); h_turbo_top.addWidget(self.combo_turbo_vi_type)
        turbo_main_layout.addLayout(h_turbo_top)

        # Turbo VI 상세 필터 (내부 그룹)
        self.group_turbo_filter = QGroupBox("🔍 Turbo VI 정밀 필터링")
        self.group_turbo_filter.setStyleSheet("QGroupBox { border: 1px solid #444; border-radius: 6px; margin-top: 5px; padding-top: 10px; color: #ddd; font-size: 11px; }")
        turbo_filter_layout = QFormLayout()
        self.input_turbo_min_price = QSpinBox(); self.input_turbo_min_price.setRange(0, 100000000); self.input_turbo_min_price.setGroupSeparatorShown(True); self.input_turbo_min_price.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons); self.input_turbo_min_price.setFixedWidth(80)
        self.input_turbo_max_price = QSpinBox(); self.input_turbo_max_price.setRange(0, 100000000); self.input_turbo_max_price.setGroupSeparatorShown(True); self.input_turbo_max_price.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons); self.input_turbo_max_price.setFixedWidth(80)
        h_turbo_price = QHBoxLayout(); h_turbo_price.addWidget(self.input_turbo_min_price); h_turbo_price.addWidget(QLabel("~")); h_turbo_price.addWidget(self.input_turbo_max_price); h_turbo_price.addWidget(QLabel("원"))
        turbo_filter_layout.addRow("💰 가격대:", h_turbo_price)
        self.chk_turbo_static = QCheckBox(" 정적 VI"); self.chk_turbo_dynamic = QCheckBox(" 동적 VI")
        h_vi_type = QHBoxLayout(); h_vi_type.addWidget(self.chk_turbo_static); h_vi_type.addWidget(self.chk_turbo_dynamic); h_vi_type.addStretch()
        turbo_filter_layout.addRow("⚖️ VI 타입:", h_vi_type)
        self.chk_turbo_volume = QCheckBox(" 거래대금 상위"); self.input_turbo_volume = QSpinBox(); self.input_turbo_volume.setRange(1, 150); self.input_turbo_volume.setValue(100); self.input_turbo_volume.setFixedWidth(100)
        h_turbo_vol = QHBoxLayout(); h_turbo_vol.addWidget(self.chk_turbo_volume); h_turbo_vol.addWidget(self.input_turbo_volume); h_turbo_vol.addWidget(QLabel("위 이내")); h_turbo_vol.addStretch()
        turbo_filter_layout.addRow("🏆 자금 집중:", h_turbo_vol)
        self.chk_turbo_ex_etf = QCheckBox(" ETF 제외"); self.chk_turbo_ex_spac = QCheckBox(" 스팩 제외"); self.chk_turbo_ex_prefer = QCheckBox(" 우선주 제외")
        h_trash_filter = QHBoxLayout(); h_trash_filter.addWidget(self.chk_turbo_ex_etf); h_trash_filter.addWidget(self.chk_turbo_ex_spac); h_trash_filter.addWidget(self.chk_turbo_ex_prefer); h_trash_filter.addStretch()
        turbo_filter_layout.addRow("🚫 잡주 제외:", h_trash_filter)
        self.group_turbo_filter.setLayout(turbo_filter_layout)
        turbo_main_layout.addWidget(self.group_turbo_filter)
        
        group_turbo.setLayout(turbo_main_layout)
        extra_vbox.addWidget(group_turbo)
        extra_vbox.addStretch()

        # --- Tab 3: 🌙 종가 분석 ---
        tab_jongga = QWidget()
        jongga_vbox = QVBoxLayout(tab_jongga)
        jongga_form = QFormLayout()
        jongga_form.setVerticalSpacing(15); jongga_form.setHorizontalSpacing(12)

        lbl_kipo_info = QLabel("🌙 KipoStock 관점 필터 설정")
        lbl_kipo_info.setStyleSheet("color: #f1c40f; font-size: 15px; margin-bottom: 10px;")
        jongga_form.addRow(lbl_kipo_info)

        self.spin_peak = QDoubleSpinBox()
        self.spin_peak.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons); self.spin_peak.setDecimals(1)
        self.spin_peak.setRange(0, 100); self.spin_peak.setSuffix(" % 이상"); self.spin_peak.setSingleStep(1.0); self.spin_peak.setFixedHeight(32)
        jongga_form.addRow("🎯 당일 고가 달성:", self.spin_peak)

        self.spin_now_min = QDoubleSpinBox(); self.spin_now_min.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons); self.spin_now_min.setDecimals(1)
        self.spin_now_min.setRange(-30, 30); self.spin_now_min.setSuffix(" %"); self.spin_now_min.setFixedHeight(32)
        self.spin_now_max = QDoubleSpinBox(); self.spin_now_max.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons); self.spin_now_max.setDecimals(1)
        self.spin_now_max.setRange(-30, 30); self.spin_now_max.setSuffix(" %"); self.spin_now_max.setFixedHeight(32)
        
        h_now = QHBoxLayout(); h_now.addWidget(self.spin_now_min); h_now.addWidget(QLabel("~")); h_now.addWidget(self.spin_now_max)
        jongga_form.addRow("📊 현재 수익률 구간:", h_now)

        self.input_perspective_time = QLineEdit(); self.input_perspective_time.setPlaceholderText("예: 15:10"); self.input_perspective_time.setFixedWidth(120); self.input_perspective_time.setFixedHeight(32)
        self.btn_search_stocks = QPushButton("🔍 종목 탐색"); self.btn_search_stocks.setFixedHeight(35)
        self.btn_search_stocks.setStyleSheet("background-color: #f1c40f; color: #1a1a1a; font-weight: bold; border-radius: 6px; font-size: 13px;")
        self.btn_search_stocks.clicked.connect(self._open_kipo_filter_dialog)
        
        jongga_form.addRow("⏰ 종가 분석 시간:", self.input_perspective_time)
        jongga_form.addRow("", self.btn_search_stocks)
        
        jongga_vbox.addLayout(jongga_form)
        jongga_vbox.addStretch()

        # --- Tab 4: ⚙️ 기타 설정 (단축키 등) ---
        tab_etc = QWidget()
        etc_vbox = QVBoxLayout(tab_etc)
        etc_vbox.setContentsMargins(15, 15, 15, 15)
        
        lbl_etc_title = QLabel("⚙️ 시스템 및 편의 기능")
        lbl_etc_title.setStyleSheet("color: #3498db; font-size: 15px; margin-bottom: 10px;")
        etc_vbox.addWidget(lbl_etc_title)

        btn_layout_etc = QVBoxLayout()
        btn_layout_etc.setSpacing(10)

        # 1. 단축키 설정 버튼
        btn_shortcut_cfg = QPushButton("⌨️ 단축키 설정")
        btn_shortcut_cfg.setFixedHeight(40)
        btn_shortcut_cfg.setStyleSheet("background-color: #34495e; color: white; font-weight: bold; border-radius: 6px; font-size: 14px;")
        if parent:
            # Main Window의 open_shortcut_settings 메서드 연결 예정
            btn_shortcut_cfg.clicked.connect(parent.open_shortcut_settings)
        btn_layout_etc.addWidget(btn_shortcut_cfg)

        # 3. 🛡️ 지수 급락 자동 매매 정지 (Global) [V4.4.0 신설]
        group_idx = QGroupBox("🛡️ 지수 급락 자동 매도/매수 정지 (Global)")
        group_idx.setStyleSheet("QGroupBox { font-weight: bold; color: #ff4757; border: 1px solid #444; border-radius: 8px; margin-top: 10px; padding-top: 15px; } QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; }")
        idx_layout = QFormLayout()
        self.chk_idx_stop = QCheckBox(" 지수 급락 시 모든 자동 매수/불타기 즉시 정지")
        self.chk_idx_stop.setStyleSheet("font-weight: bold; color: #ff4757;")
        
        self.spin_kospi_threshold = QDoubleSpinBox()
        self.spin_kospi_threshold.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
        self.spin_kospi_threshold.setRange(-30.0, 0.0); self.spin_kospi_threshold.setSingleStep(0.1); self.spin_kospi_threshold.setDecimals(1); self.spin_kospi_threshold.setFixedWidth(80)
        self.spin_kosdaq_threshold = QDoubleSpinBox()
        self.spin_kosdaq_threshold.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
        self.spin_kosdaq_threshold.setRange(-30.0, 0.0); self.spin_kosdaq_threshold.setSingleStep(0.1); self.spin_kosdaq_threshold.setDecimals(1); self.spin_kosdaq_threshold.setFixedWidth(80)
        
        h_kospi = QHBoxLayout(); h_kospi.addWidget(self.spin_kospi_threshold); h_kospi.addWidget(QLabel("% 이하 시")); h_kospi.addStretch()
        h_kosdaq = QHBoxLayout(); h_kosdaq.addWidget(self.spin_kosdaq_threshold); h_kosdaq.addWidget(QLabel("% 이하 시")); h_kosdaq.addStretch()
        
        idx_layout.addRow(self.chk_idx_stop)
        idx_layout.addRow("📉 KOSPI 임계값:", h_kospi)
        idx_layout.addRow("📉 KOSDAQ 임계값:", h_kosdaq)
        group_idx.setLayout(idx_layout)
        etc_vbox.addWidget(group_idx)

        # 4. 🛡️ VI 발동 중 매수 금지 (Global) [V5.1.33 신설]
        group_vi_block = QGroupBox("🛡️ VI 상태 매수 보호 (Global)")
        group_vi_block.setStyleSheet("QGroupBox { font-weight: bold; color: #f1c40f; border: 1px solid #444; border-radius: 8px; margin-top: 10px; padding-top: 15px; } QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; }")
        vi_block_layout = QVBoxLayout()
        self.chk_block_buy_vi = QCheckBox(" VI 발동 종목 모든 자동 매수 금지 (Turbo VI 제외)")
        self.chk_block_buy_vi.setStyleSheet("font-weight: bold; color: #f1c40f;")
        vi_block_layout.addWidget(self.chk_block_buy_vi)
        group_vi_block.setLayout(vi_block_layout)
        etc_vbox.addWidget(group_vi_block)

        # 5. 📡 텔레그램 알림 설정 (Global) [V5.3.5 신설] 🚀
        group_tel = QGroupBox("📡 텔레그램 알림 설정 (Global)")
        group_tel.setStyleSheet("QGroupBox { font-weight: bold; color: #00e5ff; border: 1px solid #444; border-radius: 8px; margin-top: 10px; padding-top: 15px; } QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; }")
        tel_layout = QVBoxLayout()
        self.chk_tel_on = QCheckBox(" 텔레그램 메시지 발송 활성화")
        self.chk_tel_on.setStyleSheet("font-weight: bold; color: #00e5ff;")
        tel_layout.addWidget(self.chk_tel_on)
        group_tel.setLayout(tel_layout)
        etc_vbox.addWidget(group_tel)

        etc_vbox.addLayout(btn_layout_etc)
        etc_vbox.addStretch()

        self.tab_widget.addTab(tab_morning, "🌅 시초가")
        self.tab_widget.addTab(tab_fire, "🔥 불타기")
        self.tab_widget.addTab(tab_jongga, "🌙 종가")
        self.tab_widget.addTab(tab_extra, "🏹 기타 매매") # [V4.0.0]
        self.tab_widget.addTab(tab_etc, "⚙️ 기타")

        main_vbox.addWidget(self.tab_widget)
        
        # 하단 버튼
        btn_layout = QHBoxLayout()
        self.btn_save = QPushButton("💾 설정 저장")
        self.btn_save.setFixedWidth(120)
        self.btn_save.clicked.connect(self.apply_settings)
        btn_cancel = QPushButton("취소")
        btn_cancel.setFixedWidth(80)
        btn_cancel.setObjectName("btn_cancel")
        btn_cancel.clicked.connect(self.reject)
        
        btn_layout.addStretch()
        btn_layout.addWidget(btn_cancel)
        btn_layout.addWidget(self.btn_save)
        main_vbox.addLayout(btn_layout)
        
        if parent:
            self.apply_theme(parent.ui_theme)
        self.load_settings()

    def apply_theme(self, theme):
        """[신규] 부모의 테마 상태에 맞춰 다이얼로그 스타일 갱신"""
        is_light = (theme == 'light')
        style_vars = {
            'bg_color': "#f8f9fa" if is_light else "#1e1e1e",
            'fg_color': "#333333" if is_light else "#ffffff",
            'input_bg': "#ffffff" if is_light else "#333333",
            'input_border': "#cccccc" if is_light else "#555555"
        }
        
        self.setStyleSheet("""
            QDialog {{ background-color: {bg_color}; color: {fg_color}; }}
            QLabel {{ color: {fg_color}; font-weight: bold; }}
            QCheckBox {{ color: {fg_color}; }}
            QTabWidget::pane {{ border: 1px solid #444; top: -1px; background-color: {bg_color}; }}
            QTabBar::tab {{
                background: {input_bg}; color: {fg_color}; border: 1px solid {input_border};
                border-bottom: none; border-top-left-radius: 4px; border-top-right-radius: 4px;
                padding: 8px 12px; min-width: 85px; font-weight: bold; font-size: 12px;
            }}
            QTabBar::tab:selected {{ background: {bg_color}; color: #f1c40f; border-bottom: 2px solid #f1c40f; }}
            QLineEdit, QComboBox, QDoubleSpinBox, QSpinBox {{ 
                background-color: {input_bg}; color: {fg_color}; 
                border: 1px solid {input_border}; border-radius: 4px; padding: 4px;
            }}
            QPushButton {{ 
                background-color: #dc3545; color: white; font-weight: bold;
                border-radius: 6px; padding: 8px; font-size: 13px;
            }}
            QPushButton:hover {{ background-color: #c82333; }}
            QPushButton#btn_cancel {{ background-color: #6c757d; }}
            QPushButton#btn_cancel:hover {{ background-color: #5a6268; }}
        """.format(**style_vars))

    # --- [상호 배제 슬롯 함수] ---
    def _on_tp_toggled(self, checked):
        if checked:
            self.chk_trailing.blockSignals(True)
            self.chk_trailing.setChecked(False)
            self.chk_trailing.blockSignals(False)

    def _on_preservation_toggled(self, checked):
        if checked:
            self.chk_trailing.blockSignals(True)
            self.chk_trailing.setChecked(False)
            self.chk_trailing.blockSignals(False)

    def _on_trailing_toggled(self, checked):
        if checked:
            self.chk_tp.blockSignals(True)
            self.chk_tp.setChecked(False)
            self.chk_tp.blockSignals(False)
            self.chk_preservation.blockSignals(True)
            self.chk_preservation.setChecked(False)
            self.chk_preservation.blockSignals(False)

    # [UX 신규] 1000 단위 콤마 자동 입력
    def format_money(self):
        text = self.input_val.text().replace(',', '')
        if text.isdigit():
            self.input_val.blockSignals(True)
            self.input_val.setText(format(int(text), ','))
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
        try:
            # 1. 파일에서 설정 직접 로드 (가장 안전한 방법)
            try:
                with open(self.settings_file, 'r', encoding='utf-8') as f:
                    root = json.load(f)
            except:
                root = {}
            
            target = root
            # 2. 부모(KipoWindow)로부터 현재 프로필 인덱스 참조
            p = self.parent() if self.parent() else None
            profile_idx = str(getattr(p, 'current_profile_idx', 'M')) if p else 'M'
            
            if 'profiles' in root and profile_idx in root['profiles']:
                 target = root['profiles'][profile_idx]
            
            # 3. 위젯 값 설정
            self.input_wait.setText(str(target.get('bultagi_wait_sec', 30)))
            
            mode = target.get('bultagi_mode', 'multiplier')
            self.combo_mode.setCurrentIndex(0 if mode == 'multiplier' else 1)
            self.input_val.setText(str(target.get('bultagi_val', '10')))
            
            ptype = target.get('bultagi_price_type', 'market')
            self.combo_price_type.setCurrentIndex(0 if ptype == 'market' else 1)
            
            self.chk_tp.setChecked(target.get('bultagi_tp_enabled', True))
            self.input_tp.setText(str(target.get('bultagi_tp', 5.0)))
            
            self.chk_preservation.setChecked(target.get('bultagi_preservation_enabled', False))
            self.input_p_trigger.setText(str(target.get('bultagi_preservation_trigger', 3.0)))
            self.input_p_limit.setText(str(target.get('bultagi_preservation_limit', 2.0)))
            
            self.chk_sl.setChecked(target.get('bultagi_sl_enabled', True))
            self.input_sl.setText(str(target.get('bultagi_sl', -2.0)))
            
            self.chk_trailing.setChecked(target.get('bultagi_trailing_enabled', False))
            self.input_trailing.setText(str(target.get('bultagi_trailing_val', 1.0)))
            self.input_ts_start.setText(str(target.get('bultagi_trailing_start_rate', 0.5)))
            
            self.chk_power.setChecked(target.get('bultagi_power_enabled', False))
            self.input_power.setText(str(target.get('bultagi_power_val', 120)))
            self.chk_slope.setChecked(target.get('bultagi_slope_enabled', False))
            self.chk_orderbook.setChecked(target.get('bultagi_orderbook_enabled', False))
            self.input_orderbook.setText(str(target.get('bultagi_orderbook_val', 2.0)))

            # [신규 v4.4.0] 지수 정지 설정 로드 (Root 우선)
            self.chk_idx_stop.setChecked(root.get('global_idx_stop_enabled', False))
            self.spin_kospi_threshold.setValue(float(root.get('kospi_stop_threshold', -1.5)))
            self.spin_kosdaq_threshold.setValue(float(root.get('kosdaq_stop_threshold', -2.0)))
            
            # [신규 v5.1.33] VI 발동 중 매수 금지 설정 로드
            self.chk_block_buy_vi.setChecked(root.get('block_buy_during_vi', False))

            # [신규 v5.3.5] 텔레그램 발송 설정 로드 📡
            self.chk_tel_on.setChecked(root.get('tel_on', True))

            # [신규 v6.9.5] Turbo VI 로드
            self.chk_turbo_vi.setChecked(target.get('bultagi_turbo_vi', False))
            turbo_type = target.get('bultagi_turbo_vi_type', 'current') # 기본 현재가
            self.combo_turbo_vi_type.setCurrentIndex(0 if turbo_type == 'market' else 1)

            # [신규 v2.0.0] Turbo VI 상세 필터 로드
            min_val = target.get('bultagi_turbo_vi_min_price', '0')
            self.input_turbo_min_price.setValue(int(min_val) if str(min_val).isdigit() else 0)
            max_val = target.get('bultagi_turbo_vi_max_price', '99999999')
            self.input_turbo_max_price.setValue(int(max_val) if str(max_val).isdigit() else 99999999)
            self.chk_turbo_static.setChecked(target.get('bultagi_turbo_vi_static', True))
            self.chk_turbo_dynamic.setChecked(target.get('bultagi_turbo_vi_dynamic', True))
            
            # [V3.3.8] 거래대금 상위 필터 로드
            self.chk_turbo_volume.setChecked(target.get('bultagi_turbo_vi_volume_enabled', False))
            self.input_turbo_volume.setValue(int(target.get('bultagi_turbo_vi_volume_rank', 100)))

            # 잡주 제외 필터 로드 (기본값 True)
            self.chk_turbo_ex_etf.setChecked(target.get('bultagi_turbo_ex_etf', True))
            self.chk_turbo_ex_spac.setChecked(target.get('bultagi_turbo_ex_spac', True))
            self.chk_turbo_ex_prefer.setChecked(target.get('bultagi_turbo_ex_prefer', True))

            # [핵심] KipoStock 관점 로드 (프로필 데이터 'target' 우선 활용)
            try:
                self.spin_peak.setValue(float(target.get('kipostock_peak_rt', 15.0)))
                self.spin_now_min.setValue(float(target.get('kipostock_now_rt_min', 5.0)))
                self.spin_now_max.setValue(float(target.get('kipostock_now_rt_max', 12.0)))
                self.input_perspective_time.setText(str(target.get('kipostock_perspective_time', '15:10')))

                # [신규] 시초가 베팅 파라미터 로드
                self.chk_morning_enabled.setChecked(target.get('morning_bet_enabled', False))
                self.input_morning_time.setText(str(target.get('morning_time', '09:10')))
                self.spin_morning_gap_min.setValue(float(target.get('morning_gap_min', 3.0)))
                self.spin_morning_gap_max.setValue(float(target.get('morning_gap_max', 5.0)))
                self.spin_morning_break.setValue(float(target.get('morning_break_rt', 2.0)))
                self.spin_morning_tp.setValue(float(target.get('morning_tp', 2.0)))
                self.spin_morning_sl.setValue(float(target.get('morning_sl', -1.5)))

                # [신규 v5.3.7/v5.3.8] 불타기 가격 상한선 로드 (QLineEdit 방식)
                self.chk_bultagi_limit.setChecked(root.get('bultagi_limit_enabled', True))
                self.input_bultagi_limit.setText(str(root.get('bultagi_limit_rt', 22.0)))
                self.chk_morning_ai.setChecked(target.get('morning_ai_filter', True))
                
                # [신규] 시초가 전략별 활성화 플래그 로드 (A~D)
                self.chk_morning_a.setChecked(target.get('morning_bet_use_a', True))
                self.chk_morning_b.setChecked(target.get('morning_bet_use_b', False))
                self.chk_morning_c.setChecked(target.get('morning_bet_use_c', False))
                # self.chk_morning_d 영구 제거

                # [v2.2.0] Ranking Scout 로드 (프로필 연동)
                self.chk_rank_scout.setChecked(target.get('rank_scout_enabled', False))
                new_val = int(target.get('rank_scout_new_threshold', 10))
                idx_new = {5: 0, 10: 1, 15: 2, 20: 3}.get(new_val, 1)
                self.spin_rank_new.setCurrentIndex(idx_new)

                jump_val = int(target.get('rank_scout_jump_threshold', 10))
                idx_jump = {5: 0, 10: 1, 15: 2, 20: 3}.get(jump_val, 1)
                self.spin_rank_jump.setCurrentIndex(idx_jump)

                # [v5.2.0] 연속 상승 로드 (0: 사용안함, 3, 4, 5)
                consec_val = int(target.get('rank_scout_consecutive_count', 0))
                idx_consec = {0: 0, 3: 1, 4: 2, 5: 3}.get(consec_val, 0)
                self.spin_rank_consecutive.setCurrentIndex(idx_consec)

                int_val = int(target.get('rank_scout_interval', 30))
                # API 코드(qry_tp): 5:30s, 1:1m, 2:10m, 3:1h, 4:day
                # UI 인덱스: 0:30s, 1:1m, 2:10m, 3:1h, 4:day
                idx_int = {30: 0, 60: 1, 600: 2, 3600: 3, 0: 4}.get(int_val, 0)
                # [V5.3.0] AI Morning Sniper 로드
                self.chk_morning_ai_selection.setChecked(target.get('morning_ai_selection_enabled', False))
                self.spin_morning_ai_count.setValue(int(target.get('morning_ai_count', 3)))
                self.chk_morning_ai_news.setChecked(target.get('morning_ai_use_news', True))

            except Exception as e2:
                print(f"⚠️ Perspective/Morning Settings Load Error: {e2}")

        except Exception as e:
            print(f"❌ load_settings 치명적 오류: {e}")

    def apply_settings(self):
        try:
            from PyQt6.QtWidgets import QMessageBox
            from get_setting import get_setting
            import re
            
            # [Fix] 입력값 추출 시 공백 제거 및 기본값 처리
            def _get_float(widget, default=0.0):
                try: return float(widget.text().replace('%', '').strip() or default)
                except: return default

            tp_en = self.chk_tp.isChecked()
            tp_val = _get_float(self.input_tp, 5.0)
            
            p_en = self.chk_preservation.isChecked()
            p_trigger = _get_float(self.input_p_trigger, 3.0)
            p_limit = _get_float(self.input_p_limit, 2.0)
            
            sl_en = self.chk_sl.isChecked()
            sl_val = _get_float(self.input_sl, -2.0)

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

            val_text = self.input_val.text().replace(',', '').strip()
            if not val_text: val_text = '10'

            # [신규 v6.1.19] 시간 형식 검사 (HH:MM)
            p_time = self.input_perspective_time.text().strip()
            if not re.match(r"^\d{2}:\d{2}$", p_time):
                QMessageBox.warning(self, "입력 오류", "분석 시간 형식이 올바르지 않습니다. (예: 15:10)")
                return
            
            root = self._read_json()
            updates = {
                'bultagi_wait_sec': int(self.input_wait.text().strip() or 30),
                'bultagi_mode': 'multiplier' if self.combo_mode.currentIndex() == 0 else 'amount',
                'bultagi_val': val_text,
                'bultagi_price_type': 'market' if self.combo_price_type.currentIndex() == 0 else 'current',
                'bultagi_tp_enabled': tp_en,
                'bultagi_tp': tp_val,
                'bultagi_preservation_enabled': p_en,
                'bultagi_preservation_trigger': p_trigger,
                'bultagi_preservation_limit': p_limit,
                'bultagi_sl': sl_val,
                'bultagi_trailing_enabled': self.chk_trailing.isChecked(),
                'bultagi_trailing_val': _get_float(self.input_trailing, 1.0),
                'bultagi_trailing_start_rate': _get_float(self.input_ts_start, 0.5),
                'bultagi_power_enabled': self.chk_power.isChecked(),
                'bultagi_power_val': int(self.input_power.text().strip() or 120), # [v2.5.0] AI 뉴스 브리핑 음성 토글 기능 추가 및 무한 루프 버그 수정
                'bultagi_slope_enabled': self.chk_slope.isChecked(),
                'bultagi_orderbook_enabled': self.chk_orderbook.isChecked(),
                'bultagi_orderbook_val': float(self.input_orderbook.text().strip() or 2.0),
                # [신규 v4.4.4] 지수 정지 설정 저장
                'global_idx_stop_enabled': self.chk_idx_stop.isChecked(),
                'kospi_stop_threshold': self.spin_kospi_threshold.value(),
                'kosdaq_stop_threshold': self.spin_kosdaq_threshold.value(),
                # [신규 v5.1.33] VI 발동 중 매수 금지 설정 저장 (Root 레벨)
                'block_buy_during_vi': self.chk_block_buy_vi.isChecked(),
                # [신규 v5.3.5] 텔레그램 발송 설정 저장 📡
                'tel_on': self.chk_tel_on.isChecked(),
                'bultagi_turbo_vi': self.chk_turbo_vi.isChecked(),
                'bultagi_turbo_vi_type': 'market' if self.combo_turbo_vi_type.currentIndex() == 0 else 'current',
                'bultagi_turbo_vi_min_price': str(self.input_turbo_min_price.value()),
                'bultagi_turbo_vi_max_price': str(self.input_turbo_max_price.value()),
                'bultagi_turbo_vi_static': self.chk_turbo_static.isChecked(),
                'bultagi_turbo_vi_dynamic': self.chk_turbo_dynamic.isChecked(),
                # [V3.3.8] 신규 필드 저장
                'bultagi_turbo_vi_volume_enabled': self.chk_turbo_volume.isChecked(),
                'bultagi_turbo_vi_volume_rank': self.input_turbo_volume.value(),
                
                'bultagi_turbo_ex_etf': self.chk_turbo_ex_etf.isChecked(),
                'bultagi_turbo_ex_spac': self.chk_turbo_ex_spac.isChecked(),
                'bultagi_turbo_ex_prefer': self.chk_turbo_ex_prefer.isChecked(),
                'kipostock_peak_rt': self.spin_peak.value(),
                'kipostock_now_rt_min': self.spin_now_min.value(),
                'kipostock_now_rt_max': self.spin_now_max.value(),
                'kipostock_perspective_time': p_time,
                'morning_bet_enabled': self.chk_morning_enabled.isChecked(),
                'morning_time': self.input_morning_time.text().strip() or '09:10',
                'morning_gap_min': self.spin_morning_gap_min.value(),
                'morning_gap_max': self.spin_morning_gap_max.value(),
                'morning_break_rt': self.spin_morning_break.value(),
                'morning_tp': self.spin_morning_tp.value(),
                'morning_sl': self.spin_morning_sl.value(),
                'morning_ai_filter': self.chk_morning_ai.isChecked(),
                'morning_bet_use_a': self.chk_morning_a.isChecked(),
                'morning_bet_use_b': self.chk_morning_b.isChecked(),
                'morning_bet_use_c': self.chk_morning_c.isChecked(),
                # [v2.2.0 Ranking Scout 저장]
                'rank_scout_enabled': self.chk_rank_scout.isChecked(),
                'rank_scout_new_threshold': [5, 10, 15, 20][self.spin_rank_new.currentIndex()],
                'rank_scout_jump_threshold': [5, 10, 15, 20][self.spin_rank_jump.currentIndex()],
                'rank_scout_consecutive_count': [0, 3, 4, 5][self.spin_rank_consecutive.currentIndex()],
                'rank_scout_interval': [30, 60, 600, 3600, 0][self.spin_rank_interval.currentIndex()],
                'rank_scout_qry_tp': ['5', '1', '2', '3', '4'][self.spin_rank_interval.currentIndex()],
                # [V5.3.0] AI Morning Sniper 저장
                'morning_ai_selection_enabled': self.chk_morning_ai_selection.isChecked(),
                'morning_ai_count': self.spin_morning_ai_count.value(),
                'morning_ai_use_news': self.chk_morning_ai_news.isChecked(),
                # [신규 v5.3.7/v5.3.8] 불타기 가격 상한선 저장 (QLineEdit 방식)
                'bultagi_limit_enabled': self.chk_bultagi_limit.isChecked(),
                'bultagi_limit_rt': float(self.input_bultagi_limit.text().replace('%', '').strip() or 22.0)
            }
            
            # Update root
            for k, v in updates.items(): root[k] = v
            
            # Update active profile
            p = self.parent()
            current_profile = getattr(p, 'current_profile_idx', None)
            if current_profile is not None:
                if 'profiles' not in root: root['profiles'] = {}
                p_key = str(current_profile)
                if p_key not in root['profiles']: root['profiles'][p_key] = {}
                for k, v in updates.items(): 
                    root['profiles'][p_key][k] = v
            
            # 파일 저장 (AsyncWorker가 동시에 쓸 수 있으므로 안전하게 처리)
            try:
                with open(self.settings_file, 'w', encoding='utf-8') as f:
                    json.dump(root, f, ensure_ascii=False, indent=2)
                # [V5.3.9] 저장 직후 설정 캐시 즉시 초기화 → 감시엔진이 다음 루프에서 바로 반영
                from get_setting import clear_settings_cache
                clear_settings_cache()
            except Exception as fe:
                print(f"⚠️ 설정 파일 쓰기 오류: {fe}")

            # Live hot-reload into check_n_sell
            if p and hasattr(p, 'worker') and p.worker:
                p.worker.schedule_command('update_settings', updates, True)
            
            # [v2.2.0/V2.4.4] Ranking Scout 엔진 파라미터 리로드 (worker를 통해 안전하게)
            if p and hasattr(p, 'worker') and p.worker:
                p.worker.schedule_command('rank_reload')

            # [UX 신규] 저장 시 버튼 시각적 피드백 효과 연출 
            self.btn_save.setText("✅ 저장 완료")
            self.btn_save.setEnabled(False)
            self.btn_save.setStyleSheet("background-color: #28a745; color: white;")
            
            # [Fix] QTimer.singleShot의 람다 및 수신자 인자 안정화
            QTimer.singleShot(1500, self._reset_save_button)
            
        except ValueError:
            QMessageBox.warning(self, "입력 오류", "숫자 형식으로 정확히 입력해주세요.")
        except Exception as e:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "치명적 오류", f"설정 저장 중 오류가 발생했습니다: {e}")
            print(f"❌ apply_settings 치명적 오류: {e}")

    def _reset_save_button(self):
        """저장 완료 피드백 후 버튼 상태 복구"""
        try:
            self.btn_save.setText("💾 설정 저장")
            self.btn_save.setEnabled(True)
            self.btn_save.setStyleSheet("""
                QPushButton { 
                    background-color: #dc3545; color: white; font-weight: bold;
                    border-radius: 6px; padding: 8px; font-size: 13px;
                }
                QPushButton:hover { background-color: #c82333; }
            """)
        except: pass

    # [v6.4.8] 종목 탐색 버튼 핸들러
    def _open_kipo_filter_dialog(self):
        """KipoStock 필터 다이얼로그 열기 (장 시간 무관)"""
        dlg = KipoFilterListDialog(parent=self)
        dlg.exec()


# --- 스레드 워커 클래스 (클래스 레벨로 분리하여 안정성 확보) ---
class KipoWorker(QThread):
    done_signal = pyqtSignal(list)
    def __init__(self, parent=None):
        super().__init__(parent)
    def run(self):
        try:
            from closing_bet_engine import get_kipo_filter_stocks
            stocks = get_kipo_filter_stocks(token=None)
            self.done_signal.emit(stocks)
        except:
            self.done_signal.emit([])

class AIWorker(QThread):
    done_signal = pyqtSignal(list)
    def __init__(self, kipo_stocks, parent=None):
        super().__init__(parent)
        self.kipo_stocks = kipo_stocks
    def run(self):
        try:
            from closing_bet_engine import get_ai_closing_recommendations
            ai_stocks = get_ai_closing_recommendations(kipo_stocks=self.kipo_stocks)
            self.done_signal.emit(ai_stocks)
        except:
            self.done_signal.emit([])

class BuyWorker(QThread):
    done_signal = pyqtSignal(list)
    def __init__(self, stocks_to_buy, parent=None):
        super().__init__(parent)
        self.stocks_to_buy = stocks_to_buy
    def run(self):
        msgs = []
        try:
            from closing_bet_engine import buy_stock_qty1
            for s in self.stocks_to_buy:
                ok, msg = buy_stock_qty1(s['code'], seq_name="종베직접매수")
                msgs.append(msg)
        except Exception as e:
            msgs.append(f"❌ 매수 루프 치명적 오류: {e}")
        self.done_signal.emit(msgs)

# =============================================================================
# ✅ [신규 v6.4.8] KipoStock 필터 종목 리스트 다이얼로그
# =============================================================================
class KipoFilterListDialog(QDialog):
    """KipoStock 관점 필터 조건으로 탐색된 종목 리스트 + AI 추천 버튼"""

    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.Window)
        self.setWindowTitle("KipoStock 필터 종목 리스트")
        self.setMinimumSize(480, 520)
        self.resize(520, 580)
        self._apply_style()

        self._kipo_stocks = []
        self._ai_stocks   = []
        self._kipo_worker = None
        self._ai_worker   = None

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        # ... (이하 레이아웃 생략, 상위에서 이미 확인됨)

        # --- 상단: 조건 요약 ---
        from get_setting import get_setting as _gs
        peak  = _gs('kipostock_peak_rt',    15.0)
        nmin  = _gs('kipostock_now_rt_min',  5.0)
        nmax  = _gs('kipostock_now_rt_max', 12.0)
        p_t   = _gs('kipostock_perspective_time', '15:10')
        lbl_cond = QLabel(
            f"🎯 고가달성 ≥ {peak}%  |  📊 현재수익 {nmin}% ~ {nmax}%  |  ⏰ 분석시간: {p_t}"
        )
        lbl_cond.setStyleSheet("color: #f1c40f; font-size: 11px; font-weight: bold;")
        lbl_cond.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(lbl_cond)

        # --- 상태 라벨 ---
        self.lbl_status = QLabel("⏳ 종목 탐색 중...")
        self.lbl_status.setStyleSheet("color: #aaaaaa; font-size: 11px;")
        self.lbl_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.lbl_status)

        # --- 종목 리스트 (체크박스) ---
        lbl_list = QLabel("📌 KipoStock 필터 통과 종목")
        lbl_list.setStyleSheet("color: #f1c40f; font-weight: bold;")
        layout.addWidget(lbl_list)

        self.list_widget = QListWidget()
        from PyQt6.QtWidgets import QAbstractItemView
        self.list_widget.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection) # [v1.4.3] 선택 효과(파란 배경) 제거
        self.list_widget.setFocusPolicy(Qt.FocusPolicy.NoFocus) # [v1.4.3] 클릭 시 포커스 테두리 제거

        self.list_widget.setStyleSheet(
            "QListWidget { background:#2a2a2a; color:#ffffff; border:1px solid #555; border-radius:6px; outline: 0; }" # [v1.4.3] outline:0 추가
            " QListWidget::item { padding: 0px; border-bottom: 1px solid #3a3a3a; }" # [v1.4.3] 패딩 0 (위젯에서 처리)
            " QListWidget::item:selected { background: transparent; }" # [v1.4.3] 선택 배경 투명화
        )
        self.list_widget.setMinimumHeight(180)
        layout.addWidget(self.list_widget)

        # --- 하단 버튼 ---
        btn_row1 = QHBoxLayout()
        self.btn_ai = QPushButton("🤖 AI 종가 추천 받기")
        self.btn_ai.setStyleSheet(
            "QPushButton { background:#9b59b6; color:white; font-weight:bold;"
            " border-radius:6px; padding:8px; font-size:13px; }"
            " QPushButton:hover { background:#8e44ad; }"
            " QPushButton:disabled { background:#555; color:#888; }"
        )
        self.btn_ai.clicked.connect(self._run_ai_recommend)
        btn_row1.addWidget(self.btn_ai)
        layout.addLayout(btn_row1)

        btn_row2 = QHBoxLayout()
        self.btn_open_order = QPushButton("💸 선택 → 종가 베팅 창 열기")
        self.btn_open_order.setStyleSheet(
            "QPushButton { background:#e67e22; color:white; font-weight:bold;"
            " border-radius:6px; padding:8px; font-size:13px; }"
            " QPushButton:hover { background:#ca6f1e; }"
            " QPushButton:disabled { background:#555; color:#888; }"
        )
        self.btn_open_order.setEnabled(False)
        self.btn_open_order.clicked.connect(self._open_closing_bet_dialog)
        btn_cancel = QPushButton("닫기")
        btn_cancel.setObjectName("btn_cancel_kf")
        btn_cancel.setStyleSheet(
            "QPushButton { background:#6c757d; color:white; border-radius:6px; padding:8px; font-size:13px; }"
        )
        btn_cancel.clicked.connect(self.reject)
        btn_row2.addWidget(btn_cancel)
        btn_row2.addWidget(self.btn_open_order)
        layout.addLayout(btn_row2)

        # 열자마자 비동기 탐색 시작
        QTimer.singleShot(200, self._run_kipo_filter)

    def _apply_style(self):
        """부모 창의 테마를 안전하게 감지하여 적용"""
        try:
            # Main Window(KipoWindow) 혹은 부모를 통해 ui_theme 획득
            p = self.parent()
            theme = 'dark'
            while p:
                if hasattr(p, 'ui_theme'):
                    theme = p.ui_theme
                    break
                p = p.parent()
            
            is_light = (theme == 'light')
            bg  = '#f8f9fa' if is_light else '#1e1e1e'
            fg  = '#333333' if is_light else '#ffffff'
            self.setStyleSheet(
                f"QDialog {{ background:{bg}; color:{fg}; }}"
                f" QLabel {{ color:{fg}; font-weight:bold; }}"
            )
        except Exception:
            self.setStyleSheet("QDialog { background:#1e1e1e; color:#ffffff; }")

    # ---- 탐색 로직 (정규화된 QThread 패턴) ----
    def _run_kipo_filter(self):
        if self._kipo_worker and self._kipo_worker.isRunning():
            return
            
        self.lbl_status.setText("⏳ KipoStock 필터 종목 탐색 중...")
        self.btn_ai.setEnabled(False)
        self.btn_open_order.setEnabled(False)

        self._kipo_worker = KipoWorker(self)
        self._kipo_worker.done_signal.connect(self._on_kipo_done)
        self._kipo_worker.start()

    def _on_kipo_done(self, stocks):
        from PyQt6 import sip
        if sip.isdeleted(self): return
        
        self._kipo_stocks = stocks
        self.list_widget.clear()

        if not stocks:
            self.lbl_status.setText("ℹ️ 조건을 만족하는 종목 없음 (또는 데이터 부족)")
        else:
            self.lbl_status.setText(f"✅ {len(stocks)}종목 탐색 완료")
            for s in stocks:
                item = QListWidgetItem()
                widget = _CheckableStockRow(s)
                item.setSizeHint(widget.sizeHint())
                self.list_widget.addItem(item)
                self.list_widget.setItemWidget(item, widget)

        self.btn_ai.setEnabled(True)
        self.btn_open_order.setEnabled(True)

    def _run_ai_recommend(self):
        if self._ai_worker and self._ai_worker.isRunning():
            return
            
        self.btn_ai.setEnabled(False)
        self.btn_ai.setText("⏳ AI 분석 중...")

        self._ai_worker = AIWorker(list(self._kipo_stocks), self)
        self._ai_worker.done_signal.connect(self._on_ai_done)
        self._ai_worker.start()

    def _on_ai_done(self, ai_stocks):
        from PyQt6 import sip
        if sip.isdeleted(self): return
        
        self._ai_stocks = ai_stocks
        self.btn_ai.setText("🤖 AI 종가 추천 받기")
        self.btn_ai.setEnabled(True)

        # AI 결과 리스트에 추가 표시
        if ai_stocks:
            # 구분선
            sep = QListWidgetItem("── 🤖 AI 추천 종목 ──")
            sep.setFlags(Qt.ItemFlag.NoItemFlags)
            sep.setForeground(Qt.GlobalColor.yellow)
            self.list_widget.addItem(sep)

            for s in ai_stocks:
                item = QListWidgetItem()
                widget = _CheckableStockRow(s, show_reason=True)
                item.setSizeHint(widget.sizeHint())
                self.list_widget.addItem(item)
                self.list_widget.setItemWidget(item, widget)
            self.lbl_status.setText(
                f"✅ KipoFilter {len(self._kipo_stocks)}종목 + AI 추천 {len(ai_stocks)}종목"
            )
        else:
            self.lbl_status.setText("⚠️ AI 추천 결과 없음 (데이터 부족 또는 API 오류)")

    def _open_closing_bet_dialog(self):
        """체크된 종목을 모아 종가 베팅 통합 주문 창 열기"""
        selected = []
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            widget = self.list_widget.itemWidget(item)
            if widget and isinstance(widget, _CheckableStockRow) and widget.is_checked():
                selected.append(widget.stock_data)

        if not selected:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.information(self, "선택 없음", "매수할 종목을 체크해주세요!")
            return

        dlg = ClosingBetOrderDialog(selected, parent=self)
        dlg.exec()


# --- 체크박스 행 위젯 (내부 헬퍼) ---
class _CheckableStockRow(QWidget):
    def __init__(self, stock_data, show_reason=False, parent=None):
        super().__init__(parent)
        self.stock_data = stock_data
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6) # [v1.4.2] 상하 여백 넉넉히
        layout.setSpacing(12)
        self.setMinimumHeight(60) # [v1.4.2] 행 높이 강제 확장 (잘림 방지 필수!)

        self._chk = QCheckBox()
        self._chk.setChecked(True)  # 기본 체크
        layout.addWidget(self._chk)

        source_icon = "🤖" if stock_data.get('source') == 'AI' else "🎯"
        name   = stock_data.get('name',      '')
        code   = stock_data.get('code',      '')
        cur_rt = stock_data.get('cur_rt',   0.0)
        high_rt= stock_data.get('high_rt',  0.0)
        price  = stock_data.get('cur_price', 0)
        reason = stock_data.get('reason',    '')

        rt_color = "#ff4757" if cur_rt > 0 else "#3742fa"
        # [v1.4.1] 자기 요청 반영: 바깥은 종목명, 괄호 안은 종목코드
        display_name = name if name and name != code else f"종목({code})"
        main_text = f"{source_icon} <b style='font-size:13px;'>{display_name}</b> <span style='color:#aaaaaa;'>({code})</span> "
        
        # 수익률 표시 보완
        if cur_rt != 0 or price != 0:
            main_text += f"<span style='color:{rt_color}'>+{cur_rt:.1f}%</span>"
            
        if high_rt and stock_data.get('source') != 'AI':
            main_text += f" | 고가 {high_rt:.1f}%"
        
        if price:
            main_text += f" | {price:,}원"

        lbl_main = QLabel(main_text)
        lbl_main.setStyleSheet("color: #ffffff; font-size: 12px;")
        lbl_main.setTextFormat(Qt.TextFormat.RichText)

        col_layout = QVBoxLayout()
        col_layout.setContentsMargins(0, 0, 0, 0)
        col_layout.setSpacing(6) # [v1.4.2] 타이틀과 이유 사이 간격
        col_layout.addWidget(lbl_main)

        if show_reason and reason:
            lbl_reason = QLabel(f"  └ ✨ {reason}")
            lbl_reason.setStyleSheet("color: #9b59b6; font-size: 11px; font-style: italic;")
            lbl_reason.setWordWrap(True)
            col_layout.addWidget(lbl_reason)

        layout.addLayout(col_layout)
        layout.addStretch()

    def is_checked(self):
        return self._chk.isChecked()


# =============================================================================
# ✅ [신규 v6.4.8] 종가 베팅 통합 주문 다이얼로그
# =============================================================================
class ClosingBetOrderDialog(QDialog):
    """KipoFilter + AI 추천 종목 체크 → 1주씩 매수"""

    def __init__(self, stocks, parent=None):
        super().__init__(parent, Qt.WindowType.Window)
        self.setWindowTitle("🎯 종가 베팅 주문 창")
        self.setMinimumSize(560, 480)
        self.resize(580, 520)
        self._stocks = stocks
        self._row_checks = []  # (QCheckBox, stock_dict)
        self._apply_style()

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # 제목
        lbl_title = QLabel("🎯 종가 베팅 종목 선택 및 매수 (1주씩)")
        lbl_title.setStyleSheet("color: #f1c40f; font-size: 14px; font-weight: bold;")
        lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(lbl_title)

        # 테이블
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["선택", "종목명", "현재가", "수익률", "출처"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setColumnWidth(0, 46)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setStyleSheet(
            "QTableWidget { background:#1a1a1a; gridline-color:#333; color:#ddd;"
            " border:1px solid #444; border-radius:8px; font-size:12px; }"
            " QHeaderView::section { background:#2c3e50; color:#f1c40f; font-weight:bold;"
            " border:1px solid #34495e; padding:4px; }"
            " QTableWidget::item { padding:4px; }"
            " QTableWidget::item:alternate { background:#222; }"
        )
        layout.addWidget(self.table)

        self._fill_table()

        # 상태 라벨
        self.lbl_result = QLabel("")
        self.lbl_result.setStyleSheet("color: #2ecc71; font-size: 12px; font-weight: bold;")
        self.lbl_result.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_result.setWordWrap(True)
        layout.addWidget(self.lbl_result)

        # 버튼
        btn_row = QHBoxLayout()
        btn_cancel = QPushButton("닫기")
        btn_cancel.setStyleSheet(
            "QPushButton { background:#6c757d; color:white; border-radius:6px; padding:8px; font-size:13px; }"
        )
        btn_cancel.clicked.connect(self.reject)

        self.btn_buy = QPushButton("💸 선택 종목 1주씩 매수")
        self.btn_buy.setStyleSheet(
            "QPushButton { background:#e74c3c; color:white; font-weight:bold;"
            " border-radius:6px; padding:10px; font-size:14px; }"
            " QPushButton:hover { background:#c0392b; }"
            " QPushButton:disabled { background:#555; color:#888; }"
        )
        self.btn_buy.clicked.connect(self._execute_buy)
        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(self.btn_buy)
        layout.addLayout(btn_row)

    def _apply_style(self):
        self.setStyleSheet(
            "QDialog { background:#1e1e1e; color:#ffffff; }"
            " QLabel { color:#ffffff; }"
        )

    def _fill_table(self):
        self.table.setRowCount(len(self._stocks))
        self._row_checks.clear()
        for row, s in enumerate(self._stocks):
            # 체크박스
            chk = QCheckBox()
            chk.setChecked(True)
            chk_widget = QWidget()
            chk_layout = QHBoxLayout(chk_widget)
            chk_layout.addWidget(chk)
            chk_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            chk_layout.setContentsMargins(0, 0, 0, 0)
            self.table.setCellWidget(row, 0, chk_widget)
            self._row_checks.append((chk, s))

            # 종목명 (코드)
            self.table.setItem(row, 1, QTableWidgetItem(
                f"{s.get('name','')} ({s.get('code','')})")
            )

            # 현재가
            price = s.get('cur_price', 0)
            self.table.setItem(row, 2, QTableWidgetItem(f"{price:,}원" if price else "-"))

            # 수익률
            cur_rt = s.get('cur_rt', 0.0)
            rt_item = QTableWidgetItem(f"+{cur_rt:.1f}%" if cur_rt >= 0 else f"{cur_rt:.1f}%")
            rt_item.setForeground(
                Qt.GlobalColor.red if cur_rt > 0 else Qt.GlobalColor.blue
            )
            self.table.setItem(row, 3, rt_item)

            # 출처
            src = s.get('source', '')
            icon = "🤖 AI" if src == 'AI' else "🎯 필터"
            self.table.setItem(row, 4, QTableWidgetItem(icon))

    def _execute_buy(self):
        selected = [(chk, s) for chk, s in self._row_checks if chk.isChecked()]
        if not selected:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.information(self, "선택 없음", "매수할 종목을 하나 이상 선택해주세요!")
            return

        self.btn_buy.setEnabled(False)
        self.btn_buy.setText("⏳ 매수 중...")
        self.lbl_result.setText("")

        self._buy_worker = BuyWorker([s for _, s in selected], self)
        self._buy_worker.done_signal.connect(self._on_buy_done)
        self._buy_worker.start()

    def _on_buy_done(self, msgs):
        from PyQt6 import sip
        if sip.isdeleted(self): return
        
        self.btn_buy.setEnabled(True)
        self.btn_buy.setText("💸 선택 종목 1주씩 매수")
        self.lbl_result.setText("\n".join(msgs))

        # 메인 창 로그에도 출력
        try:
            main_win = self.window()
            if hasattr(main_win, 'log_text'):
                for m in msgs:
                    # [v6.5.1] f-string syntax error 해결: \ 제거
                    print(f"🎯 [종베] {m}")
        except Exception:
            pass


# =============================================================================
# ✅ [신규 v6.7.5] 전체 매매 일지 조회 다이얼로그
# =============================================================================
# ✅ [v1.8.9] 매매 내역 HTS 동기화용 백그라운드 워커
# =============================================================================
class HistoryWorker(QThread):
    done_signal = pyqtSignal(list)

    def __init__(self, chat_cmd):
        super().__init__()
        self.chat_cmd = chat_cmd

    def run(self):
        """별도 스레드에서 asyncio 루프를 돌려 HTS API 호출 (GUI 프리징 방지)"""
        try:
            import asyncio
            # [Fix] 기존 루프가 있을 수 있으므로 새 루프 생성 및 격리
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                # [v1.9.8.2] 최신순(is_reverse=True)으로 가져와서 동기화 효율 상향
                trades = loop.run_until_complete(self.chat_cmd.today(sync_only=False, is_reverse=True))
                self.done_signal.emit(trades if trades else [])
            finally:
                loop.close()
        except Exception as e:
            print(f"⚠️ [HistoryWorker] 동기화 중 오류: {e}")
            self.done_signal.emit([])

# ✅ [신규 v6.7.5] 전체 매매 일지 조회 다이얼로그
# =============================================================================
class HistoryDialog(QDialog):
    """SQLite DB에 저장된 모든 매매 내역을 표형태로 보여주는 창"""

    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.Window)
        self.setWindowTitle("📜 KipoStock 전체 매매 일지")
        self.setMinimumSize(900, 600)
        self.resize(1000, 700)
        self._apply_style()

        layout = QVBoxLayout(self)
        
        # --- 상단 타이틀 및 필터 ---
        header = QHBoxLayout()
        lbl_title = QLabel("📝 전체 매매 내역 (최근 1,000건)")
        lbl_title.setStyleSheet("font-size: 16px; font-weight: bold; color: #f1c40f;")
        header.addWidget(lbl_title)
        header.addStretch()
        
        self.btn_refresh = QPushButton("🔄 새로고침")
        self.btn_refresh.setFixedWidth(100)
        self.btn_refresh.clicked.connect(self.load_data)
        header.addWidget(self.btn_refresh)

        # [신규 v1.8.9] AI 패턴 분석 버튼 추가
        self.btn_ai_analysis = QPushButton("🤖 AI 패턴분석")
        self.btn_ai_analysis.setFixedWidth(120)
        self.btn_ai_analysis.setStyleSheet("background: #9b59b6; color: white;")
        self.btn_ai_analysis.clicked.connect(self._run_ai_pattern_analysis)
        header.addWidget(self.btn_ai_analysis)

        # [신규 v2.2.2] 전략 필터 콤보박스 추가
        header.addSpacing(20)
        header.addWidget(QLabel("🔍 전략 필터:"))
        self.combo_strat = QComboBox()
        self.combo_strat.setFixedWidth(150)
        self.combo_strat.addItems(["전체"])
        self.combo_strat.currentIndexChanged.connect(self._on_strat_filter_changed)
        header.addWidget(self.combo_strat)

        layout.addLayout(header)

        # [신규 v1.0.7] 전략별 통계 요약 레이아웃
        self.lbl_stats = QLabel("📊 통계 추출 중...")
        self.lbl_stats.setStyleSheet("""
            background: #2c3e50; color: #ecf0f1; padding: 10px; border-radius: 5px; 
            font-size: 13px; margin-bottom: 5px; border: 1px solid #34495e;
        """)
        layout.addWidget(self.lbl_stats)

        # --- 테이블 ---
        self.table = QTableWidget()
        headers = ["ID", "날짜", "시간", "구분", "종목명", "코드", "수량", "단가", "금액", "수익률(%)", "수익금(원)", "세금", "전략"]
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        
        # 테이블 스타일 및 설정
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True)
        
        layout.addWidget(self.table)
        
        # [v1.8.9] 창이 완전히 렌더링된 후 데이터를 로드하도록 0.1초 지연 호출 (GUI 프리징 방지)
        QTimer.singleShot(100, self.load_data)

    def _apply_style(self):
        theme = 'dark'
        try:
            p = self.parent()
            while p:
                if hasattr(p, 'ui_theme'):
                    theme = p.ui_theme
                    break
                p = p.parent()
        except: pass
        
        is_light = (theme == 'light')
        bg = '#f8f9fa' if is_light else '#1e1e1e'
        fg = '#333333' if is_light else '#ffffff'
        table_bg = '#ffffff' if is_light else '#1a1a1a'
        grid = '#dee2e6' if is_light else '#333333'
        
        self.setStyleSheet(f"""
            QDialog {{ background: {bg}; color: {fg}; }}
            QTableWidget {{ 
                background: {table_bg}; 
                gridline-color: {grid}; 
                color: {fg}; 
                border: 1px solid {grid};
                border-radius: 8px;
            }}
            QHeaderView::section {{ 
                background: {'#e9ecef' if is_light else '#2c3e50'}; 
                color: {'#333' if is_light else '#f1c40f'}; 
                font-weight: bold;
                border: 1px solid {grid};
                padding: 4px;
            }}
            QPushButton {{ 
                background: #3498db; color: white; border-radius: 4px; padding: 6px; font-weight: bold;
            }}
            QPushButton:hover {{ background: #2980b9; }}
        """)

    def load_data(self):
        """[v1.8.9] 1단계: 로컬 DB 즉시 로드 -> 2단계: HTS 비동기 동기화 (GUI 프리징 방지)"""
        try:
            self.btn_refresh.setEnabled(False)
            self.btn_refresh.setText("⏳ 동기화 중...")
            
            # [1단계] 우선 로컬 DB에 저장된 내역부터 빠르게 보여줌
            trades = kipo_db.get_all_trades(limit=1000)
            
            # [v4.2.6] 시간 데이터가 없는 무효 데이터 필터링 (사용자 요청)
            if trades:
                trades = [t for t in trades if t.get('trade_time') or t.get('buy_time') or t.get('time')]
                
            self.all_trades_cache = trades # [신규] 필터링을 위한 전체 데이터 캐싱
            
            if trades:
                self._update_strat_combo(trades) # 콤보박스 목록 갱신
                self._filter_and_display()     # 필터링 적용하여 표시
            else:
                self.table.setRowCount(0)
                if hasattr(self, 'lbl_stats'):
                    self.lbl_stats.setText("📊 매매 내역이 없습니다.")
        except Exception as e:
            print(f"⚠️ [HistoryDialog] DB 로드 오류: {e}")

        # [2단계] HTS 최신 데이터 비동기 동기화 시작 (백그라운드 스레드)
        try:
            # parent()를 통해 MainWindow 접근
            main_win = self.parent()
            if not main_win: main_win = self.window()
            
            if hasattr(main_win, 'worker') and main_win.worker and hasattr(main_win.worker, 'chat_command'):
                self._hts_worker = HistoryWorker(main_win.worker.chat_command)
                self._hts_worker.done_signal.connect(self._on_hts_done)
                self._hts_worker.start()
            else:
                self.btn_refresh.setEnabled(True)
                self.btn_refresh.setText("🔄 새로고침")
        except Exception as e:
            print(f"⚠️ [HistoryDialog] 비동기 동기화 트리거 오류: {e}")
            self.btn_refresh.setEnabled(True)
            self.btn_refresh.setText("🔄 새로고침")

    def _on_hts_done(self, trades):
        """HTS 동기화 완료 후 호출되는 콜백 (UI 갱신)"""
        from PyQt6 import sip
        if sip.isdeleted(self): return
        
        try:
            if trades:
                # [v1.9.8.2] HTS에서 가져온 데이터를 DB에 병합 (중복 제외)
                from kipodb import kipo_db
                new_sync_count = 0
                for t in trades:
                    if kipo_db.sync_trade_from_hts(t):
                        new_sync_count += 1
                
                # 병합 후 다시 DB에서 '전체' 내역을 최신순으로 불러와서 표시
                updated_trades = kipo_db.get_all_trades(limit=1000)
                self.all_trades_cache = updated_trades # 캐시 갱신
                self._update_strat_combo(updated_trades)
                self._filter_and_display()
                
                if new_sync_count > 0:
                    print(f"✅ [History] HTS 신규 매매 {new_sync_count}건 병합 완료")
            else:
                # 동기화 결과가 없더라도 기존 화면 유지
                pass
        except Exception as e:
            print(f"⚠️ [HistoryDialog] _on_hts_done 오류: {e}")
        finally:
            self.btn_refresh.setEnabled(True)
            self.btn_refresh.setText("🔄 새로고침")

    def _display_trades(self, trades):
        """전달된 거래 내역 데이터를 테이블에 렌더링"""
        self.table.setRowCount(len(trades))
        
        for row, t in enumerate(trades):
            # ID
            id_val = str(t.get('id', len(trades) - row))
            self.table.setItem(row, 0, QTableWidgetItem(id_val))
            
            # 날짜/시간
            t_date = t.get('trade_date') or t.get('date') or time.strftime("%Y%m%d")
            t_time = t.get('trade_time') or t.get('buy_time') or t.get('time', '--')
            self.table.setItem(row, 1, QTableWidgetItem(t_date))
            self.table.setItem(row, 2, QTableWidgetItem(t_time))
            
            # 구분
            t_type = t.get('type', 'BUY')
            type_item = QTableWidgetItem(t_type)
            if t_type == 'BUY':
                type_item.setForeground(QColor('#e74c3c'))
            else:
                type_item.setForeground(QColor('#2ecc71'))
            self.table.setItem(row, 3, type_item)
            
            # 종목명, 코드
            self.table.setItem(row, 4, QTableWidgetItem(t.get('name', '--')))
            self.table.setItem(row, 5, QTableWidgetItem(t.get('code', '--')))
            
            # 수량, 단가, 금액
            qty = t.get('qty') or t.get('buy_qty') or t.get('sel_qty') or 0
            price = t.get('price') or t.get('buy_avg') or t.get('sel_avg') or 0.0
            amount = t.get('amount') or t.get('buy_amt') or t.get('sel_amt') or 0.0
            
            # [v1.9.8.2] 거래 유형에 따른 수량/단가 폴백 (SELL인데 buy_qty만 있는 경우 등 대응)
            if t_type == 'SELL' and qty == 0:
                 qty = t.get('sel_qty') or t.get('buy_qty') or 0
            if t_type == 'SELL' and price == 0:
                 price = t.get('sel_avg') or t.get('buy_avg') or 0.0
            if t_type == 'SELL' and amount == 0:
                 amount = (float(qty) * float(price))
            
            self.table.setItem(row, 6, QTableWidgetItem(f"{int(float(qty)):,}"))
            self.table.setItem(row, 7, QTableWidgetItem(f"{float(price):,.0f}"))
            self.table.setItem(row, 8, QTableWidgetItem(f"{float(amount):,.0f}"))
            
            # 수익률, 수익금
            if t_type == 'SELL':
                pl_rt = t.get('pl_rt') or t.get('pnl_rt') or 0.0
                pnl_amt = t.get('pnl_amt') or t.get('pnl') or 0.0
                
                rt_item = QTableWidgetItem(f"{float(pl_rt):+.2f}%")
                rt_item.setForeground(QColor('#ff4757') if float(pl_rt) > 0 else QColor('#3742fa'))
                self.table.setItem(row, 9, rt_item)
                
                pnl_item = QTableWidgetItem(f"{float(pnl_amt):+,.0f}")
                pnl_item.setForeground(QColor('#ff4757') if float(pnl_amt) > 0 else QColor('#3742fa'))
                self.table.setItem(row, 10, pnl_item)
            else:
                self.table.setItem(row, 9, QTableWidgetItem("-"))
                self.table.setItem(row, 10, QTableWidgetItem("-"))
            
            # 세금, 전략
            tax = t.get('tax') or 0.0
            self.table.setItem(row, 11, QTableWidgetItem(f"{float(tax):,.0f}"))
            
            strat = t.get('strat_nm') or t.get('strat_mode') or '--'
            self.table.setItem(row, 12, QTableWidgetItem(strat))
            
            for col in range(self.table.columnCount()):
                item = self.table.item(row, col)
                if item: item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

        self._update_closing_stats(trades)

    def _run_ai_pattern_analysis(self):
        """[v1.8.9] 현재 매매 데이터를 바탕으로 Gemini AI 패턴 분석 실행"""
        self.btn_ai_analysis.setEnabled(False)
        self.btn_ai_analysis.setText("⏳ 분석 중...")
        
        try:
            # 최근 50건의 데이터 수집
            rows = []
            for row in range(min(50, self.table.rowCount())):
                data = {
                    'date': self.table.item(row, 1).text(),
                    'name': self.table.item(row, 4).text(),
                    'type': self.table.item(row, 3).text(),
                    'rt': self.table.item(row, 9).text(),
                    'pnl': self.table.item(row, 10).text(),
                    'strat': self.table.item(row, 12).text()
                }
                rows.append(data)
            
            if not rows:
                QMessageBox.warning(self, "데이터 부족", "분석할 매매 내역이 없습니다, 자기야! ❤️")
                return

            from gemini_bot import analyze_trade_patterns
            analysis_result = analyze_trade_patterns(rows)
            
            # 결과 표시 (HTML 다이얼로그)
            msg = QMessageBox(self)
            msg.setWindowTitle("🤖 KipoStock AI 패턴 코칭")
            msg.setTextFormat(Qt.TextFormat.RichText)
            msg.setText(f"<div style='min-width: 400px;'>{analysis_result.replace('\n', '<br>')}</div>")
            msg.setStandardButtons(QMessageBox.StandardButton.Ok)
            msg.exec()
            
        except Exception as e:
            QMessageBox.critical(self, "AI 분석 오류", f"앗, 분석 중에 문제가 생겼어: {e}")
        finally:
            self.btn_ai_analysis.setEnabled(True)
            self.btn_ai_analysis.setText("🤖 AI 패턴분석")

    # -------------------------------------------------------------------------
    # [v4.2.6] 전략 필터링 표준화: 내부 키와 표시명 통일
    # -------------------------------------------------------------------------
    def _get_strat_display_name(self, raw_strat):
        """내부 전략 키를 표준화된 한국어 표시명으로 변환"""
        if not raw_strat or raw_strat == 'none': return '기타'
        
        # 표준 매핑 테이블
        strat_map = {
            'BULTAGI': '불타기', '불타기': '불타기',
            'ACCEL': '가속매수', '가속': '가속매수', '가속매수': '가속매수',
            'CLOSING_BET': '종가베팅', '종가베팅': '종가베팅',
            'MORNING': '시초가', '시초가': '시초가',
            'VI해제': '변동성완화(VI)',
            'qty': '1주(정찰병)', '1주': '1주(정찰병)',
            'amount': '금액(정찰병)', '금액': '금액(정찰병)',
            'percent': '비율(정찰병)', '비율': '비율(정찰병)',
            'HTS': 'HTS'
        }
        return strat_map.get(raw_strat, raw_strat)

    def _update_strat_combo(self, trades):
        """전체 데이터에서 고유 전략명을 추출하여 표준화된 목록으로 갱신"""
        if not hasattr(self, 'combo_strat'): return
        
        current_text = self.combo_strat.currentText()
        self.combo_strat.blockSignals(True)
        self.combo_strat.clear()
        self.combo_strat.addItem("전체")
        
        display_strats = set()
        for t in trades:
            raw_s = t.get('strat_mode') or t.get('strat_nm') or 'none'
            display_strats.add(self._get_strat_display_name(raw_s))
            
        # 정렬하여 추가 (기타/HTS 등은 뒤로 보낼 수 있으나 우선 abc순)
        sorted_list = sorted(list(display_strats))
        if '기타' in sorted_list:
            sorted_list.remove('기타')
            sorted_list.append('기타')
            
        self.combo_strat.addItems(sorted_list)
        
        # 기존 선택 유지 시도
        idx = self.combo_strat.findText(current_text)
        if idx >= 0: self.combo_strat.setCurrentIndex(idx)
        else: self.combo_strat.setCurrentIndex(0)
        
        self.combo_strat.blockSignals(False)

    def _on_strat_filter_changed(self):
        """필터가 바뀌면 테이블과 통계를 즉시 리로드"""
        self._filter_and_display()

    def _filter_and_display(self):
        """현재 선택된 전략 필터(표준화된 이름)에 따라 데이터를 걸러서 표시"""
        if not hasattr(self, 'all_trades_cache'): return
        
        target_display_name = self.combo_strat.currentText()
        
        if target_display_name == "전체":
            filtered = self.all_trades_cache
        else:
            filtered = [
                t for t in self.all_trades_cache 
                if self._get_strat_display_name(t.get('strat_mode') or t.get('strat_nm') or 'none') == target_display_name
            ]
            
        self._display_trades(filtered)
        self._update_summary_stats(filtered, target_display_name)

    def _update_summary_stats(self, trades, strat_name="전체"):
        """전달된 데이터(필터링된 범위)의 성과를 분석하여 요약 라벨 업데이트"""
        if not trades:
            self.lbl_stats.setText(f"📊 <b>[{strat_name}]</b> 매매 내역이 없습니다.")
            return

        # SELL 내역만 추출하여 통계 계산
        sells = [t for t in trades if t.get('type') == 'SELL']
        
        total_count = len(sells)
        if total_count == 0:
            self.lbl_stats.setText(f"📊 <b>[{strat_name}]</b> 아직 완료된 매매 내역이 없습니다.")
            return

        wins = [t for t in sells if float(t.get('pnl_amt', 0)) > 0 or float(t.get('pnl', 0)) > 0]
        loss_count = total_count - len(wins)
        win_rate = (len(wins) / total_count) * 100
        total_pnl = sum(float(t.get('pnl_amt', 0)) or float(t.get('pnl', 0)) for t in sells)
        
        stat_text = (
            f"🎯 <b>[{strat_name}] 통계</b>  총 매매: <b>{total_count}건</b>  │  "
            f"승리: <font color='#ff4757'>{len(wins)}건</font>  │  "
            f"패배: <font color='#3742fa'>{loss_count}건</font>  │  "
            f"승률: <b>{win_rate:.1f}%</b>  │  "
            f"누적손익: <font color='{'#ff4757' if total_pnl >= 0 else '#3742fa'}'>{total_pnl:+,.0f}원</font>"
        )
        self.lbl_stats.setText(stat_text)

    def _update_closing_stats(self, trades):
        """(하위 호환 유지) 종가 베팅만 필터링해서 요약"""
        closing_sells = [t for t in trades if t.get('type') == 'SELL' and (t.get('strat_mode') == 'CLOSING_BET' or t.get('strat_nm') == '종가베팅')]
        self._update_summary_stats(closing_sells, "종가 베팅")

# ----------------- Shortcut Settings Dialog (V1.8.5) -----------------
class ShortcutSettingsDialog(QDialog):
    def __init__(self, current_shortcuts, parent=None):
        super().__init__(parent, Qt.WindowType.Window)
        self.parent_win = parent
        self.setWindowTitle("⌨️ 단축키 커스터마이징")
        self.setFixedWidth(400)
        self.shortcuts = current_shortcuts
        # 테마 적용
        is_light = (getattr(parent, 'ui_theme', 'dark') == 'light')
        self.bg_color = "#f8f9fa" if is_light else "#1a1a1a"
        self.fg_color = "#333333" if is_light else "#ecf0f1"
        self.setStyleSheet(f"background-color: {self.bg_color}; color: {self.fg_color};")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        title = QLabel("⌨️ 기능별 단축키 설정")
        title.setFont(QFont("Malgun Gothic", 14, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        
        container = QWidget()
        container.setStyleSheet(f"background-color: {self.bg_color};")
        self.form = QFormLayout(container)
        self.form.setSpacing(10)
        
        self.shortcut_edits = {}
        self.function_names = {
            "start": "▶ 자동매매 시작 (Start)",
            "stop": "■ 자동매매 중지 (Stop)",
            "bultagi_settings": "🔥 불타기 상세 설정",
            "history": "📋 매매 일지 보기",
            "clear_logs": "🧹 로그창 비우기",
            "ai_chat": "🎤 AI 비서 대화",
            "ai_settings": "⚙️ AI 음성 설정",
            "save_settings": "💾 현재 설정 저장",
            "theme_toggle": "💡 테마 전환 (🌞/🌙)",
            "always_on_top": "📍 항상 위에 (핀)",
            "advanced_toggle": "⚙️ 고급 설정 토글"
        }
        
        self.init_form()
        scroll.setWidget(container)
        layout.addWidget(scroll)

        # 하단 버튼
        btn_layout = QHBoxLayout()
        btn_reset = QPushButton("초기화")
        btn_reset.setFixedHeight(35)
        btn_reset.clicked.connect(self.reset_to_defaults)
        btn_reset.setStyleSheet("""
            QPushButton { background-color: #6c757d; color: white; border-radius: 6px; }
            QPushButton:hover { background-color: #5a6268; }
        """)
        
        btn_save = QPushButton("설정 저장 ✨")
        btn_save.setFixedHeight(35)
        btn_save.setFont(QFont("Malgun Gothic", 10, QFont.Weight.Bold))
        btn_save.clicked.connect(self.accept)
        btn_save.setStyleSheet("""
            QPushButton { background-color: #f1c40f; color: #2c3e50; border-radius: 6px; }
            QPushButton:hover { background-color: #f39c12; }
        """)
        
        btn_layout.addWidget(btn_reset)
        btn_layout.addWidget(btn_save)
        layout.addLayout(btn_layout)

    def init_form(self):
        for func_id, kor_name in self.function_names.items():
            key_seq = self.shortcuts.get(func_id, "")
            edit = QLineEdit(key_seq)
            edit.setFixedHeight(30)
            edit.setPlaceholderText("예: Ctrl+S")
            edit.setStyleSheet(f"""
                QLineEdit {{ 
                    background-color: {"#ffffff" if self.bg_color=="#f8f9fa" else "#333333"};
                    color: {self.fg_color};
                    border: 1px solid #555555;
                    border-radius: 4px; padding-left: 5px;
                }}
            """)
            self.form.addRow(f"{kor_name}:", edit)
            self.shortcut_edits[func_id] = edit

    def get_data(self):
        data = {}
        for func_id, edit in self.shortcut_edits.items():
            data[func_id] = edit.text().strip()
        return data

    def reset_to_defaults(self):
        defaults = {
            "start": "F5", "stop": "F6", "bultagi_settings": "Ctrl+B",
            "history": "Ctrl+H", "clear_logs": "Ctrl+L", "ai_chat": "Ctrl+A",
            "ai_settings": "Ctrl+I", "save_settings": "Ctrl+S",
            "theme_toggle": "Ctrl+T", "always_on_top": "Ctrl+P", "advanced_toggle": "Ctrl+G"
        }
        for func_id, edit in self.shortcut_edits.items():
            edit.setText(defaults.get(func_id, ""))

# [v6.0.4] 차트 로직 최적화 (매도 시에만 기록) 등을 위한 ProfitGraphWidget 등은 별도
# ---------------------------------------------------------------------------------------------------------
# ✅ 실시간 수익 그래프 위젯 (신규 v4.7)
# ---------------------------------------------------------------------------------------------------------
class ProfitGraphWidget(QWidget):
    def __init__(self, parent=None, width=5, height=2, dpi=100):
        # 폰트 깨짐 방지 
        plt.rcParams['font.family'] = 'Malgun Gothic'
        plt.rcParams['axes.unicode_minus'] = False
        
        self.fig = Figure(figsize=(width, height), dpi=dpi)
        self.axes = self.fig.add_subplot(111)
        super().__init__(parent) # Changed from FigureCanvas to QWidget
        self.canvas = FigureCanvas(self.fig) # Create a canvas instance
        
        # Layout for the QWidget to hold the canvas
        layout = QVBoxLayout(self)
        layout.addWidget(self.canvas)
        layout.setContentsMargins(0, 0, 0, 0) # Remove margins
        
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
        
        # 뷰 가독성을 위해 그리드 라인은 아주 연한 점선으로 처리
        self.axes.grid(True, color=grid_color, linestyle=':', alpha=0.3)
        self.line_color = '#00e5ff' if is_dark else '#007bff' # 쨍한 시안(Cyan) / 블루
        self.canvas.draw()

    def update_chart(self):
        """ChatCommand의 정밀 데이터를 가져와 실시간 차트 갱신"""
        # [v5.7.19] 장 마감(15:30) 후 업데이트 중단 (사용자 요청)
        now = datetime.datetime.now()
        if now.hour > 15 or (now.hour == 15 and now.minute >= 30):
            return

        try:
            # 1. 메인 윈도우의 worker와 chat_command를 통해 정밀 데이터 획득
            main_win = self.window() # [v5.1.4] self.parent() 대신 self.window() (최상위 위젯)
            if not hasattr(main_win, 'worker') or main_win.worker is None: return
            chat_cmd = main_win.worker.chat_command
            if chat_cmd is None: 
                # print("ℹ️ ChatCommand 준비 전")
                return

            raw_data = chat_cmd.get_pnl_timeline()
            
            self.axes.clear()
            # 테마 속성 재적용 (clear 시 초기화되므로)
            self.update_theme(getattr(main_win, 'ui_theme', 'dark'))

            if not raw_data:
                self.canvas.draw()
                return

            # [v6.0.4] 데이터 정렬 및 중복 제거 (시간 역행 방지)
            data_map = {}
            for item in raw_data:
                t_str = item.get('time', '09:00:00')
                # 혹시 모를 "전일" 등 특수 문자열 제거 (여기서는 순수 시공간만 필요)
                t_str = t_str.replace('[', '').replace(']', '').replace('전일 ', '').strip()
                if len(t_str) < 8 and ':' in t_str: # HH:MM 형식이면 :00 추가
                    if t_str.count(':') == 1: t_str += ":00"
                
                pnl = item.get('pnl', 0)
                data_map[t_str] = pnl # 동일 시간은 마지막 데이터로 덮어씀
            
            # [v2.2.6] 시간순 정렬 (문자열 정렬이 HH:MM:SS에서 유효함)
            sorted_times = sorted(data_map.keys())
            
            times = []
            pnls = []
            today_str = datetime.datetime.now().strftime("%Y%m%d")
            
            for t_str in sorted_times:
                try:
                    # HH:MM:SS가 아닌 경우를 대비해 유연한 파싱
                    if len(t_str) == 5: # HH:MM
                        ts = datetime.datetime.strptime(f"{today_str} {t_str}", "%Y%m%d %H:%M")
                    else:
                        ts = datetime.datetime.strptime(f"{today_str} {t_str[:8]}", "%Y%m%d %H:%M:%S")
                except: continue
                times.append(ts)
                pnls.append(data_map[t_str])
        
            if not times:
                self.canvas.draw()
                return

            # 선 및 마커 그리기 (리포트와 유사한 스타일) - [v5.1.5] 선 두께 및 도트 크기 조절
            self.axes.plot(times, pnls, color=self.line_color, linewidth=1.5, marker='o', markersize=2, linestyle='-')
            
            # 제로 라인 (빨간 점선)
            self.axes.axhline(y=0, color='#ff4757', linestyle='--', linewidth=1, alpha=0.8)
            
            # [v5.1.5] 마지막 데이터 기점 황색 가로선 및 현재 손익 텍스트 표시
            if pnls:
                last_pnl = pnls[-1]
                # 황색 가로선 그리기
                self.axes.axhline(y=last_pnl, color='#f1c40f', linestyle='-', linewidth=1, alpha=0.8)
                
                # [v5.1.5] 좌측에 현재 손익 금액 텍스트 표시 (y축 변환 활용하여 x=0.01 위치 고정)
                # 손익에 따라 색상 동적 변경 (수익: 빨간색, 손실: 파란색, 보합: 황색)
                if last_pnl > 0:
                    text_color = '#ff4757'  # Red for profit
                elif last_pnl < 0:
                    text_color = '#00e5ff'  # [V5.3.7] Bright Cyan for loss (기존 #3742fa 대비 시인성 강화)
                else:
                    text_color = '#f1c40f'  # Yellow for zero
                    
                trans = self.axes.get_yaxis_transform()
                # 글꼴 크기를 살짝 키워 가독성 확보, 약간의 그림자 같은 weight 효과
                self.axes.text(0.01, last_pnl, f' {int(last_pnl):,}', color=text_color, fontsize=10, 
                               ha='left', va='bottom', transform=trans, weight='bold')
            
            # X축 시간 포맷 설정 (mdates) - 리포트 일치화
            import matplotlib.dates as mdates
            self.axes.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
            
            # Y축 금액 포맷 설정 (천 단위 콤마) - [v5.1.1] 명시적 ticker 사용
            self.axes.yaxis.set_major_formatter(FuncFormatter(lambda x, loc: "{:,}".format(int(x))))
            
            # 여백 및 제목 설정
            self.axes.set_title("실시간 수익 현황 (P&L Trend)", fontsize=10, fontweight='bold', pad=10)
            self.fig.autofmt_xdate(rotation=0)
            self.canvas.draw()
        except Exception as e:
            print(f"⚠️ 그래프 업데이트 오류: {e}")
            self.canvas.draw()

        # [v3.3.7] 위젯이 너무 작을 때 발생하는 Tight Layout 경고 억제
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            try: self.fig.tight_layout()
            except: pass
        self.canvas.draw()

    def resizeEvent(self, event):
        """[신규 v3.3.6] 위젯 크기 변경 시 차트 레이아웃 강제 보정 (찌그러짐 방지)"""
        super().resizeEvent(event)
        # [v3.3.7] 경고 억제 추가
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            try:
                self.fig.tight_layout()
                self.canvas.draw()
            except: pass

# ---------------------------------------------------------------------------------------------------------
# ✅ 실시간 잔고 현황 테이블 위젯 (신규 v6.1.12)
# ---------------------------------------------------------------------------------------------------------
class PortfolioTableWidget(QTableWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setColumnCount(8)
        self.setHorizontalHeaderLabels(["매수 전략", "종목명", "매입 경과시간", "매입가", "현재가", "보유량", "평가손익", "수익률"])
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(24) # [신규] 행 높이 축소 (기본값보다 슬림하게)
        self.horizontalHeader().setFixedHeight(28) # [신규] 헤더 높이 축소
        self.setAlternatingRowColors(True)
        self.setStyleSheet("""
            QTableWidget {
                background-color: #1a1a1a;
                gridline-color: #333;
                color: #bbb;
                border: 1px solid #444;
                border-radius: 8px;
                font-family: 'Malgun Gothic';
                font-size: 11px;
            }
            QTableWidget::item { padding: 1px 4px; } /* [수정] 위아래 패딩 축소 */
            QHeaderView::section {
                background-color: #2c3e50;
                color: #f1c40f;
                padding: 2px; /* [수정] 헤더 패딩 축소 */
                border: 1px solid #34495e;
                font-weight: bold;
                font-size: 12px;
            }
            QTableWidget::item:selected { background-color: #34495e; color: white; }
        """)
        
        # [신규 v4.2.5] 종목명 더블클릭 시 뉴스 보이기 연동
        self.itemDoubleClicked.connect(self.on_item_double_clicked)

    def on_item_double_clicked(self, item):
        """[신규 v4.2.5] 종목명(1번 컬럼) 더블클릭 시 뉴스 검색 스나이퍼 실행"""
        if item.column() == 1: # 종목명
            stk_nm = item.text()
            # mainForm을 찾아 뉴스 검색 서비스 호출
            main_window = self.window() # QMainWindow (KipoMainForm)
            if hasattr(main_window, 'search_news_for_stock'):
                main_window.search_news_for_stock(stk_nm)

    def update_data(self, holdings, mapping=None):
        if not holdings:
            self.setRowCount(0)
            return

        # 데이터 업데이트 시 정렬 상태 등 유지할 필요 있으면 고도화 가능하나 우선 단순 갱신
        self.setRowCount(len(holdings))
        now = datetime.datetime.now()
        
        for row, (code, data) in enumerate(holdings.items()):
            # 0. 매수 전략 (v1.3.1 개선)
            strat_nm = "--"
            clean_code = code.replace('A', '') # 'A' 접두사 제거 (맵핑 일치화)
            
            if mapping and clean_code in mapping:
                m_info = mapping[clean_code]
                s_key = m_info.get('strat', 'none')
                
                # [v5.0.8] 전략 명칭 정밀 세분화 (랭크 vs 불타기 vs VI 등)
                strat_map = {
                    'qty': '1주', 'amount': '금액', 'percent': '비율', 
                    'HTS': 'HTS', 'BULTAGI': '불타기', 'MORNING': '시초가', 'ACCEL': '가속',
                    'CLOSING_BET': '종가', 'SYSTEM_VI': 'VI'
                }
                strat_nm = strat_map.get(s_key)
                
                # [v5.0.8] 불타기 진입 전 상태(정찰병)일 경우 명칭을 '랭크'로 변경
                if s_key == 'BULTAGI' and not m_info.get('bultagi_done', False):
                    strat_nm = "랭크"
                
                # [v1.3.1] 전략 키가 없으면 조건식 명칭(name)을 표시하도록 폴백
                if not strat_nm:
                    strat_nm = m_info.get('name', '--')
            
            item_strat = QTableWidgetItem(strat_nm)
            item_strat.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            
            # [v5.0.8] 색상 체계 고도화 (자기 요청!)
            strat_colors = {
                '1주': '#ff4444', '금액': '#00c851', '비율': '#33b5e5', 
                'HTS': '#8a2be2', '불타기': '#f39c12', '시초가': '#e67e22', '가속': '#e91e63',
                '종가': '#f1c40f', '랭크': '#00e5ff', 'VI': '#00e5ff'
            }
            if strat_nm in strat_colors:
                item_strat.setForeground(QColor(strat_colors[strat_nm]))
                if strat_nm in ['종가', '랭크', '불타기']:
                    font = item_strat.font()
                    font.setBold(True) # 중요 전략은 볼드 처리
                    item_strat.setFont(font)
            self.setItem(row, 0, item_strat)

            # 1. 종목명
            name = data.get('name', code)
            item_name = QTableWidgetItem(name)
            item_name.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.setItem(row, 1, item_name)
            
            # 2. 매입 경과시간 (v1.3.1)
            elapsed_str = "-"
            if mapping and clean_code in mapping:
                t_str = mapping[clean_code].get('time')
                if t_str:
                    try:
                        buy_t = datetime.datetime.strptime(f"{now.strftime('%Y%m%d')} {t_str}", "%Y%m%d %H:%M:%S")
                        diff = (now - buy_t).total_seconds()
                        if diff < 0: diff = (now + datetime.timedelta(days=1) - buy_t).total_seconds()
                        
                        hrs = int(diff // 3600)
                        mns = int((diff % 3600) // 60)
                        scs = int(diff % 60)
                        
                        if hrs > 0: elapsed_str = f"{hrs}시간 {mns}분"
                        else: elapsed_str = f"{mns}분 {scs}초"
                    except: pass
            
            item_time = QTableWidgetItem(elapsed_str)
            item_time.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.setItem(row, 2, item_time)

            # 3. 매입가
            buy_price = int(float(data.get('buy_price', 0)))
            item_buy = QTableWidgetItem(f"{buy_price:,}")
            item_buy.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.setItem(row, 3, item_buy)

            # 4. 현재가
            cur_price = int(float(data.get('cur_price', 0)))
            item_now = QTableWidgetItem(f"{cur_price:,}")
            item_now.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.setItem(row, 4, item_now)

            # 5. 보유량
            qty = int(float(data.get('qty', 0)))
            item_qty = QTableWidgetItem(f"{qty:,}주")
            item_qty.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.setItem(row, 5, item_qty)

            # 6. 평가손익
            pnl = int(float(data.get('pnl', 0)))
            pnl_color = "#ff4444" if pnl > 0 else ("#33b5e5" if pnl < 0 else "#bbb")
            item_pnl = QTableWidgetItem(f"{pnl:+,}")
            item_pnl.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            item_pnl.setForeground(QColor(pnl_color))
            self.setItem(row, 6, item_pnl)

            # 7. 수익률
            pl_rt = float(data.get('pl_rt', 0))
            rt_color = "#ff4444" if pl_rt > 0 else ("#33b5e5" if pl_rt < 0 else "#bbb")
            item_rt = QTableWidgetItem(f"{pl_rt:+.2f}%")
            item_rt.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            item_rt.setForeground(QColor(rt_color))
            self.setItem(row, 7, item_rt)

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

# ---------------------------------------------------------------------------------------------------------
# ✅ v5.0.1 AI 뉴스 전용 팝업 창 (News Sniper Viewer)
# ---------------------------------------------------------------------------------------------------------
class NewsViewerDialog(QDialog):
    def __init__(self, parent=None, html_content="", stk_nm="", voice_text=""):
        super().__init__(parent, Qt.WindowType.Window)
        title = f"📰 AI 뉴스 스나이퍼 브리핑 ({stk_nm})" if stk_nm else "📰 AI 뉴스 스나이퍼 브리핑"
        self.setWindowTitle(title)
        self.resize(600, 520) # [수정] 버튼 공간 확보를 위해 높이 약간 상향
        self.parent_win = parent
        self.voice_text = voice_text
        self.is_speaking = True # 기본적으로 음성이 실행 중인 것으로 간주
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)

        # [v3.0.4] 상단 레이아웃 제거 (스피커 버튼 하단 이동)
        
        self.browser = QTextBrowser()
        # 텔레그램 HTML 포맷을 스타일링과 함께 렌더링
        self.browser.setHtml(html_content)
        self.browser.setOpenExternalLinks(True)
        
        # 테마에 따른 스타일 적용
        ui_theme = getattr(parent, 'ui_theme', 'dark')
        is_light = (ui_theme == 'light')
        bg = "#ffffff" if is_light else "#000000"
        fg = "#212529" if is_light else "#00ff00"
        border = "#ced4da" if is_light else "#333333"
        
        self.browser.setStyleSheet(f"""
            QTextBrowser {{
                background-color: {bg};
                color: {fg};
                border: 2px solid {border};
                border-radius: 12px;
                padding: 15px;
                font-family: 'Malgun Gothic', 'Consolas';
                font-size: 14px;
                line-height: 150%;
            }}
        """)
        
        layout.addWidget(self.browser)
        
        # [v3.0.4] 하단 제어 바 (스피커 버튼 + 확인 버튼)
        bottom_layout = QHBoxLayout()
        bottom_layout.setSpacing(10)
        
        # 스피커(음성) 버튼
        self.btn_voice = QToolButton()
        self.btn_voice.setText("🔊")
        self.btn_voice.setCheckable(True)
        self.btn_voice.setChecked(True)
        self.btn_voice.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_voice.setToolTip("음성 읽기 ON/OFF")
        self.btn_voice.clicked.connect(self.toggle_voice)
        self.btn_voice.setFixedSize(40, 40) # 확인 버튼과 높이 맞춤
        
        btn_voice_style = """
            QToolButton {
                font-size: 20px;
                background-color: #2c3e50;
                color: white;
                border: none;
                border-radius: 8px;
            }
            QToolButton:hover {
                background-color: #34495e;
            }
            QToolButton:checked {
                background-color: #2980b9;
            }
        """
        self.btn_voice.setStyleSheet(btn_voice_style)
        bottom_layout.addWidget(self.btn_voice)
        
        # 확인 버튼
        btn_close = QPushButton("확인 (닫기)")
        btn_close.setFixedHeight(40)
        btn_close.clicked.connect(self.close)
        btn_close.setStyleSheet(f"""
            QPushButton {{
                background-color: {"#3498db" if is_light else "#2c3e50"};
                color: white;
                border: none;
                border-radius: 8px;
                font-weight: bold;
                font-size: 13px;
            }}
            QPushButton:hover {{
                background-color: {"#2980b9" if is_light else "#34495e"};
            }}
        """)
        bottom_layout.addWidget(btn_close)
        
        layout.addLayout(bottom_layout)

    def toggle_voice(self):
        """[신규 v6.5.0] 스피커 버튼 클릭 시 음성 재생/중단 토글"""
        is_on = self.btn_voice.isChecked()
        self.btn_voice.setText("🔊" if is_on else "🔈")
        try:
            from voice_utils import stop_all_voice
            stop_all_voice() # 일단 멈춤
            
            if is_on and self.voice_text:
                if hasattr(self.parent_win, 'speak_text'):
                    # 현재 텍스트로 다시 낭독
                    self.parent_win.speak_text(self.voice_text)
        except Exception as e:
            print(f"⚠️ 음성 토글 오류: {e}")

    def closeEvent(self, event):
        """[v5.7.31] 창이 닫힐 때 재생 중인 AI 음성도 함께 정지합니다."""
        try:
            from voice_utils import stop_all_voice
            stop_all_voice()
        except:
            pass
        super().closeEvent(event)

class AiVoiceSettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("⚙️ AI 음성 및 환경 설정")
        self.setFixedSize(350, 300) # [수정] 높이 상향
        self.parent_win = parent
        
        # 밝은/어두운 테마 대비를 위한 배경색 처리
        is_light = (getattr(parent, 'ui_theme', 'dark') == 'light')
        bg_color = "#f8f9fa" if is_light else "#2c3e50"
        fg_color = "#333333" if is_light else "#ecf0f1"
        self.setStyleSheet(f"background-color: {bg_color}; color: {fg_color};")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        title = QLabel("🎙️ AI 비서 음성 설정")
        title.setFont(QFont("Malgun Gothic", 14, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        form = QFormLayout()
        form.setSpacing(10)
        
        # 1. 음성 선택
        self.combo_voice = QComboBox()
        self.voices = {
            "선희 (밝고 명랑한 여성)": "ko-KR-SunHiNeural",
            "인준 (차분하고 신뢰감 있는 남성)": "ko-KR-InJoonNeural",
            "현수 (부드럽고 친절한 남성)": "ko-KR-HyunsuMultilingualNeural"
        }
        for name in self.voices.keys():
            self.combo_voice.addItem(name)
            
        self.combo_voice.setFixedHeight(30)
        form.addRow("AI 목소리:", self.combo_voice)
        
        # 2. 말하기 속도
        self.spin_speed = QSpinBox()
        self.spin_speed.setRange(0, 100)
        self.spin_speed.setSuffix(" %")
        self.spin_speed.setSingleStep(5)
        self.spin_speed.setFixedHeight(30)
        form.addRow("속도 증가 (+%):", self.spin_speed)
        
        # 3. 볼륨 조절 (Slider + SpinBox 연동)
        self.slider_vol = WedgeSlider(Qt.Orientation.Horizontal)
        self.slider_vol.setRange(0, 100)
        
        self.spin_vol = QSpinBox()
        self.spin_vol.setRange(0, 100)
        self.spin_vol.setSuffix(" %")
        self.spin_vol.setFixedWidth(60)
        
        # 슬라이더와 스핀박스 상호 연동
        self.slider_vol.valueChanged.connect(self.spin_vol.setValue)
        self.spin_vol.valueChanged.connect(self.slider_vol.setValue)
        
        h_vol = QHBoxLayout()
        h_vol.addWidget(self.slider_vol)
        h_vol.addWidget(self.spin_vol)
        form.addRow("음성 볼륨:", h_vol)
        
        layout.addLayout(form)
        
        layout.addStretch()

        # 저장 버튼
        btn_save = QPushButton("설정 저장 ✨")
        btn_save.setFixedHeight(40)
        btn_save.setFont(QFont("Malgun Gothic", 11, QFont.Weight.Bold))
        btn_save.clicked.connect(self.save_settings)
        btn_save.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_save.setStyleSheet("""
            QPushButton { 
                background-color: #f1c40f; color: #2c3e50; 
                border-radius: 8px; border: none;
            }
            QPushButton:hover { background-color: #f39c12; }
        """)
        layout.addWidget(btn_save)
        
        self.load_settings()

    def load_settings(self):
        from get_setting import get_setting
        voice = get_setting('ai_voice_name', 'ko-KR-SunHiNeural')
        speed = get_setting('ai_voice_speed', 20)
        
        for idx, (name, v_id) in enumerate(self.voices.items()):
            if v_id == voice:
                self.combo_voice.setCurrentIndex(idx)
                break
        self.spin_speed.setValue(speed)
        
        vol = get_setting('ai_voice_volume', 100)
        self.slider_vol.setValue(vol)

    def save_settings(self):
        voice_name = self.voices[self.combo_voice.currentText()]
        speed_val = self.spin_speed.value()
        
        try:
            with open(self.parent_win.settings_file, 'r', encoding='utf-8') as f:
                root = json.load(f)
        except:
            root = {}
            
        root['ai_voice_name'] = voice_name
        root['ai_voice_speed'] = speed_val
        root['ai_voice_volume'] = self.slider_vol.value()
        
        with open(self.parent_win.settings_file, 'w', encoding='utf-8') as f:
            json.dump(root, f, ensure_ascii=False, indent=2)
            
        QMessageBox.information(self, "저장 완료", "AI 비서의 새로운 목소리가 저장되었습니다! ❤️")
        self.close()

# ----------------- Main Window -----------------
class KipoWindow(QMainWindow):
    async def wait_for_ready(self):
        """Worker가 준비(chat_command 객체 생성)될 때까지 대기"""
        while not (self.worker and self.worker.chat_command):
            await asyncio.sleep(0.1)

    # -------------------------------------------------------------------------
    # ⌨️ [Gate 3] 단축키 시스템 로직 (V1.8.8)
    # -------------------------------------------------------------------------
    def setup_shortcuts(self):
        """단축키 데이터 로드 및 적용 (초기화용)"""
        self.load_shortcuts()
        self.apply_shortcuts()

    def load_shortcuts(self):
        """shortcuts.json 파일에서 단축키 로드"""
        try:
            if os.path.exists(self.shortcuts_file):
                with open(self.shortcuts_file, 'r', encoding='utf-8') as f:
                    self.shortcuts = json.load(f)
            else:
                self.shortcuts = {}
        except:
            self.shortcuts = {}

        # 기본값 설정
        defaults = {
            "start": "F5", "stop": "F6", "bultagi_settings": "Ctrl+B",
            "history": "Ctrl+H", "clear_logs": "Ctrl+L", "ai_chat": "Ctrl+A",
            "ai_settings": "Ctrl+I", "save_settings": "Ctrl+S",
            "theme_toggle": "Ctrl+T", "always_on_top": "Ctrl+P",
            "advanced_toggle": "Ctrl+G"
        }
        for key, val in defaults.items():
            if key not in self.shortcuts:
                self.shortcuts[key] = val
        
    def apply_shortcuts(self):
        """기존 단축키 제거 후 로드된 정보로 QShortcut 생성 및 연결"""
        for qs in self.shortcut_objects:
            qs.setEnabled(False)
            qs.deleteLater()
        self.shortcut_objects = []
        
        # 동작 매핑 (MainWindow의 메서드들 연결)
        actions = {
            "start": self.on_start_clicked,
            "stop": self.on_stop_clicked,
            "bultagi_settings": self.open_bultagi_dialog,
            "history": self.open_history_dialog,
            "clear_logs": self.clear_logs,
            "ai_chat": self.focus_chat_input,
            "ai_settings": self.open_ai_settings,
            "save_settings": self.save_all_settings,
            "theme_toggle": self.toggle_theme,
            "always_on_top": lambda: self.toggle_always_on_top(not self.btn_top.isChecked()),
            "advanced_toggle": self.toggle_advanced_settings
        }
        
        for key, seq in self.shortcuts.items():
            if not seq or key not in actions: continue
            try:
                qs = QShortcut(QKeySequence(seq), self)
                qs.activated.connect(actions[key])
                self.shortcut_objects.append(qs)
            except Exception as e:
                print(f"⚠️ 단축키 적용 오류 ({key}): {e}")

    def open_shortcut_settings(self):
        """단축키 설정 다이얼로그 열기"""
        dialog = ShortcutSettingsDialog(self.shortcuts, self)
        if dialog.exec():
            self.shortcuts = dialog.get_data()
            try:
                with open(self.shortcuts_file, 'w', encoding='utf-8') as f:
                    json.dump(self.shortcuts, f, indent=4, ensure_ascii=False)
                self.apply_shortcuts()
                self.append_log("✅ 단축키 설정이 저장되고 적용되었습니다.")
            except Exception as e:
                self.append_log(f"❌ 단축키 저장 오류: {e}")

    def focus_chat_input(self):
        """AI 채팅 입력창으로 포커스 이동"""
        if hasattr(self, 'chat_input'):
            self.chat_input.setFocus()

    def open_ai_settings(self):
        """AI 설정 창 열기 (현재는 로그 출력으로 대체)"""
        self.append_log("⚙️ AI 음성 및 기타 상세 설정 기능은 준비 중입니다.")

    def save_all_settings(self):
        """모든 설정을 강제로 저장"""
        if hasattr(self, 'btn_save'):
            self.btn_save.click()
        else:
            if hasattr(self, 'save_settings'):
                self.save_settings()

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
        self.version = "V5.3.9" # [V5.3.9] 불타기 상한선 감시루프 연동(Safety Guard Fix) 및 설정 캐시 즉시 반영 구현 🛡️포
        self.setWindowTitle(f"KipoStock AI Dashboard [{self.version}] - Advanced Fortress")
        self.is_closing = False # [신규] 프로그램 종료 중임을 나타내는 플래그
        self.is_initialized = False # [Fix v4.3.0] 초기 설정 로드 완료 전 자동 저장 차단 플래그 🚀
        # [최우선] 로그 및 상태 변수 초기화 (UI/Worker 호출 전 반드시 선행되어야 함)
        self.last_log_message = None
        self.log_buffer = [] 
        # [NEW v6.5.1] 대량 로그 유입 시 UI 프리징 방지용 버퍼 시스템
        self.log_queue = {"main": [], "bultagi": []}
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
        self.last_buy_stock_name = "대기" # [신규] 최근 매수 종목명
        self.last_buy_color = "#2ecc71" # [신규] 최근 매수 전략별 색상
        self.vi_alarm_cache = {} # [v1.9.5] VI 해제 알람 중복 방지용 캐시

        # [v2.2.0] Ranking Scout 엔진 인스턴스 생성
        import check_n_buy # [v2.2.7] 엔진과의 무전기 연결용 임포트
        self.check_n_buy = check_n_buy # [v2.2.7] 엔진에서 접근 가능하도록 할당
        self.rank_engine = RankingBetEngine(self) 
        self.rank_engine.load_parameters() # [신규 v2.2.0] 초기 설정 로드
        
        # [신규 V5.0.0] AI 오토파일럿 모의 트레이딩 엔진 연결
        from ai_autopilot_engine import AiAutopilotEngine
        self.ai_autopilot_engine = AiAutopilotEngine(self)
        self.ai_autopilot_engine.start() # 프로그램 시작과 동시에 백그라운드 타이머 작동
        
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
        
        self.seq_blink_timer = QTimer(self) # [Fix] 누락된 타이머 초기화 추가
        self.seq_blink_timer.setInterval(1000)
        self.seq_blink_timer.timeout.connect(self.blink_seq_button)
        
        # [NEW v1.6.6] 불타기 진단(Diagnosis) 감시용 워치독 타이머
        # 진단 로그가 수신되는 동안 레이저 점멸이 멈추지 않고 계속 유지되도록 관리합니다.
        self.bultagi_watchdog_timer = QTimer(self)
        self.bultagi_watchdog_timer.setSingleShot(True)
        self.bultagi_watchdog_timer.setInterval(7000) # 7초 (진단 주기 5초 + 여유 2초)
        self.bultagi_watchdog_timer.timeout.connect(self.stop_laser_blinking)

        # [NEW v6.1.12] 실시간 잔고 현황 테이블 갱신 타이머 (1초 주기 - v6.2.6 단축)
        self.portfolio_timer = QTimer(self)
        self.portfolio_timer.setInterval(1000)
        self.portfolio_timer.timeout.connect(self.update_portfolio_table)
        self.portfolio_timer.start()

        self.bultagi_dialog = None # [신규] 모달리스 인스턴스 유지 변수
        self.advanced_visible = False # [Fix v6.2.5] AttributeError: 'KipoWindow' object has no attribute 'advanced_visible' 긴급 복구
        self.disabled_auto_stocks = set() # [V4.3.4] 개별 종목 자동매매 일시 정지 목록
        self.load_disabled_stocks()      # [v5.1.25] 정지 목록 파일에서 복원 💾
        
        # [v2.5.1] 성능 최적화 및 음성 토글 기능 통합 빌드
        self.is_closing = False # [v3.0.1] 종료 플래그 초기화

        # [NEW v6.5.1] 로그 버퍼링 타이머 가동 (0.25초 주기로 뭉쳐서 출력)
        self.log_timer = QTimer(self)
        self.log_timer.setInterval(250)
        self.log_timer.timeout.connect(self.process_log_queue)
        self.log_timer.start()

        
        # [v6.5.4] Heartbeat 타이머 (앱 생존 확인용)
        self.heartbeat_timer = QTimer(self)
        self.heartbeat_timer.setInterval(10000) # 10초
        self.heartbeat_timer.timeout.connect(self._update_heartbeat)
        self.heartbeat_timer.start()
        
        # 파일 경로 설정 (V2.4.6 get_base_path 통합)
        self.script_dir = get_base_path()
        if getattr(sys, 'frozen', False):
            self.resource_dir = sys._MEIPASS
        else:
            self.resource_dir = self.script_dir
            
        self.shortcuts_file = os.path.join(self.script_dir, 'shortcuts.json')
        self.shortcut_objects = []
        self.setup_shortcuts()

        icon_path = os.path.join(self.resource_dir, "kipo_yellow.png")
        self.setWindowIcon(QIcon(icon_path))
            
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
        # [Fix v6.6.0] 불타기 상시 활성화 강제 (사용자 요청)
        try:
            settings = load_json_safe(self.settings_file)
            if settings.get('bultagi_enabled') is not True:
                settings['bultagi_enabled'] = True
                with open(self.settings_file, 'w', encoding='utf-8') as f:
                    json.dump(settings, f, ensure_ascii=False, indent=2)
                self.append_log("🚀 불타기(Fire-up) 모드 항시 가동 프로토콜 가동! (기본값 ON 강제)")
            
            # [v6.3.0] UI 초기화 후 체크박스 강제 동기화 (설정값이 True라도 UI가 꺼져있을 수 있음)
            # [v1.3.0] 부팅 시 즉시 로그 출력 및 스타일 동기화
            def _startup_bultagi_sync():
                if hasattr(self, 'bultagi_group'):
                    self.bultagi_group.setChecked(True)
                    self.update_bultagi_group_style(True)
                    self.update_bultagi_status_label(True)
                    self.append_log("🔥 <b>[불타기]</b> 시스템 초기 활성화 상태: <font color='#f1c40f'>ON</font>")
                # [V2.4.7 Fix] UI 동기화 후 실제 엔진(worker)에도 bultagi_enabled 상태를 전달
                # [v3.0.6] 멤버 변수도 동기화
                self.is_bultagi_enabled = True
                if hasattr(self, 'worker') and self.worker:
                    self.worker.schedule_command('update_settings', {'bultagi_enabled': True}, True)
                    self.append_log("🔥 <b>[불타기]</b> 엔진 초기 활성화 신호 전송 완료 ✅")
                    
            QTimer.singleShot(1500, _startup_bultagi_sync)
        except: pass

        # [V1.6.2] 레드 레이저 효과용 변수 초기화
        self.laser_lines = []
        self.laser_timer = QTimer(self)
        self.laser_timer.setInterval(150)
        self.laser_timer.timeout.connect(self.toggle_laser_effect)
        self.laser_count = 0

        self.setup_ui()
        self.setup_worker()
        
        # UI 구성 후 레이저 대상 라인(HLine) 수집
        self.collect_laser_lines(self)
        
        # 타이머 구동
        self.alarm_timer.start()

        # [수정] 프로그램 로딩 후 'M' 버튼 클릭 효과 및 그래프 초기 로드
        def _initial_refresh():
            self.on_profile_clicked("M")
            if hasattr(self, 'profit_graph'):
                self.profit_graph.update_chart()
        
        QTimer.singleShot(1500, _initial_refresh)
        
        # [신규 v3.3.6] 소켓 연결 안정화 대기 후 최종 데이터 동기화 (자기 요청: 15초 지연)
        QTimer.singleShot(15000, self._perform_initial_sync)

    def _perform_initial_sync(self):
        """[신규 v3.3.6] 시작 15초 후 잔고 및 불타기 상태 최종 동기화 (소켓 연결 안정화 대응)"""
        if getattr(self, 'is_closing', False): return
        
        try:
            self.append_log("🔄 <b>[동기화]</b> 소켓 연결 안정화 확인. 최종 데이터 동기화를 시작합니다.")
            
            # 1. 잔고 데이터 강제 업데이트 요청 (today sync_only)
            if hasattr(self, 'worker') and self.worker:
                self.worker.schedule_command('today', {'sync_only': True}, True)
            
            # 2. 불타기 활성화 상태 재전송 (확실한 활성화 보장)
            if getattr(self, 'is_bultagi_enabled', False):
                if hasattr(self, 'worker') and self.worker:
                    self.worker.schedule_command('update_settings', {'bultagi_enabled': True}, True)
                    self.append_log("🔥 <b>[불타기]</b> 엔진 활성화 신호 재전송 완료 ✅")
                    
            self.append_log("✅ <b>[동기화]</b> 모든 초기 데이터가 성공적으로 반영되었습니다. 성투하세요! ❤️")
        except Exception as e:
            print(f"⚠️ _perform_initial_sync 오류: {e}")

    def _update_heartbeat(self):
        """10초마다 살아있음을 파일에 기록"""
        try:
            h_path = os.path.join(self.data_dir, "heartbeat.txt")
            with open(h_path, "w", encoding="utf-8") as f:
                f.write(f"ALIVE: {datetime.datetime.now()}\n")
                f.flush()
        except: pass
        


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
        try:
            # 다이얼로그 객체 생성 (없다면)
            if self.bultagi_dialog is None:
                self.bultagi_dialog = BultagiSettingsDialog(self)
            
            # 객체 유효성 확인 및 로드 (RuntimeError: wrapped C/C++ object... 방지)
            try:
                self.bultagi_dialog.load_settings()
            except:
                self.bultagi_dialog = BultagiSettingsDialog(self)
                self.bultagi_dialog.load_settings()

            self.bultagi_dialog.show()
            self.bultagi_dialog.raise_()
            self.bultagi_dialog.activateWindow()
        except Exception as e:
            self.append_log(f"❌ 상세 설정창 열기 실패: {e}")
            print(f"❌ open_bultagi_dialog error: {e}")

    # [신규 v6.7.5] 전체 매매 일지 다이얼로그 호출
    def open_history_dialog(self):
        dlg = HistoryDialog(self)
        dlg.exec()

    def on_bultagi_toggled(self, checked):
        if hasattr(self, 'worker') and self.worker:
            self.worker.schedule_command('update_settings', {'bultagi_enabled': checked}, True)
        # [v6.8.5] [불타기] 태그 명시하여 전용 로그창으로 라우팅 보장
        self.append_log(f"[불타기] 감시 모드가 {'[활성화]' if checked else '[비활성화]'} 되었습니다.")
        # [v6.8.3] UI 체크 박스가 제거된 경우(isChecked() 미사용)에도 스타일만 안전하게 갱신
        if hasattr(self, 'bultagi_group'):
            try:
                self.bultagi_group.blockSignals(True)
                if self.bultagi_group.isCheckable():
                    self.bultagi_group.setChecked(checked)
                self.bultagi_group.blockSignals(False)
            except: pass
            self.update_bultagi_group_style(checked)

    # [신규] 더블 클릭 시 상태 반전 및 저장 처리
    def toggle_bultagi_enabled(self):
        try:
            try:
                with open(self.settings_file, 'r', encoding='utf-8') as f:
                    root = json.load(f)
            except Exception:
                root = {}
                
            target = root
            if hasattr(self, 'current_profile_idx') and self.current_profile_idx is not None and 'profiles' in root:
                if str(self.current_profile_idx) not in root['profiles']:
                    root['profiles'][str(self.current_profile_idx)] = {}
                target = root['profiles'][str(self.current_profile_idx)]
                
            # [Fix v6.5.9] target에 키가 없는 경우에도 기본값 True에서 반전 적용
            current_state = target.get('bultagi_enabled', self.is_bultagi_enabled)
            new_state = not current_state
            target['bultagi_enabled'] = new_state
            
            # [Fix v6.5.8/9] 루트 설정도 함께 동기화하여 엔진(chk_n_sell)이 즉시 알 수 있게 함
            root['bultagi_enabled'] = new_state
            self.is_bultagi_enabled = new_state # [v3.0.6] 멤버 변수 동기화
            
            with open(self.settings_file, 'w', encoding='utf-8') as f:
                json.dump(root, f, ensure_ascii=False, indent=2)
            
            # [v6.8.8] 캐시 무효화 후 UI 전면 동기화
            from get_setting import clear_settings_cache
            clear_settings_cache()                
            self.on_bultagi_toggled(new_state)
            self.update_bultagi_status_label(new_state) # [v6.8.7] 토글 시 새 상태를 직접 전달하여 캐시 지연 방지
        except Exception as e:
            print(f"⚠️ toggle_bultagi_enabled error: {e}")
            self.append_log(f"⚠️ 불타기 상태 전환 중 오류 발생: {e}")

    def update_bultagi_group_style(self, checked):
        # [신규] 켜졌을 때만 테두리 붉게, 꺼지면 일반 그룹박스 스타일로 원복
        is_light = getattr(self, 'ui_theme', 'dark') == 'light'
        border_color = "#f1c40f" if checked else ("#dcdcdc" if is_light else "#555555")
        text_color = "#f1c40f" if checked else ("#333333" if is_light else "#888888")
        
        self.bultagi_group.setStyleSheet(f"""
            QGroupBox::title {{
                subcontrol-origin: border;
                subcontrol-position: top center;
                padding: 2px 12px;
                color: {text_color};
                background-color: {("#ffffff" if is_light else "#1a1a1a")};
                border: 1px solid {border_color};
                border-radius: 6px;
                font-weight: bold;
                top: -12px;
            }}
            QGroupBox {{
                border: 2px solid {border_color};
                margin-top: 20px;
                border-radius: 12px;
                padding-top: 5px;
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
                margin-top: 25px; 
                padding-top: 15px; 
                background-color: #ffffff; 
            }
            QGroupBox::title {
                color: #495057;
                background-color: #ffffff;
                border: 1px solid #ced4da;
                border-radius: 6px;
                padding: 2px 8px;
                subcontrol-origin: margin;
                subcontrol-position: top center;
                left: 0px;
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
                margin-top: 18px; 
                padding-top: 8px; 
            }
            QGroupBox#settings_group::title { 
                font-size: 15px; 
                font-weight: bold; 
                color: #dc3545; 
                background-color: #ffffff; 
                border: 1px solid #dc3545; 
                border-radius: 6px; 
                subcontrol-origin: border; 
                subcontrol-position: top center; 
                left: 0px; 
                top: -14px; 
                padding: 2px 12px; 
            }
            
            QGroupBox#strategy_group { background-color: #ffffff; border: 2px solid #27ae60; border-radius: 12px; margin-top: 16px; padding-top: 8px; }
            QGroupBox#strategy_group::title { color: #27ae60; background-color: #ffffff; border: 1px solid #27ae60; border-radius: 6px; subcontrol-origin: border; subcontrol-position: top center; left: 0px; top: -12px; padding: 2px 12px; font-weight: bold; }
            
            QGroupBox#profile_group { background-color: #f8f9fa; border: 2px solid #2980b9; border-radius: 12px; margin-top: 16px; padding-top: 8px; }
            QGroupBox#profile_group::title { color: #3498db; font-size: 13px; font-weight: bold; background-color: #f8f9fa; border: 1px solid #3498db; border-radius: 6px; subcontrol-origin: border; subcontrol-position: top center; left: 0px; top: -12px; padding: 2px 12px; }
            
            QGroupBox#rt_group { background-color: #f8f9fa; border: 2px solid #e67e22; border-radius: 12px; margin-top: 16px; padding-top: 8px; }
            QGroupBox#rt_group::title { color: #e67e22; font-size: 13px; font-weight: bold; background-color: #f8f9fa; border: 1px solid #e67e22; border-radius: 6px; subcontrol-origin: border; subcontrol-position: top center; left: 0px; top: -12px; padding: 2px 12px; }

            QGroupBox#bultagi_group { background-color: #ffffff; border: 2px solid #f1c40f; border-radius: 12px; margin-top: 16px; padding-top: 8px; }
            QGroupBox#bultagi_group::title { color: #f1c40f; background-color: #ffffff; border: 1px solid #f1c40f; border-radius: 6px; subcontrol-origin: border; subcontrol-position: top center; left: 0px; top: -12px; padding: 2px 12px; font-weight: bold; }

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
            QGroupBox { font-weight: bold; border: 2px solid #3d3d3d; border-radius: 12px; margin-top: 25px; padding-top: 15px; background-color: #1e1e1e; }
            QGroupBox::title { color: #f1c40f; background-color: #1e1e1e; border: 1px solid #f1c40f; border-radius: 6px; padding: 2px 8px; subcontrol-origin: margin; subcontrol-position: top center; left: 0px; top: 0px; }
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
            
            QGroupBox#settings_group { background-color: #1a1a1a; border: 2px solid #dc3545; border-radius: 12px; margin-top: 18px; padding-top: 8px; }
            QGroupBox#settings_group::title { 
                font-size: 15px; 
                font-weight: bold; 
                color: #dc3545; 
                background-color: #1a1a1a; 
                border: 1px solid #dc3545; 
                border-radius: 6px; 
                subcontrol-origin: border; 
                subcontrol-position: top center; 
                top: -14px; 
                left: 0px; 
                padding: 2px 12px; 
            }
            
            QGroupBox#strategy_group { background-color: #1a1a1a; border: 2px solid #27ae60; border-radius: 12px; margin-top: 16px; padding-top: 8px; font-weight: bold; }
            QGroupBox#strategy_group::title { color: #2ecc71; background-color: #1a1a1a; border: 1px solid #2ecc71; border-radius: 6px; subcontrol-origin: border; subcontrol-position: top center; top: -12px; left: 0px; padding: 2px 12px; }
            
            QGroupBox#profile_group { background-color: #1a1a1a; border: 2px solid #2980b9; border-radius: 12px; margin-top: 16px; padding-top: 8px; }
            QGroupBox#profile_group::title { color: #3498db; font-size: 13px; font-weight: bold; background-color: #1a1a1a; border: 1px solid #3498db; border-radius: 6px; subcontrol-origin: border; subcontrol-position: top center; top: -12px; left: 0px; padding: 2px 12px; }
            
            QGroupBox#rt_group { background-color: #1a1a1a; border: 2px solid #e67e22; border-radius: 12px; margin-top: 16px; padding-top: 8px; font-weight: bold; }
            QGroupBox#rt_group::title { color: #e67e22; font-size: 13px; font-weight: bold; background-color: #1a1a1a; border: 1px solid #e67e22; border-radius: 6px; subcontrol-origin: border; subcontrol-position: top center; top: -12px; left: 0px; padding: 2px 12px; }

            QGroupBox#bultagi_group { background-color: #1a1a1a; border: 2px solid #f1c40f; border-radius: 12px; margin-top: 16px; padding-top: 8px; }
            QGroupBox#bultagi_group::title { color: #f1c40f; background-color: #1a1a1a; border: 1px solid #f1c40f; border-radius: 6px; subcontrol-origin: border; subcontrol-position: top center; left: 0px; top: -12px; padding: 2px 12px; font-weight: bold; }

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
        status_text = self.lbl_status.text() if hasattr(self, 'lbl_status') else ""
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

    def update_bultagi_status_label(self, checked=None):
        """[v6.8.7] 불타기 ON/OFF 상태를 즉시 반영 (인자가 있으면 해당 값 사용, 없으면 설정 로드)"""
        try:
            if not hasattr(self, 'lbl_log'): return
            
            if checked is not None:
                is_on = checked
            else:
                # [v6.8.3] 위젯의 isChecked() 대신 실제 설정값을 우선 참조 (캐시 1초 지연 가능성 있음)
                from get_setting import get_setting
                is_on = get_setting('bultagi_enabled', True)
                
            status_text = "ON" if is_on else "OFF"
            self.lbl_log.setText(f"📊 Analysis & Logs (불타기: {status_text})")
            self.lbl_log.setStyleSheet(f"color: {'#f1c40f' if is_on else '#7f8c8d'}; font-weight: bold;")
        except Exception as e:
            print(f"⚠️ update_bultagi_status_label error: {e}")


    from PyQt6.QtCore import pyqtSlot
    
    @pyqtSlot(str, object)
    def _capture_helper(self, save_path, event_dict):
        if hasattr(self, 'profit_graph'):
            try:
                # [v5.7.3] 캡처 직전 강제 렌더링(draw()) 제거 -> 데드락 및 프리징 유발 원인 해결
                pixmap = self.profit_graph.grab()
                pixmap.save(save_path, 'PNG')
                event_dict['success'] = True
            except Exception as e:
                print(f"⚠️ [캡처 오류] 실시간 차트 캡처 실패: {e}")
        event_dict['event'].set()

    def capture_profit_graph(self, save_path):
        """[v5.6.0] 메인 윈도우의 실시간 수익 위젯(profit_graph)을 캡처하여 파일로 저장합니다. (Thread-Safe)"""
        import threading
        from PyQt6.QtCore import QMetaObject, Qt, Q_ARG
        
        event_dict = {'success': False, 'event': threading.Event()}
        
        if threading.current_thread() is threading.main_thread():
            self._capture_helper(save_path, event_dict)
        else:
            QMetaObject.invokeMethod(self, "_capture_helper",
                                     Qt.ConnectionType.QueuedConnection,
                                     Q_ARG(str, save_path),
                                     Q_ARG(object, event_dict))
            event_dict['event'].wait(timeout=5.0)
            
        return event_dict['success']

    def apply_theme(self):
        """현재 ui_theme 변수에 맞춰 QMainWindow 및 기본 색상을 적용합니다."""
        css = self.get_theme_stylesheet(self.ui_theme)
        self.setStyleSheet(css)

    # [V5.7.1] Progressive Disclosure: 고급 설정 영역 토글
    def toggle_advanced_settings(self):
        self.advanced_visible = not self.advanced_visible
        
        # 1. 고급 설정 위젯 (시간, 종목수 등)
        if hasattr(self, 'advanced_widget'):
            self.advanced_widget.setVisible(self.advanced_visible)
            
        # 2. 매수 전략 및 불타기 설정 그룹 연동 (자기의 요청사항 반영! ❤️)
        if hasattr(self, 'strategy_group'):
            self.strategy_group.setVisible(self.advanced_visible)
        if hasattr(self, 'bultagi_group'):
            self.bultagi_group.setVisible(self.advanced_visible)
            
        # 3. 버튼 텍스트 및 툴팁 업데이트
        if hasattr(self, 'btn_adv_toggle'):
            self.btn_adv_toggle.setText("🔼" if self.advanced_visible else "⚙️")
            self.btn_adv_toggle.setToolTip(self._style_tooltip("🔓 [고급 설정 닫기]" if self.advanced_visible else "🔒 [고급 설정 열기]\n시간 및 종목수 설정"))

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
        root_layout.setContentsMargins(8, 2, 8, 8) # [v6.9.0] 상단 여백 대폭 축소 (10 -> 2)
        root_layout.setSpacing(6) # [v6.9.0] 간격 조절 (10 -> 6)

        # === 0. Global Header (Nested Layout for V2.1) ===
        header_widget = QWidget()
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(0, 0, 0, 2) # [v6.9.0] 하단 여백 축소 (10 -> 2)
        
        # Left Spacer
        header_layout.addSpacing(40)
        header_layout.addStretch()
        
        # Center Vertical Container (Title / Info Bar)
        center_container = QWidget()
        center_vbox = QVBoxLayout(center_container)
        center_vbox.setContentsMargins(0, 0, 0, 0)
        center_vbox.setSpacing(2) # [v6.9.2] 타이틀 하단 간격 축소 (5 -> 2)
        
        self.lbl_main_title = QLabel("KipoStock AI")
        self.lbl_main_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_main_title.setFont(QFont("Arial Black", 24, QFont.Weight.Bold)) # [v6.9.2] 크기 축소 (28 -> 24)
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
        self.lbl_status.setFont(QFont("Arial", 18, QFont.Weight.Bold)) # [v6.9.2] 공간 확보를 위한 크기 축소 (22 -> 18)
        self.lbl_status.setStyleSheet("color: #6c757d;")
        
        # 현재 시간 (오른쪽) - 아이콘 없이 더 심플하고 고급스럽게
        clock_layout = QHBoxLayout()
        clock_layout.setSpacing(10)
        
        self.lbl_clock = QLabel(datetime.datetime.now().strftime("%H:%M:%S"))
        self.lbl_clock.setFont(QFont("Arial", 18, QFont.Weight.Bold, True)) # [v6.9.2] 크기 축소 (22 -> 18)
        self.lbl_clock.setStyleSheet("color: #007bff;")
        
        clock_layout.addWidget(self.lbl_clock)
        
        # [v4.4.0] 지수 표시 영역 (KOSPI / KOSDAQ)
        self.lbl_index = QLabel("⏳ 지수 로딩 중...")
        self.lbl_index.setFont(QFont("Arial", 11, QFont.Weight.Bold))
        self.lbl_index.setStyleSheet("color: #aaaaaa;")
        self.lbl_index.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        info_bar.addLayout(timer_box)
        info_bar.addWidget(self.lbl_status)
        info_bar.addWidget(self.lbl_index) # [v4.4.0] 중앙에 배치
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
        
        # [신규 v6.7.5] History Button (📋)
        self.btn_history = QPushButton("📋")
        self.btn_history.setFixedSize(40, 40)
        self.btn_history.setToolTip(self._style_tooltip("📜 [매매 일지]\n지금까지의 모든 매매 내역을 확인합니다."))
        self.btn_history.setStyleSheet("""
            QPushButton { 
                background-color: transparent; 
                font-size: 24px; 
                border: none; 
                padding: 0px; 
            }
            QPushButton:hover { 
                background-color: rgba(128, 128, 128, 0.2); 
                border-radius: 20px; 
            }
        """)
        self.btn_history.clicked.connect(self.open_history_dialog)
        header_layout.addWidget(self.btn_history)

        # Always on Top Button (Fixed to Right) - [V2.2.3] 순서 변경 (맨 뒤로)
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
        left_layout.setSpacing(2) # [v6.9.0] 그룹 간 간격 최소화 (기존 명시적 설정 없음 - 기본값 10 예상)
        
        # 1. Settings Group
        self.settings_group = QGroupBox("⚙️ Settings")
        self.settings_group.setObjectName("settings_group")
        
        settings_layout = QVBoxLayout()
        settings_layout.setContentsMargins(5, 0, 5, 2) # [v1.7.3] 내부 상단/하단 여백 최소화
        settings_layout.setSpacing(4) # [v6.9.2] 요소 간 간격 극한 축소 (10 -> 4)

        # Condition Select Header & Advanced Toggle Button
        cond_row_layout = QHBoxLayout()
        cond_label = QLabel("<b>조건식 선택 (0-9)</b>")
        cond_row_layout.addWidget(cond_label)
        
        cond_row_layout.addStretch()
        
        # [V5.7.25] 고급 설정 토글 버튼 (Segoe UI Symbol 혼용으로 호환성 극대화)
        self.btn_adv_toggle = QPushButton("\u2699") # Gear 아이콘 (⚙)
        self.btn_adv_toggle.setFixedSize(34, 34)
        self.btn_adv_toggle.setFont(QFont("Segoe UI Emoji", 14)) 
        self.btn_adv_toggle.setToolTip(self._style_tooltip("🔒 [고급 설정 열기]\n시간 및 종목수 설정"))
        self.btn_adv_toggle.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                border: 1px solid #777;
                border-radius: 6px;
                color: #f1c40f;
                padding: 0px;
            }
            QPushButton:hover {
                background-color: rgba(241, 196, 15, 0.3);
                border: 1px solid #f1c40f;
            }
        """)
        self.btn_adv_toggle.clicked.connect(self.toggle_advanced_settings)
        cond_row_layout.addWidget(self.btn_adv_toggle)
        
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

        # [V5.7.1] Advanced Settings Widget (Hidden by default)
        self.advanced_widget = QWidget()
        advanced_vbox = QVBoxLayout(self.advanced_widget)
        advanced_vbox.setContentsMargins(0, 5, 0, 0) # [v1.7.3] 하단 여백 제거하여 매수전략과 밀착
        advanced_vbox.setSpacing(4) # [v1.7.3] 간격 축소 (8 -> 4)
        
        # 1) Max Stocks Row
        max_stocks_row = QHBoxLayout()
        max_stocks_row.addWidget(QLabel("<b>🎯 최대 보유 종목수</b>"))
        max_stocks_row.addStretch()
        self.input_max = QLineEdit()
        self.input_max.setObjectName("input_max")
        self.input_max.setFixedWidth(50)
        self.input_max.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.input_max.setStyleSheet("font-weight: bold; color: #f1c40f;")
        max_stocks_row.addWidget(self.input_max)
        advanced_vbox.addLayout(max_stocks_row)

        # 2) Time Settings (Horizontal)
        time_row = QHBoxLayout()
        time_row.setSpacing(5)
        time_row.addWidget(QLabel("<b>🕒 시간</b>"))
        self.input_start_time = QLineEdit(); self.input_start_time.setFixedWidth(50); self.input_start_time.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.input_start_time.setStyleSheet("font-weight: bold; color: #f1c40f; background-color: #1a1a1a; border: 1px solid #555; border-radius: 4px;")
        time_row.addWidget(self.input_start_time)
        time_row.addWidget(QLabel("~"))
        self.input_end_time = QLineEdit(); self.input_end_time.setFixedWidth(50); self.input_end_time.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.input_end_time.setStyleSheet("font-weight: bold; color: #f1c40f; background-color: #1a1a1a; border: 1px solid #555; border-radius: 4px;")
        time_row.addWidget(self.input_end_time)
        
        self.btn_alarm_stop = QPushButton("🔔")
        self.btn_alarm_stop.setFixedSize(26, 26) # [v1.7.3] 종모양 사이즈 축소 (32 -> 26, 약 80%)
        self.btn_alarm_stop.setFont(QFont("Segoe UI Emoji", 11)) # [v1.7.3] 폰트 크기 조정 (14 -> 11)
        self.btn_alarm_stop.setStyleSheet("""
            QPushButton { 
                background-color: #f1c40f; 
                color: #1a1a1a; 
                border: 1px solid #d4ac0d; 
                border-radius: 4px; 
                padding: 0;
            }
            QPushButton:hover { background-color: #f39c12; }
            QPushButton:disabled { background-color: #333; color: #777; border: 1px solid #555; }
        """)
        self.btn_alarm_stop.clicked.connect(self.stop_laser_blinking) # [v1.7.3] 알람 중지 기능 복구
        time_row.addWidget(self.btn_alarm_stop)
        advanced_vbox.addLayout(time_row)
        self.advanced_widget.setVisible(False) 
        settings_layout.addWidget(self.advanced_widget)

        # 💎 Buying Strategy Group
        self.strategy_group = QGroupBox("💎 매수 전략 (Buying Strategy)")
        self.strategy_group.setObjectName("strategy_group")
        strat_vbox = QVBoxLayout()
        strat_vbox.setContentsMargins(5, 5, 5, 5); strat_vbox.setSpacing(4)

        def create_tpsl_inputs(color):
            tp = QLineEdit("12.0"); tp.setFixedWidth(45); tp.setAlignment(Qt.AlignmentFlag.AlignCenter)
            tp.setStyleSheet(f"border: 1px solid {color}; border-radius: 4px; font-weight: bold; color: #dc3545;")
            sl = QLineEdit("-1.2"); sl.setFixedWidth(45); sl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            sl.setStyleSheet(f"border: 1px solid {color}; border-radius: 4px; font-weight: bold; color: #007bff;")
            return tp, sl

        header_layout = QHBoxLayout()
        header_layout.addStretch()
        lbl_tp_hdr = QLabel("익절(%)"); lbl_sl_hdr = QLabel("손절(%)")
        lbl_tp_hdr.setFixedWidth(45); lbl_sl_hdr.setFixedWidth(45); lbl_tp_hdr.setAlignment(Qt.AlignmentFlag.AlignCenter); lbl_sl_hdr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_tp_hdr.setStyleSheet("color: #eee; font-size: 11px; font-weight: bold;"); lbl_sl_hdr.setStyleSheet("color: #eee; font-size: 11px; font-weight: bold;")
        header_layout.addWidget(lbl_tp_hdr); header_layout.addWidget(lbl_sl_hdr)
        strat_vbox.addLayout(header_layout)

        def add_strat_row(label, color, obj_name, val_w=50):
            vbox = QVBoxLayout(); vbox.setSpacing(2)
            lbl = QLabel(label); lbl.setStyleSheet(f"color: {color}; font-weight: bold; font-size: 13px;")
            row = QHBoxLayout()
            val = QLineEdit(); val.setObjectName(f"input_{obj_name}_val"); val.setFixedWidth(val_w)
            val.setAlignment(Qt.AlignmentFlag.AlignCenter)
            # [v6.6.6] 입력 필드 색상 복구 (고대비 강조)
            val.setStyleSheet(f"""
                QLineEdit {{ 
                    background-color: #1a1a1a; 
                    color: white; 
                    border: 1px solid {color}; 
                    border-radius: 4px; 
                    font-weight: bold; 
                    font-size: 14px;
                    padding: 1px;
                }}
            """)
            btn = QPushButton("시"); btn.setCheckable(True); btn.setFixedSize(26, 26)
            btn.clicked.connect(lambda: self.update_price_type_style(obj_name))
            tp, sl = create_tpsl_inputs(color)
            row.addWidget(val); row.addWidget(btn); row.addStretch(); row.addWidget(tp); row.addWidget(sl)
            vbox.addWidget(lbl); vbox.addLayout(row) # [v6.6.5] 레이블 상단 고정
            strat_vbox.addLayout(vbox)
            return val, btn, tp, sl

        # Qty, Amount, Percent
        self.input_qty_val, self.btn_qty_type, self.input_qty_tp, self.input_qty_sl = add_strat_row("🔴 1주 매수", "#dc3545", "qty")
        self.input_amt_val, self.btn_amt_type, self.input_amt_tp, self.input_amt_sl = add_strat_row("🟢 금액 매수", "#28a745", "amount", 90)
        self.input_amt_val.textEdited.connect(lambda: self.format_comma(self.input_amt_val))
        self.input_pct_val, self.btn_pct_type, self.input_pct_tp, self.input_pct_sl = add_strat_row("🔵 비율 매수", "#007bff", "percent")

        strat_vbox.addStretch(1)
        self.strategy_group.setLayout(strat_vbox)
        settings_layout.addWidget(self.strategy_group)
        settings_layout.addSpacing(2) # [v6.7.11] 박스 간 간격 극한 최적화 (5 -> 2)

        # 🔥 불타기(Fire-up) 설정 그룹
        self.bultagi_group = DoubleClickGroupBox("🔥 불타기(Fire-up) 설정")
        self.bultagi_group.setObjectName("bultagi_group")
        # [v6.7.9] 체크박스 제거 (스타일 충돌 방지 및 더블 클릭 위주 레이아웃)
        self.bultagi_group.doubleClicked.connect(self.toggle_bultagi_enabled)
        self.bultagi_group.doubleClicked.connect(self.update_bultagi_status_label)
        
        bultagi_layout = QVBoxLayout()
        bultagi_layout.setContentsMargins(10, 10, 10, 10) # [v1.7.5] 상단 여백 보정 (2 -> 10)하여 테두리 겹침 해결
        bultagi_layout.setSpacing(5)
        
        self.btn_bultagi_open = QPushButton("⚙️ 상세 설정 열기")
        self.btn_bultagi_open.setFixedHeight(34) # [v1.7.5] 버튼 높이 미세 조정 (32 -> 34)로 텍스트 가림 해결
        self.btn_bultagi_open.setFont(QFont("Arial", 10, QFont.Weight.Bold)) # [v1.7.4] 폰트 크기 조정 (11 -> 10)
        self.btn_bultagi_open.setStyleSheet("background-color: #dc3545; color: white; border: 2px solid #C82333; border-radius: 8px; padding: 0;")
        self.btn_bultagi_open.clicked.connect(self.open_bultagi_dialog)
        bultagi_layout.addWidget(self.btn_bultagi_open)
        
        self.bultagi_group.setLayout(bultagi_layout)
        settings_layout.addWidget(self.bultagi_group)
        settings_layout.addStretch(5) # [v6.6.5] 두 박스를 상단으로 강력 밀착

        # [v6.6.3] 좌측 박스 간 공백 최소화를 위해 stretch 제거 (여백 타이트하게 조정)
        self.settings_group.setLayout(settings_layout)
        self.settings_group.setContentsMargins(8, 5, 8, 8) # [v1.7.3] 상단 여백 축소 (12 -> 5)
        # [V5.7.26] 수직 크기를 내부 콘텐츠에 맞게 고정 (창 확대 시 늘어남 방지)
        self.settings_group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
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
        # [V5.7.26] 수직 크기 고정
        self.profile_group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
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
        # [v6.6.4] 실시간 조건식 영역이 남는 공간을 모두 차지하도록 stretch 1 부여 (확장성 극대화)
        left_layout.addWidget(self.rt_group, stretch=1)

        # [V5.7.26] 초기 상태는 숨김 (Progressive Disclosure)
        self.strategy_group.setVisible(False)
        self.bultagi_group.setVisible(False)
        self.advanced_visible = False

        # 액션 버튼 완전히 삭제되었음 (여백 처리도 삭제하여 타이트하게)
        body_layout.addWidget(left_panel)

        # === Right Panel: Logs & Graph (v4.7 분할형) ===
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        
        # 1. 상단 타이틀 및 명령창
        log_header = QHBoxLayout()
        self.lbl_log = QLabel("📊 Analysis & Logs") # [v6.6.2] 인스턴스 변수로 전환
        self.lbl_log.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        self.lbl_log.setStyleSheet("color: #f1c40f;")
        log_header.addWidget(self.lbl_log)

        # [v4.7.3] 최근 매수 후 경과 시간 타이머 레이블 (사용자 요청으로 제거 v2.4.8)
        self.lbl_last_buy_timer = QLabel("구매 대기")
        self.lbl_last_buy_timer.setVisible(False) 
        # log_header.addWidget(self.lbl_last_buy_timer)

        # [v1.9.7] 상세 로그 체크박스 추가
        self.chk_detailed_log = QCheckBox("상세 로그")
        self.chk_detailed_log.setStyleSheet("margin-left: 10px; color: #f1c40f; font-size: 11px; font-weight: bold;")
        self.chk_detailed_log.setToolTip(self._style_tooltip("✅ [상세 로그 보기]\n체크 시 기술 로그창(상세로그)을 표시합니다."))
        self.chk_detailed_log.setChecked(get_setting('detailed_log_visible', True))
        self.chk_detailed_log.stateChanged.connect(self.on_detailed_log_toggled)
        log_header.addWidget(self.chk_detailed_log)

        log_header.addStretch()

        # [V5.7.24] 음성 제어 통합 섹션 (🔊 + 🤖 AI + 명령어창) 순서 정밀 조정
        # 1. TTS 토글 버튼 (스피커)
        self.btn_tts_toggle = QPushButton("🔊")
        self.btn_tts_toggle.setCheckable(True)
        self.btn_tts_toggle.setChecked(True)
        self.btn_tts_toggle.setFixedSize(36, 36)
        self.btn_tts_toggle.setFont(QFont("Segoe UI Emoji", 16))
        self.btn_tts_toggle.setToolTip(self._style_tooltip("🔊 [음성 출력 켜기/끄기]\nAI의 목소리를 들을지 선택합니다."))
        self.btn_tts_toggle.toggled.connect(self.on_tts_toggled)
        self.btn_tts_toggle.setStyleSheet("""
            QPushButton { border-radius: 6px; background-color: transparent; border: none; padding: 0px; }
            QPushButton:checked { color: #28a745; }
            QPushButton:hover { background-color: rgba(128, 128, 128, 0.1); }
        """)
        
        # [v5.7.34] 우클릭 시 볼륨 조절 슬라이더 팝업 (UX 극대화)
        def show_vol_popup(pos):
            menu = QMenu(self)
            menu.setStyleSheet(f"""
                QMenu {{ background-color: {'#ffffff' if getattr(self, 'ui_theme', 'dark') == 'light' else '#2c3e50'}; border: 1px solid #7f8c8d; border-radius: 4px; }}
            """)
            
            slider = WedgeSlider(Qt.Orientation.Horizontal)
            slider.setRange(0, 100)
            slider.setFixedSize(150, 40) # 웨지형이라 조금 더 크게
            vol = get_setting('ai_voice_volume', 100)
            slider.setValue(vol)
            
            def update_vol(v):
                # 실시간 저장 및 반영
                try:
                    with open(self.settings_file, 'r', encoding='utf-8') as f:
                        root = json.load(f)
                    root['ai_voice_volume'] = v
                    with open(self.settings_file, 'w', encoding='utf-8') as f:
                        json.dump(root, f, ensure_ascii=False, indent=2)
                except: pass
                
            slider.valueChanged.connect(update_vol)
            
            action = QWidgetAction(menu)
            action.setDefaultWidget(slider)
            menu.addAction(action)
            menu.exec(self.btn_tts_toggle.mapToGlobal(pos))
            
        self.btn_tts_toggle.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.btn_tts_toggle.customContextMenuRequested.connect(show_vol_popup)
        
        log_header.addWidget(self.btn_tts_toggle)

        # 2. AI 대화 버튼 (v5.7.27 스피커 버튼과 동일한 36x36 크기 및 투명 스타일 적용)
        self.btn_ai = QPushButton("🎤")
        self.btn_ai.setFont(QFont("Segoe UI Emoji", 16))
        self.btn_ai.setFixedSize(36, 36) 
        self.btn_ai.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_ai.setToolTip(self._style_tooltip("🎤 [AI와 대화하기]\n클릭 후 말씀하시면 AI 비서(Gemini)와 대화할 수 있습니다."))
        self.btn_ai.clicked.connect(self.start_voice_recognition)
        self.btn_ai.setStyleSheet("""
            QPushButton { 
                background-color: transparent; border: none; color: #f39c12; 
                padding: 0px;
            }
            QPushButton:hover { background-color: rgba(128, 128, 128, 0.1); border-radius: 6px; }
            QPushButton:pressed { color: #d35400; }
        """)
        log_header.addWidget(self.btn_ai)

        # 2-1. [v5.7.31] AI 음성 설정 버튼 (⚙️)
        self.btn_ai_setting = QPushButton("⚙️")
        self.btn_ai_setting.setFont(QFont("Segoe UI Emoji", 14))
        self.btn_ai_setting.setFixedSize(36, 36)
        self.btn_ai_setting.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_ai_setting.setToolTip(self._style_tooltip("⚙️ [AI 음성 설정]\nAI 비서의 목소리 종류와 말하기 속도를 커스터마이징합니다."))
        self.btn_ai_setting.clicked.connect(self.open_ai_voice_settings)
        self.btn_ai_setting.setStyleSheet("""
            QPushButton { background-color: transparent; border: none; color: #7f8c8d; padding: 0px; }
            QPushButton:hover { background-color: rgba(128, 128, 128, 0.1); border-radius: 6px; color: #bdc3c7; }
        """)
        log_header.addWidget(self.btn_ai_setting)

        # [v1.9.9] 로그 간소화 체크박스 제거 (사용자 요청: 상세 로그와 통합 및 UI 정리)
        # self.chk_simple_log = QCheckBox("로그 간단히") 
        # ... 제거됨 ...

        # 3. 명령어 입력창 (너비 200으로 조정하여 전체 레이아웃 유지)
        self.input_cmd = QLineEdit()
        self.input_cmd.setObjectName("input_cmd")
        self.input_cmd.setPlaceholderText("명령어를 입력하세요...")
        self.input_cmd.setFixedWidth(200) 
        self.input_cmd.returnPressed.connect(self.send_custom_command)
        log_header.addWidget(self.input_cmd)
        
        right_layout.addLayout(log_header)
        
        # [v1.9.6] 우측 패널 5단계 위젯 레이아웃 구성
        self.log_splitter = QSplitter(Qt.Orientation.Vertical)
        
        # 1. 수익현황 차트
        self.profit_graph = ProfitGraphWidget(self)
        self.log_splitter.addWidget(self.profit_graph)
        
        # 2. 보유종목 테이블
        self.portfolio_table = PortfolioTableWidget()
        self.log_splitter.addWidget(self.portfolio_table)
        
        # 3. 불타기 현황 보드 (Diagnosis Board)
        self.bultagi_status_board = QTableWidget()
        self.bultagi_status_board.setColumnCount(10) # [V4.3.4] 9 -> 10 (일시정지 체크박스 추가)
        self.bultagi_status_board.setHorizontalHeaderLabels(["정지", "종목명", "진행", "거래대금", "1차(대기)", "2차(수익)", "3차(강도)", "4차(추세)", "5차(호가)", "매도조건"])
        self.bultagi_status_board.verticalHeader().setVisible(False)
        self.bultagi_status_board.verticalHeader().setDefaultSectionSize(24) # [V3.0.1] 보유 현황 테이블과 동일하게 24px 행 높이 설정
        self.bultagi_status_board.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.bultagi_status_board.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.bultagi_status_board.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        
        # [V5.0.0] AI 오토파일럿 설정 컨텍스트 메뉴 허용
        self.ai_autopilot_stocks = {} # 에이전틱 AI 오토파일럿 대상 종목 저장소 { "stk_cd": { "stk_nm": "...", "enabled": True } }
        self.bultagi_status_board.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.bultagi_status_board.customContextMenuRequested.connect(self.show_bultagi_context_menu)
        self.bultagi_status_board.setStyleSheet("""
            QTableWidget {
                background-color: #1a1a1a; color: #e0e0e0; gridline-color: #333; border: none;
                font-family: 'Malgun Gothic', 'Dotum'; font-size: 11px;
            }
            QHeaderView::section { background-color: #2c3e50; color: #ff6b6b; padding: 2px; border: 1px solid #333; font-weight: bold; }
            QCheckBox::indicator { width: 11px; height: 11px; }
        """)
        self.bultagi_status_board.setColumnWidth(0, 35) # [V4.3.4] 정지 컬럼 너비 슬림하게 조정
        self.bultagi_status_board.horizontalHeader().setStretchLastSection(True)
        self.bultagi_status_board.horizontalHeader().setFixedHeight(28) # [V3.0.1] 보유 현황 테이블과 동일한 헤더 높이(28px) 적용
        self.bultagi_status_board.setFixedHeight(146) # [V3.0.1] 5개 종목 표시에 맞게 최적화 (24px * 5 + 헤더 높이 + 여백)
        self.log_splitter.addWidget(self.bultagi_status_board)

        # 4. 상세 로그창 (Detailed)
        self.log_display = ZoomableTextEdit()
        self.log_display.setReadOnly(True)
        # [v3.0.1 Fix] 속성만 전달하여 applyZoomStyle 에서 셀렉터로 감싸도록 함
        self.log_display.setBaseStyle("background-color: #1a1a1a; color: #bbb; border: none; font-family: 'Consolas';")
        self.log_display.document().setMaximumBlockCount(2000)
        self.log_splitter.addWidget(self.log_display)
        self.log_display.setVisible(self.chk_detailed_log.isChecked() if hasattr(self, 'chk_detailed_log') else True)
        
        # 5. 간소화 로그창 (Simplified)
        self.bultagi_log_display = ZoomableTextEdit()
        self.bultagi_log_display.setReadOnly(True)
        # [v3.0.1 Fix] 속성만 전달하여 applyZoomStyle 에서 셀렉터로 감싸도록 함
        self.bultagi_log_display.setBaseStyle("background-color: #000000; color: #00ff00; font-family: 'Consolas', 'Courier New'; border: 2px solid #333; border-radius: 10px; padding: 10px;")
        self.bultagi_log_display.document().setMaximumBlockCount(1000)
        self.log_splitter.addWidget(self.bultagi_log_display)

        # 비율 및 초기 크기 조정
        self.log_splitter.setStretchFactor(0, 2) # 그래프
        self.log_splitter.setStretchFactor(1, 4) # 실시간 잔고
        self.log_splitter.setStretchFactor(2, 2) # 불타기 보드
        self.log_splitter.setStretchFactor(3, 4) # 상세 로그
        self.log_splitter.setStretchFactor(4, 5) # 간소화 로그
        self.log_splitter.setSizes([140, 180, 120, 200, 350])
        
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
        self.worker.signals.index_signal.connect(self.update_index_ui) # [v4.4.0] 지수 업데이트 연결
        self.worker.signals.clr_signal.connect(self.log_display.clear)
        self.worker.signals.request_log_signal.connect(self.save_logs_to_file)
        self.worker.signals.auto_seq_signal.connect(self.on_remote_auto_sequence)
        self.worker.signals.condition_loaded_signal.connect(self.refresh_condition_list_ui)
        self.worker.signals.graph_update_signal.connect(self.profit_graph.update_chart)
        self.worker.signals.news_signal.connect(self.show_news_viewer) # [신규 v5.0.1] 뉴스 팝업 연결
        self.worker.signals.ai_voice_signal.connect(self.speak_text) # [NEW V5.6.3] 제미나이 음성 출력 연동
        self.worker.signals.report_signal.connect(self.append_report) # [v5.7.16] REPORT 전용 HTML 안전 연동
        self.worker.signals.perspective_signal.connect(self.show_perspective_viewer) # [v6.1.17] KipoStock 관점 연동
        self.worker.signals.open_config_signal.connect(self.open_bultagi_dialog) # [v6.1.21] 설정창 연동
        self.worker.signals.open_ai_settings_signal.connect(self.open_ai_voice_settings) # [v6.1.21] AI 설정 연동
        self.worker.start()

    def search_news_for_stock(self, stk_nm):
        """[신규 v4.2.5] 종목명 기반 실시간 뉴스 검색 및 AI 분석 팝업 (비동기)"""
        if not stk_nm or stk_nm == "--": return
        self.append_log(f"🔍 <b>[{stk_nm}]</b> 최신 뉴스를 AI가 수집 중입니다... (약 10초 소요)")
        
        # 가비지 컬렉션 방지를 위해 인스턴스 참조 유지
        self._news_worker = NewsWorker(stk_nm)
        self._news_worker.finished.connect(self.show_news_viewer)
        self._news_worker.start()

    def show_perspective_viewer(self, perspective_list=None):
        """[수정 v6.4.8] KipoStock 관점 탐색 및 AI 추천 통합 다이얼로그 팝업"""
        self.append_log("🎯 [종가분석] 지정된 시간이 되어 종가 베팅 탐색 창을 엽니다.")
        dlg = KipoFilterListDialog(parent=self)
        dlg.exec()

    # ================== AI 음성 비서 기능 (V5.6.3) ==================
    def start_voice_recognition(self):
        if hasattr(self, 'stt_worker') and self.stt_worker.isRunning():
            self.append_log("⚠️ 음성 인식이 이미 진행 중입니다.")
            return
            
        self.btn_ai.setStyleSheet("QPushButton { border-radius: 6px; background-color: #dc3545; color: white; border: none; padding: 0px; }")
        
        from voice_utils import VoiceSTTWorker
        self.stt_worker = VoiceSTTWorker()
        self.stt_worker.status_signal.connect(lambda msg: self.input_cmd.setPlaceholderText(msg))
        self.stt_worker.finished_signal.connect(self.on_stt_finished)
        self.stt_worker.error_signal.connect(self.on_stt_error)
        self.stt_worker.start()

    def on_stt_finished(self, text):
        self.btn_ai.setStyleSheet("""
            QPushButton { 
                background-color: transparent;
                border: none;
                color: #f39c12; 
                padding: 0px;
            }
            QPushButton:hover { background-color: rgba(128, 128, 128, 0.1); border-radius: 6px; }
            QPushButton:pressed { color: #d35400; }
        """)
        self.input_cmd.setPlaceholderText("명령어를 입력하세요...")
        if text:
            # 텍스트 입력 후 자동 실행
            self.input_cmd.setText(text)
            self.send_custom_command()

    def on_stt_error(self, err_msg):
        self.btn_ai.setStyleSheet("""
            QPushButton { 
                background-color: transparent;
                border: none;
                color: #f39c12; 
                padding: 0px;
            }
            QPushButton:hover { background-color: rgba(128, 128, 128, 0.1); border-radius: 6px; }
            QPushButton:pressed { color: #d35400; }
        """)
        self.input_cmd.setPlaceholderText("명령어를 입력하세요...")
        self.append_log(f"🕒 <font color='#c0392b'>[음성 인식 오류] {err_msg}</font>")

    def on_tts_toggled(self, checked):
        if checked:
            self.btn_tts_toggle.setText("🔊")
        else:
            self.btn_tts_toggle.setText("🔇")

    # [v1.9.9] on_simple_log_toggled 메서드 제거됨

    def on_detailed_log_toggled(self, state):
        """[v1.9.6] 상세 로그 가시성 제어 및 설정 저장"""
        checked = (state == Qt.CheckState.Checked.value)
        try:
            if hasattr(self, 'log_display'):
                self.log_display.setVisible(checked)
                
            with open(self.settings_file, 'r', encoding='utf-8') as f:
                root = json.load(f)
            root['detailed_log_visible'] = checked
            with open(self.settings_file, 'w', encoding='utf-8') as f:
                json.dump(root, f, ensure_ascii=False, indent=2)
            
            status = "표시" if checked else "숨김"
            self.append_log(f"⚙️ [설정] 상세 로그창이 <b>{status}</b> 상태로 변경되었습니다.")
        except Exception as e:
            self.append_log(f"⚠️ [설정] 상세 로그 설정 저장 실패: {e}")

    def speak_text(self, text):
        # 토글이 켜져있을 때만 낭독
        if hasattr(self, 'btn_tts_toggle') and self.btn_tts_toggle.isChecked():
            from voice_utils import VoiceTTSWorker
            from get_setting import get_setting
            
            # [v5.7.31] 사용자 설정 로드
            voice_name = get_setting('ai_voice_name', 'ko-KR-SunHiNeural')
            speed = get_setting('ai_voice_speed', 20)
            vol_pct = get_setting('ai_voice_volume', 100)
            
            # volume 인자는 0.0 ~ 1.0 사이의 float 값을 기대함
            self.tts_worker = VoiceTTSWorker(text, voice_name=voice_name, rate=f"+{speed}%", volume=vol_pct/100.0)
            self.tts_worker.start()


    def open_ai_voice_settings(self):
        """[v5.7.31] AI 음성 설정 다이얼로그를 엽니다."""
        dialog = AiVoiceSettingsDialog(self)
        dialog.exec()
    # ==============================================================


    def animate_button_click(self, btn):
        """버튼 클릭 시 색상 반전 애니메이션 효과 (아이콘 찌그러짐 방지)"""
        original_style = btn.styleSheet()
        btn.setStyleSheet(original_style + "background-color: #555; color: white; border: 2px solid #fff;")
        QTimer.singleShot(150, lambda: btn.setStyleSheet(original_style))

    def on_start_clicked(self, force=False, manual=None):
        self.animate_button_click(self.btn_start)
        if manual is None:
            manual_override = True
        else:
            manual_override = manual

        if not force and not self.btn_start.isEnabled(): return
        self.btn_start.setEnabled(False)

        try:
            self.save_settings(restart_if_running=False) 
            target_profile = f"{self.current_profile_idx}번 프로필" if self.current_profile_idx else "기본 설정"
        except Exception as e:
            self.append_log(f"⚠️ 설정 동기화 실패: {e}")
            target_profile = None
            self.btn_start.setEnabled(True)
            
        QTimer.singleShot(500, lambda: self.worker.schedule_command('start', target_profile, manual_override))
        
        # [v3.3.7] 엔진 시작 15초 후 데이터 동기화 강제 수행 (소켓 안정화 대응)
        QTimer.singleShot(15000, self._perform_initial_sync)

    def on_stop_clicked(self):
        """STOP 버튼 클릭 핸들러 (메서드로 분리)"""
        self.animate_button_click(self.btn_stop)
        self.worker.schedule_command('stop')
        
        if self.btn_auto_seq.isChecked():
           self.btn_auto_seq.setChecked(False)
           self.on_auto_seq_toggled()
           
        QTimer.singleShot(500, lambda: self.lock_ui_for_sequence(self.btn_auto_seq.isChecked()))

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
        
        # [수정 v6.0.5] 다른 설정(익절/손절 등)과 엉키지 않도록 마킹 전용 저장 함수 호출
        self.save_marking_only()

        # [신규] 엔진에 마킹 상태 동기화 요청
        marked = [i for i, m in enumerate(self.marked_states) if m]
        self.worker.schedule_command('sync_marking', marked)

    def save_marking_only(self):
        """
        [신규 v6.0.5] UI의 다른 입력값(익절/손절 등)을 건드리지 않고
        오직 마킹 상태(marked_conditions)만 settings.json에 업데이트합니다.
        """
        try:
            if not os.path.exists(self.settings_file):
                return

            with open(self.settings_file, 'r', encoding='utf-8') as f:
                settings = json.load(f)

            marked_list = [i for i, m in enumerate(self.marked_states) if m]

            # 1. 루트 설정 업데이트
            settings['marked_conditions'] = marked_list

            # 2. 현재 활성화된 프로필이 있다면 해당 프로필 데이터도 업데이트
            if self.current_profile_idx is not None:
                if 'profiles' not in settings: settings['profiles'] = {}
                p_idx_str = str(self.current_profile_idx)
                if p_idx_str in settings['profiles']:
                    settings['profiles'][p_idx_str]['marked_conditions'] = marked_list

            # 3. 파일 저장
            with open(self.settings_file, 'w', encoding='utf-8') as f:
                json.dump(settings, f, ensure_ascii=False, indent=2)
            
            # self.append_log("📌 뉴스 마킹 상태가 독립적으로 저장되었습니다.") # 로그 노이즈 방지를 위해 생략 가능
        except Exception as e:
            self.append_log(f"⚠️ 마킹 상태 저장 실패: {e}")

    def _on_price_input_changed(self, line_edit):
        """[v2.4.8] 입력값에 자동으로 천단위 콤마(,)를 추가합니다."""
        text = line_edit.text().replace(',', '')
        if not text: return
        try:
            # 커서 위치 저장
            cursor_pos = line_edit.cursorPosition()
            old_len = len(line_edit.text())
            
            # 콤마 포맷팅
            formatted = f"{int(text):,}"
            line_edit.blockSignals(True)
            line_edit.setText(formatted)
            line_edit.blockSignals(False)
            
            # 커서 위치 보정
            new_len = len(formatted)
            new_pos = cursor_pos + (new_len - old_len)
            line_edit.setCursorPosition(max(0, new_pos))
        except:
            pass


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

    def show_news_viewer(self, html_msg):
        """[v5.0.1] AI 뉴스 분석 결과를 팝업창으로 띄웁니다."""
        if not html_msg: return
        
        html_msg = html_msg.strip() # [v5.1.4] 양쪽 공백 제거하여 방어력 상승
        
        # [신규 v5.1.3] 중복 팝업 패스 메시지 처리
        if html_msg.startswith("SKIP:"):
            # SKIP 메시지는 로그창에만 회색으로 작게 표시하여 사용자에게 정보 제공
            self.append_log(f"🕒 <font color='#aaaaaa'>{html_msg.replace('SKIP:', '').strip()}</font>")
            return

        try:
            # 줄바꿈 정규화 및 가독성 개선
            clean_html = html_msg.replace('\n', '<br>')
            # 뉴스 정보와 AI 분석 사이에 구분선 강조
            clean_html = clean_html.replace('💡 <b>Gemini 2.5 分析:</b>', '<br><hr style="border: 1px dashed #555;"><br>💡 <b>Gemini 2.5 分析:</b>')

            # [v6.2.7] 종목명 추출 (HTML 태그 제거 후 [ ... ] 패턴에서 파싱)
            import re as _re
            stk_nm = ""
            plain_msg = _re.sub(r'<[^>]+>', '', html_msg)
            m = _re.search(r'\[(.+?)\]', plain_msg)
            if m:
                stk_nm = m.group(1).strip()

            # [v6.5.0] 음성 읽기용 순수 텍스트 추출 (HTML 태그 제거)
            voice_text = _re.sub(r'<[^>]+>', '', clean_html)
            # 불필요한 공백 및 이모지 라인 정리
            voice_text = voice_text.replace('\n\n', '\n').strip()

            dialog = NewsViewerDialog(self, clean_html, stk_nm=stk_nm, voice_text=voice_text)
            # 모달리스로 띄워 매매 중에도 참고할 수 있도록 함
            dialog.show()
            dialog.raise_()
            dialog.activateWindow()
        except Exception as e:
            self.append_log(f"⚠️ 뉴스 뷰어 생성 실패: {e}")

    # -------------------------------------------------------------------------
    # 🤖 [AI V5.0.0] 에이전틱 오토파일럿 컨텍스트 메뉴
    # -------------------------------------------------------------------------
    def show_bultagi_context_menu(self, pos):
        item = self.bultagi_status_board.itemAt(pos)
        if not item: return
        row = item.row()
        stk_nm_item = self.bultagi_status_board.item(row, 1) # 종목명 (Index 1)
        if not stk_nm_item: return
        
        # UI에서 종목명 추출 (🤖 마크 제거)
        stk_nm_raw = stk_nm_item.text().replace("🤖 ", "").strip()
        if not stk_nm_raw: return
        
        # 종목 코드 찾기 (ACCOUNT_CACHE에서 확인)
        stk_cd = None
        from check_n_buy import ACCOUNT_CACHE
        for code, name in ACCOUNT_CACHE.get('names', {}).items():
            if name == stk_nm_raw:
                stk_cd = code
                break
                
        if not stk_cd:
            self.append_log(f"<font color='#ff9900'>⚠️ [AI] '{stk_nm_raw}' 현재 보유 종목이 아니므로 오토파일럿 마크를 부여할 수 없습니다.</font>")
            return

        menu = QMenu(self)
        menu.setStyleSheet("QMenu { background-color: #2c3e50; color: #fff; padding: 5px; font-family: 'Malgun Gothic'; } QMenu::item:selected { background-color: #1abc9c; color: #111; }")
        
        is_active = stk_cd in self.ai_autopilot_stocks
        action_text = "❌ AI 오토파일럿 해제" if is_active else "🤖 AI 오토파일럿 전담 마크 활성화 (모의)"
        action = QAction(action_text, self)
        
        def _toggle_ai():
            if is_active:
                del self.ai_autopilot_stocks[stk_cd]
                self.append_log(f"<font color='#ff9900'>📉 [AI 오토파일럿] '{stk_nm_raw}' 종목의 전담 마크가 해제되었습니다.</font>")
                try:
                    stk_nm_item.setText(stk_nm_raw)
                    stk_nm_item.setForeground(QColor("#e0e0e0"))
                except RuntimeError: pass
            else:
                self.ai_autopilot_stocks[stk_cd] = {"stk_nm": stk_nm_raw, "enabled": True}
                self.append_log(f"<font color='#1abc9c'>🚀 [AI 오토파일럿] '{stk_nm_raw}' 단독전담 AI 모드 활성화 완료! 60초마다 모의 진단을 시작합니다.</font>")
                try:
                    stk_nm_item.setText(f"🤖 {stk_nm_raw}")
                    stk_nm_item.setForeground(QColor("#00ff00")) # 녹색으로 하이라이트
                except RuntimeError: pass

        action.triggered.connect(_toggle_ai)
        menu.addAction(action)
        menu.exec(self.bultagi_status_board.mapToGlobal(pos))

    # -------------------------------------------------------------------------
    # 📋 [Gate 4] 불타기 현황 보드 관리 (V1.9.0)
    # -------------------------------------------------------------------------
    def update_bultagi_status_board(self, payload):
        """불타기 진행 상황을 테이블에 인플레이스로 업데이트합니다."""
        try:
            parts = payload.split('|')
            if len(parts) < 2: return
            stk_nm = parts[0]
            is_paused = stk_nm in self.disabled_auto_stocks
            
            row = -1
            # [V4.3.4] 종목명 컬럼이 1번(index)으로 이동
            for i in range(self.bultagi_status_board.rowCount()):
                item = self.bultagi_status_board.item(i, 1)
                if item and item.text().replace("🤖 ", "").strip() == stk_nm:
                    row = i
                    break
            
            # [V5.0.0] AI 오토파일럿 활성 확인 (종목명 기반)
            ai_stocks = getattr(self, 'ai_autopilot_stocks', {})
            is_ai_active = any(info.get('stk_nm') == stk_nm.strip() for info in ai_stocks.values())

            if row == -1:
                row = self.bultagi_status_board.rowCount()
                self.bultagi_status_board.insertRow(row)
                
                # [V4.3.4] col 0: 일시정지 체크박스
                chk_widget = QWidget()
                chk_layout = QHBoxLayout(chk_widget)
                chk_layout.setContentsMargins(2, 0, 0, 0)
                chk_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
                chk = QCheckBox()
                chk.setChecked(is_paused)
                chk.setToolTip(f"{stk_nm} 자동매매 일시 정지")
                chk.stateChanged.connect(lambda state, nm=stk_nm: self.on_auto_trade_toggle(state, nm))
                chk_layout.addWidget(chk)
                self.bultagi_status_board.setCellWidget(row, 0, chk_widget)
                
                # col 1: 종목명 (AI 활성 시 🤖 부착)
                display_name = f"🤖 {stk_nm}" if is_ai_active else stk_nm
                name_item = QTableWidgetItem(display_name)
                name_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if is_ai_active:
                    name_item.setForeground(QColor("#00ff00"))
                self.bultagi_status_board.setItem(row, 1, name_item)
            else:
                # 이미 존재하는 행이라도 AI 상태에 따라 강제 업데이트
                display_name = f"🤖 {stk_nm}" if is_ai_active else stk_nm
                name_item = self.bultagi_status_board.item(row, 1)
                if name_item:
                    name_item.setText(display_name)
                    name_item.setForeground(QColor("#00ff00") if is_ai_active else QColor("#e0e0e0"))
            
            # [V4.3.4] 데이터 컬럼은 2번부터 시작 (기존 1번->2번 시프트)
            for col, val in enumerate(parts[1:], 2):
                if col >= 10: break # [V4.3.4] 최대 10컬럼
                item = QTableWidgetItem(val)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                
                if col == 2: # 진행
                    if "완료" in val: item.setForeground(QColor("#2ecc71"))
                    elif "관문" in val: item.setForeground(QColor("#f1c40f"))
                    elif any(x in val for x in ["종가", "랭크", "시초가"]): # [v5.0.8] 주요 전략 종목 강조
                         if "종가" in val: item.setForeground(QColor("#f1c40f")) # 노란색 (종가)
                         elif "시초가" in val: item.setForeground(QColor("#00e5ff")) # 청록색 (시초가)
                         else: item.setForeground(QColor("#ff4757")) # 빨간색 (랭크)
                         
                         font = item.font()
                         font.setBold(True)
                         item.setFont(font)
                
                elif col == 3: # 거래대금 (하늘색)
                    item.setForeground(QColor("#00e5ff"))
                    if "위" in val:
                        font = item.font()
                        font.setBold(True)
                        item.setFont(font)

                elif col == 9: # 매도조건 (기존 8 -> 9)
                    is_entry_done = ("진입완료" in parts[1])
                    if "✅" in val or is_entry_done: 
                        item.setForeground(QColor("#2ecc71"))
                        font = item.font()
                        font.setBold(True)
                        item.setFont(font)
                elif "✅" in val: item.setForeground(QColor("#2ecc71"))
                elif any(x in val for x in ["🚫", "📉", "⚖️"]): item.setForeground(QColor("#e74c3c"))
                
                # 일시정지 상태면 행 전체 배경 어둡게
                if is_paused:
                    item.setBackground(QColor("#2a2a2a"))
                    item.setForeground(QColor("#888888"))
                
                self.bultagi_status_board.setItem(row, col, item)
        except Exception as e:
            print(f"⚠️ [update_bultagi_status_board] 에러: {e}")

    def on_auto_trade_toggle(self, state, stk_nm):
        """[V4.3.4] 불타기 보드 체크박스 클릭 시 자동매매 일시 정지/재개 처리"""
        try:
            is_paused = (state == 2)  # Qt.CheckState.Checked == 2
            if is_paused:
                self.disabled_auto_stocks.add(stk_nm)
                self.append_log(f"⏸ <b>[정지]</b> <font color='#f39c12'>{stk_nm}</font> 자동매매가 일시 정지되었습니다.")
            else:
                self.disabled_auto_stocks.discard(stk_nm)
                self.append_log(f"▶️ <b>[재개]</b> <font color='#2ecc71'>{stk_nm}</font> 자동매매가 재개되었습니다.")
        except Exception as e:
            print(f"⚠️ [on_auto_trade_toggle] 에러: {e}")
        
        # [v5.1.25] 정지 처리 후 파일에 즉시 저장
        self.save_disabled_stocks()

    def save_disabled_stocks(self):
        """[v5.1.25] 불타기 정지 종목 목록을 파일에 저장합니다."""
        try:
            file_path = os.path.join(self.data_dir, "disabled_stocks.json")
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(list(self.disabled_auto_stocks), f, ensure_ascii=False, indent=4)
            # print(f"💾 [Persistence] 정지 목록 저장 완료: {len(self.disabled_auto_stocks)}종목")
        except Exception as e:
            print(f"⚠️ [save_disabled_stocks] 에러: {e}")

    def load_disabled_stocks(self):
        """[v5.1.25] 파일에서 불타기 정지 종목 목록을 불러옵니다."""
        try:
            file_path = os.path.join(self.data_dir, "disabled_stocks.json")
            if os.path.exists(file_path):
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        self.disabled_auto_stocks = set(data)
                        self.append_log(f"📥 <b>[복원]</b> 기존 정지 종목 <font color='#f1c40f'>{len(self.disabled_auto_stocks)}개</font>를 불러왔습니다. ❤️")
        except Exception as e:
            print(f"⚠️ [load_disabled_stocks] 에러: {e}")

    def remove_from_bultagi_status_board(self, stk_nm):
        """특정 종목을 불타기 보드에서 제거합니다."""
        try:
            target_nm = stk_nm.strip()
            for i in range(self.bultagi_status_board.rowCount() - 1, -1, -1):
                item = self.bultagi_status_board.item(i, 1) # [V4.3.4] col 0->1로 이동
                if item:
                    current_nm = item.text().replace("🤖 ", "").strip()
                    if current_nm == target_nm or target_nm in current_nm:
                        self.bultagi_status_board.removeRow(i)
                        self.disabled_auto_stocks.discard(current_nm) # 정지 목록에서도 제거
                        
                        # [V5.0.0] 매도/리스트 제거 시 AI 오토파일럿 활성 상태 자동 해제
                        ai_stocks = getattr(self, 'ai_autopilot_stocks', {})
                        keys_to_del = [k for k, v in ai_stocks.items() if v.get('stk_nm') == current_nm]
                        for k in keys_to_del:
                            del self.ai_autopilot_stocks[k]
                            self.append_log(f"<font color='#ff9900'>📉 [AI 오토파일럿] 미보유 전환으로 '{current_nm}' 전담 마크 자동 해제</font>")
                            
                        # [v3.0.9] 동기화 가시성 확보를 위한 로그 추가
                        self.append_log(f"🧹 [동기화] 불타기 보드에서 종목 제거: {target_nm}")
        except Exception as e:
            print(f"⚠️ remove_from_bultagi_status_board 오류: {e}")

    def purge_bultagi_status_board(self, holdings):
        """[V3.0.9] 실시간 보유 종목 리스트와 대조하여, 보유하지 않은 종목은 불타기 보드에서 제거합니다."""
        try:
            # holdings는 {code: data, ...} 형태
            held_names = {h.get('name', '').strip() for h in holdings.values() if h.get('name')}
            
            # 테이블 역순 순회 (제거 시 인덱스 변화 방지)
            for i in range(self.bultagi_status_board.rowCount() - 1, -1, -1):
                item = self.bultagi_status_board.item(i, 1) # [V4.3.4] col 0->1로 이동
                if item:
                    current_stk_nm = item.text().replace("🤖 ", "").strip()
                    # 만약 보유 종목 리스트에 없다면 삭제 (주의: "종목명" 컬럼 기준)
                    if current_stk_nm and current_stk_nm not in held_names:
                        self.bultagi_status_board.removeRow(i)
                        
                        # [V5.0.0] 매도/무보유 판정 시 AI 오토파일럿 활성 상태 자동 해제
                        ai_stocks = getattr(self, 'ai_autopilot_stocks', {})
                        keys_to_del = [k for k, v in ai_stocks.items() if v.get('stk_nm') == current_stk_nm]
                        for k in keys_to_del:
                            del self.ai_autopilot_stocks[k]
                            self.append_log(f"<font color='#ff9900'>📉 [AI 오토파일럿] 동기화 제거로 '{current_stk_nm}' 전담 마크 자동 해제</font>")

                        # [v3.0.9] 동기화 가시성 확보를 위한 로그 추가
                        self.append_log(f"🧹 [동기화] 미보유 종목 제거: {current_stk_nm}")
        except Exception as e:
            print(f"⚠️ purge_bultagi_status_board 오류: {e}")

    def append_log(self, text):
        # [v3.0.1] 종료 중 접근 방지 가드 (RuntimeError 방지)
        if getattr(self, 'is_closing', False): return
        try:
            if not self.log_display: return
        except: return
        
        if not text: return
        
        # [v4.2.1] 로데이터 및 기술 로그 강제 라우팅 (분할 출력 대응 ✨)
        # 1. 태그 기반: [Rank Raw], [BULTAGI-DEBUG] 등이 포함된 경우
        # 2. 길이 기반: 메시지가 500자를 초과할 경우 (분할된 로데이터 조각들까지 상세 로그창으로 강제 격리)
        force_detailed_tags = ["[Rank Raw]", "[BULTAGI-DEBUG]", "[Ranking-DEBUG]", "[RANK_SCOUT]", "[VI-DEBUG]"]
        is_force_detailed = any(tag in text for tag in force_detailed_tags) or len(text) > 500
        
        if is_force_detailed:
            target_display = self.log_display
            timestamp = datetime.datetime.now().strftime("%H:%M:%S")
            text_html = text.replace('\n', '<br>')
            full_html = f"""
            <table border="0" cellpadding="0" cellspacing="0" style="margin-bottom: 2px;">
                <tr>
                    <td valign="top" style="color: #ccc; font-family: 'Courier New'; white-space: nowrap;">[{timestamp}]</td>
                    <td valign="top" style="padding-left: 5px; color: #00ff00; font-family: 'Consolas', 'Monospace';">
                        {text_html if '<font color' in text_html else f"<span>{text_html}</span>"}
                    </td>
                </tr>
            </table>
            """
            self.log_queue["main"].append(full_html)
            return

        # [v2.2.8] "이미 처리 중인 종목" 및 "시스템락" 차단 로그 필터링 (사용자 요청 ✨)
        if any(x in text for x in ["이미 처리 중인 종목", "차단", "스킵"]):
            # 단, 중요 알람(VI, 매수체결 등)은 제외
            if not any(important in text for important in ["[VI", "[매수", "[매도", "[HTS"]):
                return
        
        # [v5.7.16] DEBUG_HTML_LOG는 이제 report_signal로 직접 수신하므로 append_report로 위임
        if text.startswith("DEBUG_HTML_LOG:"):
            self.append_report(text[len("DEBUG_HTML_LOG:"):].strip())
            return
        
        # [v1.5.9/1.6.1] 로그 라우팅 (불타기 및 VI 전용 창으로 분리)
        # [v1.9.0] 실시간 상태 보드(Table) 인플레이스 업데이트 연동
        if text.startswith("[BULTAGI_STAT]"):
            self.update_bultagi_status_board(text[len("[BULTAGI_STAT]"):].strip())
            return
            
        if text.startswith("[BULTAGI_REMOVE]"):
            self.remove_from_bultagi_status_board(text[len("[BULTAGI_REMOVE]"):].strip())
            return

        # [v1.9.6] 로그 라우팅 최적화 (상세 로그 vs 간소화 로그)
        technical_keywords = [
            "[시스템락]", "[불타기차단]", "[불타기대기]", "[LASER]", "[진단]", "[발송]", "[오류]", "[디버그]",            "[VI감지]", "[VI발동]", "[VI해제임박]", "[Turbo VI 감지]", "[VI감지-1h]", "[VI-DEBUG]", 
            "💓 [RT-SEARCH]", "📡 [REG응답]", "[BULTAGI-DEBUG]", "RAW_DATA", "[필터]", "[스킵]",
            "[RANK_SCOUT]", "[Ranking Scout]", "[RankingData]", "[Rank Raw]", "[Ranking-DEBUG]", # [v3.3.3/v4.0.4] 상단 상세 로그창으로 보내기 위해 필터
            "[AI", # [V5.0.0] AI 분석 및 로깅 상단으로 격리
            "pygame", "Hello from the pygame", # [v3.3.3] 라이브러리 시작 로그 상단 이동
            "🧹", "[동기화]", # [v3.3.3] 동기화 로그 상단 이동
            "🕵️‍♂️" # [v3.3.4] 시간 경과 보정 로그 등 기술 메시지 상단 이동
        ]
        
        target_display = self.bultagi_log_display
        is_summary_report = "오늘 전체 매매 요약 리포트" in text
        is_technical = any(kw in text for kw in technical_keywords)
        
        if is_technical and not is_summary_report:
            target_display = self.log_display
            
        # [v1.6.6] 불타기 진단 로그 감지 시 워치독 리셋 및 점멸 보장
        if any(x in text for x in ["진단", "발송", "불타기-FullScan 진단"]):
            self.start_laser_blinking()
            if hasattr(self, 'bultagi_watchdog_timer'):
                self.bultagi_watchdog_timer.start()
        
        # [v4.7] 실시간 그래프 갱신 트리거 (매수/매도 완료 시)
        if ("완료" in text or "체결" in text) and hasattr(self, 'profit_graph'):
            self.profit_graph.update_chart()

        # [v1.6.2] 레드 레이저 시각 효과 트리거 (구분선 점멸)
        if "[LASER]" in text:
            self.start_laser_blinking()

        # [v1.5.4 / v2.3.2] 보유 종목 VI 실시간 발동 알람 (해제/중지 등 제외)
        if "[VI발동]" in text or ("[VI감지]" in text and "상태: 발동" in text):
            # [v1.5.7 / v2.2.7 / v2.3.0] 종목명 추출 정규식 고도화 (대괄호 제거 대응 ✨)
            # 패턴: ] 태그 뒤부터 ' 상태:' 글자 전까지의 텍스트 추출
            # [V4.2.9] HTML 태그 제거 후 순수 텍스트에서 종목명 추출 (정확도 향상)
            clean_text = re.sub(r'<.*?>', '', text)
            stk_match = re.search(r'\]\s*([^(\s]+)', clean_text) 
            stk_name = stk_match.group(1).strip() if stk_match else ""
            # 110초 대기 후 알람 실행
            if stk_name:
                QTimer.singleShot(110000, lambda: self.trigger_vi_release_alarm(stk_name))

        # [v4.7.3] 최근 매수 타이머 리셋 트리거 및 종목명 추출
        # [v6.6.6] 타이머 리셋 조건 강화: '불타기' 단독 매칭 대신 명확한 매수 로그 패턴 사용
        # [v1.0.8] 리포트(@today) 출력 시 간섭 방지: '|' 기호가 포함된 줄은 필터링
        actual_buy_keywords = ["매수체결", "추가매수", "HTS매수", "HTS매매", "HTS외부감지", "직접매매", "불타기진입", "RankScout", "Ranking Scout"]
        if any(kw in text for kw in actual_buy_keywords) and "|" not in text:
            self.last_buy_time = datetime.datetime.now()
            if hasattr(self, 'lbl_last_buy_timer'):
                # 종목명 추출 (예: [매수체결] 삼성전자 (7,350원...))
                stock_match = re.search(r'\]\s*(.*?)\s*\(', text)
                if stock_match:
                    raw_name = stock_match.group(1).strip()
                    self.last_buy_stock_name = re.sub(r'<.*?>', '', raw_name)
                elif "불타기" in text:
                    self.last_buy_stock_name = "불타기"
                else:
                    self.last_buy_stock_name = "매수"
                
                # [v5.1.1] 전략별 컬러 추출 및 적용
                color_match = re.search(r"color=['\"](.*?)['\"]", text)
                if color_match:
                    raw_color = color_match.group(1).lower()
                    # 사용자 요청 컬러로 매핑 보정
                    if "#ffc107" in raw_color or "orange" in raw_color: self.last_buy_color = "#ff9800" # 주황
                    elif "#f1c40f" in raw_color or "yellow" in raw_color: self.last_buy_color = "#f1c40f" # 노랑 (불타기 등)
                    elif "#007bff" in raw_color or "blue" in raw_color: self.last_buy_color = "#007bff" # 파랑
                    elif "#28a745" in raw_color or "green" in raw_color: self.last_buy_color = "#28a745" # 초록
                    elif "#dc3545" in raw_color or "red" in raw_color: self.last_buy_color = "#e74c3c" # 빨강
                    elif "#00e5ff" in raw_color or "cyan" in raw_color: self.last_buy_color = "#00e5ff" # 밝은 청록 (정찰병)
                    else: self.last_buy_color = raw_color
                else:
                    # 키워드 기반 보정
                    if "HTS매수" in text or "직접매매" in text: self.last_buy_color = "#ff9800"
                    elif "비율" in text: self.last_buy_color = "#007bff"
                    elif "금액" in text: self.last_buy_color = "#28a745"
                    elif "한주" in text or "정찰병" in text: self.last_buy_color = "#00e5ff"
                    else: self.last_buy_color = "#2ecc71"

                self.lbl_last_buy_timer.setText(f"{self.last_buy_stock_name} 00:00")
                self.lbl_last_buy_timer.setStyleSheet(f"color: {self.last_buy_color}; font-weight: bold;")

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
        # [NEW v6.5.1] 직접 출력 대신 큐에 적재 (GUI 스레드 점유 최소화)
        q_key = "main" if target_display == self.log_display else "bultagi"
        self.log_queue[q_key].append(full_html)
        
    def process_log_queue(self):
        """[신규 v6.5.1] 0.25초마다 쌓인 로그를 한꺼번에 출력하여 성능 극대화"""
        try:
            for q_key, display in [("main", self.log_display), ("bultagi", self.bultagi_log_display)]:
                if self.log_queue[q_key]:
                    # 큐에 있는 모든 로그를 하나로 합침
                    combined_html = "".join(self.log_queue[q_key])
                    self.log_queue[q_key].clear()
                    
                    # 한 번에 append (QTextEdit 성능 최적화)
                    display.append(combined_html)
                    
                    # [성능] 최대 1,000줄로 제한하여 메모리 폭발 방지
                    if display.document().blockCount() > 1000:
                        display.document().setMaximumBlockCount(1000)
        except Exception as e:
            print(f"⚠️ [process_log_queue] 에러: {e}")
        
    def append_report(self, raw_html):
        """[v5.7.16] REPORT 전용 HTML 안전 렌더링 슬롯.
        report_signal을 통해 HTML 태그가 절대 잘리지 않은 완전한 HTML을 수신하여
        화면에 출력합니다. 기존 로그를 비우고 리포트를 단독으로 표시합니다."""
        if not raw_html: return
        try:
            html = raw_html.replace('\n', '<br>')
            # self.log_display.clear() # [v6.3.3] 자기의 요청으로 기존 로그를 유지하면서 리포트를 추가함! ❤️
            self.log_display.append(html)
            self.log_display.append("\n===========================\n")
            QApplication.processEvents()
            sb = self.log_display.verticalScrollBar()
            sb.setValue(sb.maximum())
        except Exception as e:
            print(f"⚠️ [append_report 오류] {e}")

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
            cmd_lower = cmd.lower()
            if cmd.upper() == 'PRINT': self.export_log()
            elif cmd_lower == 'clr':
                self.log_display.clear()
                self.bultagi_log_display.clear()
                self.append_log("🧹 모든 로그가 초기화되었습니다.")
            elif cmd_lower == 'start': self.on_start_clicked()
            elif cmd_lower == 'stop': self.on_stop_clicked()
            elif cmd_lower == 'help':
                # [v1.9.9] 명령어 도움말 리스트 출력
                help_msg = """
<span style='color: #f1c40f; font-weight: bold;'>[ KIPOSTOCK 명령어 도움말 ]</span><br>
--------------------------------------------------<br>
• <span style='color: #2ecc71;'><b>HELP</b></span> : 지금 보고 계신 명령어 목록을 출력합니다.<br>
• <span style='color: #2ecc71;'><b>CLR</b></span> : 모든 로그창을 깨끗이 비웁니다.<br>
• <span style='color: #2ecc71;'><b>START</b></span> : 자동 매매를 시작합니다.<br>
• <span style='color: #2ecc71;'><b>STOP</b></span> : 자동 매매를 중지합니다.<br>
• <span style='color: #2ecc71;'><b>PRINT</b></span> : 지금까지의 로그를 파일로 저장합니다.<br>
--------------------------------------------------<br>
※ 그 외의 문장은 AI 비서와 대화로 처리됩니다. ❤️
"""
                self.append_log(help_msg)
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
        """조건식 버튼 클릭 시 전략 모드(Qty -> Amt -> Pct -> Off) 순환 전환"""
        # [신규 v6.1.12 Hotfix] 자동 매매 또는 시퀀스 작동 중에는 전략 변경을 차단 (우클릭 마킹은 허용)
        current_status = self.lbl_status.text()
        is_seq_auto = self.btn_auto_seq.isChecked()
        if "RUNNING" in current_status or is_seq_auto:
            self.append_log(f"⚠️ 매매/시퀀스 작동 중에는 전략을 변경할 수 없습니다. (우클릭 마킹은 가능)")
            return

        self.cond_states[idx] = (self.cond_states[idx] + 1) % 4
        self.update_button_style(idx)
        self.animate_button_click(self.cond_buttons[idx]) # [v6.7.0 Bug Fix] 스타일 업데이트 후 애니메이션 호출
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

        # -------------------------------------------------------------
        # ✅ 3. 최근 매수 경과 시간 업데이트 (매초 실행)
        # -------------------------------------------------------------
        if hasattr(self, 'last_buy_time') and self.last_buy_time:
            elapsed = datetime.datetime.now() - self.last_buy_time
            tot_sec = int(elapsed.total_seconds())
            mm = tot_sec // 60
            ss = tot_sec % 60
            
            # 종목명과 함께 표시 (예: 삼성전자 01:23)
            stock_nm = getattr(self, 'last_buy_stock_name', '대기')
            t_color = getattr(self, 'last_buy_color', '#2ecc71')
            self.lbl_last_buy_timer.setText(f"{stock_nm} {mm:02d}:{ss:02d}")
            
            # 10분 경과 전까지는 전략별 색상 유지
            if mm < 10:
                self.lbl_last_buy_timer.setStyleSheet(f"color: {t_color}; font-weight: bold;")
            else:
                # 10분 경과 시 강렬한 빨간색으로 경고 (공통 규칙)
                self.lbl_last_buy_timer.setStyleSheet("color: #ff0000; font-weight: bold;")

 

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
                profile_key = str(profile_idx)
                
                # [v6.3.0 개선] 수동 모드('M')는 루트 설정과 프로필 설정을 병합하여 로드 (누락 방지) 🚀
                if profile_key.upper() == "M":
                    target = settings.copy() # 루트 설정을 기반으로 시작
                    if profile_key in profiles:
                        target.update(profiles[profile_key]) # M 프로필 데이터가 있으면 덮어씀
                        self.append_log("📂 'M' 프로필 설정을 루트와 병합하여 불러왔습니다.")
                    else:
                        self.append_log("ℹ️ 'M' 프로필 데이터가 없어 기본(루트) 설정을 적용합니다.")
                else:
                    target = profiles.get(profile_key)
                    if not target:
                        # [수정] 데이터가 없어도 중단하지 않고 기본값으로 UI를 갱신하도록 함 (구버전 호환성)
                        self.append_log(f"ℹ️ 프로필 {profile_idx}번 데이터가 없어 기본 설정을 적용합니다.")
                        target = {} 
                    self.append_log(f"📂 프로필 {profile_idx}번 설정을 불러왔습니다.")

            # [v6.8.8] 로드 시 상시 활성화(v6.6.4)를 제거하고 실제 설정값을 따름
            # target['bultagi_enabled'] = True
            # settings['bultagi_enabled'] = True
            # try:
            #     with open(self.settings_file, 'w', encoding='utf-8') as f:
            #         json.dump(settings, f, ensure_ascii=False, indent=2)
            # except: pass

            self.input_max.setText(str(target.get('max_stocks', '20')))
            
            # [v1.9.9] 로그 간소화 옵션 UI 제거로 인해 로드 로직 주석 처리
            # is_simple = settings.get('simple_log', target.get('simple_log', False))
            # if hasattr(self, 'chk_simple_log'):
            #     self.chk_simple_log.blockSignals(True)
            #     self.chk_simple_log.setChecked(is_simple)
            #     self.chk_simple_log.blockSignals(False)
            
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

            # [신규 v5.1] 마킹 상태 로드
            marked_list = target.get('marked_conditions', [])
            if isinstance(marked_list, list):
                self.marked_states = [False] * 10
                for m_idx in marked_list:
                    try:
                        idx_i = int(m_idx)
                        if 0 <= idx_i < 10: self.marked_states[idx_i] = True
                    except: pass

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
            
            # [v3.3.7] 프로필 전환 시 불타기 상태판 초기화 (잔재 제거)
            if hasattr(self, 'bultagi_status_board'):
                self.bultagi_status_board.setRowCount(0)
                
            # [Fix v6.2.9] 프로필 불러오기 후, 해당 프로필의 불타기 설정을 루트(settings.json 최상위)로 강제 동기화
            # 이를 통해 매매 엔진(chk_n_sell)이 항상 현재 선택된 프로필의 불타기 상세 설정을 참조하게 함
            bultagi_keys = [
                'bultagi_enabled', 'bultagi_wait_sec', 'bultagi_mode', 
                'bultagi_price_type', 'bultagi_val', 'bultagi_tp', 'bultagi_sl',
                'bultagi_power_enabled', 'bultagi_power_val', 'bultagi_slope_enabled',
                'bultagi_preservation_enabled', 'bultagi_preservation_trigger', 'bultagi_preservation_limit',
                'bultagi_tp_enabled', 'bultagi_sl_enabled', 'bultagi_trailing_enabled', 'bultagi_trailing_val',
                'bultagi_orderbook_enabled', 'bultagi_orderbook_val',
                # Turbo VI 관련 키 추가
                'bultagi_turbo_vi', 'bultagi_turbo_vi_type', 'bultagi_turbo_vi_min_price', 'bultagi_turbo_vi_max_price',
                'bultagi_turbo_vi_static', 'bultagi_turbo_vi_dynamic', 'bultagi_turbo_vi_volume_enabled', 'bultagi_turbo_vi_volume_rank',
                'bultagi_turbo_ex_etf', 'bultagi_turbo_ex_spac', 'bultagi_turbo_ex_prefer',
                # Ranking Scout 관련 키 추가
                'rank_scout_enabled', 'rank_scout_new_threshold', 'rank_scout_jump_threshold', 'rank_scout_interval', 'rank_scout_qry_tp',
                # 시초가 베팅 및 분석 관련 키 추가
                'morning_bet_enabled', 'morning_time', 'morning_gap_min', 'morning_gap_max', 'morning_break_rt', 
                'morning_tp', 'morning_sl', 'morning_ai_filter', 'morning_bet_use_a', 'morning_bet_use_b', 'morning_bet_use_c', 'morning_bet_use_d',
                'kipostock_peak_rt', 'kipostock_now_rt_min', 'kipostock_now_rt_max', 'kipostock_perspective_time'
            ]
            
            sync_data = {}
            for k in bultagi_keys:
                if k in target:
                    sync_data[k] = target[k]
            
            if sync_data:
                # 1. 워커 엔진 메모리 즉시 갱신
                if hasattr(self, 'worker') and self.worker:
                    self.worker.schedule_command('update_settings', sync_data, True)
                
                # 2. settings.json 파일 물리적 동기화 (chk_n_sell.py의 load_json_safe 참조용)
                try:
                    with open(self.settings_file, 'r', encoding='utf-8') as f:
                        full_settings = json.load(f)
                    full_settings.update(sync_data)
                    with open(self.settings_file, 'w', encoding='utf-8') as f:
                        json.dump(full_settings, f, indent=4, ensure_ascii=False)
                    
                    # [v3.0.6] 프로필 로드 후 캐시 강제 무효화 (엔진 즉시 인지!)
                    from get_setting import clear_settings_cache
                    clear_settings_cache()
                except: pass
            
            # [v6.3.0] UI 하이라이트 상태 즉시 갱신
            # [v6.8.8] 레이블과 그룹박스 스타일링을 통합 동기화
            is_bultagi_enabled = sync_data.get('bultagi_enabled', target.get('bultagi_enabled', True))
            self.is_bultagi_enabled = is_bultagi_enabled # [v3.0.6] 멤버 변수 동기화
            self.update_bultagi_group_style(is_bultagi_enabled)
            self.update_bultagi_status_label(is_bultagi_enabled)
            
            # [v1.3.0] 설정 로드 시에도 로그 출력 (단, 부팅 직후 2.0초 이내에는 _startup_bultagi_sync가 처리하므로 중복 방지)
            if (datetime.datetime.now() - self.app_start_time).total_seconds() > 2.0:
                b_color = "#f1c40f" if is_bultagi_enabled else "#888888"
                b_status = "ON" if is_bultagi_enabled else "OFF"
                self.append_log(f"🔥 <b>[불타기]</b> 프로필 설정 로드: <font color='{b_color}'>{b_status}</font>")

            # [신규] 프로필 불러오기 후, 팝업창(Bultagi)이 열려있다면 UI 동기화
            if hasattr(self, 'bultagi_dialog') and self.bultagi_dialog and self.bultagi_dialog.isVisible():
                self.bultagi_dialog.load_settings()
            
            # [v2.2.0] Ranking Scout 엔진 설정도 즉시 동기화 (자기 요청 ❤️)
            if hasattr(self, 'rank_engine'):
                self.rank_engine.reload_parameters()
                print(f"✅ 프로필 '{profile_idx}' Ranking Scout 엔진 동기화 완료")

            # [Fix v4.3.0] 모든 로딩 완료 후 초기화 플래그 활성화 (이 이후부터 자동 저장 허용) 🚀
            self.is_initialized = True
            
        except Exception as e:
            self.append_log(f"❌ 설정 불러오기 실패: {e}")
            self.is_initialized = True # [Fix] 실패해도 플래그 활성화 (UI 조작 차단 방지)
            # [중요] 실패하더라도 READY 상태로 전환하여 UI 조작이 가능하게 함
            QTimer.singleShot(500, lambda: self.update_status_ui("READY"))

    # [V1.6.2] Missing method 복구 및 별칭 추가
    def apply_settings(self):
        """KipoWindow object has no attribute 'apply_settings' 에러를 방지하기 위한 별칭"""
        return self.save_settings()

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

            # UI에 보정된 값 즉시 반영
            self.input_qty_tp.setText(q_tp); self.input_qty_sl.setText(q_sl)
            self.input_amt_tp.setText(a_tp); self.input_amt_sl.setText(a_sl)
            self.input_pct_tp.setText(p_tp); self.input_pct_sl.setText(p_sl)

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
                    'percent': {'tp': safe_float(p_tp, 1.0), 'sl': safe_float(p_sl, -1.0)}
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
                # [신규 v5.1] 마킹 상태 저장
                'marked_conditions': [i for i, m in enumerate(self.marked_states) if m],
                # [v4.6] 불타기 관련 세팅은 이제 BultagiSettingsDialog에서 다이렉트로 관리함 (여기서는 덮어쓰지 않음)
            }

            if profile_idx is not None:
                # 특정 프로필에 저장
                with open(self.settings_file, 'r', encoding='utf-8') as f:
                    settings = json.load(f)
                
                if 'profiles' not in settings: settings['profiles'] = {}
                
                # 불타기 관련 키 추출 (UI 상태가 아닌 settings.json 파일의 루트가 현재 기준임)
                bultagi_keys = [
                    'bultagi_enabled', 'bultagi_wait_sec', 'bultagi_mode', 
                    'bultagi_price_type', 'bultagi_val', 'bultagi_tp', 'bultagi_sl',
                    'bultagi_power_enabled', 'bultagi_power_val', 'bultagi_slope_enabled',
                    'bultagi_preservation_enabled', 'bultagi_preservation_trigger', 'bultagi_preservation_limit',
                    'bultagi_tp_enabled', 'bultagi_sl_enabled', 'bultagi_trailing_enabled', 'bultagi_trailing_val'
                ]
                
                # 루트 설정 로드 (최신 불타기 설정을 얻기 위함)
                root_settings = {}
                try:
                    with open(self.settings_file, 'r', encoding='utf-8') as f:
                        root_settings = json.load(f)
                except: pass

                for k in bultagi_keys:
                    # 루트 설정에 있으면 그걸 쓰고, 없으면 기본값(또는 현재 UI값) 주입
                    if k in root_settings:
                        current_data[k] = root_settings[k]
                    elif k == 'bultagi_enabled':
                        # [v3.0.6] isChecked() 대신 멤버 변수를 사용하여 오토 시퀀스 시 OFF되는 버그 수정 🚀✨
                        current_data[k] = self.is_bultagi_enabled 
                
                # [v6.3.0 개선] 기존 프로필 데이터가 있다면 가져와서 업데이트 (파괴적 저장 방지)
                p_idx_str = str(profile_idx)
                existing_profile_data = settings['profiles'].get(p_idx_str, {})
                existing_profile_data.update(current_data)
                settings['profiles'][p_idx_str] = existing_profile_data
                
                if p_idx_str.upper() == "M":
                    # [Fix] 수동 모드('M') 저장 시 루트 공통 설정도 함께 업데이트 (동기화 보장) 🚀✨
                    settings.update(current_data)
                
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
                    summary = f"📋 [저장] 1주({q_tp}/{q_sl}%) | 금액({a_tp}/{a_sl}%) | 비율({p_tp}/{p_sl}%)"
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
                        'percent': {'tp': safe_float(p_tp, 1.0), 'sl': safe_float(p_sl, -1.0)}
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
                    'bultagi_enabled': self.bultagi_group.isChecked(), # [v6.6.4] 람다 제거 및 직관적 상태 반영
                    'bultagi_wait_sec': get_setting('bultagi_wait_sec', 30),
                    'bultagi_mode': get_setting('bultagi_mode', 'multiplier'),
                    'bultagi_price_type': get_setting('bultagi_price_type', 'market'),
                    'bultagi_val': get_setting('bultagi_val', '10'),
                    'bultagi_tp': get_setting('bultagi_tp', 5.0),
                    'bultagi_sl': get_setting('bultagi_sl', -3.0),
                    'bultagi_sl': get_setting('bultagi_sl', -3.0),
                    # [신규 v5.1] 루트 설정값 전송 시 마킹 상태 포함
                    'marked_conditions': [i for i, m in enumerate(self.marked_states) if m],
                    # [신규 v1.2.6] 로그 간소화 상태 포함
                    # [v1.9.9] 로그 간소화 체크박스 제거로 인해 저장 로직에서 참조 제외
                    # 'simple_log': self.chk_simple_log.isChecked() if hasattr(self, 'chk_simple_log') else False,
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
                    summary = f"📋 [저장] 1주({q_tp}/{q_sl}%) | 금액({a_tp}/{a_sl}%) | 비율({p_tp}/{p_sl}%) | 종목수:{max_s} | 시간:{st}~{et}"
                    self.append_log(f"<font color='#28a745'>{summary}</font>")

            self.refresh_condition_list_ui()
            
        except ValueError:
            QMessageBox.warning(self, "입력 오류", "숫자 형식이 올바르지 않습니다.")
        except Exception as e:
             QMessageBox.critical(self, "오류", f"저장 중 오류 발생: {e}")

    # [미씽 메서드 복구] 프로필 버튼 클릭 핸들러
    def on_profile_clicked(self, idx):
        """[v6.3.0 개선] 프로필 전환 직전 현재 설령을 안전하게 저장합니다."""
        # [Fix v4.3.0] 초기 로딩 완료 후에만 자동 저장 실행 (Save-Before-Load 버그 차단) 🚀
        if not self.is_save_mode and self.current_profile_idx is not None and getattr(self, 'is_initialized', False):
             self.save_settings(profile_idx=self.current_profile_idx, restart_if_running=False, quiet=True)
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
                
                # [v3.1.3] 프로필 전환 시 불타기 자동 재활성화 (자기 요청 ❤️)
                if not getattr(self, 'is_bultagi_enabled', False):
                    self.toggle_bultagi_enabled()
                    self.append_log("🔥 [시퀀스] 프로필 전환에 따른 불타기 모드 자동 재활성화 완료!")
            
            # [수정] 시퀀스 자동 모드 조건 강화 (기존에 이미 켜져 있었을 때만 로드 후 자동 시작)
            # 단, M모드일 때는 절대 자동 시작 안 함
            if str(idx) != "M" and is_seq_before_load and self.btn_auto_seq.isChecked():
                self.append_log(f"🚀 시퀀스 자동: 프로필 {idx}번 선택됨 - 엔진을 자동 재기동합니다.")
                # [수정] 이미 실행 중일 수도 있으므로 force=True로 재시작 강제 (원격에서 온 경우 이미 READY 체크됨)
                # [중요] 오토 시퀀스에 의한 자동 시작이므로 manual=False로 시간 체크를 강제함!
                QTimer.singleShot(1000, lambda: self.on_start_clicked(force=True, manual=False))
            
            # [v6.6.2] 프로필 전환 시 불타기 상태 레이블 갱신 (load_settings_to_ui에서 이미 갱신됨)
            # self.update_bultagi_status_label()

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

    def update_portfolio_table(self):
        """[v6.1.12] ACCOUNT_CACHE의 보유 종목 데이터를 실시간 테이블에 렌더링"""
        try:
            from check_n_buy import ACCOUNT_CACHE
            holdings = ACCOUNT_CACHE.get('realtime_holdings', {})
            
            # 매입 시간 계산을 위한 mapping 데이터 획득
            mapping = {}
            if self.worker and self.worker.chat_command:
                mapping_file = self.worker.chat_command.stock_conditions_file
                if os.path.exists(mapping_file):
                    try:
                        with open(mapping_file, 'r', encoding='utf-8') as f:
                            mapping = json.load(f)
                    except: pass
            
            # 테이블 업데이트 수행
            if hasattr(self, 'portfolio_table'):
                self.portfolio_table.update_data(holdings, mapping)
                
                # [V3.0.9] 불타기 보드 데이터 정제 (Sync Purge)
                if hasattr(self, 'bultagi_status_board'):
                    self.purge_bultagi_status_board(holdings)

                # [신규 v1.6.9] 테이블 업데이트 시 종목이 발견되면 레이저 효과 자동 활성화
                if self.has_bultagi_targets():
                    self.start_laser_blinking()
        except Exception as e:
            # 실시간 업데이트 중 오류는 로그에 남기지 않고 콘솔에만 출력
            print(f"⚠️ 잔고 테이블 업데이트 오류: {e}")

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

        # [신규 v6.1.15] 오후 자동 시장 분석 및 종가 배팅 추천 트리거 (v6.1.19 매개변수화)
        from get_setting import get_setting
        perspective_time = get_setting('kipostock_perspective_time', '15:10')
        target_time_str = perspective_time + ":00"

        if current_time_str == target_time_str:
            # [수정] 워커 플래그를 직접 체크하여 하루 1회만 실행 보장
            if self.worker and not getattr(self.worker, 'perspective_opened_today', False):
                self.log_and_tel(f"⏰ [{perspective_time}] 오늘의 시장을 총정리하고 내일의 '종가 베팅' 종목을 분석합니다... (잠시만 기다려줘)")
                self.worker.perspective_opened_today = True
                self.worker.schedule_command('close_bet')
                
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
            
            # [V5.1.9 수정] 중합 리포트 중복 출력 통합 (1회로 축소)
            # 2초/7초 간격으로 시퀀스/전체 리포트가 중복되던 것을 7초 뒤 최종 1회로 통합합니다.
            # QTimer.singleShot(2000, lambda: self.worker.schedule_command('report', current_idx)) 
            QTimer.singleShot(7000, lambda: self.worker.schedule_command('report')) # 최종 종합 리포트 1회만 실행
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
            # [V3.3.8] 종료 전 설정 강제 저장 (유실 방지 ❤️)
            try:
                self.save_all_settings()
                # 소량의 대기 시간을 주어 파일 쓰기 완료 보장
                time.sleep(0.3)
            except: pass

            self.is_closing = True # [v3.0.1] 즉시 무조건 종료 플래그 On
            
            # [v3.0.1] 모든 활성 타이머 일괄 정지하여 백그라운드 접근 원천 차단
            timers = [
                'alarm_timer', 'blink_timer', 'profile_blink_timer', 'trade_timer', 
                'alert_close_timer', 'seq_blink_timer', 'bultagi_watchdog_timer', 
                'portfolio_timer', 'log_timer', 'heartbeat_timer', 'laser_timer'
            ]
            for t_name in timers:
                if hasattr(self, t_name):
                    try: getattr(self, t_name).stop()
                    except: pass

            # [v3.0.1] 종료 전 안전장치: 모든 주요 시그널 연결 해제
            try:
                self.worker.signals.log_signal.disconnect()
                self.worker.signals.status_signal.disconnect()
                self.worker.signals.report_signal.disconnect()
                self.worker.signals.graph_update_signal.disconnect()
                self.worker.signals.news_signal.disconnect()
                self.worker.signals.ai_voice_signal.disconnect()
            except: pass
            
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
            
        # [신규 v4.7.3] 최근 매수 경과 시간 업데이트 (사용자 요청으로 제거 v2.4.8)
        pass

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
    # [V1.6.2] 레드 레이저 애니메이션용 헬퍼 메서드 모음
    def collect_laser_lines(self, widget):
        """[신규] 위젯 트리 내 모든 QFrame(HLine)을 재귀적으로 찾아 리스트에 저장"""
        from PyQt6.QtWidgets import QFrame
        for child in widget.findChildren(QFrame):
            # 가로 구분선(HLine)인 경우에만 레이저 대상에 포함
            if child.frameShape() == QFrame.Shape.HLine:
                self.laser_lines.append(child)

    def start_laser_blinking(self):
        """[신규] 레이저 점멸 애니메이션 시작 (0.5초 간격으로 무한/유한 점멸)"""
        # [v1.6.3] 사용자 요청 반영: 0.5초 간격(500ms)으로 조정
        if hasattr(self, 'laser_timer'):
            self.laser_timer.setInterval(500)
            
        if hasattr(self, 'laser_timer') and not self.laser_timer.isActive():
            # [Fix v1.6.2] 매번 최신 구분선들을 수집 (설정창 등 열려있는 모든 창 대상)
            self.laser_lines = []
            self.collect_laser_lines(self)
            if hasattr(self, 'bultagi_dialog') and self.bultagi_dialog:
                self.collect_laser_lines(self.bultagi_dialog)
            
            self.laser_count = 0
            self.laser_timer.start()

    def has_bultagi_targets(self):
        """[수정 v1.7.0] 잔고 테이블 내 실제 '불타기 대기' 종목 존재 여부 확인 (진입 완료 제외)"""
        try:
            if not hasattr(self, 'portfolio_table'): return False
            row_cnt = self.portfolio_table.rowCount()
            for r in range(row_cnt):
                item = self.portfolio_table.item(r, 0) # 매수 전략 컬럼
                if item:
                    strat = item.text().strip()
                    # 전략이 '불타기진입'이거나 설정되지 않은('--') 경우를 제외한 실제 '대기' 종목이 있으면 True
                    if strat != "--" and strat != "불타기진입":
                        return True
            return False
        except: return False

    def toggle_laser_effect(self):
        """[신규] 레이저 색상 토글 로직 (심장부 ❤️) - 흰색/빨강 교차 점멸"""
        self.laser_count += 1
        # 빨강(#ff4444)과 흰색(#ffffff)을 번갈아 가며 적용 (자기 요청 반영!)
        is_red = (self.laser_count % 2 != 0)
        target_color = "#ff4444" if is_red else "#ffffff"
        
        # 1. 구분선(HLine) 레이저 효과
        for line in self.laser_lines:
            try: line.setStyleSheet(f"background-color: {target_color}; border: none;")
            except: pass
            
        # 2. [v3.0.2 제거] 사용자 요청에 따라 로그창 테두리 반짝임 레이저 효과 삭제 🚫
        # if hasattr(self, 'bultagi_log_display'):
        #     try:
        #         # 굵고 선명한 3px 테두리 적용 (applyZoomStyle 사용하여 줌 레벨 보존)
        #         self.bultagi_log_display.applyZoomStyle(f"border: 3px solid {target_color};")
        #     except: pass

        # [v1.6.9] 잔고에 종목이 있으면 무한 점멸, 없으면 워치독 확인 또는 6회 후 정지
        if self.has_bultagi_targets():
             return # 종목이 있으면 무한 지속! (리턴하여 중지 로직 건너뜀)

        # [v1.6.6] 워치독 타이머가 작동 중이면 무한 점멸, 아니면 자동 정지
        if hasattr(self, 'bultagi_watchdog_timer') and not self.bultagi_watchdog_timer.isActive():
            if self.laser_count >= 20: # [v1.7.3] 자동 종료 연장 (6회 -> 20회, 약 10초)
                self.stop_laser_blinking()

    # [v1.9.5 / v2.3.1] 누락된 VI 해제 알람 메서드 복구 및 중복/빈이름 방지
    def trigger_vi_release_alarm(self, stk_name):
        """110초 대기 후 호출되는 알람 실행부. 중복 알람 및 빈 이름을 차단함."""
        try:
            # [v2.3.1] 빈 이름이나 너무 짧은 이름(유령 알람) 차단
            if not stk_name or len(stk_name) < 2:
                return

            now = datetime.datetime.now()
            # 1. 쿨타임 체크: 2분 이내 동일 종목 알람이 울렸다면 무시
            if stk_name in self.vi_alarm_cache:
                last_time = self.vi_alarm_cache[stk_name]
                if (now - last_time).total_seconds() < 120:
                    return
            
            # 2. 캐시 업데이트
            self.vi_alarm_cache[stk_name] = now
            
            # [v4.0.1] 보유 종목 여부 추가 레이어 확인 (불필요한 알람 차단)
            is_holding = False
            try:
                from check_n_buy import ACCOUNT_CACHE
                if stk_name in [h.get('name') for h in ACCOUNT_CACHE.get('holdings', {}).values() if h.get('name')]:
                    is_holding = True
                # 코드로도 체크 (종목명으로 안 올 때 대비)
                elif any(stk_name in str(v) for v in ACCOUNT_CACHE.get('holdings', {}).keys()):
                    is_holding = True
            except: pass
            
            if not is_holding: return

            # 3. 알람 로그 및 음성 출력
            log_msg = f"📢 <font color='#f1c40f'><b>[VI해제임박]</b> {stk_name} VI 해제 10초 전! 얼른 보러 와!</font>"
            self.append_log(log_msg)
            
            # [v4.2.9] 비프음 효과음 추가 (사용자 요청 ✨)
            import winsound
            winsound.Beep(1000, 500) # 1000Hz로 0.5초간 비프

            # [v1.9.5] PowerShell say_text 중복 실행에 따른 프리징 방지를 위해 직접 호출 대신 유닛화
            from check_n_buy import say_text
            say_text(f"{stk_name} 브이아이 해제 예보")

        except Exception as e:
            print(f"⚠️ trigger_vi_release_alarm 오류: {e}")

    def stop_laser_blinking(self):
        """[신규] 레이저 중지 및 색상 원복"""
        self.laser_timer.stop()
        final_color = "#444" if self.ui_theme == 'dark' else "#ccc"
        
        # 1. 구분선 원복
        for line in self.laser_lines:
            try: line.setStyleSheet(f"background-color: {final_color};")
            except: pass

        # 2. [v1.6.3] 불타기 로그창 테두리 원복 (applyZoomStyle 사용하여 줌 레벨 보존 ✅)
        if hasattr(self, 'bultagi_log_display'):
            try:
                self.bultagi_log_display.applyZoomStyle("")
            except: pass

    def play_timer_alarm(self):
        try:
            # 1000Hz의 맑은 소리로 0.4초간 비프음
            import winsound
            winsound.Beep(1000, 400)
        except: pass

    def update_index_ui(self, idx_data):
        """[v4.4.0] 지수 데이터를 받아 화면 상단 라벨(lbl_index)을 실시간으로 업데이트합니다."""
        try:
            kospi_val = idx_data.get('kospi', '0.0')
            kospi_rate = float(idx_data.get('kospi_rate', '0.0'))
            kosdaq_val = idx_data.get('kosdaq', '0.0')
            kosdaq_rate = float(idx_data.get('kosdaq_rate', '0.0'))
            
            # 색상 결정 (상승: 빨강, 하락: 파랑, 보합: 회색)
            def get_rate_color(rate):
                if rate > 0: return "#e74c3c"
                elif rate < 0: return "#3498db"
                else: return "#aaaaaa"
                
            kospi_color = get_rate_color(kospi_rate)
            kosdaq_color = get_rate_color(kosdaq_rate)
            
            # HTML 포맷팅 (KOSPI 0,000.00 (±0.00%) | KOSDAQ 000.00 (±0.00%))
            idx_html = (
                f"<span style='color:#eee; font-size:10pt;'>KOSPI</span> "
                f"<span style='color:{kospi_color}; font-weight:bold;'>{kospi_val} ({kospi_rate:+.2f}%)</span> "
                f" <span style='color:#555;'>|</span> "
                f"<span style='color:#eee; font-size:10pt;'>KOSDAQ</span> "
                f"<span style='color:{kosdaq_color}; font-weight:bold;'>{kosdaq_val} ({kosdaq_rate:+.2f}%)</span>"
            )
            self.lbl_index.setText(idx_html)
            self.lbl_index.setStyleSheet("background-color: rgba(0,0,0,0.1); border-radius: 4px; padding: 2px;")
            
        except Exception as e:
            # UI 업데이트 중 오류 발생 시 조용히 처리 (로그 노이즈 방지)
            print(f"⚠️ 지수 UI 업데이트 오류: {e}")

    def closeEvent(self, event):
        """[신규 v6.3.1] 프로그램 종료 시 설정을 강제 저장하고 워커를 안전하게 종료합니다."""
        try:
            self.is_closing = True # [신규] 종료 플래그 활성화 (excepthook 팝업 방지용)
            
            # 1. 시퀀스 자동 모드 작동 중이면 종료 알림
            if hasattr(self, 'btn_auto_seq') and self.btn_auto_seq.isChecked():
                self.append_log("⚠️ 시퀀스 자동 모드 작동 중 종료가 감지되었습니다.")
                
            # 2. 현재 설정 강제 저장 (루트 및 현재 프로필)
            self.save_settings(profile_idx=self.current_profile_idx, restart_if_running=False, quiet=True)
            self.append_log("💾 종료 전 모든 설정이 안전하게 저장되었습니다.")
            
            # 3. 워커 중단 시도 (비동기 루프 종료)
            if hasattr(self, 'ai_autopilot_engine') and self.ai_autopilot_engine.isRunning():
                self.ai_autopilot_engine.stop()
            
            if hasattr(self, 'worker') and self.worker:
                self.worker.keep_running = False
                self.worker.schedule_command('stop')
                self.worker.wait(1000) # 최대 1초 대기
                
            self.append_log("👋 시스템을 종료합니다. 자기야 고생했어! 내일 또 만나❤️")
            
            # 4. 종료 승인
            event.accept()
        except Exception as e:
            print(f"❌ 종료 이벤트 처리 중 오류: {e}")
            event.accept()

if __name__ == '__main__':
    import faulthandler
    import os
    import sys
    import datetime
    import traceback
    
    # [v6.5.4] 정밀 추적 시스템
    # [V2.4.6] 사용자 요청에 따른 데이터 고정 경로 적용 (get_base_path 통합)
    from get_setting import get_base_path
    base_path = get_base_path()
    
    log_data_dir = os.path.join(base_path, 'LogData')
    if not os.path.exists(log_data_dir): os.makedirs(log_data_dir, exist_ok=True)
    
    fault_path = os.path.join(log_data_dir, "crash_fault.txt")
    report_path = os.path.join(log_data_dir, "crash_report.txt")
    
    def my_excepthook(type, value, tback):
        """[V2.4.6] PyInstaller 환경에서 처리되지 않은 모든 예외를 포착하여 기록"""
        # [v3.0.1 Fix] 프로그램 종료 중(is_closing) 발생하는 지엽적 에러는 무시하여 유령 팝업 방지
        try:
            # 전역 변수 window가 생성되어 있고, 종료 플래그가 켜져 있다면 팝업 생략
            if 'window' in globals() and hasattr(window, 'is_closing') and window.is_closing:
                return
        except: pass

        import traceback
        import ctypes
        import datetime
        err_msg = "".join(traceback.format_exception(type, value, tback))
        try:
            with open(report_path, "a", encoding="utf-8") as f:
                f.write(f"\n[{datetime.datetime.now()}] !!! UNHANDLED EXCEPTION (EXCEPTHOOK) !!!\n")
                f.write(err_msg)
                f.write("-" * 50 + "\n")
                f.flush()
            # 0x10 (MB_ICONERROR) 아이콘이 있는 팝업은 타이틀바가 강조될 수 있으나 종료 중에는 뜨지 않도록 가드함
            ctypes.windll.user32.MessageBoxW(0, f"Unhandled Error: {value}\nPlease check LogData/crash_report.txt", "KipoStock AI Error", 0x10)
        except: pass
        sys.__excepthook__(type, value, tback)

    sys.excepthook = my_excepthook
    
    def log_step(msg):
        try:
            with open(report_path, "a", encoding="utf-8") as f:
                f.write(f"[{datetime.datetime.now()}] [STEP] {msg}\n")
                f.flush()
        except: pass

    # faulthandler 설정 (Binary Unbuffered)
    f_fault = open(fault_path, "ab", buffering=0)
    faulthandler.enable(file=f_fault)
    # [v6.5.4] 5분 이상 응답 없으면 트레이스백 덤프
    faulthandler.dump_traceback_later(300, repeat=True, file=f_fault)

    try:
        log_step("--- START V5.1.28 ---")
        
        # [추가] Windows 작업표시줄 아이콘 고동
        if sys.platform == 'win32':
            import ctypes
            myappid = 'kipo.buy.auto.5.1.28'
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
            log_step("OS ID Set")

        from PyQt6.QtWidgets import QApplication
        from PyQt6.QtGui import QIcon, QFont
        from PyQt6.QtCore import QSharedMemory
        from PyQt6.QtWidgets import QMessageBox

        app = QApplication(sys.argv)
        log_step("QApp Created")
        
        icon_path = os.path.join(base_path, 'kipo_yellow.ico')
        if os.path.exists(icon_path):
            app.setWindowIcon(QIcon(icon_path))
            log_step("Icon Loaded")
        
        shared_memory = QSharedMemory("KipoStock_Singleton_Lock")
        if not shared_memory.create(1):
            log_step("Instance Conflict")
            # 만약 이미 존재한다면, 사용자에게 강제 실행 여부를 묻거나 경고
            QMessageBox.warning(None, "실행 오류", "프로그램이 이미 실행 중이거나 비정상 종료되었습니다.\n작업 관리자에서 기존 프로세스를 종료해주세요.")
            sys.exit(0)
        
        app.setFont(QFont("Malgun Gothic", 9))
        log_step("Font Set")
        
        window = KipoWindow()
        log_step("Window Instance Created")
        window.show()
        log_step("Window Shown")
        
        retCode = app.exec()
        log_step(f"EXIT with code {retCode}")
        sys.exit(retCode)
        
    except BaseException as e:
        if isinstance(e, SystemExit) and e.code == 0:
            sys.exit(0)
            
        with open(report_path, "a", encoding="utf-8") as f:
            f.write(f"\n[{datetime.datetime.now()}] !!! CRITICAL CRASH !!!\n")
            f.write(traceback.format_exc())
            f.write("-" * 50 + "\n")
            f.flush()
        
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, f"Critical Error: {e}\nSee LogData/crash_report.txt", "Error", 0x10)
        except: pass
        sys.exit(1)
