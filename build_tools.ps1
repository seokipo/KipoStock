# 🔨 KipoStock 분석 도구 전용 빌드 스크립트 (v4.8.8)
# 자기야! 안정성을 위해 빌드 중간에 충분한 휴식 시간을 넣었어! ❤️

$PYTHON_EXE = Join-Path $env:LOCALAPPDATA "Microsoft\WindowsApps\python.exe"
$DIST_DIR = Join-Path $PSScriptRoot "dist_tools"
$BUILD_DIR = Join-Path $PSScriptRoot "build_temp"

# 1. 환경 준비 (폴더 정리)
if (Test-Path $DIST_DIR) { Remove-Item -Recurse -Force $DIST_DIR; Start-Sleep -Seconds 2 }
if (Test-Path $BUILD_DIR) { Remove-Item -Recurse -Force $BUILD_DIR; Start-Sleep -Seconds 2 }
New-Item -ItemType Directory -Force $DIST_DIR

Write-Host "--------------------------------------------------" -ForegroundColor Cyan
Write-Host "🧱 분석 도구 EXE 빌드를 시작할게, 자기야! ❤️" -ForegroundColor Yellow
Write-Host "--------------------------------------------------" -ForegroundColor Cyan

# 2. strategy_performance.py 빌드 (당분간 제외)
# Write-Host "🚀 [1/2] 성과 분석기(PerformanceAnalyst.exe) 빌드 중..." -ForegroundColor Green
# & $PYTHON_EXE -m PyInstaller --clean --onefile --distpath $DIST_DIR --workpath $BUILD_DIR --name "PerformanceAnalyst" `
#     --hidden-import "pandas" --hidden-import "matplotlib" --hidden-import "numpy" `
#     "strategy_performance.py"

# Write-Host "`n☕ 첫 번째 빌드 완료! 잠시만 웅크리고 있을게 (5초 대기)..." -ForegroundColor Cyan
# Start-Sleep -Seconds 5

# 3. research_fireup.py 빌드 (당분간 제외)
# Write-Host "🚀 [2/2] AI 리서치(FireupResearch.exe) 빌드 중..." -ForegroundColor Green
# & $PYTHON_EXE -m PyInstaller --clean --onefile --distpath $DIST_DIR --workpath $BUILD_DIR --name "FireupResearch" `
#     --hidden-import "google.genai" --hidden-import "pydantic" `
#     "research_fireup.py"

# Write-Host "`n☕ 두 번째 빌드 완료! 잠시만 웅크리고 있을게 (5초 대기)..." -ForegroundColor Cyan
# Start-Sleep -Seconds 5

# 3-1. news_sniper.py 단독 실행 파일 빌드 (당분간 제외)
# Write-Host "🚀 [New] AI 뉴스 스나이퍼(NewsSniper.exe) 단독 프로그램 빌드 중..." -ForegroundColor Green
# & $PYTHON_EXE -m PyInstaller --clean --onefile --distpath $DIST_DIR --workpath $BUILD_DIR --name "NewsSniper" `
#     --hidden-import "google.genai" --hidden-import "bs4" --hidden-import "requests" `
#     "news_sniper.py"
# 
# Write-Host "`n☕ 뉴스 스나이퍼 빌드 완료! 잠시만 웅크리고 있을게 (2초 대기)..." -ForegroundColor Cyan
# Start-Sleep -Seconds 2

Write-Host "🚀 [3/3] KipoStock 메인 엔진(KipoStock_v5.1.exe) 빌드 중..." -ForegroundColor Green
& $PYTHON_EXE -m PyInstaller --clean --onefile -w -i "kipo_yellow.ico" --distpath $DIST_DIR --workpath $BUILD_DIR --name "KipoStock_v5.1" `
    --hidden-import "PyQt6" --hidden-import "matplotlib" --hidden-import "requests" `
    --hidden-import "google.genai" --hidden-import "pydantic" `
    --hidden-import "matplotlib.backends.backend_qt5agg" `
    --hidden-import "matplotlib.backends.backend_qtagg" `
    "Kipo_GUI_main.py"

Write-Host "`n--------------------------------------------------" -ForegroundColor Cyan
Write-Host "✅ 모든 빌드 완벽하게 종료!! dist_tools 폴더를 확인해줘, 자기야! 🎉" -ForegroundColor Yellow
Write-Host "--------------------------------------------------" -ForegroundColor Cyan

