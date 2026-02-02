import traceback
import sys
import os
import datetime
from PyQt6.QtWidgets import QApplication

# Ensure current directory is in path
sys.path.append(os.getcwd())

def log_error(msg):
    with open("debug_log.txt", "a", encoding="utf-8") as f:
        f.write(f"[{datetime.datetime.now()}] {msg}\n")

try:
    log_error("Starting debug session")
    from Kipo_GUI_main import KipoWindow
    log_error("Import SUCCESS")
    
    app = QApplication(sys.argv)
    log_error("QApplication initialized")
    
    window = KipoWindow()
    log_error("KipoWindow instance created")
    window.show()
    log_error("Window shown")
    
    # Run for a short time or catch the crash
    # app.exec() is blocking, so we need to be careful.
    # We'll use a timer to close it after 5 seconds if no crash.
    from PyQt6.QtCore import QTimer
    QTimer.singleShot(5000, app.quit)
    
    log_code = app.exec()
    log_error(f"App exited normally with code {log_code}")
    
except BaseException as e:
    log_error("CRITICAL ERROR CAUGHT")
    log_error(traceback.format_exc())
    print("FAILED during execution. See debug_log.txt")
