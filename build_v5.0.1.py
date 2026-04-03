import PyInstaller.__main__
import os
import shutil

# KipoStock AI V5.0.1 빌드 스크립트
# 시초가 베팅 엔진 버그 수정 및 최적화 버전! ✨🚀

def build_kipo():
    VERSION = "V5.0.1"

    target_file = "Kipo_GUI_main.py"

    # PyInstaller 실행 인자
    opts = [
        target_file,
        '--windowed',
        '--onefile',
        f'--name=KipoStock_AI_{VERSION}',
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
        dist_path = os.path.join("dist", f"KipoStock_AI_{VERSION}.exe")
        if os.path.exists(dist_path):
            print(f"✅ 빌드 성공: {dist_path}")
            exe_folder = "ExeFile"
            if not os.path.exists(exe_folder):
                os.makedirs(exe_folder)
            
            final_dest = os.path.join(exe_folder, f"KipoStock_AI_{VERSION}.exe")
            shutil.copy(dist_path, os.path.join(exe_folder, f"KipoStock_AI_{VERSION}.exe"))
            print(f"📂 실행 파일이 {exe_folder} 폴더로 복사되었습니다.")
            
            # [신규] 사용자 요청 추가 배포 경로
            extra_dest_folder = r"D:\Work\Python\AutoBuy\ExeFile\KipoStockAi"
            if not os.path.exists(extra_dest_folder):
                os.makedirs(extra_dest_folder)
            shutil.copy(dist_path, os.path.join(extra_dest_folder, f"KipoStock_AI_{VERSION}.exe"))
            print(f"📂 추가 배포 경로로 복사 완료: {extra_dest_folder}")
        else:
            print("❌ 빌드 실패: dist 폴더에 결과물이 없습니다.")
    except Exception as e:
        print(f"❌ 빌드 중 오류 발생: {e}")

if __name__ == "__main__":
    build_kipo()
