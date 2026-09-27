@echo off
setlocal enabledelayedexpansion
title HoopsMatic - matchup check round

REM ---------------------------------------------------------------------
REM ONE CHECK ROUND. Double-click it, wait for Notepad, paste the whole
REM file to Claude. It never waits for a keypress.
REM
REM   1. Downloads the latest build\*.py and build\*.bat from the
REM      fetcher-dev branch on GitHub - the list is build/fetcher-files.txt
REM      on that branch - and says which ones changed. All or nothing: if
REM      any download fails, no file is replaced.
REM   2. Runs build\check_runner.py, which runs verify-matchup-fetch.bat
REM      and, if that fails, the read-only investigation.
REM   3. Saves everything to build\last-check.txt and opens it in Notepad.
REM
REM Writes only inside build\ and the temp folder. It never touches
REM data\, m\ or p\. This file itself is never replaced by a download.
REM ---------------------------------------------------------------------

set "SELF=%~nx0"
cd /d "%~dp0.."
set "REPO=%CD%"
set "BUILD=%REPO%\build"
set "LOG=%BUILD%\last-check.txt"
set "GH=jsierrahoopshype/nba-matchups"
set "BRANCH=fetcher-dev"
if not defined TEMP set "TEMP=%BUILD%"
set "DL=%TEMP%\hoopsmatic-check-download"
set "HOOPSMATIC_NONINTERACTIVE=1"
set "PYTHONUTF8=1"
set "NFILES=0"
set "NNEW=0"
set "NUPD=0"
set "NSAME=0"
set "DLFAIL="

> "%LOG%" echo HoopsMatic matchup check round   %DATE% %TIME%
if errorlevel 1 goto :nolog
call :say "repo    %REPO%"

if not exist "%REPO%\data\meta.json" goto :notrepo

REM ---- 1. download ------------------------------------------------------
set "CURL=%SystemRoot%\System32\curl.exe"
if not exist "%CURL%" set "CURL=curl"
"%CURL%" --version >nul 2>&1
if errorlevel 1 goto :nocurl

if exist "%DL%" rmdir /s /q "%DL%"
mkdir "%DL%\files" >nul 2>&1
mkdir "%DL%\previous" >nul 2>&1

REM Pin the exact commit, so a raw.githubusercontent.com copy cached from
REM a few minutes ago cannot be served. Falls back to the branch name.
set "REF=%BRANCH%"
set "SHA="
"%CURL%" -fsSL --max-time 30 -H "Accept: application/vnd.github.sha" -o "%DL%\sha.txt" "https://api.github.com/repos/%GH%/commits/%BRANCH%" >nul 2>&1
if not errorlevel 1 set /p SHA=<"%DL%\sha.txt"
call :checksha
if defined SHA set "REF=!SHA!"
if defined SHA call :say "source  %BRANCH% at commit !SHA!"
if not defined SHA call :say "source  %BRANCH% - commit lookup failed, using the branch name; a copy up to 5 minutes old is possible"
set "BASE=https://raw.githubusercontent.com/%GH%/!REF!/build"

"%CURL%" -fsSL --max-time 60 --retry 2 -o "%DL%\fetcher-files.txt" "!BASE!/fetcher-files.txt" >nul 2>&1
if errorlevel 1 goto :nomanifest

call :say ""
call :say "downloading..."
for /f "usebackq eol=# delims=" %%F in ("%DL%\fetcher-files.txt") do call :fetchone "%%F"
if defined DLFAIL goto :dlfailed
if "%NFILES%"=="0" goto :dlfailed

call :say ""
call :say "files in build\ after this round:"
for /f "usebackq eol=# delims=" %%F in ("%DL%\fetcher-files.txt") do call :place "%%F"
call :say "   %NNEW% new, %NUPD% updated, %NSAME% unchanged. Replaced versions are kept in %DL%\previous"
call :say ""

REM ---- 2. run the check ---------------------------------------------------
set "PY="
where py >nul 2>&1 && set "PY=py -3"
if not defined PY ( where python >nul 2>&1 && set "PY=python" )
if not defined PY goto :nopython

if not exist "%BUILD%\check_runner.py" goto :fallback
%PY% "%BUILD%\check_runner.py" --log "%LOG%"
goto :finish

