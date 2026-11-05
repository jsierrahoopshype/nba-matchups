@echo off
setlocal enabledelayedexpansion
title HoopsMatic - weekly matchup refresh (leave this window open)

REM ---------------------------------------------------------------------
REM The unattended version of refresh-matchup-data.bat. Windows runs it
REM every Monday morning once build\install-weekly-refresh.bat has been
REM double-clicked; you can also double-click it yourself at any time.
REM
REM   1. checks this folder is on main with nothing uncommitted
REM   2. git pull, so it builds on what is already published
REM   3. re-runs the read-only check on one player LIVE (the same gate as
REM      the manual refresh); stops, writing nothing, if it fails
REM   4. fetches from stats.nba.com. Only the season in progress is
REM      downloaded again; finished seasons come from the local cache
REM   5. regenerates the pages and runs the build\ scripts in the same
REM      order as the GitHub Action (build\run_build_steps.py)
REM   6. commits and pushes data\, m\, p\ and the sitemap to main, which
REM      publishes them on hoopsmatic.com/matchups/
REM
REM It runs on your PC because stats.nba.com blocks datacenter IPs: a
REM GitHub Actions runner times out on every request (tested 2026-11-05).
REM
REM No pauses: nothing waits for a key press. The full output goes to
REM   %LOCALAPPDATA%\HoopsMatic\weekly-refresh.log      (every run)
REM   %LOCALAPPDATA%\HoopsMatic\weekly-refresh-last.log (latest run only)
REM ---------------------------------------------------------------------

cd /d "%~dp0.."
REM UTF-8 throughout: the console code page, and Python's own I/O, so a
REM player name like Jokic with its accent prints and logs instead of
REM crashing on the Windows default code page.
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "SLUG=nikola-jokic"
set "HMDIR=%LOCALAPPDATA%\HoopsMatic"
if not exist "%HMDIR%" mkdir "%HMDIR%" >nul 2>&1
set "LOG=%HMDIR%\weekly-refresh-last.log"
set "HISTORY=%HMDIR%\weekly-refresh.log"
set "MARKER=%HMDIR%\verify-ok.txt"
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd"') do set "TODAY=%%i"
if not defined TODAY set "TODAY=%DATE%"

> "%LOG%" echo HoopsMatic weekly matchup refresh, %DATE% %TIME%, folder %CD%
call :say "HoopsMatic weekly matchup refresh - %TODAY%"
call :say "Full log: %LOG%"

REM ---- tools -----------------------------------------------------------
set "PY="
where py >nul 2>&1 && set "PY=py -3"
if not defined PY ( where python >nul 2>&1 && set "PY=python" )
if not defined PY ( call :fail "Python was not found on this computer." & goto :end )
where git >nul 2>&1 || ( call :fail "git was not found on this computer." & goto :end )

REM ---- 1. on main, nothing uncommitted ---------------------------------
set "BR="
for /f "delims=" %%b in ('git rev-parse --abbrev-ref HEAD 2^>nul') do set "BR=%%b"
if /i not "%BR%"=="main" (
  call :fail "This folder is on branch '%BR%', not main. Switch to main and it runs next week."
  goto :end
)
git status --porcelain --untracked-files=no > "%TEMP%\hm_weekly_dirty.txt" 2>nul
for %%A in ("%TEMP%\hm_weekly_dirty.txt") do set "DIRTY=%%~zA"
del "%TEMP%\hm_weekly_dirty.txt" >nul 2>&1
if not "%DIRTY%"=="0" (
  call :fail "There are uncommitted changes in this folder. Commit or undo them; nothing was touched."
  goto :end
)

REM ---- 2. pull ---------------------------------------------------------
call :say "[1/6] git pull"
git pull --ff-only >> "%LOG%" 2>&1 || ( call :fail "git pull failed (no internet, or local commits that are not on GitHub)." & goto :end )

REM ---- 3. live check ---------------------------------------------------
call :say "[2/6] Live check of %SLUG% against the committed data"
%PY% "build\fetch_matchup_data.py" --verify-slug "%SLUG%" >> "%LOG%" 2>&1
if errorlevel 1 (
  call :fail "The live check did not match the committed data. Nothing was written. Send the log to Claude."
  goto :end
)
%PY% "build\fetch_matchup_data.py" --marker-write "%MARKER%" --verify-slug "%SLUG%" >> "%LOG%" 2>&1

REM ---- 4. fetch --------------------------------------------------------
call :say "[3/6] Fetching from stats.nba.com (only the season in progress is new)"
%PY% "build\fetch_matchup_data.py" >> "%LOG%" 2>&1
if errorlevel 1 (
  git checkout -- data >> "%LOG%" 2>&1
  git clean -fdq -- data\p >> "%LOG%" 2>&1
  call :fail "The fetch failed (no internet, VPN, or NBA rate-limiting). Nothing was published; next week retries."
  goto :end
)

REM ---- 5. build --------------------------------------------------------
call :say "[4/6] Regenerating pages and applying the build\ fixes"
REM The generator, then the exact step list of the GitHub Action
REM (.github\workflows\apply-build-fixes.yml), read from that file by
REM run_build_steps.py, so this and the Action always run the same steps
REM in the same order.
%PY% "build\run_build_steps.py" --generate >> "%LOG%" 2>&1
if errorlevel 1 (
  git checkout -- data m p sitemap.xml build\sitemap-hashes.json >> "%LOG%" 2>&1
  git clean -fdq -- data\p p >> "%LOG%" 2>&1
  call :fail "A build step failed - the log names it after the last == step line. Everything was put back; nothing was published."
  goto :end
)

REM ---- 6. commit + push ------------------------------------------------
call :say "[5/6] Committing"
git add -A data m p sitemap.xml build\sitemap-hashes.json >> "%LOG%" 2>&1
git diff --cached --quiet
if not errorlevel 1 (
  call :say "Nothing changed since last week. Done."
  set "RC=0"
  goto :end
)
git commit -q -m "Weekly matchup data refresh %TODAY%" >> "%LOG%" 2>&1 || ( call :fail "git commit failed." & goto :end )
call :say "[6/6] Pushing to GitHub"
git push >> "%LOG%" 2>&1
if errorlevel 1 (
  git pull --rebase >> "%LOG%" 2>&1 && git push >> "%LOG%" 2>&1
)
if errorlevel 1 (
  call :fail "git push failed. The refresh is committed on this PC; push it by hand with: git push"
  goto :end
)
for /f "delims=" %%c in ('git rev-parse --short HEAD') do set "SHA=%%c"
call :say "Published as commit !SHA!. Live on hoopsmatic.com/matchups/ in a minute or two."
set "RC=0"
goto :end

REM ---------------------------------------------------------------------
:say
echo %~1
>> "%LOG%" echo %~1
exit /b 0

:fail
echo [X] %~1
>> "%LOG%" echo [X] %~1
set "RC=1"
exit /b 0

:end
if not defined RC set "RC=1"
>> "%LOG%" echo exit code %RC%
type "%LOG%" >> "%HISTORY%" 2>nul
>> "%HISTORY%" echo.
exit /b %RC%
