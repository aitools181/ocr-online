@echo off
setlocal enableextensions
cd /d "%~dp0"
title Push "OCR Online" to GitHub

echo ============================================================
echo   OCR Online  -^>  GitHub push
echo   Folder: %cd%
echo ============================================================
echo.

REM ---- 1) git check ----
where git >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Git install nathi malyu.
    echo         Install: https://git-scm.com/download/win
    goto :end
)

REM ---- 2) .gitignore ----
if not exist ".gitignore" (
    >  .gitignore echo __pycache__/
    >> .gitignore echo *.pyc
    >> .gitignore echo jobs/
    >> .gitignore echo .venv/
    >> .gitignore echo venv/
    >> .gitignore echo .env
    >> .gitignore echo .DS_Store
    echo [ok] .gitignore banavyu.
)

REM ---- 3) git init ----
if not exist ".git" (
    git init
    git branch -M main
    echo [ok] git initialized.
)

REM ---- 4) git identity (naam + email) ek vakhat ----
git config user.email >nul 2>&1
if errorlevel 1 goto :set_identity
git config user.name >nul 2>&1
if errorlevel 1 goto :set_identity
goto :have_identity

:set_identity
echo.
echo Git identity set nathi - ek vakhat set karvi pade (commit mate).
set /p "GEMAIL=Tamaru email: "
set /p "GNAME=Tamaru naam: "
git config --global user.email "%GEMAIL%"
git config --global user.name "%GNAME%"
echo [ok] identity set thai gayi.
echo.

:have_identity

REM ---- 5) commit message ----
set "MSG=Update OCR Online"
set /p "MSG=Commit message [%MSG%]: "

echo.
echo [..] Staging files...
git add -A

echo [..] Committing...
git commit -m "%MSG%"
echo [info] (Jo "nothing to commit" aave to vandho nahi - already committed chhe.)
echo.

REM ---- 6) remote set chhe? ----
git remote get-url origin >nul 2>&1
if errorlevel 1 goto :setup_remote
goto :do_push

:setup_remote
echo Repository hju GitHub sathe link nathi.
set /p "GHREPO=Repository name (e.g. ocr-online): "
where gh >nul 2>&1
if errorlevel 1 goto :manual_remote

echo [ok] GitHub CLI malyu - repo banavi ne push karu chhu...
set "VIS=public"
set /p "VIS=Public ke private? [public]: "
gh repo create "%GHREPO%" --%VIS% --source=. --remote=origin --push
if errorlevel 1 goto :end
echo.
echo [ok] Repo banyu ane push thai gayu.
goto :end

:manual_remote
set /p "GHUSER=GitHub username: "
git remote add origin https://github.com/%GHUSER%/%GHREPO%.git
echo [ok] remote set: https://github.com/%GHUSER%/%GHREPO%.git
echo.
echo [!] GitHub par "%GHREPO%" naam nu KHALI repo pehla banavo:
echo     https://github.com/new   (README/gitignore add karya VAGAR)
echo.
echo     Repo banaya pachhi koi pan key dabavo...
pause >nul

:do_push
echo.
echo [..] Pushing to GitHub...
echo      (Password puchhe to: Personal Access Token nakho, GitHub password nahi)
git push -u origin main
if errorlevel 1 goto :pushfail
echo.
echo [ok] Push success! GitHub par repo check karo.
goto :end

:pushfail
echo.
echo [ERROR] Push fail thayu. Sambhav kaaran:
echo   - GitHub par repo banavyu nathi (https://github.com/new - khali repo)
echo   - Authentication: password ni jagya e Personal Access Token joiye
echo     GitHub ^> Settings ^> Developer settings ^> Personal access tokens
echo     ^> Tokens (classic) ^> 'repo' scope select ^> Generate ^> token paste
echo.

:end
echo.
echo ============================================================
echo  Window band karva koi pan key dabavo.
echo ============================================================
pause >nul
