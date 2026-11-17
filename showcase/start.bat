@echo off
rem Unpack RTL-To-Graph-showcase.zip next to this script (again whenever the zip is newer) and open the results page.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$z='RTL-To-Graph-showcase.zip'; $d='RTL-To-Graph-showcase'; $m=Join-Path $d '.unpacked';" ^
  "if (-not (Test-Path $m) -or (Get-Item $z).LastWriteTime -gt (Get-Item $m).LastWriteTime) {" ^
  "  Write-Host 'Unpacking' $z '...';" ^
  "  if (Test-Path $d) { Remove-Item -Recurse -Force $d };" ^
  "  Expand-Archive -LiteralPath $z -DestinationPath '.' -Force;" ^
  "  Set-Content -Path $m -Value (Get-Date) }"
if errorlevel 1 (
  echo Could not unpack RTL-To-Graph-showcase.zip
  pause
  exit /b 1
)
start "" "%~dp0RTL-To-Graph-showcase\proof.html"
