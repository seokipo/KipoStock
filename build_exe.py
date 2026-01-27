"""
Python 파일을 exe로 변환하는 스크립트
"""

import subprocess
import sys
import os
import shutil  # 파일 복사를 위해 추가

def build_exe(script_name, exe_name=None, use_console=False, options=None):
    if options is None:
        options = []
    
    # 기본 옵션
    base_options = [
        '--onefile',
        '--noconfirm', # 덮어쓰기 확인 안 함
    ]

    if use_console:
        base_options.append('--console') # 콘솔창 표시
    else:
        base_options.append('--noconsole') # GUI 모드 (콘솔창 숨김)

    if exe_name:
         base_options.extend(['--name', exe_name])

    # script_name이 마지막에 와야 함
    cmd = [sys.executable, '-m', 'PyInstaller'] + base_options + options + ['--add-data', 'icon.ico;.', '--icon=icon.ico'] + [script_name]
    
    print(f"빌드 시작: {script_name} -> {exe_name if exe_name else 'default'}")
    
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        print(f"✅ 빌드 완료! dist 폴더를 확인하세요.")
        
        # ---------------------------------------------------------
        # [추가] 필수 파일 자동 복사 기능
        # ---------------------------------------------------------
        target_dir = 'dist'
        if not os.path.exists(target_dir):
            os.makedirs(target_dir)

        for filename in ['settings.json', 'icon.ico', 'icon.png']:
            if os.path.exists(filename):
                shutil.copy(filename, os.path.join(target_dir, filename))
                print(f"📂 {filename} 파일을 {target_dir} 폴더로 복사했습니다.")
        # ---------------------------------------------------------
        
        return True
    except subprocess.CalledProcessError as e:
        print(f"\n❌ 빌드 실패:")
        print(e.stderr)
        return False

if __name__ == '__main__':
    # (스크립트 파일명, 실행파일 이름, 콘솔사용여부)
    scripts = [
        ('Kipo_GUI_main.py', 'KipoStock_V5.4.9_Auto', False),
        # ('Kipo_main.py', 'KipoStock_Console_V1.2', True),
    ]
    
    for script, exe_name, use_console in scripts:
        if not os.path.exists(script):
            print(f"⚠️ 파일을 찾을 수 없습니다: {script}")
            continue
        
        print(f"\n{'='*50}")
        build_exe(script, exe_name=exe_name, use_console=use_console)
        print(f"{'='*50}\n")