:fallback
call :say "check_runner.py is missing - running verify-matchup-fetch.bat on its own"
call "%BUILD%\verify-matchup-fetch.bat" < nul >> "%LOG%" 2>&1
cd /d "%REPO%"
goto :finish

REM ---- failures: each writes its reason to the log, then opens it -------
:notrepo
call :say "[X] %REPO%\data\meta.json not found."
call :say "    This file must sit in the build folder of the nba-matchups checkout."
goto :finish

:nocurl
call :say "[X] curl was not found. It ships with Windows 10 version 1803 and later."
goto :finish

:nomanifest
call :say "[X] Could not download !BASE!/fetcher-files.txt"
call :say "    Check the internet connection. Nothing was changed."
goto :finish

:dlfailed
call :say ""
call :say "[X] Not every file downloaded, so NO file was replaced and the check did not run."
call :say "    Double-click this file again in a minute. If it keeps failing, paste this to Claude."
goto :finish

:nopython
call :say "[X] Python was not found. Files were updated, but the check did not run."
goto :finish

:nolog
echo [X] Cannot write %LOG%
echo     Is the build folder read-only? This window closes in 60 seconds.
timeout /t 60 /nobreak >nul
exit /b 1

:finish
call :say ""
call :say "Saved to %LOG%"
start "" notepad "%LOG%"
endlocal
exit /b 0

REM ---- subroutines ---------------------------------------------------------

:say
REM Print a line to the console and append it to the log.
set "MSG=%~1"
echo(!MSG!
>> "%LOG%" echo(!MSG!
exit /b 0

:checksha
REM Keep SHA only if it is exactly 40 lowercase hex characters.
if not defined SHA exit /b 0
if "!SHA:~39,1!"=="" set "SHA="
if not defined SHA exit /b 0
if not "!SHA:~40,1!"=="" set "SHA="
if not defined SHA exit /b 0
for /f "delims=0123456789abcdef" %%X in ("!SHA!") do set "SHA="
exit /b 0

:fetchone
REM Bare .py / .bat names only: letters, digits, - _ and one extension.
set "NAME=%~1"
set "BAD="
for /f "delims=abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_." %%X in ("!NAME!") do set "BAD=1"
if not "!NAME:..=!"=="!NAME!" set "BAD=1"
set "EXTOK="
if /i "!NAME:~-3!"==".py" set "EXTOK=1"
if /i "!NAME:~-4!"==".bat" set "EXTOK=1"
if not defined EXTOK set "BAD=1"
if defined BAD goto :fetchone_bad
if /i "!NAME!"=="%SELF%" goto :fetchone_self
"%CURL%" -fsSL --max-time 180 --retry 2 -o "%DL%\files\!NAME!" "!BASE!/!NAME!" >nul 2>&1
if errorlevel 1 goto :fetchone_fail
set /a NFILES+=1
exit /b 0
:fetchone_bad
call :say "   [X] refused manifest entry: !NAME!"
set "DLFAIL=1"
exit /b 0
:fetchone_self
call :say "   skipped    !NAME! - this file is never replaced by a download"
exit /b 0
:fetchone_fail
call :say "   [X] download failed: !NAME!"
set "DLFAIL=1"
exit /b 0

:place
set "NAME=%~1"
if not exist "%DL%\files\!NAME!" exit /b 0
if not exist "%BUILD%\!NAME!" goto :place_new
fc /b "%DL%\files\!NAME!" "%BUILD%\!NAME!" >nul 2>&1
if not errorlevel 1 goto :place_same
copy /y "%BUILD%\!NAME!" "%DL%\previous\!NAME!" >nul
copy /y "%DL%\files\!NAME!" "%BUILD%\!NAME!" >nul
if errorlevel 1 goto :place_fail
call :say "   updated    !NAME!"
set /a NUPD+=1
exit /b 0
:place_new
copy /y "%DL%\files\!NAME!" "%BUILD%\!NAME!" >nul
if errorlevel 1 goto :place_fail
call :say "   new        !NAME!"
set /a NNEW+=1
exit /b 0
:place_same
call :say "   unchanged  !NAME!"
set /a NSAME+=1
exit /b 0
:place_fail
call :say "   [X] could not write build\!NAME! - is it open in another program?"
exit /b 0
