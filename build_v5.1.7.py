import PyInstaller.__main__
import os
import shutil
import time

# KipoStock AI V5.1.7 빌드 스크립트
# [V5.1.7] 시초가 베팅 엔진 무결성 강화 및 실시간 감시 연동 버전 🚀✨

def build_kipo():
    VERSION = "V5.1.7"
    SPEC_FILE = "Kipo_AI_Master.spec"

    # PyInstaller 실행 인자 (스펙 파일 사용)
    opts = [
        SPEC_FILE,
        '--clean',
        '--noconfirm',
    ]

    print(f"🚀 KipoStock {VERSION} 빌드 시작 (Spec: {SPEC_FILE})...")
    
    try:
        # 빌드 실행
        PyInstaller.__main__.run(opts)
        
        # 결과 확인 및 정리
        # 스펙 파일 내 name='KipoStock_AI' 로 설정되어 있으므로 기본 출력은 KipoStock_AI.exe
        original_dist_path = os.path.join("dist", "KipoStock_AI.exe")
        versioned_dist_path = os.path.join("dist", f"KipoStock_AI_{VERSION}.exe")
        
        if os.path.exists(original_dist_path):
            # 파일명에 버전 추가
            if os.path.exists(versioned_dist_path):
                os.remove(versioned_dist_path)
            os.rename(original_dist_path, versioned_dist_path)
            
            print(f"✅ 빌드 성공: {versioned_dist_path}")
            
            # 1. 메인 ExeFile 폴더로 복사
            exe_folder = "ExeFile"
            if not os.path.exists(exe_folder):
                os.makedirs(exe_folder)
            
            final_dest = os.path.join(exe_folder, f"KipoStock_AI_{VERSION}.exe")
            shutil.copy(versioned_dist_path, final_dest)
            print(f"📂 실행 파일이 {exe_folder} 폴더로 복사되었습니다.")
            
            # 2. 추가 배포 경로 (D:\Work\Python\AutoBuy\ExeFile\KipoStockAi)
            extra_dest_folder = r"D:\Work\Python\AutoBuy\ExeFile\KipoStockAi"
            if not os.path.exists(extra_dest_folder):
                os.makedirs(extra_dest_folder)
            
            extra_final_dest = os.path.join(extra_dest_folder, f"KipoStock_AI_{VERSION}.exe")
            shutil.copy(versioned_dist_path, extra_final_dest)
            print(f"📂 추가 배포 경로로 복사 완료: {extra_dest_folder}")
            
        else:
            print(f"❌ 빌드 실패: {original_dist_path} 파일을 찾을 수 없습니다.")
    except Exception as e:
        print(f"❌ 빌드 중 오류 발생: {e}")

if __name__ == "__main__":
    start_time = time.time()
    build_kipo()
    end_time = time.time()
    print(f"⏱️ 총 빌드 소요 시간: {end_time - start_time:.2f}초")
