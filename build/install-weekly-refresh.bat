@echo off
setlocal
title HoopsMatic - set up the weekly matchup refresh

REM ---------------------------------------------------------------------
REM Double-click this ONCE. It registers a Windows scheduled task that runs
REM build\weekly-refresh.bat every Monday at 09:00 (this PC's time), so the
REM matchup pages pick up the season in progress without anyone running
REM anything. Running it again just updates the same task.
REM
REM Why on this PC and not on GitHub: stats.nba.com blocks datacenter IPs,
REM and a GitHub Actions runner timed out on every request (tested
REM 2026-11-05). Your home connection is not blocked.
REM
REM If the PC is off or asleep at 09:00 on Monday, the task runs as soon as
REM you next log in. It runs as you, so it pushes with your usual git login.
REM
REM To remove it later, run this in a Command Prompt:
REM   schtasks /Delete /TN "HoopsMatic matchups weekly refresh" /F
REM ---------------------------------------------------------------------

cd /d "%~dp0.."
set "TASK=HoopsMatic matchups weekly refresh"
set "HM_BAT=%CD%\build\weekly-refresh.bat"
set "HM_DIR=%CD%"

echo.
echo ======================================================================
echo  HoopsMatic weekly matchup refresh - setup
echo  Folder: %CD%
echo ======================================================================
echo.

if not exist "%HM_BAT%" (
  echo [X] build\weekly-refresh.bat is missing. Run "git pull" in this folder first.
  pause
  exit /b 1
)
set "PY="
where py >nul 2>&1 && set "PY=py -3"
if not defined PY ( where python >nul 2>&1 && set "PY=python" )
if not defined PY (
  echo [X] Python was not found. Install it from https://www.python.org/downloads/
  echo     ^(tick "Add python.exe to PATH"^), then double-click this file again.
  pause
  exit /b 1
)
where git >nul 2>&1
if errorlevel 1 (
  echo [X] git was not found. Install Git for Windows, then double-click this again.
  pause
  exit /b 1
)

echo [1/2] Registering the scheduled task "%TASK%"...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$a = New-ScheduledTaskAction -Execute 'cmd.exe' -Argument ('/c ' + [char]34 + $env:HM_BAT + [char]34) -WorkingDirectory $env:HM_DIR;" ^
  "$t = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday -At '09:00';" ^
  "$s = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 4) -MultipleInstances IgnoreNew;" ^
  "Register-ScheduledTask -TaskName $env:TASK -Description 'Refreshes hoopsmatic.com/matchups from stats.nba.com and pushes it. Log: %%LOCALAPPDATA%%\HoopsMatic\weekly-refresh.log' -Action $a -Trigger $t -Settings $s -Force | Out-Null"
if errorlevel 1 (
  echo.
  echo [X] Windows refused to create the task. Scroll up for the reason.
  pause
  exit /b 1
)
set "NEXT="
for /f "delims=" %%n in ('powershell -NoProfile -Command "(Get-ScheduledTaskInfo -TaskName $env:TASK).NextRunTime"') do set "NEXT=%%n"
echo       Done. Next run: %NEXT%
echo       Log of every run: %LOCALAPPDATA%\HoopsMatic\weekly-refresh.log
echo.

echo [2/2] Run the first refresh now?
echo       It downloads the season in progress, adds pages for players who
echo       now qualify ^(rookies included^), and publishes the result. The very
echo       first run can take up to an hour if this PC has no playoff cache
echo       yet; later Mondays take a few minutes.
echo.
choice /C YN /M "Run it now"
if errorlevel 2 (
  echo.
  echo  OK. It will run on its own next Monday at 09:00.
  echo.
  pause
  exit /b 0
)
echo.
call "%HM_BAT%"
set "RC=%ERRORLEVEL%"
echo.
if "%RC%"=="0" (
  echo  First refresh finished. From now on it runs every Monday by itself.
) else (
  echo  The first refresh stopped - the reason is on the [X] line above.
  echo  Full log: %LOCALAPPDATA%\HoopsMatic\weekly-refresh-last.log
  echo  The weekly task is still set up and will try again next Monday.
)
echo.
pause
exit /b %RC%
