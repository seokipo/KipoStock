from PIL import Image
import os

def convert_png_to_ico(png_path, ico_path):
    try:
        if not os.path.exists(png_path):
            print(f"Error: {png_path} not found.")
            return
        
        img = Image.open(png_path)
        # 여러 사이즈를 포함하여 탐색기에서도 선명하게 보이도록 함
        icon_sizes = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
        img.save(ico_path, format='ICO', sizes=icon_sizes)
        print(f"Successfully converted {png_path} to {ico_path}")
    except Exception as e:
        print(f"Failed to convert: {e}")

if __name__ == "__main__":
    convert_png_to_ico("kipo_yellow.png", "kipo_yellow.ico")
