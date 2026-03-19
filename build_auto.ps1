# KipoStock Build Script (V3.0.7)
$VERSION = "V3.0.7"
$SPEC_FILE = "KipoStock_AI_$VERSION.spec"
$DEST_DIR = "D:\Work\Python\AutoBuy\ExeFile\KipoStockAi"

Write-Host "--------------------------------------------------"
Write-Host "Build Start: KipoStock AI $VERSION"
Write-Host "--------------------------------------------------"

# PyInstaller 실행
python -m PyInstaller --clean --noconfirm $SPEC_FILE

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "Success! Copying to $DEST_DIR..."
    
    if (!(Test-Path $DEST_DIR)) {
        New-Item -ItemType Directory -Path $DEST_DIR -Force
    }
    
    Copy-Item -Path "dist\KipoStock_AI_$VERSION.exe" -Destination "$DEST_DIR\KipoStock_AI_$VERSION.exe" -Force
    
    Write-Host "Done! File copied."
} else {
    Write-Host ""
    Write-Host "Failed... Please check errors above."
}
