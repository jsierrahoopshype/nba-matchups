@echo off
setlocal enabledelayedexpansion
title HoopsMatic - refresh NBA matchup data

REM ---------------------------------------------------------------------
REM Double-click this to rebuild the matchup section from scratch:
REM   0. refuse unless the read-only verification has passed
REM   1. re-run that verification live, against the cache this run will use
REM   2. back up data\ outside the repo
REM   3. fetch fresh data from stats.nba.com   (needs the internet)
REM   4. regenerate the pages in m\ and p\     (offline)
REM   5. run the four build\ fixes             (offline)
REM
REM Steps 0 and 1 exist so a wrong endpoint guess cannot silently
REM overwrite 2,545 pages. Run build\verify-matchup-fetch.bat first.
REM
REM This must run on your own machine. stats.nba.com blocks datacenter
REM IPs, so it will not work from a cloud sandbox or a GitHub Action.
REM ---------------------------------------------------------------------

cd /d "%~dp0.."
set "SLUG=nikola-jokic"
set "MARKER=%LOCALAPPDATA%\HoopsMatic\verify-ok.txt"

echo.
echo ======================================================================
echo  HoopsMatic matchup data refresh
echo  Folder: %CD%
echo ======================================================================
echo.

REM ---- find Python -----------------------------------------------------
set "PY="
where py >nul 2>&1 && set "PY=py -3"
if not defined PY ( where python >nul 2>&1 && set "PY=python" )
if not defined PY (
  echo [X] Python was not found on this computer.
  echo.
  echo     Install it from https://www.python.org/downloads/
  echo     On the first screen, tick "Add python.exe to PATH".
  echo     Then close this window and double-click this file again.
  echo.
  pause
  exit /b 1
)
for /f "tokens=*" %%v in ('%PY% -c "import sys;print(sys.version.split()[0])" 2^>nul') do set "PYVER=%%v"
echo [1/8] Python %PYVER% found.

REM ---- dependencies ----------------------------------------------------
if exist "build\requirements.txt" (
  echo [2/8] Installing dependencies...
  %PY% -m pip install --quiet --disable-pip-version-check -r "build\requirements.txt"
  if errorlevel 1 (
    echo [X] Installing dependencies failed. Scroll up for the reason.
    pause
    exit /b 1
  )
) else (
  echo [2/8] No extra dependencies needed ^(standard library only^).
)

REM ---- GATE 1: the verification must have passed for THIS fetcher ------
echo [3/8] Checking that the fetch has been verified...
%PY% "build\fetch_matchup_data.py" --marker-check "%MARKER%"
set "MRC=%ERRORLEVEL%"
if "%MRC%"=="3" (
  echo.
  echo [X] STOPPED - the fetch has never been verified on this computer.
  echo.
  echo     Double-click  build\verify-matchup-fetch.bat  first.
  echo     It is read-only: it checks one player against the committed
  echo     data and writes nothing. Come back here once it says PASS.
  echo.
  pause
  exit /b 1
)
if "%MRC%"=="4" (
  echo.
  echo [X] STOPPED - the last verification does not match this fetcher.
  echo.
  echo     build\fetch_matchup_data.py has changed since it was last
  echo     verified, so the old PASS no longer proves anything.
  echo.
  echo     Double-click  build\verify-matchup-fetch.bat  again.
  echo.
  pause
  exit /b 1
)
echo       Previous verification on record.

REM ---- GATE 2: re-verify live, into the cache this run will use --------
REM Not wasted work: these responses are exactly what step 5 needs, so
REM the real fetch reuses them instead of asking the NBA again.
echo [4/8] Re-checking one player against the committed data ^(live^)...
echo       This is the slow part and it is deliberately rate-limited.
echo.
%PY% "build\fetch_matchup_data.py" --verify-slug "%SLUG%"
if errorlevel 1 (
  echo.
  echo [X] STOPPED - the live check did not match the committed data.
  echo.
  echo     NOTHING has been written. data\, m\ and p\ are untouched.
  echo     Scroll up: the diff shows exactly which sections differ.
  echo     Send it to Claude before running this again.
  echo.
  pause
  exit /b 1
)
echo.
echo       Live check passed.

