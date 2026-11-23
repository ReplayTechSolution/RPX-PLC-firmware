# Compila RPX-PLC-Flasher.exe (un unico file, nessuna installazione):  .\build.ps1
Set-Location $PSScriptRoot
# licenze nell'eseguibile: GPL v2 e avvisi dei componenti inclusi (generati da tools/third_party.py)
# (nel progetto completo LICENZE.txt si rigenera; nel sorgente pubblicato è già presente)
if (Test-Path ..\third_party.py) {
    & py -3 ..\third_party.py
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    Copy-Item ..\..\licenze\LICENZE-TERZE-PARTI-FLASHER.txt LICENZE.txt
}
Copy-Item COPYING.txt assets\COPYING.txt
Copy-Item LICENZE.txt assets\LICENZE.txt
py -3 -m PyInstaller --noconfirm --onefile --windowed --name RPX-PLC-Flasher --icon assets/app.ico --add-data "assets;assets" --collect-all esptool rpx_flasher.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
# controllo: esptool e immagini inclusi nell'eseguibile
$env:RPX_FLASHER_SELFTEST = "$PWD\selftest.txt"
Start-Process -FilePath dist\RPX-PLC-Flasher.exe -Wait
$r = Get-Content selftest.txt -Raw
Remove-Item Env:\RPX_FLASHER_SELFTEST
Write-Output $r
if (-not $r.StartsWith('OK')) { exit 1 }
