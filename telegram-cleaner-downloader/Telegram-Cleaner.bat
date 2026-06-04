@echo off
REM ===========================================================================
REM  Telegram Cleaner - Windows launcher
REM  [1] First-time setup : create .venv and install requirements
REM  [2] Run dashboard    : start the Flask app and open the browser
REM ===========================================================================
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
title Telegram Cleaner

set "VENV_DIR=.venv"
set "VPY=%VENV_DIR%\Scripts\python.exe"
set "URL=http://127.0.0.1:5000"

:menu
cls
echo(
echo   ============================================================
echo               T E L E G R A M   C L E A N E R
echo   ============================================================
echo(
echo     [1]   First-time setup   (create .venv + install packages)
echo     [2]   Run dashboard
echo     [3]   Exit
echo(
if exist "%VPY%" (
    echo     status: virtual environment found ^(setup done^)
) else (
    echo     status: not set up yet  -^>  run option 1 first
)
echo(
set "choice="
set /p "choice=  Select an option [1/2/3]: "
if "%choice%"=="1" goto setup
if "%choice%"=="2" goto run
if "%choice%"=="3" goto end
goto menu


REM ---------------------------------------------------------------------------
:setup
cls
echo   ------------------------------------------------------------
echo    FIRST-TIME SETUP
echo   ------------------------------------------------------------
echo(
call :detect_python
if not defined PYCMD goto no_python

echo   Using Python:
%PYCMD% --version
echo(

REM require Python 3.8 or newer
%PYCMD% -c "import sys; raise SystemExit(0 if sys.version_info[:2]>=(3,8) else 1)"
if errorlevel 1 goto old_python

if exist "%VPY%" (
    echo   Virtual environment already exists - reusing it.
) else (
    echo   Creating virtual environment in "%VENV_DIR%" ...
    %PYCMD% -m venv "%VENV_DIR%"
    if errorlevel 1 goto venv_fail
)

echo(
echo   Upgrading pip ...
"%VPY%" -m pip install --upgrade pip >nul 2>&1

echo   Installing requirements ...
"%VPY%" -m pip install -r requirements.txt
if errorlevel 1 goto pip_fail

if not exist ".env" (
    if exist ".env.example" (
        copy /y ".env.example" ".env" >nul
        echo(
        echo   A .env file was created from the template.
        echo   >>> Open .env and fill in API_ID, API_HASH and PHONE
        echo       ^(get them from https://my.telegram.org^).
    )
)

echo(
echo   ------------------------------------------------------------
echo    SETUP COMPLETE. Use option 2 to run the dashboard.
echo   ------------------------------------------------------------
echo(
pause
goto menu


REM ---------------------------------------------------------------------------
:run
cls
echo   ------------------------------------------------------------
echo    RUN DASHBOARD
echo   ------------------------------------------------------------
echo(
if not exist "%VPY%" (
    echo   No virtual environment found.
    echo   Please run option 1 ^(First-time setup^) first.
    echo(
    pause
    goto menu
)
if not exist ".env" (
    echo   No .env file found - the app needs your credentials.
    echo   Run option 1, then edit the .env file before running.
    echo(
    pause
    goto menu
)

echo   Starting the dashboard at %URL%
echo   The browser will open automatically in a few seconds.
echo(
echo   Keep this window open while you use the app.
echo   Press Ctrl+C here to stop the server.
echo(

REM open the browser shortly after the server has had time to start
start "" /b powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 3; Start-Process '%URL%'" >nul 2>&1

"%VPY%" app.py

echo(
echo   Server stopped.
pause
goto menu


REM ---------------------------------------------------------------------------
REM  Detect a usable Python interpreter into PYCMD.
REM  Order: py launcher -> python -> python3 -> versioned install folders.
REM ---------------------------------------------------------------------------
:detect_python
set "PYCMD="

py -3 -c "import sys" >nul 2>&1
if not errorlevel 1 (
    set "PYCMD=py -3"
    goto :eof
)

where python >nul 2>&1
if not errorlevel 1 (
    python -c "import sys" >nul 2>&1
    if not errorlevel 1 (
        set "PYCMD=python"
        goto :eof
    )
)

where python3 >nul 2>&1
if not errorlevel 1 (
    python3 -c "import sys" >nul 2>&1
    if not errorlevel 1 (
        set "PYCMD=python3"
        goto :eof
    )
)

REM search common install roots for a Python3xx folder containing python.exe
for %%R in (
    "%LocalAppData%\Programs\Python"
    "%ProgramFiles%"
    "%ProgramFiles(x86)%"
    "%SystemDrive%\"
) do (
    if exist "%%~R" (
        for /d %%P in ("%%~R\Python*") do (
            if exist "%%~P\python.exe" (
                "%%~P\python.exe" -c "import sys" >nul 2>&1
                if not errorlevel 1 set "PYCMD="%%~P\python.exe""
            )
        )
    )
)
goto :eof


REM ---------------------------------------------------------------------------
:no_python
echo   ------------------------------------------------------------
echo    PYTHON NOT FOUND
echo   ------------------------------------------------------------
echo(
echo   Python does not appear to be installed (or it is the
echo   Microsoft Store placeholder, which will not work).
echo(
echo   Please install Python 3.8 or newer:
echo       https://www.python.org/downloads/windows/
echo(
echo   IMPORTANT: on the first installer screen, tick
echo       [x] Add python.exe to PATH
echo(
echo   Then restart this launcher and choose option 1 again.
echo(
pause
goto menu

:old_python
echo(
echo   The Python found is too old. Version 3.8 or newer is required.
echo   Please install a newer Python from:
echo       https://www.python.org/downloads/windows/
echo(
pause
goto menu

:venv_fail
echo(
echo   Failed to create the virtual environment.
echo   Make sure your Python install includes the "venv" module.
echo(
pause
goto menu

:pip_fail
echo(
echo   Installing requirements failed.
echo   Check your internet connection / proxy and try again.
echo   If you are behind a corporate proxy, set HTTPS_PROXY first.
echo(
pause
goto menu

:end
endlocal
exit /b 0
