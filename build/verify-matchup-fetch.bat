@echo off
setlocal enabledelayedexpansion
title HoopsMatic - VERIFY matchup fetch (read-only)

REM ---------------------------------------------------------------------
REM READ-ONLY CHECK. This never writes to data\, m\, p\ or anywhere else
REM in the repository. Everything it downloads goes to your temp folder.
REM
REM It fetches one player from stats.nba.com, transforms the response in
REM memory, and diffs the result against the committed
REM data\p\nikola-jokic.json. If that comes back identical then the
REM endpoint, its parameters, the response shape and the whole transform
REM are confirmed against real data, and refresh-matchup-data.bat is safe
REM to run. If it does not, nothing has been damaged - send the output to
REM Claude.
REM ---------------------------------------------------------------------

cd /d "%~dp0.."
set "SLUG=nikola-jokic"

echo.
echo ======================================================================
echo  VERIFY matchup fetch   ^(read-only^)
echo  Repo:   %CD%
echo  Player: %SLUG%
echo ======================================================================
echo.
echo  Nothing in the repository will be written. Downloads go to your
echo  temp folder and can be deleted afterwards.
echo.
echo  Heads up: this pulls the same league-wide season data that a full
echo  refresh needs - a few hundred MB, several minutes, deliberately
echo  rate-limited. That is the point: it is the real request.
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
echo [1/3] Python found.

REM ---- scratch space, outside the repo ---------------------------------
set "VCACHE=%TEMP%\hoopsmatic-verify-cache"
if not exist "%VCACHE%" mkdir "%VCACHE%" >nul 2>&1
echo [2/3] Scratch folder: %VCACHE%

REM ---- run the check ---------------------------------------------------
echo [3/3] Fetching and comparing...
echo.
%PY% "build\fetch_matchup_data.py" --verify-slug "%SLUG%" --cache-dir "%VCACHE%"
set "RC=%ERRORLEVEL%"

echo.
if "%RC%"=="0" goto :ok
if "%RC%"=="2" goto :nodata
goto :mismatch

:ok
REM Record the pass, keyed to the fetcher's contents so that editing the
REM fetcher invalidates it.
%PY% "build\fetch_matchup_data.py" --marker-write "%LOCALAPPDATA%\HoopsMatic\verify-ok.txt" --verify-slug "%SLUG%" >nul
echo ======================================================================
echo  PASS - the fetched data matches the committed file exactly.
echo ======================================================================
echo.
echo  The endpoint and the transform are confirmed against real data.
echo  You can now run build\refresh-matchup-data.bat to rebuild the site.
echo.
echo  Nothing in the repository was changed by this check.
echo  You can delete %VCACHE% to reclaim the disk space
echo  ^(the refresh keeps its own cache, so deleting this costs nothing^).
echo.
pause
exit /b 0

:nodata
echo ======================================================================
echo  COULD NOT CHECK
echo ======================================================================
echo.
echo  The fetch returned nothing usable for %SLUG%, so there was
echo  nothing to compare. Usual causes:
echo.
echo    - no internet connection
echo    - a VPN routing you through a datacenter the NBA blocks
echo    - the endpoint or its parameters are wrong
echo.
echo  Run  build\diagnose-matchup-fetch.bat  and send Claude the output.
echo.
echo  Nothing in the repository was changed. Send the output above to
echo  Claude and do NOT run refresh-matchup-data.bat yet.
echo.
pause
exit /b 2

:mismatch
echo ======================================================================
echo  FAIL - the fetched data does NOT match the committed file.
echo ======================================================================
echo.
echo  Do NOT run refresh-matchup-data.bat. It will refuse to run anyway.
echo.
echo  Nothing in the repository was changed. Scroll up: the diff above
echo  shows exactly which sections differ.
echo.
echo  If the diff does not explain itself, run this for more detail and
echo  send both outputs to Claude:
echo.
echo      build\diagnose-matchup-fetch.bat
echo.
pause
exit /b 1
