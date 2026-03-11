import sys
import os
import time
import wave  # [v5.7.20] PyInstaller 빌드 시 누락 방지를 위한 명시적 임포트
from PyQt6.QtCore import QThread, pyqtSignal

# D드라이브용 패키지 경로 추가
sys.path.append(r"D:\Program files\Kipo_Libs")

try:
    import speech_recognition as sr
except Exception as e:
    sr = None
    STT_ERROR = str(e)
    
try:
    import edge_tts
    import asyncio
    import pygame
except Exception as e:
    edge_tts = None
    pygame = None
    TTS_ERROR = str(e)

class VoiceSTTWorker(QThread):
    finished_signal = pyqtSignal(str)
    error_signal = pyqtSignal(str)
    status_signal = pyqtSignal(str)

    def run(self):
        if sr is None:
            self.error_signal.emit(f"음성 인식 라이브러리 로드 실패: {STT_ERROR}")
            return
            
        recognizer = sr.Recognizer()
        
        try:
            with sr.Microphone() as source:
                self.status_signal.emit("🎤 듣는 중... (말씀해주세요)")
                recognizer.adjust_for_ambient_noise(source, duration=0.5)
                audio = recognizer.listen(source, timeout=5, phrase_time_limit=10)
                
            self.status_signal.emit("⏳ 변환 중...")
            text = recognizer.recognize_google(audio, language="ko-KR")
            self.finished_signal.emit(text)
            
        except sr.WaitTimeoutError:
            self.error_signal.emit("입력 시간이 초과되었습니다.")
        except sr.UnknownValueError:
            self.error_signal.emit("음성을 이해하지 못했습니다.")
        except sr.RequestError as e:
            self.error_signal.emit(f"구글 서비스 에러: {e}")
        except Exception as e:
            self.error_signal.emit(f"마이크 오류: {e}")

def stop_all_voice():
    """재생 중인 모든 음성을 즉시 중단합니다."""
    try:
        if pygame and pygame.mixer.get_init():
            pygame.mixer.music.stop()
            # [Fix v6.8.5] quit()은 워커 스레드가 안전하게 종료되면서 호출하도록 메인 스레드에서는 stop()만 수행
            # pygame.mixer.quit() 
    except:
        pass

class VoiceTTSWorker(QThread):
    finished_signal = pyqtSignal()
    error_signal = pyqtSignal(str)

    def __init__(self, text, voice_name="ko-KR-SunHiNeural", rate="+20%", volume=1.0):
        super().__init__()
        self.text = text
        self.voice_name = voice_name
        self.rate = rate
        self.volume = volume

    def run(self):
        if edge_tts is None or pygame is None:
            self.error_signal.emit(f"TTS 라이브러리 오류: {TTS_ERROR}")
            return
            
        if not self.text or not self.text.strip():
            self.finished_signal.emit()
            return
            
        try:
            # 특수기호나 이모지 제거하여 TTS 오류 방지
            clean_text = self.text.replace("*", "").replace("#", "").replace("💡", "").replace("📊", "")
            
            temp_file = f"temp_voice_{int(time.time())}.mp3"
            
            # edge-tts 비동기 작업 실행
            async def generate_audio():
                communicate = edge_tts.Communicate(clean_text, self.voice_name, rate=self.rate)
                await communicate.save(temp_file)
                
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(generate_audio())
            loop.close()
            
            # 오디오 재생
            pygame.mixer.init()
            pygame.mixer.music.load(temp_file)
            pygame.mixer.music.set_volume(self.volume) # [신규] 볼륨 설정 반영
            pygame.mixer.music.play()
            
            while pygame.mixer.music.get_busy():
                time.sleep(0.1)
                
            pygame.mixer.quit()
            
            try:
                if os.path.exists(temp_file):
                    os.remove(temp_file)
            except:
                pass
                
            self.finished_signal.emit()
            
        except Exception as e:
            self.error_signal.emit(f"음성 출력 오류: {e}")
