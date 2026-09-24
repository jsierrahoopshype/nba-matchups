@echo off
setlocal enabledelayedexpansion
title HoopsMatic - refresh NBA matchup data

REM ---------------------------------------------------------------------
REM Double-click this to rebuild the matchup section from scratch:
REM   1. fetch fresh data from stats.nba.com   (needs the internet)
REM   2. regenerate the pages in m\ and p\     (offline)
REM   3. run the four build\ fixes             (offline)
REM Then commit and push - the GitHub Action re-applies the fixes anyway,
REM but pushing finished pages keeps the site correct immediately.
REM
REM This must run on your own machine. stats.nba.com blocks datacenter IPs,
REM so it will not work from a cloud sandbox or a GitHub Action.
REM ---------------------------------------------------------------------

cd /d "%~dp0.."
echo.
echo ======================================================================
echo  HoopsMatic matchup data refresh
echo  Folder: %CD%
echo ======================================================================
echo.

REM ---- find Python -----------------------------------------------------
set "PY="
where py >nul 2>&1 && set "PY=py -3"
if not defined PY (
  where python >nul 2>&1 && set "PY=python"
)
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
echo [1/6] Python %PYVER% found.

REM ---- dependencies ----------------------------------------------------
REM The scripts use only the standard library, so there is normally nothing
REM to install. This stays here so a future dependency cannot silently break
REM the run for you.
if exist "build\requirements.txt" (
  echo [2/6] Installing dependencies...
  %PY% -m pip install --quiet --disable-pip-version-check -r "build\requirements.txt"
  if errorlevel 1 (
    echo [X] Installing dependencies failed. Scroll up for the reason.
    pause
    exit /b 1
  )
) else (
  echo [2/6] No extra dependencies needed ^(standard library only^).
)

REM ---- snapshot so we can report what changed --------------------------
set "STAMP=%TEMP%\hoopsmatic_refresh_%RANDOM%.txt"
git rev-parse HEAD > "%STAMP%" 2>nul

REM ---- 1. fetch --------------------------------------------------------
echo [3/6] Fetching fresh matchup data from stats.nba.com...
echo       This is the slow part. It is rate-limited on purpose so the NBA
echo       does not block you. Leave it running.
%PY% "build\fetch_matchup_data.py"
if errorlevel 1 (
  echo.
  echo [X] The fetch failed. Nothing has been changed on disk that matters:
  echo     already-downloaded seasons are cached, so running this file again
  echo     picks up where it stopped instead of starting over.
  echo.
  echo     If it keeps failing, the usual causes are:
  echo       - no internet connection
  echo       - a VPN routing you through a datacenter the NBA blocks
  echo       - the NBA rate-limiting you: wait ten minutes and retry
  echo.
  pause
  exit /b 1
)

REM ---- 2. generate -----------------------------------------------------
echo [4/6] Regenerating the pages in m\ and p\...
%PY% "build\generate_matchup_pages.py"
if errorlevel 1 (
  echo [X] Generating the pages failed. Scroll up for the reason.
  pause
  exit /b 1
)

REM ---- 3. build fixes --------------------------------------------------
echo [5/6] Applying the build fixes ^(paths, legend, canonicals, pre-render^)...
%PY% "build\fix_matchup_paths.py"        || goto :fixfail
%PY% "build\apply_ui_tweaks.py"          || goto :fixfail
%PY% "build\fix_canonical_urls.py"       || goto :fixfail
%PY% "build\prerender_matchup_tables.py" || goto :fixfail
goto :fixok

:fixfail
echo.
echo [X] One of the build fixes failed. Scroll up to see which one.
echo     Nothing has been committed, so the repository is safe to inspect.
pause
exit /b 1

:fixok

REM ---- 4. report -------------------------------------------------------
echo [6/6] Done. Here is what changed:
echo.
git status --short --untracked-files=no > "%TEMP%\hoopsmatic_changed.txt" 2>nul
if errorlevel 1 (
  echo     ^(git is not available here, so the summary is skipped^)
) else (
  for /f %%c in ('find /c /v "" ^< "%TEMP%\hoopsmatic_changed.txt"') do set "NCHANGED=%%c"
  if "!NCHANGED!"=="0" (
    echo     Nothing changed. The data was already up to date.
    echo.
    echo     Nothing to do - you can close this window.
    del "%TEMP%\hoopsmatic_changed.txt" >nul 2>&1
    echo.
    pause
    exit /b 0
  )
  echo     !NCHANGED! file^(s^) changed. First few:
  echo.
  %PY% -c "import itertools,sys;print(''.join('       '+l for l in itertools.islice(open(r'%TEMP%\hoopsmatic_changed.txt',encoding='utf-8',errors='replace'),12)))"
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
pause
exit /b 0
