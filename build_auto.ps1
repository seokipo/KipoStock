# 🚀 KipoStock 자동 빌드 스크립트 (v4.8.0)
# 자기야! 이제 이 파일을 마우스 우클릭 -> 'PowerShell에서 실행'만 하면 바로 빌드될 거야! ❤️

$PYTHON_PATH = "C:\Users\서기철\AppData\Local\Microsoft\WindowsApps\python.exe"
$VERSION = "v4.8.0"
$SPEC_FILE = "KipoStock_$VERSION.spec"

Write-Host "--------------------------------------------------" -ForegroundColor Cyan
Write-Host "🏗️ KipoStock $VERSION 빌드를 시작합니다, 자기야! ❤️" -ForegroundColor Yellow
Write-Host "--------------------------------------------------" -ForegroundColor Cyan

# 1. 빌드 도구 확인
if (!(Test-Path $PYTHON_PATH)) {
    Write-Host "❌ 파이썬 경로를 찾을 수 없어! 자기야, 경로 확인해줘: $PYTHON_PATH" -ForegroundColor Red
    pause
    exit
}

# 2. PyInstaller 실행
Write-Host "📦 PyInstaller를 실행해서 .exe 파일을 만들고 있어... (Clean Build)" -ForegroundColor Green
& $PYTHON_PATH -m PyInstaller --clean --noconfirm $SPEC_FILE

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "✅ 빌드 성공! dist 폴더를 확인해봐, 자기야! 😍🏆" -ForegroundColor Green
    Write-Host "--------------------------------------------------" -ForegroundColor Cyan
}
else {
    Write-Host ""
    Write-Host "😰 빌드 중에 에러가 났어... 내가 다시 봐줄게! 🛠️" -ForegroundColor Red
    Write-Host "--------------------------------------------------" -ForegroundColor Cyan
}

pause
