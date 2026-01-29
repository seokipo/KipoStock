import traceback
import sys
import os
from PyQt6.QtWidgets import QApplication

sys.path.append(os.getcwd())

try:
    from Kipo_GUI_main import KipoWindow
    print("Class Import SUCCESS")
    
    app = QApplication(sys.argv)
    print("QApplication initialized")
    
    window = KipoWindow()
    print("KipoWindow instance created SUCCESS")
    
except Exception:
    print("FAILED during execution")
    traceback.print_exc()
