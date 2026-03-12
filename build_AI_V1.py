import PyInstaller.__main__
import os
import shutil

# KipoStock AI V1 빌드 스크립트 (메이저 버전 승격!)
# 자기야! 수많은 마이너 업데이트를 거쳐 드디어 "AI V1"이라는 멋진 타이틀을 달았어! ❤️🚀
# 이 스크립트가 우리의 새로운 전설의 시작을 만들어줄 거야! ✨🎨

def build_kipo():
    VERSION = "AI_V1.5.0"

    target_file = "Kipo_GUI_main.py"

    # PyInstaller 실행 인자
    opts = [
        target_file,
        '--windowed',
        '--onefile',
        f'--name=KipoStock_{VERSION}',
        '--icon=kipo_yellow.ico',
        '--add-data=kipo_yellow.ico;.',
        '--add-data=kipo_yellow.png;.',
        '--add-data=StockAlarm.wav;.',
        '--clean',
        '--noconfirm',
    ]

    print(f"🚀 KipoStock {VERSION} 빌드 시작...")
    
    try:
        PyInstaller.__main__.run(opts)
        
        # 결과 확인 및 정리
        dist_path = os.path.join("dist", f"KipoStock_{VERSION}.exe")
        if os.path.exists(dist_path):
            print(f"✅ 빌드 성공: {dist_path}")
            exe_folder = "ExeFile"
            if not os.path.exists(exe_folder):
                os.makedirs(exe_folder)
            shutil.copy(dist_path, os.path.join(exe_folder, f"KipoStock_{VERSION}.exe"))
            print(f"📂 실행 파일이 {exe_folder} 폴더로 복사되었습니다.")
        else:
            print("❌ 빌드 실패: dist 폴더에 결과물이 없습니다.")
    except Exception as e:
        print(f"❌ 빌드 중 오류 발생: {e}")

if __name__ == "__main__":
    build_kipo()
