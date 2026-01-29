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
    cmd = [sys.executable, '-m', 'PyInstaller'] + base_options + options + ['--add-data', 'kipo_yellow.ico;.', '--icon=kipo_yellow.ico'] + [script_name]
    
    print(f"빌드 시작: {script_name} -> {exe_name if exe_name else 'default'}")
    
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        print(f"✅ 빌드 완료! dist 폴더를 확인하세요.")
        
        # ---------------------------------------------------------
        # [추가] 필수 파일 자동 복사 기능 (dist 및 상위 KipoStock_V5.4 폴더)
        # ---------------------------------------------------------
        target_dirs = ['dist', '../KipoStock_Lite_V1.0']
        
        for t_dir in target_dirs:
            if not os.path.exists(t_dir):
                try: os.makedirs(t_dir)
                except: pass

            # 1. 실행 파일 복사
            if exe_name:
                final_exe = f"{exe_name}.exe"
                src_exe = os.path.abspath(os.path.join('dist', final_exe))
                dst_exe = os.path.abspath(os.path.join(t_dir, final_exe))
                if os.path.exists(src_exe) and src_exe != dst_exe:
                    shutil.copy(src_exe, dst_exe)
                    print(f"🚀 {final_exe}를 {t_dir} 폴더로 복사했습니다.")

            # 2. 리소스 파일 복사
            for filename in ['settings.json', 'kipo_yellow.ico', 'kipo_yellow.png']:
                if os.path.exists(filename):
                    src_res = os.path.abspath(filename)
                    dst_res = os.path.abspath(os.path.join(t_dir, filename))
                    # settings.json의 경우 이미 존재하면 덮어쓰지 않음 (사용자 데이터 보호)
                    if filename == 'settings.json' and os.path.exists(dst_res):
                        print(f"ℹ️ {t_dir}에 {filename} 파일이 이미 존재하여 기존 데이터를 유지합니다.")
                        continue
                    if src_res != dst_res:
                        shutil.copy(src_res, dst_res)
                        print(f"📂 {filename} 파일을 {t_dir} 폴더로 복사했습니다.")
        # ---------------------------------------------------------
        
        return True
    except subprocess.CalledProcessError as e:
        print(f"\n❌ 빌드 실패:")
        print(e.stderr)
        return False

if __name__ == '__main__':
    # (스크립트 파일명, 실행파일 이름, 콘솔사용여부)
    scripts = [
        ('Kipo_GUI_main.py', 'KipoStock_Lite_V1_GOLD', False),
        # ('Kipo_main.py', 'KipoStock_Console_V1.2', True),
    ]
    
    for script, exe_name, use_console in scripts:
        if not os.path.exists(script):
            print(f"⚠️ 파일을 찾을 수 없습니다: {script}")
            continue
        
        print(f"\n{'='*50}")
        build_exe(script, exe_name=exe_name, use_console=use_console)
        print(f"{'='*50}\n")