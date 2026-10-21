@echo off
setlocal
cd /d "%~dp0"
echo WARNING: This will delete all Academic Weapon demo changes on this computer.
echo Stop Academic Weapon before continuing.
choice /M "Reset database to initial synthetic test records"
if errorlevel 2 exit /b 0
if exist "apss_demo.sqlite3" del /q "apss_demo.sqlite3"
echo Done. Restart Academic Weapon to recreate the demo database.
pause
