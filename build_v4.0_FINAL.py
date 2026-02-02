import os
import subprocess
import shutil
import sys

def build():
    # 1. 설정
    app_name = "KipoStock_V4.0_GOLD"
    main_script = "Kipo_GUI_main.py"
    icon_file = "icon.ico"
    # assets: EXE와 같은 폴더에 있어야 하는 파일들
    assets = ["settings.json", "StockAlarm.wav", "stock_conditions.json"]
    
    print(f"🚀 빌드 시작: {app_name}")
    
    # 2. 정리
    for folder in ["build", "dist"]:
        if os.path.exists(folder):
            print(f"🧹 {folder} 폴더 삭제 중...")
            shutil.rmtree(folder)
            
    spec_file = f"{app_name}.spec"
    if os.path.exists(spec_file):
        os.remove(spec_file)

    # 3. PyInstaller 실행
    # --hidden-import=pandas 를 추가하여 안전하게 빌드
    cmd = [
        "python", "-m", "PyInstaller",
        "--onefile",
        "--noconsole",
        "--noconfirm",
        f"--name={app_name}",
        f"--icon={icon_file}",
        "--add-data=icon.ico;.",
        "--hidden-import=pandas",
        "--hidden-import=requests",
        "--hidden-import=websockets",
        main_script
    ]
    
    print(f"📦 PyInstaller 실행 중: {' '.join(cmd)}")
    result = subprocess.run(cmd)
    
    if result.returncode != 0:
        print("❌ 빌드 실패!")
        return

    # 4. 자산 복사
    dist_path = os.path.join("dist")
    for asset in assets:
        if os.path.exists(asset):
            print(f"📄 자산 복사 중: {asset} -> {dist_path}")
            shutil.copy(asset, dist_path)
        else:
            print(f"ℹ️ 참고: 자산 파일이 현재 없습니다 (정상일 수 있음): {asset}")

    print("\n✅ 빌드 완료!")
    output_exe = os.path.join(dist_path, f"{app_name}.exe")
    
    # 상위 폴더로 복사 시도
    try:
        shutil.copy(output_exe, "..")
        print(f"🚚 실행 파일을 상위 폴더로 복사했습니다: {os.path.abspath(os.path.join('..', f'{app_name}.exe'))}")
    except Exception as e:
        print(f"⚠️ 상위 폴더 복사 실패 (사용 중일 수 있음): {e}")
    
    print(f"📂 결과물 확인: {os.path.abspath(dist_path)}")

if __name__ == "__main__":
    build()
