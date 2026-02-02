from PIL import Image, ImageDraw

def create_rocket_icon(path):
    size = (256, 256)
    # Transparent background
    img = Image.new('RGBA', size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 1. Circle Background (Blue Gradient-ish or Solid)
    # Let's do a solid nice blue
    blue_color = (0, 123, 255, 255) # #007bff
    draw.ellipse([10, 10, 246, 246], fill=blue_color)

    # 2. Rocket / Arrow Shape (White)
    # Simple sleek arrow pointing up-right
    arrow_color = (255, 255, 255, 255)
    
    # Body of rocket/arrow
    # Points: (Tip, RightWing, CenterBase, LeftWing)
    # Tip: (180, 76) - rough coordinate for up-right
    # Let's simple polygon
    
    # Triangle pointing top-right
    # Tip at (190, 66)
    # Base center around (66, 190)
    
    coords = [
        (190, 60),  # Tip
        (140, 140), # Right wing notch
        (60, 190),  # Bottom Left Base
        (110, 110)  # Left wing notch (inner)
    ]
    # Actually let's draw a simple "Paper Plane" / "Rocket" shape
    #  /\
    # /  \
    # \  /
    #  \/
    
    rocket_coords = [
        (128, 50),   # Top Tip
        (170, 180),  # Right Wing Bottom
        (128, 150),  # Center indentation
        (86, 180)    # Left Wing Bottom
    ]
    # But user wants "Stock" feel, maybe a chart arrow?
    # Let's do a Rocket taking off diagonally
    
    # Tip (top-right)
    tip = (200, 56)
    # Tail (bottom-left)
    tail = (56, 200)
    
    rocket_poly = [
        tip,                # Tip
        (150, 180),         # Right wing
        tail,               # Base
        (80, 110)           # Left wing
    ]
    
    draw.polygon(rocket_poly, fill=arrow_color)
    
    # Add a small window (blue dot)
    center_x = (tip[0] + tail[0]) // 2
    center_y = (tip[1] + tail[1]) // 2
    draw.ellipse([center_x-10, center_y-10, center_x+10, center_y+10], fill=blue_color)

    img.save(path)
    print(f"Icon saved to {path}")

if __name__ == "__main__":
    create_rocket_icon("d:/Work/Python/AutoBuy/KipoBuy_Gui/icon.png")
