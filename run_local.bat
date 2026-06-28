@echo off
setlocal enableextensions
cd /d "%~dp0"
title OCR Online - Local test server

REM ==========================================================
REM  Repo ne LOCALLY chalavo (offline check).
REM  Pinned Python + badhi requirements aa j folder na env
REM  ma install thay - system Python par dependency NAHI.
REM ==========================================================

set "PYVER=3.12"
set "PORT=8000"
set "UV_PYTHON_INSTALL_DIR=%CD%\python"
set "UV_CACHE_DIR=%CD%\.uvcache"

REM ---- 0) app.py chhe? (saachi folder ma chhe e confirm) ----
if not exist "app.py" (
    echo [ERROR] aa folder ma app.py nathi. Aa bat ne repo folder ma muko.
    goto :end
)

REM ---- 1) uv install (single tool, pre-installed Python ni jarur nahi) ----
where uv >nul 2>&1
if not errorlevel 1 goto :have_uv
echo [..] uv install kari rahyu chhu ...
winget install --id=astral-sh.uv -e --accept-source-agreements --accept-package-agreements
if not errorlevel 1 goto :have_uv
echo [..] winget na malyu - official installer thi try ...
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
:have_uv
set "PATH=%USERPROFILE%\.local\bin;%PATH%"
where uv >nul 2>&1
if errorlevel 1 (
    echo [ERROR] uv install nathi thayu. Internet check karo.
    goto :end
)

REM ---- 2) Pinned Python aa folder ma ----
echo [..] Python %PYVER% install (.\python) ...
uv python install %PYVER%
if errorlevel 1 goto :end

REM ---- 3) venv (.venv) ----
if exist ".venv\Scripts\python.exe" goto :have_venv
echo [..] .venv banavi rahyu chhu ...
uv venv --python %PYVER% .venv
if errorlevel 1 goto :end
:have_venv

REM ---- 4) requirements install (venv ma) ----
echo [..] requirements install kari rahyu chhu ...
uv pip install --python ".venv\Scripts\python.exe" -r requirements.txt
if errorlevel 1 goto :end

REM ---- 5) Tesseract check (OCR mate) ----
where tesseract >nul 2>&1
if not errorlevel 1 goto :tess_ok
if exist "C:\Program Files\Tesseract-OCR\tesseract.exe" (
    set "PATH=C:\Program Files\Tesseract-OCR;%PATH%"
    goto :tess_ok
)
echo.
echo [!] WARNING: Tesseract nathi malyu - scanned/image OCR kaam nahi kare.
echo     (Text-based PDF / Word extraction to chalse.)
echo     OCR joiye to install: https://github.com/UB-Mannheim/tesseract/wiki
echo     (Gujarati + je language joiye te pack check karjo)
echo.
:tess_ok

REM ---- 6) Server chalu + browser kholo ----
echo.
echo ==========================================================
echo  Server chalu thay chhe:  http://127.0.0.1:%PORT%
echo  Browser jate khulshe. Band karva aa window ma Ctrl+C.
echo ==========================================================
echo.
start "" http://127.0.0.1:%PORT%
".venv\Scripts\python.exe" -m uvicorn app:app --host 127.0.0.1 --port %PORT%

:end
echo.
pause
