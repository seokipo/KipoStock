import os
import subprocess
import shutil
import sys

def build():
    # 1. 설정
    app_name = "KipoStock_V4.0_GOLD"
    main_script = "Kipo_GUI_main.py"
    icon_file = "icon.png"
    assets = ["settings.json", "StockAlarm.wav"]
    
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
    cmd = [
        "python", "-m", "PyInstaller",
        "--onefile",
        "--noconsole",
        "--noconfirm",
        f"--name={app_name}",
        f"--add-data={icon_file};."
    ]
    
    cmd.append(main_script)
    
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
            print(f"⚠️ 경고: 자산 파일을 찾을 수 없습니다: {asset}")

    print("\n✅ 빌드 완료!")
    output_exe = os.path.join(dist_path, f"{app_name}.exe")
    final_exe = os.path.join("..", f"{app_name}.exe")
    if os.path.exists(output_exe):
        print(f"🚚 실행 파일을 상위 폴더로 복사 중... -> {os.path.abspath(final_exe)}")
        shutil.copy(output_exe, "..")
    
    print(f"📂 결과물 확인: {os.path.abspath(dist_path)}")

if __name__ == "__main__":
    build()
