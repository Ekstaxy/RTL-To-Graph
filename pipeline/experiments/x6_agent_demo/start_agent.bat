@echo off
rem RTL-To-Graph agent demo, one click on Windows. Needs Python 3.10+ and an Anthropic API key.
setlocal
cd /d "%~dp0"

rem 1. API key, kept in .env (never committed)
if not exist .env copy /y .env.example .env >nul
findstr /r /c:"^ANTHROPIC_API_KEY=.." .env >nul
if errorlevel 1 (
  echo.
  echo  Put your Anthropic API key after ANTHROPIC_API_KEY= in the .env file that just opened,
  echo  save it, then run start_agent.bat again.
  echo.
  notepad .env
  exit /b 1
)

rem 2. Python environment, created once
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY (
  echo Python 3 was not found. Install it from https://www.python.org/downloads/ and run this again.
  pause
  exit /b 1
)
if not exist .venv\Scripts\python.exe (
  echo Creating the Python environment...
  %PY% -m venv .venv || (pause & exit /b 1)
)
.venv\Scripts\python -m pip install -q --disable-pip-version-check anthropic || (pause & exit /b 1)

rem 3. Results of the 30 corpus designs; unpacked again whenever a pulled demo_cache.zip is newer
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$m='cache\.unpacked'; if (-not (Test-Path $m) -or (Get-Item 'demo_cache.zip').LastWriteTime -gt (Get-Item $m).LastWriteTime) {" ^
  "  Write-Host 'Unpacking demo_cache.zip ...'; if (Test-Path cache) { Remove-Item -Recurse -Force cache };" ^
  "  Expand-Archive -LiteralPath 'demo_cache.zip' -DestinationPath 'cache' -Force; Set-Content -Path $m -Value (Get-Date) }"
if errorlevel 1 (pause & exit /b 1)

rem 4. Start the server and open the page
echo Starting http://localhost:8765  (close this window to stop)
start "" /b cmd /c "timeout /t 3 >nul && start "" http://localhost:8765"
.venv\Scripts\python server.py
pause
