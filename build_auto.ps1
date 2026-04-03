# KipoStock Build Script (Master Version)
# [v4.3.6+] 이제 버전을 수동으로 고칠 필요가 없어, 자기야! ✨

$MAIN_FILE = "Kipo_GUI_main.py"
$SPEC_FILE = "Kipo_AI_Master.spec"
$DEST_BASE = "D:\Work\Python\AutoBuy\ExeFile\KipoStockAi"

# 1. 버전 정보 자동 추출 (Kipo_GUI_main.py의 세팅된 윈도우 타이틀에서 정밀 추출)
$versionLine = Select-String -Path $MAIN_FILE -Pattern 'setWindowTitle\("KipoStock Professional Trader AI - (V[\d\.]+)'
if ($versionLine) {
    $VERSION = $versionLine.Matches.Groups[1].Value
} else {
    Write-Host "⚠️ 버전을 찾지 못했어! 기본값(V5.0.0)을 사용할게." -ForegroundColor Yellow
    $VERSION = "V5.0.0"
}

$APP_NAME = "KipoStock_AI_$VERSION"
$DEST_DIR = $DEST_BASE

Write-Host "--------------------------------------------------"
Write-Host "Build Start: $APP_NAME (Master Mode)"
Write-Host "--------------------------------------------------"

# 2. PyInstaller 실행 (마스터 스펙 고정 사용)
python -m PyInstaller --clean --noconfirm $SPEC_FILE

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "Success! Renaming and Copying to $DEST_DIR..."
    
    if (!(Test-Path $DEST_DIR)) {
        New-Item -ItemType Directory -Path $DEST_DIR -Force
    }
    
    # 3. 파일명 변경 (KipoStock_AI.exe -> KipoStock_AI_V4.3.6.exe)
    $BUILD_EXE = "dist\KipoStock_AI.exe"
    $FINAL_EXE = "dist\$APP_NAME.exe"
    
    if (Test-Path $FINAL_EXE) { Remove-Item $FINAL_EXE -Force }
    Rename-Item -Path $BUILD_EXE -NewName "$APP_NAME.exe"
    
    # 4. 배포 폴더로 복사
    Copy-Item -Path $FINAL_EXE -Destination "$DEST_DIR\$APP_NAME.exe" -Force
    
    Write-Host "Done! File copied."
    Write-Host "Location: $DEST_DIR\$APP_NAME.exe" -ForegroundColor Green
} else {
    Write-Host ""
    Write-Host "Failed... Please check errors above." -ForegroundColor Red
}
