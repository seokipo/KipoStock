from PyQt6.QtGui import QImage, QPainter, QColor, QPolygonF, QBrush, QPen
from PyQt6.QtCore import QPointF, Qt, QRectF
import sys
from PyQt6.QtWidgets import QApplication

def create_icon_gen():
    app = QApplication(sys.argv)
    
    # 1. Create High-Res Image for ICO
    size_l = 256
    image = QImage(size_l, size_l, QImage.Format.Format_ARGB32)
    image.fill(QColor(0,0,0,0))
    
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    
    # Blue Circle Background
    # Using #007bff (Dodger Blue)
    painter.setBrush(QBrush(QColor(0, 123, 255)))
    painter.setPen(Qt.PenStyle.NoPen)
    # Leave small margin
    painter.drawEllipse(10, 10, 236, 236)
    
    # White Rocket Shape
    painter.setBrush(QBrush(QColor(255, 255, 255)))
    
    # Rocket Polygon (Taking off to Top-Right)
    # Tip
    tip = QPointF(190, 66)
    # Tail Base
    tail = QPointF(66, 190)
    # Right Wing Tip
    wr = QPointF(170, 160)
    # Left Wing Tip
    wl = QPointF(96, 86)
    
    # Let's try a better shape
    #      /\
    #     /  \
    #    /    \
    #   /      \
    #  /___  ___\
    #     |  |
    
    # Let's rotate -45 degrees (pointing TR)
    
    # Main Body
    # Tip (190, 66)
    # Base Center (66, 190)
    
    # Drawing simple triangle-like dart
    poly = QPolygonF()
    poly.append(QPointF(196, 60))  # Tip
    poly.append(QPointF(150, 140)) # Right wing mid
    poly.append(QPointF(160, 190)) # Right wing end
    poly.append(QPointF(60, 196))  # Base (Flame area)
    poly.append(QPointF(110, 96))  # Left wing mid
    
    # Simplified Paper Plane / Rocket
    poly2 = QPolygonF([
        QPointF(196, 60),  # Top-Right Tip
        QPointF(130, 126), # Mid-Right
        QPointF(150, 180), # Bottom-Right Wing
        QPointF(128, 128), # Center tail notch
        QPointF(76, 106),  # Top-Left Wing
        QPointF(126, 130), # Mid-Left
    ])
    
    # Let's do the emoji style: Simple Rocket
    #        / \
    #       | O |
    #      /|   |\
    #     /_|___|_\ 
    #       vvv
    
    # Draw rotated
    painter.translate(128, 128)
    painter.rotate(45)
    painter.translate(-128, -128)
    
    # Draw vertical rocket first then it gets rotated 45 deg to allow "Take off" look
    # Center x=128
    
    # Body (White)
    path = QPolygonF()
    path.append(QPointF(128, 40))  # Tip
    path.append(QPointF(160, 100))
    path.append(QPointF(160, 180))
    path.append(QPointF(96, 180))
    path.append(QPointF(96, 100))
    painter.drawPolygon(path)
    
    # Window (Blue)
    painter.setBrush(QBrush(QColor(0, 123, 255)))
    painter.drawEllipse(113, 90, 30, 30)
    
    # Fins (Red)
    painter.setBrush(QBrush(QColor(220, 53, 69))) # Red
    # Left Fin
    fin_l = QPolygonF([QPointF(96, 140), QPointF(96, 180), QPointF(60, 190)])
    painter.drawPolygon(fin_l)
    # Right Fin
    fin_r = QPolygonF([QPointF(160, 140), QPointF(160, 180), QPointF(196, 190)])
    painter.drawPolygon(fin_r)
    
    # Flame (Orange)
    painter.setBrush(QBrush(QColor(255, 193, 7))) # Orange/Yellow
    flame = QPolygonF([QPointF(110, 180), QPointF(146, 180), QPointF(128, 220)])
    painter.drawPolygon(flame)
    
    painter.end()
    
    # Save as PNG
    image.save("icon.png")
    print("Saved icon.png")
    
    # Save as ICO (Qt supports saving to .ico depending on plugins, but let's try)
    # If not, we might need PIL, but PIL failed.
    # We will rely on `image.save('icon.ico')`. 
    # If standard Qt plugins are present, it works.
    image.save("icon.ico")
    print("Saved icon.ico")

if __name__ == "__main__":
    create_icon_gen()
