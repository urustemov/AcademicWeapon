@echo off
setlocal
cd /d "%~dp0"
echo =================================================
echo  Academic Weapon - AUCA Academic Advising Center (LOCAL DEMO)
echo =================================================
echo.
where py >nul 2>nul
if %errorlevel%==0 (
  set "PYCMD=py -3"
) else (
  where python >nul 2>nul
  if errorlevel 1 (
    echo Python is not installed. Install Python 3.11 or later from python.org.
    echo Re-open this file after installation.
    pause
    exit /b 1
  )
  set "PYCMD=python"
)
if not exist ".venv\Scripts\python.exe" (
  echo Creating Python virtual environment...
  %PYCMD% -m venv .venv
  if errorlevel 1 (echo Could not create environment. & pause & exit /b 1)
)
if not exist ".apss_deps_ready" (
  echo Installing required Python packages for the first time...
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 (echo Could not install packages. Check internet and try again. & pause & exit /b 1)
  echo ready>".apss_deps_ready"
)
echo.
echo Ready! Open http://127.0.0.1:8000 in a browser.
echo This app binds to your computer only, not your network.
echo Keep this window open while using Academic Weapon.
echo Close this window to stop the server.
echo.
start "" "http://127.0.0.1:8000"
".venv\Scripts\python.exe" app.py
pause