REM ---- back up data\ ---------------------------------------------------
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd-HHmmss"') do set "STAMP=%%i"
if not defined STAMP set "STAMP=manual"
set "BACKUP=%CD%\..\nba-matchups-data-backup\data-%STAMP%"
echo [5/8] Backing up data\ to:
echo       %BACKUP%
robocopy "data" "%BACKUP%" /E /NFL /NDL /NJH /NJS /NC /NS /R:1 /W:1 >nul
if %ERRORLEVEL% GEQ 8 (
  echo [X] The backup failed, so nothing was changed.
  echo     Free up disk space ^(data\ is around 570 MB^) and try again.
  pause
  exit /b 1
)
echo       Backup complete.
echo       ^(data\ is also tracked in git, so "git checkout -- data" restores it too^)

REM ---- fetch -----------------------------------------------------------
echo [6/8] Fetching the remaining seasons...
%PY% "build\fetch_matchup_data.py"
if errorlevel 1 (
  echo.
  echo [X] The fetch failed. Downloaded seasons are cached, so running
  echo     this file again resumes instead of starting over.
  echo.
  echo     Your data is backed up at:
  echo       %BACKUP%
  echo.
  echo     Usual causes: no internet, a VPN routing you through a
  echo     datacenter the NBA blocks, or NBA rate-limiting ^(wait ten
  echo     minutes^).
  echo.
  pause
  exit /b 1
)

REM ---- generate --------------------------------------------------------
echo [7/8] Regenerating the pages in m\ and p\, then applying the fixes...
%PY% "build\generate_matchup_pages.py"       || goto :stagefail
%PY% "build\fix_matchup_paths.py"            || goto :stagefail
%PY% "build\apply_ui_tweaks.py"              || goto :stagefail
%PY% "build\fix_canonical_urls.py"           || goto :stagefail
%PY% "build\prerender_matchup_tables.py"     || goto :stagefail
goto :stageok

:stagefail
echo.
echo [X] One of the build steps failed. Scroll up to see which.
echo     Nothing has been committed. To undo everything:
echo         git checkout -- data m p
echo     Or restore from: %BACKUP%
pause
exit /b 1

:stageok

REM ---- report ----------------------------------------------------------
echo [8/8] Done. Here is what changed:
echo.
git status --short --untracked-files=no > "%TEMP%\hoopsmatic_changed.txt" 2>nul
if errorlevel 1 (
  echo     ^(git is not available here, so the summary is skipped^)
) else (
  for /f %%c in ('find /c /v "" ^< "%TEMP%\hoopsmatic_changed.txt"') do set "NCHANGED=%%c"
  if "!NCHANGED!"=="0" (
    echo     Nothing changed. The data was already up to date.
    del "%TEMP%\hoopsmatic_changed.txt" >nul 2>&1
    echo.
    echo     Nothing to do - you can close this window.
    echo.
    pause
    exit /b 0
  )
  echo     !NCHANGED! file^(s^) changed. First few:
  echo.
  set /a _n=0
  for /f "usebackq delims=" %%L in ("%TEMP%\hoopsmatic_changed.txt") do (
    set /a _n+=1
    if !_n! LEQ 12 echo        %%L
  )
  del "%TEMP%\hoopsmatic_changed.txt" >nul 2>&1
)

echo.
echo ======================================================================
echo  WHAT TO DO NEXT
echo ======================================================================
echo.
echo  The new pages are on your disk but not yet on the website.
echo  To publish them, run these three commands in this folder:
echo.
echo      git add -A
echo      git commit -m "Refresh matchup data"
echo      git push
echo.
echo  GitHub Pages picks the change up within a minute or two, and the
echo  "Apply build/ fixes" Action double-checks the fixes after the push.
echo.
echo  If anything looks wrong, undo it with:
echo      git checkout -- data m p
echo  or restore the backup at:
echo      %BACKUP%
echo.
pause
exit /b 0
