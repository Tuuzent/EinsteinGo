@echo off
setlocal
title EinsteinGo
cd /d "%~dp0"

chcp 65001 >nul
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"

echo [EinsteinGo] locating a Python interpreter with tkinter ...

rem This file is intentionally ASCII-only. Non-ASCII bytes in a .bat get parsed
rem with the OEM codepage and can be turned into bogus commands.
rem The python on PATH may lack tkinter, so probe candidates and take the first
rem one that can import it. Inside a for-block %%VAR%% is expanded at parse time,
rem so we only WRITE PYEXE there and READ it on a later line.
set "PYEXE="
for %%P in ("py -3" "py -3.13" "python" "python3") do (
    if not defined PYEXE (
        %%~P -c "import tkinter" >nul 2>nul
        if not errorlevel 1 set "PYEXE=%%~P"
    )
)

if not defined PYEXE goto :no_tk

echo [EinsteinGo] interpreter : %PYEXE%
echo [EinsteinGo] launching GUI ...
echo.

%PYEXE% run_ui.py
set "RC=%ERRORLEVEL%"

echo.
echo [EinsteinGo] exit code %RC%
if not "%RC%"=="0" echo [EinsteinGo] GUI exited abnormally, see messages above.
pause
exit /b %RC%

:no_tk
echo.
echo [EinsteinGo] ERROR: no Python interpreter with tkinter was found.
echo [EinsteinGo] tried: py -3, py -3.13, python, python3
echo.
echo How to fix:
echo   1. Install the official build from https://www.python.org/downloads/windows/
echo      Keep the optional feature "tcl/tk and IDLE" checked during setup.
echo   2. Or repair an existing install:
echo      Settings - Apps - Installed apps - Python - Modify - check "tcl/tk and IDLE"
echo.
echo Note: the Python bundled with this workspace has no tkinter on purpose.
echo.
pause
exit /b 9009
