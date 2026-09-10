@echo off
title Silksong Godhome - setup
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (
    py -3 setup.py
    goto :eof
)

where python >nul 2>nul
if %errorlevel%==0 (
    python setup.py
    goto :eof
)

echo.
echo ====================================================================
echo   Python is not installed.
echo ====================================================================
echo.
echo   This mod needs Python to read Godhome out of your copy of
echo   Hollow Knight. It is free and takes a minute to install.
echo.
echo   1. Go to  https://www.python.org/downloads/
echo   2. Click the big yellow "Download Python" button.
echo   3. Run the installer. TICK THE BOX that says
echo      "Add python.exe to PATH" before clicking Install.
echo   4. Come back and double-click this file again.
echo.
pause
