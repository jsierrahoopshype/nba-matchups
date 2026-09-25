@echo off
setlocal
title HoopsMatic - diagnose matchup fetch (read-only)

REM Describes what the NBA actually returned: which requests produced rows,
REM what the result sets and columns are called, the SEASON_ID prefixes seen,
REM and one sample row. Makes NO requests and writes nothing - it only reads
REM the cache that verify-matchup-fetch.bat already downloaded.

cd /d "%~dp0.."
set "VCACHE=%TEMP%\hoopsmatic-verify-cache"

echo.
echo ======================================================================
echo  DIAGNOSE matchup fetch   ^(read-only, no downloads^)
echo  Cache: %VCACHE%
echo ======================================================================
echo.

set "PY="
where py >nul 2>&1 && set "PY=py -3"
if not defined PY ( where python >nul 2>&1 && set "PY=python" )
if not defined PY (
  echo [X] Python was not found. Install it from https://www.python.org/downloads/
  pause
  exit /b 1
)

if not exist "%VCACHE%" (
  echo [X] No cache found at %VCACHE%
  echo     Run build\verify-matchup-fetch.bat first - it downloads the data
  echo     this reads.
  echo.
  pause
  exit /b 1
)

%PY% "build\fetch_matchup_data.py" --diagnose --cache-dir "%VCACHE%" > "%TEMP%\hoopsmatic-diagnose.txt" 2>&1
type "%TEMP%\hoopsmatic-diagnose.txt"
echo.
echo ======================================================================
echo  Saved to: %TEMP%\hoopsmatic-diagnose.txt
echo  Send that file to Claude.
echo ======================================================================
echo.
pause
exit /b 0
