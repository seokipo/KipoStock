import sys
import os
import traceback
from PyQt6.QtWidgets import QApplication

# Ensure current directory is in path
sys.path.append(os.getcwd())

try:
    print("Initializing QApplication...")
    app = QApplication(sys.argv)
    
    print("Importing KipoWindow...")
    from Kipo_GUI_main import KipoWindow
    
    print("Instantiating KipoWindow...")
    window = KipoWindow()
    
    print("Showing window...")
    window.show()
    
    print("Starting event loop...")
    app.exec()
except Exception as e:
    print("\n" + "="*50)
    print("CRASH DETECTED")
    print("="*50)
    traceback.print_exc()
    print("="*50)
