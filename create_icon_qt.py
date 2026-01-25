from PyQt6.QtGui import QImage, QPainter, QColor, QFont, QBrush, QPen
from PyQt6.QtCore import Qt, QRectF
import sys
from PyQt6.QtWidgets import QApplication

def create_icon(path):
    app = QApplication(sys.argv)
    
    size = 256
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(QColor(0,0,0,0)) # Transparent background
    
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    
    # Draw the Rocket Emoji 🚀
    # We need a font that supports emojis, commonly Segoe UI Emoji on Windows
    font = QFont("Segoe UI Emoji", 200) 
    # font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    painter.setFont(font)
    
    rect = QRectF(0, 0, size, size)
    painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "🚀")
    
    painter.end()
    image.save(path)
    print(f"Icon saved to {path}")

if __name__ == "__main__":
    create_icon("d:/Work/Python/AutoBuy/KipoBuy_Gui/icon.png")
