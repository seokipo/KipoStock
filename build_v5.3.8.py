# build_v5.3.8.py
import os
import shutil
import subprocess
import time

VERSION = "V5.3.8"

def build():
    print(f"KipoStock {VERSION} Build Start (Spec: Kipo_AI_Master.spec)...")
    start_time = time.time()

    try:
        subprocess.run(["python", "-m", "PyInstaller", "--noconfirm", "Kipo_AI_Master.spec"], check=True)
        
        dist_path = os.path.join("dist", "KipoStock_AI.exe")
        versioned_dist_path = os.path.join("dist", f"KipoStock_AI_{VERSION}.exe")
        
        if os.path.exists(dist_path):
            if os.path.exists(versioned_dist_path):
                os.remove(versioned_dist_path)
            os.rename(dist_path, versioned_dist_path)
            print(f"Build Success: {versioned_dist_path}")
            
            exe_folder = "ExeFile"
            if not os.path.exists(exe_folder):
                os.makedirs(exe_folder)
            
            final_dest = os.path.join(exe_folder, f"KipoStock_AI_{VERSION}.exe")
            shutil.copy(versioned_dist_path, final_dest)
            print(f"Executable copied to {exe_folder} folder.")
            
            extra_dest_folder = r"D:\Work\Python\AutoBuy\ExeFile\KipoStockAi"
            if os.path.exists(extra_dest_folder):
                try:
                    shutil.copy(versioned_dist_path, os.path.join(extra_dest_folder, f"KipoStock_AI_{VERSION}.exe"))
                    print(f"Deployment successful to: {extra_dest_folder}")
                except Exception as e:
                    print(f"External deployment failed: {e}")

            end_time = time.time()
            print(f"Total build time: {round(end_time - start_time, 2)} seconds")
        else:
            print("Error: Executable not found in dist folder.")

    except Exception as e:
        print(f"An error occurred during build: {e}")

if __name__ == "__main__":
    build()
