@echo off
rem Start the RTL-To-Graph agent demo inside WSL and open it in the browser.
cd /d "%~dp0"
for /f "delims=" %%p in ('wsl wslpath -a "%~dp0."') do set WDIR=%%p
start "" /b cmd /c "timeout /t 4 >nul && start "" http://localhost:8765"
wsl -e bash -lc "cd '%WDIR%' && tr -d '\r' < start_demo.sh > /tmp/x5_start_demo.sh && bash /tmp/x5_start_demo.sh"
