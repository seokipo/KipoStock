import PyInstaller.__main__
import os
import shutil
import time

# KipoStock AI V5.2.1 빌드 스크립트
# "Voice Clarity": Ranking Scout 상황별 음성 접두어 고도화 패치 🔊🗣️✨

def build_kipo():
    VERSION = "V5.2.1"
    SPEC_FILE = "Kipo_AI_Master.spec"

    # PyInstaller 실행 인자 (스펙 파일 사용)
    opts = [
        SPEC_FILE,
        '--clean',
        '--noconfirm',
    ]

    print(f"KipoStock {VERSION} Build Start (Spec: {SPEC_FILE})...")
    
    try:
        # 빌드 실행
        PyInstaller.__main__.run(opts)
        
        # 결과 확인 및 정리
        original_dist_path = os.path.join("dist", "KipoStock_AI.exe")
        versioned_dist_path = os.path.join("dist", f"KipoStock_AI_{VERSION}.exe")
        
        if os.path.exists(original_dist_path):
            # 파일명에 버전 추가
            if os.path.exists(versioned_dist_path):
                os.remove(versioned_dist_path)
            os.rename(original_dist_path, versioned_dist_path)
            
            print(f"Build Success: {versioned_dist_path}")
            
            # 1. 메인 ExeFile 폴더로 복사
            exe_folder = "ExeFile"
            if not os.path.exists(exe_folder):
                os.makedirs(exe_folder)
            
            final_dest = os.path.join(exe_folder, f"KipoStock_AI_{VERSION}.exe")
            shutil.copy(versioned_dist_path, final_dest)
            print(f"Executable copied to {exe_folder} folder.")
            
            # 2. 추가 배포 경로 (D:\Work\Python\AutoBuy\ExeFile\KipoStockAi)
            extra_dest_folder = r"D:\Work\Python\AutoBuy\ExeFile\KipoStockAi"
            if not os.path.exists(extra_dest_folder):
                os.makedirs(extra_dest_folder)
            shutil.copy(versioned_dist_path, os.path.join(extra_dest_folder, f"KipoStock_AI_{VERSION}.exe"))
            print(f"Extra deployment copy complete: {extra_dest_folder}")
            
        else:
            print(f"Build Failed: {original_dist_path} not found.")
    except Exception as e:
        print(f"An error occurred during build: {e}")

if __name__ == "__main__":
    start_time = time.time()
    build_kipo()
    end_time = time.time()
    print(f"Total build time: {end_time - start_time:.2f} seconds")
